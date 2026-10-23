<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Preview;

use OCA\Golblick\Insta360\Calibration;
use OCA\Golblick\Insta360\EmbeddedPreview;
use OCA\Golblick\Insta360\FormatError;
use OCA\Golblick\Insta360\Imu;
use OCA\Golblick\Insta360\LensProfile;
use OCA\Golblick\Insta360\Protobuf;
use OCA\Golblick\Insta360\Trailer;
use OCA\Golblick\Render\Equirectangular;
use OCA\Golblick\Render\Orientation;
use OCP\Files\File;
use OCP\Files\FileInfo;
use OCP\IImage;
use OCP\Image;
use OCP\Preview\IProviderV2;
use Psr\Log\LoggerInterface;

/**
 * Timeline thumbnails for Insta360 .insp stills.
 *
 * A .insp is a JPEG with a trailer, so it is mapped to image/jpeg (Memories
 * indexes only the image types on its own list), and this provider shares
 * that type with core's: it is tried first and returns null for anything
 * without the trailer. That ordering is not published API; if it changes,
 * core shows the unprojected lens pair. AGENT-NOTES.md, "Sharing image/jpeg
 * with Nextcloud's own provider" and "Why image/jpeg".
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
	 * Narrowed by extension, decided by content (getThumbnail checks the
	 * trailer). This runs for every JPEG in the library, and opening each one
	 * to seek to its end would cost far too much: the same deliberate
	 * exception triage makes. A .insp renamed to .jpg gets core's thumbnail of
	 * the lens pair.
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
			// Refusing is a normal outcome, not a failure: some .insp carry no
			// trailer at all.
			\OC::$server->get(LoggerInterface::class)->debug(
				'golblick: declined ' . $file->getPath() . ': ' . $e->getMessage(),
				['app' => 'golblick']
			);

			return null;
		} catch (\Throwable $e) {
			\OC::$server->get(LoggerInterface::class)->warning(
				'golblick: failed to preview ' . $file->getPath(),
				['app' => 'golblick', 'exception' => $e]
			);

			return null;
		}
	}

	/**
	 * An equirectangular frame is 2:1, so the requested box constrains both.
	 *
	 * Don't cap this at tile size: Nextcloud serves the same preview to the
	 * full-size viewer and the sphere, where 1024 for 360 degrees is a
	 * five-fold upscale. The ceiling is Nextcloud's own preview_max_x default;
	 * a tile still asks for a tile. {@see sourceFor} decides what can supply it.
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
		// nothing to project, only a colour conversion. Not upgraded to the
		// full frame when more width is asked for: projecting the lens pair
		// ourselves would buy pixels and lose the camera's seam and levelling.
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
		$calibration = Calibration::parse($text)->withMei(Protobuf::firstText($fields, Protobuf::CALIBRATION_MEI));

		[$encoded, $available] = $this->sourceFor($trailer, $handle, $preview, $width);

		$source = imagecreatefromstring($encoded);
		if ($source === false) {
			throw new FormatError('the frame is not a decodable image');
		}

		return Equirectangular::fromLensPair(
			$source,
			$calibration,
			min($width, $available),
			$this->orientationFor($file, $trailer, $fields, $calibration),
			Protobuf::firstText($fields, Protobuf::MODEL),
		);
	}

	/**
	 * The cheapest source that can supply the width asked for.
	 *
	 * A fisheye circle of diameter d spans 180 degrees, so a pair -- two
	 * circles side by side, 2d across -- samples the scene as finely as an
	 * equirectangular frame 2d wide, so the useful output width of a source is
	 * its own width. The embedded preview is 1920x960 on a OneR and an X3, the
	 * frame behind it 6080 and 11968 wide.
	 *
	 * The full frame is 18 to 72 megapixels and GD decodes to four bytes a
	 * pixel whatever the output size (AGENT-NOTES.md, "Memory"), so it is
	 * taken only when the extra width was asked for, and this steps back to
	 * the preview when it won't fit: a narrower panorama beats none.
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
			// Some stills carry no preview record at all, so this is also the
			// only route for those, and a failure is fatal when there is
			// nothing to fall back to.
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
	 * Don't read $preview->width directly: {@see EmbeddedPreview::parse}
	 * leaves it 0 for a JPEG lens pair (only the NV12 form has a header), which
	 * is every OneR and X3. getimagesizefromstring reads the JPEG header only.
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
	 * Gravity knows how the camera was held, so it fixes pitch as well as
	 * roll; the calibration knows only the sensor's mounting angle, so a shot
	 * taken tilted stays tilted. The calibration route is the fallback for a
	 * file whose whole burst carries no inertial record, or a camera whose
	 * axes nobody has measured. AGENT-NOTES.md, "Levelling routes"; the
	 * measurements are in the format notes, "Levelling".
	 */
	private function orientationFor(File $file, Trailer $trailer, array $fields, Calibration $calibration): array {
		return $this->levelling($file, $trailer, $fields, $calibration)[0];
	}

	/**
	 * The orientation, and in words which route produced it. Public so the
	 * report for GitHub issues can say what this provider actually does with a file
	 * rather than repeat the decision and risk drifting from it.
	 *
	 * @return array{array, string}
	 */
	public function levelling(File $file, Trailer $trailer, array $fields, Calibration $calibration): array {
		// Either route is then turned so the middle is the middle of Insta360 Studio's export.
		[$orientation, $route] = $this->levelled($file, $trailer, $fields, $calibration);

		return [Orientation::face($orientation, LensProfile::PHOTO_FORWARD), $route];
	}

	/**
	 * How far, in radians, facing turned this photo's panorama about the
	 * vertical: 0.5 golblick and earlier rendered it levelled but unturned, and
	 * a panorama cached then is this one shifted sideways by that much
	 * (PanoramaStore). Zero for an X5's own stitch, which is shown as the
	 * camera made it and already faces the right way.
	 *
	 * @throws FormatError
	 */
	public function facingTurn(File $file): float {
		$handle = $file->fopen('r');
		if ($handle === false) {
			throw new FormatError('could not open the file');
		}
		try {
			$trailer = Trailer::read($handle);
		} finally {
			fclose($handle);
		}
		$payload = $trailer->get(Trailer::PREVIEW);
		if ($payload !== null && EmbeddedPreview::parse($payload)->isStitched) {
			return 0.0;
		}
		$metadata = $trailer->get(Trailer::METADATA);
		$fields = $metadata === null ? [] : Protobuf::fields($metadata);
		$text = Protobuf::firstText($fields, Protobuf::CALIBRATION_EQUIDISTANT);
		if ($text === null) {
			throw new FormatError('no equidistant calibration');
		}
		[$m] = $this->levelled($file, $trailer, $fields, Calibration::parse($text));
		$f = LensProfile::PHOTO_FORWARD;
		$x = $m[0][0] * $f[0] + $m[0][1] * $f[1] + $m[0][2] * $f[2];
		$z = $m[2][0] * $f[0] + $m[2][1] * $f[1] + $m[2][2] * $f[2];

		return hypot($x, $z) < 0.2 ? 0.0 : atan2($x, $z);
	}

	/**
	 * levelling() before facing.
	 *
	 * @return array{array, string}
	 */
	private function levelled(File $file, Trailer $trailer, array $fields, Calibration $calibration): array {
		$fallback = Orientation::fromRoll($calibration->bodyRoll());
		$model = Protobuf::firstText($fields, Protobuf::MODEL);
		$route = 'gravity, from this file\'s inertial record';
		$record = $trailer->get(Trailer::IMU);
		if ($record === null && $model !== null) {
			$record = $this->burstImu($file);
			$route = 'gravity, from another frame of the same shutter press';
		}
		if ($record === null || $model === null) {
			return [$fallback, 'calibration only: no inertial record here or in the rest of the burst'];
		}
		try {
			return [Orientation::level(Imu::gravityUp($record, $model)), $route];
		} catch (FormatError $e) {
			// An unmeasured camera, an unreadable record or a reading too
			// small to be gravity. None of those is a reason to refuse the
			// file: the calibration route still corrects the mounting
			// angle, which is most of the correction on most cameras.
			return [$fallback, 'calibration only: ' . $e->getMessage()];
		}
	}

	/**
	 * The inertial record of another frame from the same shutter press: a port
	 * of imu.gravity_up_nearby in the library (docs/formats/insta360-agent-notes.md,
	 * "Borrowing the record from the same shutter press"). The
	 * camera takes one reading per press and writes it to some frames and not
	 * others, so this borrows identical bytes rather than inventing an attitude.
	 *
	 * A burst shares the timestamp and differs in sequence number, which only
	 * identifies a group within one directory, so the search never leaves the
	 * file's own folder.
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
