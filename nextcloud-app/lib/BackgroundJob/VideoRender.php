<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\BackgroundJob;

use OCA\Golblick\AppInfo\Application;
use OCA\Golblick\Insta360\FormatError;
use OCA\Golblick\Preview\Insta360Video;
use OCA\Golblick\Service\Settings;
use OCA\Golblick\Service\VideoRenderer;
use OCA\Golblick\Service\VideoStore;
use OCP\AppFramework\Utility\ITimeFactory;
use OCP\BackgroundJob\TimedJob;
use OCP\Files\Config\IUserMountCache;
use OCP\Files\File;
use OCP\Files\IMimeTypeLoader;
use OCP\Files\IRootFolder;
use OCP\IAppConfig;
use OCP\IDBConnection;
use Psr\Log\LoggerInterface;

/**
 * Renders stitched copies of Insta360 videos, one at a time, newest first.
 *
 * Off by default. A render takes hours for a long clip, far longer than a
 * cron run, so this only ever starts one (VideoRenderer runs ffmpeg detached
 * at the lowest priority) and on each later run checks whether it has
 * finished; then it moves the result into place and starts the next. What is
 * running is kept in app config, so a run picks up where the last one left
 * off; a render that disappeared without finishing (a restart) is tried once
 * more, and one that fails twice, or a file that can't be rendered at all,
 * is remembered and skipped until the cache is cleared.
 *
 * Only clips' first files: a OneR or X3 clip's _00_ file (its _10_ partner
 * is read alongside it), and an X5's only file. Proxies (LRV_) are skipped.
 * Files are opened through a user who has them mounted, as Prerender does.
 */
final class VideoRender extends TimedJob {
	private const MASTER = '/^VID_\d{8}_\d{6}_00_\d+\.insv$/i';

	public function __construct(
		ITimeFactory $time,
		private Settings $settings,
		private VideoStore $store,
		private VideoRenderer $renderer,
		private IAppConfig $appConfig,
		private IDBConnection $db,
		private IMimeTypeLoader $mimeTypes,
		private IUserMountCache $mounts,
		private IRootFolder $rootFolder,
		private LoggerInterface $logger,
	) {
		parent::__construct($time);
		$this->setInterval(5 * 60);
		$this->setTimeSensitivity(self::TIME_INSENSITIVE);
	}

	protected function run($argument): void {
		$current = $this->current();
		if ($current !== null && !$this->collect($current)) {
			return;   // still rendering
		}
		if (!$this->settings->flag('video_render') || !$this->store->isUsable()) {
			return;
		}
		$this->startNext();
	}

	/** @return array{fileid: int, name: string, deadline: int, started?: int, attempts: int, guards?: bool}|null */
	public function current(): ?array {
		$state = json_decode($this->appConfig->getValueString(Application::APP_ID, 'video_current', ''), true);

		return \is_array($state) ? $state : null;
	}

	/** @return array<string, string> entry name => why it was given up on */
	public function failed(): array {
		$failed = json_decode($this->appConfig->getValueString(Application::APP_ID, 'video_failed', '{}'), true);

		return \is_array($failed) ? $failed : [];
	}

	/** Forget the failures, so they are tried again (the settings page does this when clearing). */
	public function forgetFailures(): void {
		$this->appConfig->deleteKey(Application::APP_ID, 'video_failed');
	}

	/** Returns whether the slot is free now. */
	private function collect(array $current): bool {
		$status = $this->renderer->status($current['name']);
		if ($status['state'] === 'running') {
			if (time() <= $current['deadline']) {
				return false;
			}
			$this->renderer->abandon($current['name']);
			$status = ['state' => 'failed', 'detail' => 'took longer than its time limit and was stopped'];
		}

		if ($status['state'] === 'done') {
			try {
				$this->renderer->finish($current['name'], $current['fileid']);
				$this->logger->info('golblick: stitched video ' . $current['name']
					. (!empty($current['guards']) ? ' (lens guards detected)' : ''), ['app' => 'golblick']);
			} catch (FormatError $e) {
				$this->fail($current['name'], $e->getMessage());
			}
		} elseif ($status['state'] === 'lost' && $current['attempts'] < 2) {
			$this->renderer->abandon($current['name']);
			$this->appConfig->setValueString(Application::APP_ID, 'video_retry', $current['name']);
		} else {
			$this->renderer->abandon($current['name']);
			$this->fail($current['name'], $status['detail']);
		}
		$this->appConfig->deleteKey(Application::APP_ID, 'video_current');

		return true;
	}

	private function startNext(): void {
		$finished = $this->store->finishedNames();
		$failed = $this->failed();
		$width = $this->settings->videoWidth();
		$retry = $this->appConfig->getValueString(Application::APP_ID, 'video_retry', '');

		foreach ($this->candidates() as $row) {
			$name = VideoStore::nameFor($row['fileid'], $row['etag'], $width);
			if (isset($finished[$name]) || isset($failed[$name])) {
				continue;
			}
			$file = $this->open($row['fileid']);
			if ($file === null) {
				continue;
			}
			try {
				$started = $this->renderer->start($file);
			} catch (\Throwable $e) {
				$this->fail($name, $e->getMessage());
				continue;   // nothing was started; try the next one
			}
			$this->appConfig->setValueString(Application::APP_ID, 'video_current', json_encode([
				'fileid' => $row['fileid'],
				'name' => $started['name'],
				'deadline' => $started['deadline'],
				'started' => time(),
				'attempts' => $retry === $started['name'] ? 2 : 1,
				'guards' => $started['guards'],
			]));
			$this->appConfig->deleteKey(Application::APP_ID, 'video_retry');

			return;
		}
	}

	private function fail(string $name, string $why): void {
		$failed = $this->failed();
		$failed[$name] = substr($why, 0, 300);
		$this->appConfig->setValueString(Application::APP_ID, 'video_failed', json_encode($failed));
		$this->logger->warning("golblick: could not stitch video $name: $why", ['app' => 'golblick']);
	}

	/**
	 * Every clip's first file, newest first. Only under files/, as in Prerender.
	 *
	 * @return list<array{fileid: int, etag: string}>
	 */
	public function candidates(): array {
		$qb = $this->db->getQueryBuilder();
		$qb->select('fileid', 'etag', 'name')
			->from('filecache')
			->where($qb->expr()->iLike('name', $qb->createNamedParameter('%.insv')))
			->andWhere($qb->expr()->like('path', $qb->createNamedParameter('files/%')))
			->andWhere($qb->expr()->eq('mimetype', $qb->createNamedParameter($this->mimeTypes->getId(Insta360Video::MIME))))
			->orderBy('mtime', 'DESC')
			->addOrderBy('fileid', 'DESC');
		$result = $qb->executeQuery();
		$rows = [];
		while ($row = $result->fetch()) {
			if (preg_match(self::MASTER, (string)$row['name'])) {
				$rows[] = ['fileid' => (int)$row['fileid'], 'etag' => (string)$row['etag']];
			}
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
