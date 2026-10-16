<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Preview;

use OCA\Golblick\Insta360\FormatError;
use OCA\Golblick\Render\FrameCode;
use OCA\Golblick\Service\VideoDecoder;
use OCA\Golblick\Service\VideoStore;
use OCP\Files\File;
use OCP\Files\FileInfo;
use OCP\IImage;
use OCP\Image;
use OCP\Preview\IProviderV2;
use Psr\Log\LoggerInterface;

/**
 * Thumbnails for the stitched copies saved next to their clips (*.360.mp4),
 * without the frame-number strip along their bottom edge.
 *
 * Nextcloud's own video thumbnails take a frame as it is, so every copy's
 * thumbnail had a dashed line along the bottom, in Files and in Memories.
 * This takes the same frame core would (5 s in, else 1 s, else the first)
 * and cuts the strip off. It's tried before core's provider because its
 * pattern is longer (see "Sharing image/jpeg" in AGENT-NOTES.md), and anything
 * that isn't a *.360.mp4 marked as 360° video on local storage is left to core.
 * Cutting 16 rows off a 360° video someone else made, if it has that name,
 * loses a sliver straight below the camera, which a thumbnail doesn't show.
 */
final class SphericalCopy implements IProviderV2 {
	private const MAX_WIDTH = 2048;
	/** Where core's Movie provider looks for a frame, in order. */
	private const AT = [5.0, 1.0, 0.0];

	public function __construct(
		private VideoDecoder $decoder,
	) {
	}

	public function getMimeType(): string {
		return '/^video\/mp4$/';
	}

	public function isAvailable(FileInfo $file): bool {
		return str_ends_with(strtolower($file->getName()), VideoStore::BESIDE);
	}

	public function getThumbnail(File $file, int $maxX, int $maxY): ?IImage {
		try {
			if (!VideoStore::isSphericalVideo($file)) {
				return null;
			}
			$path = VideoStore::localPath($file);
			if ($path === null) {
				return null;
			}
			$width = min(max(64, min($maxX, $maxY * 2)), self::MAX_WIDTH);
			$frame = null;
			foreach (self::AT as $at) {
				try {
					$frame = $this->decoder->equirectangularFrame($path, $at, $width, FrameCode::ROWS);
					break;
				} catch (FormatError $e) {
					// Shorter than $at, most likely; try nearer the start.
				}
			}
			if ($frame === null) {
				return null;
			}

			ob_start();
			imagejpeg($frame, null, 90);
			$image = new Image();
			$image->loadFromData((string)ob_get_clean());

			return $image->valid() ? $image : null;
		} catch (\Throwable $e) {
			\OC::$server->get(LoggerInterface::class)->warning(
				'golblick: failed to preview ' . $file->getPath(),
				['app' => 'golblick', 'exception' => $e]
			);

			return null;
		}
	}
}
