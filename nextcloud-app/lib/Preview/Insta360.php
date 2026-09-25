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
	 * How far gravity may disagree with the calibration before it is refused.
	 *
	 * 🔴 The inertial record is not trustworthy everywhere, and the failures
	 * are not random -- they correlate with how large a tilt the reading
	 * claims. Rendering fifteen OneR stills grouped by that figure: every one
	 * below 40 degrees came out level, and every one above came out visibly
	 * wrong. The likely reason is that a camera being swung on a stick has
	 * linear acceleration in the median as well as gravity, which both spoils
	 * the direction and inflates the apparent tilt, so the two arrive together.
	 *
	 * ⚠️ The cost is that a genuinely steep shot is refused along with the
	 * bad readings; it keeps the calibration's roll correction, which is what
	 * it had before. Better than confidently standing it on its side.
	 */
	private const MAX_TRUSTED_TILT = 35.0;

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
		$fields = Protobuf::fields($metadata);
		$text = Protobuf::firstText($fields, Protobuf::CALIBRATION_EQUIDISTANT);
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

		return Equirectangular::fromLensPair(
			$source, $calibration, $width, self::orientationFor($trailer, $fields, $calibration)
		);
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
	 * Measured over the files that carry an inertial record: what the
	 * calibration route leaves behind is a median of 10.8 degrees on a OneR,
	 * with three quarters of files over 5 degrees. That is a visible wobble
	 * when the panorama is turned, which is what makes this worth doing.
	 *
	 * 🔴 It reaches a minority of files. 965 of 1,415 stills in one library
	 * carry no inertial record at all, and the X3's axis mapping is refused
	 * rather than guessed, so roughly a quarter of the OneR files and none of
	 * the X3 are levelled this way. Falling back is the normal case, not the
	 * exception.
	 */
	private static function orientationFor(Trailer $trailer, array $fields, Calibration $calibration): array {
		$fallback = Orientation::fromRoll($calibration->bodyRoll());
		$record = $trailer->get(Trailer::IMU);
		$model = Protobuf::firstText($fields, Protobuf::MODEL);
		if ($record !== null && $model !== null) {
			try {
				$up = Imu::gravityUp($record, $model);
				if (self::tiltDegrees($fallback, $up) <= self::MAX_TRUSTED_TILT) {
					return Orientation::level($up);
				}
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
	 * How far the gravity vector is from where the calibration puts the zenith.
	 *
	 * ⚠️ The renderer applies the transpose, so the output's zenith is
	 * (R^T . e_y)_i = sum_j R[j][i] (e_y)_j, i.e. ROW 1 of R -- not column 1.
	 */
	private static function tiltDegrees(array $rotation, array $up): float {
		$zenith = [$rotation[1][0], $rotation[1][1], $rotation[1][2]];
		$dot = $zenith[0] * $up[0] + $zenith[1] * $up[1] + $zenith[2] * $up[2];

		return rad2deg(acos(max(-1.0, min(1.0, $dot))));
	}

}
