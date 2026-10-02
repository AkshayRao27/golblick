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
use OCP\IAppConfig;

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
	/** Set with `occ config:app:set golblick zoom_width`. */
	private const DEFAULT_WIDTH = 4096;

	public function __construct(
		private IAppData $appData,
		private IAppConfig $appConfig,
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
		$width = $this->width();
		$prefix = $file->getId() . '-';
		$name = $prefix . $file->getEtag() . '-' . $width . '.jpg';

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

	private function width(): int {
		$configured = (int)$this->appConfig->getValueString('golblick', 'zoom_width', (string)self::DEFAULT_WIDTH);

		return max(1024, min(4096, $configured));
	}

	private function cacheFolder(): ISimpleFolder {
		try {
			return $this->appData->getFolder('zoom');
		} catch (NotFoundException $e) {
			return $this->appData->newFolder('zoom');
		}
	}
}
