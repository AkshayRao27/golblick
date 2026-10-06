<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\BackgroundJob;

use OCA\Golblick\Service\PanoramaStore;
use OCA\Golblick\Service\Settings;
use OCP\AppFramework\Utility\ITimeFactory;
use OCP\BackgroundJob\TimedJob;
use OCP\Files\Config\IUserMountCache;
use OCP\Files\File;
use OCP\Files\IMimeTypeLoader;
use OCP\Files\IRootFolder;
use OCP\IDBConnection;
use Psr\Log\LoggerInterface;

/**
 * Renders full-size panoramas ahead of time, so the first zoom or sphere view
 * of a photo doesn't wait for one. Off by default: at 4096 wide a OneR photo
 * costs about 19 s of CPU, so a library of a couple of thousand photos is many
 * hours of work, spread over cron runs.
 *
 * Each run stops after RUN_SECONDS. Files are taken in id order and skipped
 * when already cached at the current width, so a run picks up where the last
 * one left off without keeping any state of its own.
 *
 * A file is opened through the folder of a user who has it mounted, which is
 * what makes group folder files reachable at all; the cached panorama is the
 * same whoever renders it, and it is only ever served through endpoints that
 * check the viewer's own access.
 */
final class Prerender extends TimedJob {
	private const RUN_SECONDS = 120;
	private const BATCH = 200;

	public function __construct(
		ITimeFactory $time,
		private Settings $settings,
		private PanoramaStore $store,
		private IDBConnection $db,
		private IMimeTypeLoader $mimeTypes,
		private IUserMountCache $mounts,
		private IRootFolder $rootFolder,
		private LoggerInterface $logger,
	) {
		parent::__construct($time);
		$this->setInterval(15 * 60);
		$this->setTimeSensitivity(self::TIME_INSENSITIVE);
	}

	protected function run($argument): void {
		if (!$this->settings->flag('prerender')) {
			return;
		}
		$deadline = microtime(true) + self::RUN_SECONDS;
		$rendered = 0;
		$after = 0;

		while (microtime(true) < $deadline) {
			$ids = $this->candidates($after);
			if ($ids === []) {
				break;
			}
			foreach ($ids as $id) {
				$after = $id;
				if (microtime(true) >= $deadline) {
					break 2;
				}
				$file = $this->open($id);
				if ($file === null || $this->store->isCached($file)) {
					continue;
				}
				try {
					if ($this->store->get($file) !== null) {
						$rendered++;
					}
				} catch (\Throwable $e) {
					$this->logger->warning('golblick: pre-render failed for file ' . $id,
						['app' => 'golblick', 'exception' => $e]);
				}
			}
		}

		if ($rendered > 0) {
			$this->logger->info("golblick: pre-rendered $rendered panoramas", ['app' => 'golblick']);
		}
	}

	/** @return list<int> */
	private function candidates(int $after): array {
		$qb = $this->db->getQueryBuilder();
		$qb->select('fileid')
			->from('filecache')
			->where($qb->expr()->iLike('name', $qb->createNamedParameter('%.insp')))
			->andWhere($qb->expr()->like('path', $qb->createNamedParameter('files/%')))
			->andWhere($qb->expr()->eq('mimetype', $qb->createNamedParameter($this->mimeTypes->getId('image/jpeg'))))
			->andWhere($qb->expr()->gt('fileid', $qb->createNamedParameter($after)))
			->orderBy('fileid')
			->setMaxResults(self::BATCH);
		$result = $qb->executeQuery();
		$ids = array_map('intval', $result->fetchFirstColumn());
		$result->closeCursor();

		return $ids;
	}

	private function open(int $id): ?File {
		foreach ($this->mounts->getMountsForFileId($id) as $mount) {
			try {
				$node = $this->rootFolder->getUserFolder($mount->getUser()->getUID())->getFirstNodeById($id);
				if ($node instanceof File) {
					return $node;
				}
			} catch (\Throwable $e) {
			}
		}

		return null;
	}
}
