<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Service;

use OCP\Files\File;
use OCP\IConfig;

/**
 * Stitched copies of Insta360 videos, one per file version and width.
 *
 * ⚠️ A plain directory in the app's data folder, not IAppData. ffmpeg writes
 * the file itself, which needs a real path, and playback seeks by byte range,
 * which needs a seekable local file; a stitched copy is hundreds of megabytes,
 * too much to pass through the storage layer in either direction. So this
 * needs the data directory on local disk, which isRendering() checks (an
 * object store as primary storage has no such directory). Nextcloud's file
 * cache doesn't know about these files, and nothing here relies on it.
 *
 * Names are <fileid>-<etag>-<width>.mp4, so a changed file gets a new entry,
 * as the panorama cache does. Work in progress sits next to them under the
 * same name with .part, .log, .status, .pid and a .tables directory.
 */
final class VideoStore {
	public function __construct(
		private IConfig $config,
		private Settings $settings,
	) {
	}

	/** Whether the data directory is a local directory this can write into. */
	public function isUsable(): bool {
		if ($this->config->getSystemValue('objectstore', null) !== null) {
			return false;
		}
		$root = $this->root();

		return $root !== null && (is_dir($root) || @mkdir($root, 0770, true)) && is_writable($root);
	}

	public function root(): ?string {
		$data = rtrim((string)$this->config->getSystemValueString('datadirectory', ''), '/');
		$instance = $this->config->getSystemValueString('instanceid', '');
		if ($data === '' || $instance === '') {
			return null;
		}

		return "$data/appdata_$instance/golblick/videos";
	}

	public static function nameFor(int $fileId, string $etag, int $width): string {
		return "$fileId-$etag-$width";
	}

	public function nameOf(File $file): string {
		return self::nameFor($file->getId(), $file->getEtag(), $this->settings->videoWidth());
	}

	/**
	 * The file a clip's stitched copy is keyed on: the clip's first file.
	 * A OneR or X3 clip's second-lens file (_10_) and any clip's low-resolution
	 * copy (LRV_..._11_) play the same video, so they are resolved to their
	 * VID_..._00_ partner in the same folder. Null if there is none.
	 */
	public static function master(File $file): ?File {
		$name = $file->getName();
		if (preg_match('/^VID_\d{8}_\d{6}_00_\d+\.insv$/i', $name)) {
			return $file;
		}
		if (!preg_match('/^(?:VID|LRV)_(\d{8}_\d{6})_1[01]_(\d+)\.(?:insv|lrv)$/i', $name, $m)) {
			return null;
		}
		try {
			$partner = $file->getParent()->get('VID_' . $m[1] . '_00_' . $m[2] . '.insv');
		} catch (\Throwable $e) {
			return null;
		}

		return $partner instanceof File ? $partner : null;
	}

	/** The stitched copy's path, or null if there isn't one at the current width. */
	public function ready(File $file): ?string {
		$root = $this->root();
		if ($root === null) {
			return null;
		}
		$path = "$root/" . $this->nameOf($file) . '.mp4';

		return is_file($path) ? $path : null;
	}

	/**
	 * Every finished entry's name, as a set, so the job can skip them without opening anything.
	 *
	 * @return array<string, true>
	 */
	public function finishedNames(): array {
		$names = [];
		foreach (glob(($this->root() ?? '/nonexistent') . '/*.mp4') ?: [] as $path) {
			$name = basename($path, '.mp4');
			if (!str_ends_with($name, '.part')) {
				$names[$name] = true;
			}
		}

		return $names;
	}

	/** @return array{files: int, bytes: int, current: int} */
	public function stats(): array {
		$suffix = '-' . $this->settings->videoWidth();
		$files = $bytes = $current = 0;
		foreach (array_keys($this->finishedNames()) as $name) {
			$files++;
			$bytes += (int)@filesize($this->root() . "/$name.mp4");
			if (str_ends_with($name, $suffix)) {
				$current++;
			}
		}

		return ['files' => $files, 'bytes' => $bytes, 'current' => $current];
	}

	/** Removes everything except a render in progress, whose files the job still needs. */
	public function clear(?string $keep = null): int {
		$removed = 0;
		foreach (glob(($this->root() ?? '/nonexistent') . '/*') ?: [] as $path) {
			if ($keep !== null && str_starts_with(basename($path), $keep . '.')) {
				continue;
			}
			if (is_dir($path)) {
				self::removeDirectory($path);
			} else {
				@unlink($path);
			}
			$removed += str_ends_with($path, '.mp4') && !str_ends_with($path, '.part.mp4') ? 1 : 0;
		}

		return $removed;
	}

	/** Drops older versions or widths of the same file once a new one is finished. */
	public function dropOthers(int $fileId, string $keep): void {
		foreach (glob(($this->root() ?? '/nonexistent') . "/$fileId-*.mp4") ?: [] as $path) {
			if (basename($path, '.mp4') !== $keep && !str_ends_with($path, '.part.mp4')) {
				@unlink($path);
			}
		}
	}

	public static function removeDirectory(string $path): void {
		foreach (glob("$path/*") ?: [] as $entry) {
			@unlink($entry);
		}
		@rmdir($path);
	}
}
