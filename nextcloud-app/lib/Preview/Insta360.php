<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Kugelblick\Preview;

use OCA\Kugelblick\Insta360\Calibration;
use OCA\Kugelblick\Insta360\EmbeddedPreview;
use OCA\Kugelblick\Insta360\FormatError;
use OCA\Kugelblick\Insta360\Imu;
use OCA\Kugelblick\Insta360\Protobuf;
use OCA\Kugelblick\Insta360\Trailer;
use OCA\Kugelblick\Render\Equirectangular;
use OCA\Kugelblick\Render\Orientation;
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
				$rendered = $this->render($file, $trailer, $handle, $this->widthFor($maxX, $maxY));
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
	 *
	 * 🔴 This used to cap at 1024 on the grounds that a timeline tile is small
	 * and the cost is per output pixel. That was right about tiles and wrong
	 * about everything else: Nextcloud serves the same preview to the full-size
	 * viewer, and the panorama viewer wraps it around a whole sphere. At 1024
	 * for 360 degrees that is 2.8 pixels per degree -- a five-fold upscale at
	 * the default field of view and eleven-fold zoomed in. It is the same
	 * mistake as cutting the lens seam because it was invisible at thumbnail
	 * size.
	 *
	 * The ceiling now matches Nextcloud's own preview_max_x default, and the
	 * cost stays proportional because Nextcloud asks for the size it wants: a
	 * tile still requests a tile. {@see sourceFor} decides what can actually
	 * supply it.
	 */
	private const MAX_WIDTH = 4096;

	private function widthFor(int $maxX, int $maxY): int {
		$width = min(max($maxX, 1), max($maxY, 1) * 2);

		return max(64, min($width, self::MAX_WIDTH));
	}

	/**
	 * @param resource $handle
	 */
	private function render(File $file, Trailer $trailer, $handle, int $width): ?\GdImage {
		$payload = $trailer->get(Trailer::PREVIEW);
		$preview = $payload === null ? null : EmbeddedPreview::parse($payload);

		// An X5 already stitched and levelled this on the device; there is
		// nothing to project, only a colour conversion.
		//
		// ⚠️ Deliberately NOT upgraded to the full frame when more width is
		// asked for. The camera's own stitch blends the seam and knows how the
		// body was held; projecting the 11904-wide lens pair ourselves would
		// buy pixels and lose both. Its 2560 is the honest ceiling for an X5.
		if ($preview !== null && $preview->isStitched) {
			return Equirectangular::fromNv12($preview, min($width, $preview->width));
		}

		$metadata = $trailer->get(Trailer::METADATA);
		if ($metadata === null) {
			throw new FormatError('no metadata record (0x0101), so the lens geometry is unknown');
		}
		$fields = Protobuf::fields($metadata);
		$text = Protobuf::firstText($fields, Protobuf::CALIBRATION_EQUIDISTANT);
		if ($text === null) {
			throw new FormatError('no equidistant calibration');
		}
		$calibration = Calibration::parse($text);

		[$encoded, $available] = $this->sourceFor($trailer, $handle, $preview, $width);

		$source = imagecreatefromstring($encoded);
		if ($source === false) {
			throw new FormatError('the frame is not a decodable image');
		}

		return Equirectangular::fromLensPair(
			$source,
			$calibration,
			min($width, $available),
			$this->orientationFor($file, $trailer, $fields, $calibration)
		);
	}

	/**
	 * The cheapest source that can supply the width asked for.
	 *
	 * A fisheye circle of diameter d spans 180 degrees, so a pair -- two
	 * circles side by side, 2d across -- samples the scene as finely as an
	 * equirectangular frame 2d wide. The useful output width of a source is
	 * therefore just its own width, which is what makes this one comparison
	 * rather than a lens calculation. Measured: the embedded preview is
	 * 1920x960 on a OneR and an X3, and the frame behind it is 6080 and 11968.
	 *
	 * ⚠️ The full frame is 18 to 72 megapixels and GD decodes to four bytes a
	 * pixel regardless of the output size, so this is the expensive path. It is
	 * taken only when the extra width was actually asked for, and it steps back
	 * to the preview rather than failing when it will not fit -- a panorama
	 * narrower than requested beats no panorama at all.
	 *
	 * @param resource $handle
	 * @return array{string, int} the encoded frame, and the width it can supply
	 */
	private function sourceFor(Trailer $trailer, $handle, ?EmbeddedPreview $preview, int $want): array {
		$embedded = $preview === null ? 0 : self::widthOf($preview);
		if ($embedded > 0 && $want <= $embedded) {
			return [$preview->data, $embedded];
		}

		try {
			// 25 of the 1,415 stills in one library carry no preview record at
			// all, so this is also the only route for those -- which is why a
			// failure here is fatal when there is nothing to fall back to.
			$frame = $trailer->sourceFrame($handle);
			Equirectangular::refuseIfTooBigToDecode($frame);
			$size = @getimagesizefromstring($frame);

			return [$frame, $size === false ? $want : $size[0]];
		} catch (FormatError $e) {
			if ($embedded <= 0) {
				throw $e;
			}

			return [$preview->data, $embedded];
		}
	}

	/**
	 * How wide a source frame is, in pixels.
	 *
	 * 🔴 {@see EmbeddedPreview::parse} leaves width and height at ZERO for a
	 * JPEG lens pair -- deliberately, because the record does not carry them
	 * and it will not invent what it has not read. Only the NV12 form declares
	 * its geometry in a header. Comparing against the raw property therefore
	 * silently answers "0" for every OneR and X3, which is every file that has
	 * a choice of source to make.
	 *
	 * getimagesizefromstring reads the JPEG header only, so this costs nothing
	 * next to a decode.
	 */
	private static function widthOf(EmbeddedPreview $preview): int {
		if ($preview->width > 0) {
			return $preview->width;
		}

		$size = @getimagesizefromstring($preview->data);

		return $size === false ? 0 : $size[0];
	}

	/**
	 * Which way is up, by the best route this file supports.
	 *
	 * ⚠️ The two routes are not equivalent and the better one is not always
	 * available. Gravity knows how the camera was actually held, so it fixes
	 * PITCH as well as roll; the calibration knows only the sensor's mounting
	 * angle, which is a constant of the camera body, so a shot taken tilted
	 * forward stays tilted.
	 *
	 * Measured against Insta360 Studio's own levelled exports, over 358 OneR
	 * stills: gravity lands the horizon within 1.2 degrees (p90 3.8), where
	 * the calibration route alone leaves a median of 9.7 and a p90 of 46.9.
	 *
	 * 🔴 It reaches a minority of files, and that limit is real rather than a
	 * gap waiting to be filled. 965 of 1,415 stills in one library carry no
	 * inertial record at all, and on those Studio's export agrees with this
	 * code's calibration-only render to 0.8 degrees -- so Studio is not
	 * levelling them either, and there is nothing further in the file to
	 * recover. The X3's axis mapping is still refused rather than guessed.
	 * Falling back is the normal case, not the exception.
	 */
	private function orientationFor(File $file, Trailer $trailer, array $fields, Calibration $calibration): array {
		$fallback = Orientation::fromRoll($calibration->bodyRoll());
		$model = Protobuf::firstText($fields, Protobuf::MODEL);
		$record = $trailer->get(Trailer::IMU);
		if ($record === null && $model !== null) {
			$record = $this->burstImu($file);
		}
		if ($record !== null && $model !== null) {
			try {
				return Orientation::level(Imu::gravityUp($record, $model));
			} catch (FormatError $e) {
				// An unmeasured camera, an unreadable record or a reading too
				// small to be gravity. None of those is a reason to refuse the
				// file: the calibration route still corrects the mounting
				// angle, which is most of the correction on most cameras.
			}
		}

		return $fallback;
	}

	/**
	 * The inertial record of another frame from the same shutter press.
	 *
	 * 🔴 Most stills carry none of their own -- 965 of 1,438 in one library --
	 * and every one of them sits in a burst or HDR bracket where another frame
	 * does. The record is not merely similar across those frames, it is
	 * IDENTICAL: on the 13 capture instants carrying three records apiece, the
	 * gravity vectors agree to 0.00 degrees over 36 frames. The camera takes one
	 * reading per shutter press and writes it to some frames and not others, so
	 * this borrows bytes rather than inventing an attitude.
	 *
	 * Measured against Insta360 Studio's own levelled exports, on 291 frames
	 * that carry no record: 1.09 degrees median, p90 1.94, 98% within 5 --
	 * against 10.43 and 52.99 for the mounting-angle fallback this replaces.
	 *
	 * ⚠️ A burst shares the timestamp and differs in sequence number, and that
	 * only identifies a group WITHIN a directory, so the search never leaves
	 * the file's own folder.
	 */
	private function burstImu(File $file): ?string {
		if (!preg_match('/^(IMG_\d{8}_\d{6})_\d{2}_\d+\.insp$/i', $file->getName(), $m)) {
			return null;
		}

		try {
			$siblings = $file->getParent()->getDirectoryListing();
		} catch (\Throwable $e) {
			return null;
		}

		// Sorted, so a cached preview and a freshly generated one cannot pick
		// different donors and disagree about the horizon.
		usort($siblings, static fn ($a, $b) => strcmp($a->getName(), $b->getName()));

		foreach ($siblings as $sibling) {
			if ($sibling->getId() === $file->getId()
				|| !preg_match('/^' . preg_quote($m[1], '/') . '_\d{2}_\d+\.insp$/i', $sibling->getName())) {
				continue;
			}
			try {
				$handle = $sibling->fopen('r');
				if ($handle === false) {
					continue;
				}
				try {
					if (!Trailer::looksLikeOurs($handle)) {
						continue;
					}
					$record = Trailer::read($handle)->get(Trailer::IMU);
					if ($record !== null) {
						return $record;
					}
				} finally {
					fclose($handle);
				}
			} catch (\Throwable $e) {
				continue;
			}
		}

		return null;
	}
}
