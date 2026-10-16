<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\BackgroundJob;

use OCA\Golblick\AppInfo\Application;
use OCA\Golblick\Insta360\FormatError;
use OCA\Golblick\Preview\Insta360Video;
use OCA\Golblick\Service\BakeQueue;
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
use OCP\IUser;
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
		private BakeQueue $bake,
		private IAppConfig $appConfig,
		private IDBConnection $db,
		private IMimeTypeLoader $mimeTypes,
		private IUserMountCache $mounts,
		private IRootFolder $rootFolder,
		private LoggerInterface $logger,
	) {
		parent::__construct($time);
		// Shorter than any cron's period, so every pass looks in: at five
		// minutes, a five-minute cron skipped every other pass and a bake the
		// GPU finished in seconds waited twelve minutes to be collected.
		$this->setInterval(60);
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

	/** @return array{fileid: int, name: string, deadline: int, started?: int, attempts: int, guards?: bool, seam?: string, phase?: string, clip?: string, duration?: float}|null */
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
		if (($current['phase'] ?? 'render') === 'bake') {
			return $this->collectBake($current);
		}
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
					. (!empty($current['guards']) ? ' (lens guards detected)' : '')
					. (isset($current['seam']) ? ', seam: ' . $current['seam'] : ''), ['app' => 'golblick']);
				if ($this->startBake($current)) {
					return false;   // the slot stays taken until the worker is done
				}
				$this->besideClip($current['fileid'], $current['name']);
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

	/**
	 * With baking on and a GPU worker there, hand it the finished copy and
	 * keep the slot for it. Returns whether a bake was started.
	 */
	private function startBake(array $current): bool {
		if (!$this->settings->flag('video_bake')) {
			return false;
		}
		$file = $this->open($current['fileid']);
		try {
			if ($file === null || !$this->bake->start($current['name'], $file, $this->settings->videoWidth())) {
				return false;
			}
		} catch (FormatError $e) {
			$this->logger->warning('golblick: could not hand ' . $current['name'] . ' to the GPU worker: ' . $e->getMessage(), ['app' => 'golblick']);
			return false;
		}
		// As long again as the render was allowed, which is far more than a GPU needs.
		$span = max(3600, $current['deadline'] - ($current['started'] ?? $current['deadline']));
		$this->appConfig->setValueString(Application::APP_ID, 'video_current', json_encode(
			['phase' => 'bake', 'deadline' => time() + $span, 'baking' => time()] + $current));

		return true;
	}

	/**
	 * A bake that ends either way still leaves a playable copy: a failed one
	 * keeps the copy as rendered, which the player steadies itself.
	 */
	private function collectBake(array $current): bool {
		$name = $current['name'];
		$status = $this->bake->status($name);
		if ($status['state'] === 'running') {
			if (time() <= $current['deadline']) {
				return false;
			}
			$status = ['state' => 'failed', 'detail' => 'took longer than its time limit'];
		}
		if ($status['state'] === 'done') {
			try {
				$this->bake->finish($name);
				$this->logger->info("golblick: baked the steadying into $name", ['app' => 'golblick']);
			} catch (FormatError $e) {
				$this->bake->abandon($name);
				$this->logger->warning("golblick: kept $name unbaked: " . $e->getMessage(), ['app' => 'golblick']);
			}
		} else {
			$this->bake->abandon($name);
			$this->logger->warning("golblick: kept $name unbaked: " . $status['detail'], ['app' => 'golblick']);
		}
		$this->besideClip($current['fileid'], $name);
		$this->appConfig->deleteKey(Application::APP_ID, 'video_current');

		return true;
	}

	/**
	 * With "save next to the clip" on, move a finished copy into its clip's
	 * folder. A copy that can't go there stays in the app's data, still
	 * playable from Files, and the reason is logged.
	 */
	private function besideClip(int $fileId, string $name): void {
		if (!$this->settings->flag('video_beside')) {
			return;
		}
		$file = $this->open($fileId, $user);
		if ($file === null) {
			return;
		}
		try {
			$this->renderer->publish($file, $name, $user);
		} catch (FormatError $e) {
			$this->logger->warning("golblick: kept $name in app data: " . $e->getMessage(), ['app' => 'golblick']);
		}
	}

	/**
	 * Copies made before "save next to the clip" was switched on, moved over
	 * one per run, current versions only. Returns whether one was moved.
	 */
	private function moveOneBeside(): bool {
		if (!$this->settings->flag('video_beside')) {
			return false;
		}
		$width = $this->settings->videoWidth();
		$root = $this->store->root();
		foreach (glob(($root ?? '/nonexistent') . "/*-$width.mp4") ?: [] as $path) {
			$name = basename($path, '.mp4');
			if (str_ends_with($name, '.part') || !preg_match('/^(\d+)-/', $name, $m)) {
				continue;
			}
			$file = $this->open((int)$m[1]);
			if ($file === null || VideoStore::nameFor($file->getId(), $file->getEtag(), $width) !== $name) {
				continue;
			}
			$this->besideClip($file->getId(), $name);

			return true;
		}

		return false;
	}

	private function startNext(): void {
		$this->moveOneBeside();
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
				'seam' => $started['seam'],
				// For the settings page: which clip, and how long it is.
				'clip' => $file->getName(),
				'duration' => $started['duration'],
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
	 * The clips still to stitch at the current size, and their size on disk,
	 * both lens files counted: everything not done, given up on, or rendering.
	 *
	 * @return array{clips: int, bytes: int}
	 */
	public function queue(): array {
		$finished = $this->store->finishedNames();
		$failed = $this->failed();
		$current = $this->current()['name'] ?? null;
		$width = $this->settings->videoWidth();
		$clips = $bytes = 0;
		foreach ($this->candidates() as $row) {
			$name = VideoStore::nameFor($row['fileid'], $row['etag'], $width);
			if (isset($finished[$name]) || isset($failed[$name]) || $name === $current) {
				continue;
			}
			$clips++;
			$bytes += $row['size'];
		}

		return ['clips' => $clips, 'bytes' => $bytes];
	}

	/**
	 * Every clip's first file, newest first. Only under files/, as in Prerender.
	 * `size` adds the second lens file of a OneR or X3 clip, which is half of it.
	 *
	 * @return list<array{fileid: int, etag: string, size: int}>
	 */
	public function candidates(): array {
		$qb = $this->db->getQueryBuilder();
		$qb->select('fileid', 'etag', 'name', 'size', 'parent')
			->from('filecache')
			->where($qb->expr()->iLike('name', $qb->createNamedParameter('%.insv')))
			->andWhere($qb->expr()->like('path', $qb->createNamedParameter('files/%')))
			->andWhere($qb->expr()->eq('mimetype', $qb->createNamedParameter($this->mimeTypes->getId(Insta360Video::MIME))))
			->orderBy('mtime', 'DESC')
			->addOrderBy('fileid', 'DESC');
		$result = $qb->executeQuery();
		$rows = $partners = [];
		while ($row = $result->fetch()) {
			$name = (string)$row['name'];
			if (preg_match(self::MASTER, $name)) {
				$rows[] = ['fileid' => (int)$row['fileid'], 'etag' => (string)$row['etag'], 'size' => (int)$row['size'],
					'key' => $row['parent'] . '/' . strtolower(preg_replace('/_00_/', '_', $name, 1))];
			} elseif (preg_match('/^VID_\d{8}_\d{6}_10_\d+\.insv$/i', $name)) {
				$partners[$row['parent'] . '/' . strtolower(preg_replace('/_10_/', '_', $name, 1))] = (int)$row['size'];
			}
		}
		$result->closeCursor();

		return array_map(static function (array $row) use ($partners): array {
			$row['size'] += $partners[$row['key']] ?? 0;
			unset($row['key']);

			return $row;
		}, $rows);
	}

	/**
	 * Deletes the copies saved next to their clips, through the Files API so
	 * they go to the trash bin where there is one, and drops their markers, so
	 * with stitching and saving on they're made again. Only a <clip>.360.mp4
	 * next to a clip that is marked as 360° video goes: a file of the user's
	 * own that happens to have that name and isn't one is left alone.
	 *
	 * The copies exist only because Memories lists nothing else; see
	 * AGENT-NOTES.md on pulsejet/memories#1739 before building on this.
	 *
	 * @return array{removed: int, bytes: int}
	 */
	public function deleteBeside(): array {
		$removed = $bytes = 0;
		foreach ($this->besideCopies() as $fileId => $copy) {
			$size = $copy->getSize();
			try {
				$copy->delete();
			} catch (\Throwable $e) {
				$this->logger->warning('golblick: could not delete ' . $copy->getPath() . ': ' . $e->getMessage(), ['app' => 'golblick']);
				continue;
			}
			$removed++;
			$bytes += $size;
			$this->store->dropMarkers($fileId);
		}

		return ['removed' => $removed, 'bytes' => $bytes];
	}

	/**
	 * Each registered clip's copy saved next to it, if it's marked as 360°
	 * video, keyed by the clip's file id.
	 *
	 * @return \Generator<int, File>
	 */
	public function besideCopies(): \Generator {
		foreach ($this->candidates() as $row) {
			$clip = $this->open($row['fileid']);
			$copy = $clip === null ? null : VideoStore::beside($clip);
			if ($copy !== null && VideoStore::isSphericalVideo($copy)) {
				yield $row['fileid'] => $copy;
			}
		}
	}

	/** The file $id, as the first user it's mounted for sees it; $user is set to that user. */
	private function open(int $id, ?IUser &$user = null): ?File {
		foreach ($this->mounts->getMountsForFileId($id) as $mount) {
			try {
				$node = $this->rootFolder->getUserFolder($mount->getUser()->getUID())->getFirstNodeById($id);
				if ($node instanceof File) {
					$user = $mount->getUser();
					return $node;
				}
			} catch (\Throwable $e) {
			}
		}

		return null;
	}
}
