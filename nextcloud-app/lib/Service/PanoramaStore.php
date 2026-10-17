<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Service;

use OCA\Golblick\Preview\Insta360;
use OCP\Files\File;
use OCP\Files\IAppData;
use OCP\Files\NotFoundException;
use OCP\Files\SimpleFS\ISimpleFolder;

/**
 * Full-size panoramas, rendered once per file version and kept in app data.
 *
 * Two things need a panorama larger than Nextcloud's preview cap allows: the
 * Memories zoom image and the sphere viewer's texture. They share this cache,
 * so whichever runs first pays for the render.
 *
 * ⚠️ The render costs about 2.2 microseconds per output pixel on a OneR,
 * whatever the source: measured 5.7 s at 1920 wide, 11 s at 3072 and 19 s at
 * 4096. It is paid once per photo and then cached under the file's etag, so a
 * changed file gets a new entry and the stale one is dropped when it is
 * replaced. 4096 is the most the preview provider renders, and an X5 stops at
 * 2560, its own stitch.
 */
final class PanoramaStore {
	public function __construct(
		private IAppData $appData,
		private Settings $settings,
	) {
	}

	/**
	 * Narrowed by extension, like the preview provider; the render itself
	 * decides by content and returns null for anything that isn't ours.
	 */
	public static function isCandidate(File $file): bool {
		return strcasecmp($file->getExtension(), 'insp') === 0;
	}

	/** The panorama as JPEG bytes, or null if this file can't be rendered. */
	public function get(File $file): ?string {
		if (!self::isCandidate($file)) {
			return null;
		}

		$folder = $this->cacheFolder();
		$width = $this->settings->zoomWidth();
		$prefix = $file->getId() . '-';
		$name = self::entryName($file, $width);

		try {
			return $folder->getFile($name)->getContent();
		} catch (NotFoundException $e) {
		}

		$jpeg = $this->turnedFromBefore($file, $width) ?? $this->rendered($file, $width);
		if ($jpeg === null) {
			return null;
		}

		foreach ($folder->getDirectoryListing() as $old) {
			if (str_starts_with($old->getName(), $prefix)) {
				$old->delete();
			}
		}
		$folder->newFile($name, $jpeg);

		return $jpeg;
	}

	private function rendered(File $file, int $width): ?string {
		$image = (new Insta360())->getThumbnail($file, $width, intdiv($width, 2));
		if ($image === null || !($image->resource() instanceof \GdImage)) {
			return null;
		}
		ob_start();
		imagejpeg($image->resource(), null, 90);

		return (string)ob_get_clean();
	}

	/**
	 * A panorama cached before panoramas faced the way Insta360 Studio opens
	 * them, turned to face that way: null if there is none, or it can't be.
	 *
	 * The facing only turns a panorama about the vertical, which in an
	 * equirectangular frame is a sideways shift with wrap-around, so the old
	 * entry is shifted rather than rendered again: a fraction of a second in
	 * place of up to 20, over a cache that can hold a whole library. The shift
	 * is rounded to a whole column, under a tenth of a degree at 4096, and the
	 * JPEG is encoded once more.
	 */
	private function turnedFromBefore(File $file, int $width): ?string {
		$folder = $this->cacheFolder();
		$old = $file->getId() . '-' . $file->getEtag() . '-' . $width . '.jpg';
		if (!$folder->fileExists($old)) {
			return null;
		}
		try {
			$turn = (new Insta360())->facingTurn($file);
			$before = @imagecreatefromstring($folder->getFile($old)->getContent());
		} catch (\Throwable $e) {
			return null;
		}
		if ($before === false) {
			return null;
		}
		$w = imagesx($before);
		$h = imagesy($before);
		// The new frame's column c shows what the old one had at c + shift.
		$shift = ((int)round($turn / (2 * M_PI) * $w) % $w + $w) % $w;
		$after = imagecreatetruecolor($w, $h);
		imagecopy($after, $before, 0, 0, $shift, 0, $w - $shift, $h);
		if ($shift > 0) {
			imagecopy($after, $before, $w - $shift, 0, 0, 0, $shift, $h);
		}
		ob_start();
		imagejpeg($after, null, 90);

		return (string)ob_get_clean();
	}

	/** Whether this version of the file is already rendered at the current width. */
	public function isCached(File $file): bool {
		return $this->cacheFolder()->fileExists(self::entryName($file, $this->settings->zoomWidth()));
	}

	/**
	 * Every entry's name, as a set, so a caller walking many files can skip
	 * the cached ones without opening them.
	 *
	 * @return array<string, true>
	 */
	public function cachedNames(): array {
		$names = [];
		foreach ($this->cacheFolder()->getDirectoryListing() as $entry) {
			$names[$entry->getName()] = true;
		}

		return $names;
	}

	/**
	 * What the cache holds: every entry, and those at the current width (the
	 * rest are left behind by a width change until their file is rendered again
	 * or the cache is cleared).
	 *
	 * @return array{files: int, bytes: int, current: int}
	 */
	public function stats(): array {
		$suffix = '-' . $this->settings->zoomWidth() . self::VERSION . '.jpg';
		$files = $bytes = $current = 0;
		foreach ($this->cacheFolder()->getDirectoryListing() as $entry) {
			$files++;
			$bytes += $entry->getSize();
			if (str_ends_with($entry->getName(), $suffix)) {
				$current++;
			}
		}

		return ['files' => $files, 'bytes' => $bytes, 'current' => $current];
	}

	/** Drops every cached panorama; each is rendered again when next needed. */
	public function clear(): int {
		$removed = 0;
		foreach ($this->cacheFolder()->getDirectoryListing() as $entry) {
			$entry->delete();
			$removed++;
		}

		return $removed;
	}

	private static function entryName(File $file, int $width): string {
		return self::entryNameFor($file->getId(), $file->getEtag(), $width);
	}

	public static function entryNameFor(int $fileId, string $etag, int $width): string {
		return $fileId . '-' . $etag . '-' . $width . self::VERSION . '.jpg';
	}

	/**
	 * Marks entries rendered facing the way Insta360 Studio opens a photo
	 * (0.6). Entries without it are turned on their next use (turnedFromBefore).
	 */
	private const VERSION = '-f';

	private function cacheFolder(): ISimpleFolder {
		try {
			return $this->appData->getFolder('zoom');
		} catch (NotFoundException $e) {
			return $this->appData->newFolder('zoom');
		}
	}
}
