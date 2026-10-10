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
 *
 * With "save next to the clip" on, a finished copy is moved out of here into
 * the clip's own folder as <clip>.360.mp4 (BESIDE), an ordinary file that
 * Memories and every other app can see, and an empty <name>.beside marker is
 * left here so the job knows that clip is done -- and doesn't make it again
 * if someone deletes the copy.
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

	/** What a copy saved next to its clip is called, after the clip's name. */
	public const BESIDE = '.360.mp4';

	public static function besideName(File $master): string {
		return pathinfo($master->getName(), PATHINFO_FILENAME) . self::BESIDE;
	}

	/** The copy saved next to $master, if there is one. */
	public static function beside(File $master): ?File {
		try {
			$node = $master->getParent()->get(self::besideName($master));
		} catch (\Throwable $e) {
			return null;
		}

		return $node instanceof File ? $node : null;
	}

	/**
	 * Whether $file is itself a 360 video: an MP4 marked as one, as the copies
	 * this app saves next to their clips are, and Insta360 Studio's exports.
	 */
	public static function isSphericalVideo(File $file): bool {
		if (!\in_array($file->getMimetype(), ['video/mp4', 'video/quicktime'], true)) {
			return false;
		}
		try {
			$handle = $file->fopen('r');
		} catch (\Throwable $e) {
			return false;
		}
		if ($handle === false) {
			return false;
		}
		try {
			return SphericalTag::isSpherical($handle, $file->getSize());
		} finally {
			fclose($handle);
		}
	}

	/** A local path to $file's own bytes, or null if its storage isn't local. */
	public static function localPath(File $file): ?string {
		try {
			$storage = $file->getStorage();
			if (!$storage->isLocal()) {
				return null;
			}
			$local = $storage->getLocalFile($file->getInternalPath());
		} catch (\Throwable $e) {
			return null;
		}

		return \is_string($local) && is_file($local) ? $local : null;
	}

	/**
	 * The local path a player should stream for $file: a clip's stitched copy,
	 * or a 360 MP4's own bytes.
	 */
	public function playable(File $file): ?string {
		if (strcasecmp($file->getExtension(), 'insv') === 0) {
			$master = self::master($file);

			return $master === null ? null : $this->ready($master);
		}

		return self::isSphericalVideo($file) ? self::localPath($file) : null;
	}

	/** Record that the copy called $name now lives next to its clip. */
	public function markBeside(string $name): void {
		$root = $this->root();
		if ($root !== null) {
			@touch("$root/$name.beside");
		}
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

	/**
	 * A local path to the stitched copy, or null if there isn't one: the copy
	 * in here at the current width, or else the one saved next to the clip.
	 * That one is served only from local storage; on any other (object
	 * storage, encryption) getting a path would mean copying the whole video
	 * first, so it doesn't play from Files there, though it's still a normal
	 * file everywhere else.
	 */
	public function ready(File $file): ?string {
		$root = $this->root();
		if ($root === null) {
			return null;
		}
		$path = "$root/" . $this->nameOf($file) . '.mp4';
		if (is_file($path)) {
			return $path;
		}
		$beside = self::beside($file);

		return $beside === null ? null : self::localPath($beside);
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
		foreach (glob(($this->root() ?? '/nonexistent') . '/*.beside') ?: [] as $path) {
			$names[basename($path, '.beside')] = true;
		}

		return $names;
	}

	/** @return array{files: int, bytes: int, current: int} */
	public function stats(): array {
		$suffix = '-' . $this->settings->videoWidth();
		$files = $bytes = $current = 0;
		foreach (array_keys($this->finishedNames()) as $name) {
			$files++;
			// A copy saved next to its clip counts, but its size is the user's storage, not this cache.
			$bytes += (int)@filesize($this->root() . "/$name.mp4");
			if (str_ends_with($name, $suffix)) {
				$current++;
			}
		}

		return ['files' => $files, 'bytes' => $bytes, 'current' => $current];
	}

	/**
	 * Removes everything except a render in progress, whose files the job
	 * still needs, and the markers of copies saved next to their clips: those
	 * copies are users' files, which this doesn't touch, and dropping their
	 * markers would only have them made again on top of themselves.
	 */
	public function clear(?string $keep = null): int {
		$removed = 0;
		foreach (glob(($this->root() ?? '/nonexistent') . '/*') ?: [] as $path) {
			if (($keep !== null && str_starts_with(basename($path), $keep . '.')) || str_ends_with($path, '.beside')) {
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
		foreach (glob(($this->root() ?? '/nonexistent') . "/$fileId-*.beside") ?: [] as $path) {
			if (basename($path, '.beside') !== $keep) {
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
