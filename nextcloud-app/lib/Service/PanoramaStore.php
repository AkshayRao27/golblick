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

		$image = (new Insta360())->getThumbnail($file, $width, intdiv($width, 2));
		if ($image === null || !($image->resource() instanceof \GdImage)) {
			return null;
		}
		ob_start();
		imagejpeg($image->resource(), null, 90);
		$jpeg = (string)ob_get_clean();

		foreach ($folder->getDirectoryListing() as $old) {
			if (str_starts_with($old->getName(), $prefix)) {
				$old->delete();
			}
		}
		$folder->newFile($name, $jpeg);

		return $jpeg;
	}

	/** Whether this version of the file is already rendered at the current width. */
	public function isCached(File $file): bool {
		return $this->cacheFolder()->fileExists(self::entryName($file, $this->settings->zoomWidth()));
	}

	/**
	 * What the cache holds: every entry, and those at the current width (the
	 * rest are left behind by a width change until their file is rendered again
	 * or the cache is cleared).
	 *
	 * @return array{files: int, bytes: int, current: int}
	 */
	public function stats(): array {
		$suffix = '-' . $this->settings->zoomWidth() . '.jpg';
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
		return $file->getId() . '-' . $file->getEtag() . '-' . $width . '.jpg';
	}

	private function cacheFolder(): ISimpleFolder {
		try {
			return $this->appData->getFolder('zoom');
		} catch (NotFoundException $e) {
			return $this->appData->newFolder('zoom');
		}
	}
}
