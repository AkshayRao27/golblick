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
use OCP\DB\QueryBuilder\IQueryBuilder;
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
 * Each run stops after RUN_SECONDS. Files are taken newest first by
 * modification time, which sync clients carry over from the camera, so recent
 * photos are ready soonest. Files already cached at the current width are
 * skipped by name before anything is opened, so a run gets back to where the
 * last one stopped without keeping any state of its own, and a photo added
 * later is picked up by the next run.
 *
 * A file is opened through the folder of a user who has it mounted, which is
 * what makes group folder files reachable at all; the cached panorama is the
 * same whoever renders it, and it is only ever served through endpoints that
 * check the viewer's own access.
 */
final class Prerender extends TimedJob {
	private const RUN_SECONDS = 120;
	private const BATCH = 500;

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
		$cached = $this->store->cachedNames();
		$width = $this->settings->zoomWidth();
		$rendered = 0;
		$after = null;

		while (microtime(true) < $deadline) {
			$rows = $this->candidates($after);
			if ($rows === []) {
				break;
			}
			foreach ($rows as $row) {
				$after = $row;
				if (isset($cached[PanoramaStore::entryNameFor($row['fileid'], $row['etag'], $width)])) {
					continue;
				}
				if (microtime(true) >= $deadline) {
					break 2;
				}
				$file = $this->open($row['fileid']);
				if ($file === null || $this->store->isCached($file)) {
					continue;
				}
				try {
					if ($this->store->get($file) !== null) {
						$rendered++;
					}
				} catch (\Throwable $e) {
					$this->logger->warning('golblick: pre-render failed for file ' . $row['fileid'],
						['app' => 'golblick', 'exception' => $e]);
				}
			}
		}

		if ($rendered > 0) {
			$this->logger->info("golblick: pre-rendered $rendered panoramas", ['app' => 'golblick']);
		}
	}

	/**
	 * The next batch after $after, newest first.
	 *
	 * Only paths under files/ count: the data directory's own storage can hold
	 * a second, stale index of group folder files under __groupfolders/, which
	 * no user mounts.
	 *
	 * @param array{fileid: int, etag: string, mtime: int}|null $after
	 * @return list<array{fileid: int, etag: string, mtime: int}>
	 */
	private function candidates(?array $after): array {
		$qb = $this->db->getQueryBuilder();
		$qb->select('fileid', 'etag', 'mtime')
			->from('filecache')
			->where($qb->expr()->iLike('name', $qb->createNamedParameter('%.insp')))
			->andWhere($qb->expr()->like('path', $qb->createNamedParameter('files/%')))
			->andWhere($qb->expr()->eq('mimetype', $qb->createNamedParameter($this->mimeTypes->getId('image/jpeg'))))
			->orderBy('mtime', 'DESC')
			->addOrderBy('fileid', 'DESC')
			->setMaxResults(self::BATCH);
		if ($after !== null) {
			$mtime = $qb->createNamedParameter($after['mtime'], IQueryBuilder::PARAM_INT);
			$qb->andWhere($qb->expr()->orX(
				$qb->expr()->lt('mtime', $mtime),
				$qb->expr()->andX(
					$qb->expr()->eq('mtime', $mtime),
					$qb->expr()->lt('fileid', $qb->createNamedParameter($after['fileid'], IQueryBuilder::PARAM_INT)),
				),
			));
		}
		$result = $qb->executeQuery();
		$rows = [];
		while ($row = $result->fetch()) {
			$rows[] = ['fileid' => (int)$row['fileid'], 'etag' => (string)$row['etag'], 'mtime' => (int)$row['mtime']];
		}
		$result->closeCursor();

		return $rows;
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
