<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Kugelblick\Preview;

use OCA\Kugelblick\Insta360\Calibration;
use OCA\Kugelblick\Insta360\EmbeddedPreview;
use OCA\Kugelblick\Insta360\FormatError;
use OCA\Kugelblick\Insta360\Protobuf;
use OCA\Kugelblick\Insta360\Trailer;
use OCA\Kugelblick\Render\Equirectangular;
use OCP\Files\File;
use OCP\Files\FileInfo;
use OCP\IImage;
use OCP\Image;
use OCP\Preview\IProviderV2;
use Psr\Log\LoggerInterface;

/**
 * Timeline thumbnails for Insta360 .insp stills.
 *
 * WHY THIS CLAIMS image/jpeg
 * --------------------------
 * A .insp *is* a JPEG: everything in front of the proprietary trailer is a
 * complete one, and PHP's own finfo identifies it as image/jpeg. Nextcloud
 * stores application/octet-stream only because its extension map has never
 * heard of .insp, so this app ships a mapping that makes the extension agree
 * with content detection rather than inventing a new type.
 *
 * That choice is what lets the files reach a photo timeline at all: Nextcloud
 * Memories selects what to index from a hardcoded list of image mimetypes, so
 * a bespoke image/x-something would be indexed by nothing, however good its
 * previews were.
 *
 * The cost is that this provider has to share image/jpeg with the core one.
 * Nextcloud orders providers by the *length* of their mimetype regex,
 * descending, so a longer pattern than core's '/image\/jpeg/' is tried first;
 * declining by returning null then hands ordinary JPEGs straight back to core.
 * ⚠️ That ordering is an implementation detail rather than published API. If
 * it ever changes the failure is graceful -- core renders the frame it finds,
 * which is the unprojected lens pair -- so this trades a wrong-looking
 * thumbnail for a hard dependency, deliberately.
 */
final class Insta360 implements IProviderV2 {
	/**
	 * Longer than core's '/image\/jpeg/', which is how this gets first refusal.
	 * See the class docstring.
	 */
	public function getMimeType(): string {
		return '/^image\/jpeg$/';
	}

	/**
	 * ⚠️ Narrowed by extension, decided by content.
	 *
	 * The project's standing rule is to detect by content, and getThumbnail
	 * does exactly that -- it checks for the trailer magic and declines if it
	 * is absent. But isAvailable() runs for *every JPEG in the library* while
	 * previews are generated, and opening each one to seek to its end would
	 * cost a great deal to find the handful that are ours. So the cheap filter
	 * comes first. This is the same deliberate exception the triage module
	 * makes, for the same reason.
	 *
	 * What it costs: a .insp renamed to .jpg gets a core thumbnail of the lens
	 * pair instead of a panorama. It is not mistaken for something else.
	 */
	public function isAvailable(FileInfo $file): bool {
		return strcasecmp($file->getExtension(), 'insp') === 0;
	}

	public function getThumbnail(File $file, int $maxX, int $maxY): ?IImage {
		try {
			$handle = $file->fopen('r');
			if ($handle === false) {
				return null;
			}

			try {
				// Content decides. An ordinary JPEG that happens to be called
				// .insp is handed back to the core provider, not guessed at.
				if (!Trailer::looksLikeOurs($handle)) {
					return null;
				}
				$trailer = Trailer::read($handle);
				$rendered = $this->render($trailer, $handle, $this->widthFor($maxX, $maxY));
			} finally {
				fclose($handle);
			}

			if ($rendered === null) {
				return null;
			}

			ob_start();
			imagepng($rendered, null, 6);
			$png = (string)ob_get_clean();

			$image = new Image();
			$image->loadFromData($png);

			return $image->valid() ? $image : null;
		} catch (FormatError $e) {
			// Refusing is a normal outcome, not a failure: six files in one
			// library of 1,415 carry no trailer at all.
			\OC::$server->get(LoggerInterface::class)->debug(
				'kugelblick: declined ' . $file->getPath() . ': ' . $e->getMessage(),
				['app' => 'kugelblick']
			);

			return null;
		} catch (\Throwable $e) {
			\OC::$server->get(LoggerInterface::class)->warning(
				'kugelblick: failed to preview ' . $file->getPath(),
				['app' => 'kugelblick', 'exception' => $e]
			);

			return null;
		}
	}

	/**
	 * An equirectangular frame is 2:1, so the requested box constrains both.
	 * Capped because the cost is per output pixel and a timeline tile is small;
	 * Nextcloud scales the result to whatever it actually wanted.
	 */
	private function widthFor(int $maxX, int $maxY): int {
		$width = min(max($maxX, 1), max($maxY, 1) * 2);

		return max(64, min($width, 1024));
	}

	/**
	 * @param resource $handle
	 */
	private function render(Trailer $trailer, $handle, int $width): ?\GdImage {
		$payload = $trailer->get(Trailer::PREVIEW);
		$preview = $payload === null ? null : EmbeddedPreview::parse($payload);

		// An X5 already stitched and levelled this on the device; there is
		// nothing to project, only a colour conversion.
		if ($preview !== null && $preview->isStitched) {
			return Equirectangular::fromNv12($preview, $width);
		}

		$metadata = $trailer->get(Trailer::METADATA);
		if ($metadata === null) {
			throw new FormatError('no metadata record (0x0101), so the lens geometry is unknown');
		}
		$text = Protobuf::firstText(Protobuf::fields($metadata), Protobuf::CALIBRATION_EQUIDISTANT);
		if ($text === null) {
			throw new FormatError('no equidistant calibration');
		}
		$calibration = Calibration::parse($text);

		// 25 of the 1,415 stills in one library carry no preview record at
		// all. Rather than hand those to the core provider -- which would
		// show the lens pair uncorrected -- project the full-resolution frame
		// instead. It is the same geometry, just twenty times the pixels, so
		// it is a fallback and not the default.
		$encoded = $preview !== null ? $preview->data : $trailer->sourceFrame($handle);
		if ($preview === null) {
			Equirectangular::refuseIfTooBigToDecode($encoded);
		}

		$source = imagecreatefromstring($encoded);
		if ($source === false) {
			throw new FormatError('the frame is not a decodable image');
		}

		return Equirectangular::fromLensPair($source, $calibration, $width);
	}

}
