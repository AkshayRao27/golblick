<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Kugelblick\Render;

use OCA\Kugelblick\Insta360\Calibration;
use OCA\Kugelblick\Insta360\EmbeddedPreview;
use OCA\Kugelblick\Insta360\FormatError;

/**
 * Projects a dual-fisheye pair into an equirectangular thumbnail, with GD.
 *
 * GD only, on purpose. It is already a Nextcloud requirement, so a 360 preview
 * costs the administrator no new server-side dependency -- which is the whole
 * reason this is a reimplementation in PHP rather than a call out to the
 * Python library. Measured at roughly 100 ms for a 512x256 thumbnail.
 *
 * The geometry is the equidistant model: each lens maps angle from its axis
 * linearly to radius in its image circle. docs/formats/insta360.md owns what
 * is measured and what is fitted.
 */
final class Equirectangular {
	/**
	 * Full angle each lens sees, in degrees.
	 *
	 * ⚠️ Not carried in the file. Recovered by scoring: 194 on a OneR and X5,
	 * 192 on an X3. The difference is worth about a degree of seam placement
	 * at thumbnail size, so one default is used rather than a model lookup --
	 * a model table here would be a second place to keep that fact.
	 */
	private const FIELD_OF_VIEW = 194.0;

	/**
	 * Sampling the source at roughly the output resolution is enough; going
	 * finer costs time and changes nothing visible at thumbnail size.
	 */
	private const MIN_SOURCE_WIDTH = 480;

	/**
	 * Width of the cross-fade between the two lenses, in degrees.
	 *
	 * The lenses see 194 degrees, so they overlap by 14 and both of them have
	 * a real view of the scene in that band. Matches the default in
	 * render.equirectangular() in the parent library, which owns the choice.
	 *
	 * ⚠️ This was originally a hard cut, on the reasoning that a seam is
	 * invisible at thumbnail size. That was wrong, because Nextcloud serves
	 * this same preview at full viewer resolution: measured on a 1024px
	 * render, the two seam columns were the sharpest in the whole frame, at
	 * 6.6x and 4.1x the median column gradient.
	 */
	private const FEATHER_DEGREES = 5.0;

	/**
	 * Refuse a full-resolution frame that will not fit in memory.
	 *
	 * ⚠️ This guards the *fallback* path only. The embedded preview is a couple
	 * of megapixels and always fits; the full frame is 18 to 72, and GD decodes
	 * to four bytes a pixel whatever size the output is, with no way to decode
	 * at reduced scale.
	 *
	 * 🔴 It has to be a check and not a try/catch, because exhausting the PHP
	 * memory limit is a fatal error: it takes the whole request down rather
	 * than raising something this class could catch and decline on. Measured on
	 * a real server, an 18.5 MP frame peaked at 89 MB, which is already over
	 * what a 128 MB limit leaves once the framework is loaded.
	 *
	 * Nextcloud's own guard is the same shape -- see checkImageMemory() in
	 * lib/private/Image.php, which compares width * height * 4 against
	 * preview_max_memory.
	 */
	public static function refuseIfTooBigToDecode(string $encoded): void {
		$size = @getimagesizefromstring($encoded);
		if ($size === false) {
			return;   // let imagecreatefromstring be the one to complain
		}

		$limit = self::memoryLimitBytes();
		if ($limit <= 0) {
			return;   // unlimited
		}

		// Four bytes a pixel for the truecolour buffer, plus the encoded
		// string we are already holding, plus a little headroom.
		$needed = $size[0] * $size[1] * 4 + \strlen($encoded);
		$spare = $limit - memory_get_usage(true);
		if ($needed > $spare * 0.9) {
			throw new FormatError(sprintf(
				'the full-resolution frame is %.1f MP and needs about %d MB to decode, '
					. 'but only %d MB is left of the %d MB memory limit; '
					. 'raise memory_limit to render this file',
				$size[0] * $size[1] / 1e6,
				(int)($needed / 1048576),
				(int)($spare / 1048576),
				(int)($limit / 1048576),
			));
		}
	}

	/** The PHP memory limit in bytes, or -1 when it is unlimited. */
	private static function memoryLimitBytes(): int {
		$raw = trim((string)ini_get('memory_limit'));
		if ($raw === '' || $raw === '-1') {
			return -1;
		}

		$value = (int)$raw;
		return match (strtolower(substr($raw, -1))) {
			'g' => $value * 1024 * 1024 * 1024,
			'm' => $value * 1024 * 1024,
			'k' => $value * 1024,
			default => $value,
		};
	}

	/**
	 * @param \GdImage $source the dual-fisheye frame
	 * @return \GdImage an equirectangular frame, $width x $width/2
	 */
	public static function fromLensPair(
		\GdImage $source,
		Calibration $calibration,
		int $width,
		?array $orientation = null,
	): \GdImage {
		$height = intdiv($width, 2);
		$sourceWidth = imagesx($source);
		$sourceHeight = imagesy($source);

		// Downscale first: imagescale runs at C speed and prefilters, which is
		// why nearest-neighbour sampling below is good enough.
		$targetWidth = max($width, self::MIN_SOURCE_WIDTH);
		$scaled = $source;
		$shrink = 1.0;
		if ($targetWidth < $sourceWidth) {
			$scaledHeight = (int)round($sourceHeight * $targetWidth / $sourceWidth);
			$candidate = imagescale($source, $targetWidth, $scaledHeight, IMG_BILINEAR_FIXED);
			if ($candidate !== false) {
				$scaled = $candidate;
				$shrink = $targetWidth / $sourceWidth;
			}
		}
		$sampleWidth = imagesx($scaled);
		$sampleHeight = imagesy($scaled);

		$scale = $calibration->scaleFor($sourceWidth) * $shrink;
		$thetaMax = deg2rad(self::FIELD_OF_VIEW) / 2.0;
		$cosThetaMax = cos($thetaMax);
		$feather = deg2rad(self::FEATHER_DEGREES);
		$spin = deg2rad($calibration->relativeSpin());

		// Which way is up. Falling back to the calibration's mounting angle
		// corrects roll only; an orientation passed in has usually come from
		// the inertial record and corrects pitch as well.
		$m = $orientation ?? Orientation::fromRoll($calibration->bodyRoll());
		// Hoisted, and TRANSPOSED: for each output direction we want the
		// camera-frame direction that belongs there, not the other way round.
		// Applying it the other way turns a -91 degree roll into +91, i.e. 182
		// degrees out, which renders upside down rather than merely askew.
		[$m00, $m01, $m02] = [$m[0][0], $m[0][1], $m[0][2]];
		[$m10, $m11, $m12] = [$m[1][0], $m[1][1], $m[1][2]];
		[$m20, $m21, $m22] = [$m[2][0], $m[2][1], $m[2][2]];

		$geometry = [];
		foreach ($calibration->lenses as $index => $lens) {
			$geometry[$index] = [
				$lens[0] * $scale,          // radius
				$lens[1] * $scale,          // centre x
				$lens[2] * $scale,          // centre y
				$index === 1 ? $spin : 0.0, // only the relative spin is recoverable
			];
		}

		$out = imagecreatetruecolor($width, $height);
		if ($out === false) {
			throw new FormatError('could not allocate the output image');
		}

		for ($py = 0; $py < $height; ++$py) {
			$latitude = M_PI / 2 - ($py + 0.5) / $height * M_PI;
			$cosLat = cos($latitude);
			$sinLat = sin($latitude);

			for ($px = 0; $px < $width; ++$px) {
				$longitude = ($px + 0.5) / $width * 2 * M_PI - M_PI;
				$x = $cosLat * sin($longitude);
				$y = $sinLat;
				$z = $cosLat * cos($longitude);

				// Turn the scene into the camera's frame, using the
				// transposed orientation hoisted above.
				$rx = $m00 * $x + $m10 * $y + $m20 * $z;
				$ry = $m01 * $x + $m11 * $y + $m21 * $z;
				$rz = $m02 * $x + $m12 * $y + $m22 * $z;
				$x = $rx;
				$y = $ry;
				$z = $rz;

				// Take both lenses wherever both can see, and cross-fade.
				// Outside the overlap band only one of them contributes, so
				// this costs a second sample on roughly the 8% of pixels near
				// the seam and nothing anywhere else.
				$sumR = $sumG = $sumB = 0.0;
				$sumW = 0.0;
				for ($index = 0; $index < 2; ++$index) {
					$lensZ = $index === 1 ? -$z : $z;
					if ($lensZ < $cosThetaMax) {
						continue;   // outside this lens's cone entirely
					}
					$theta = acos(max(-1.0, min(1.0, $lensZ)));
					// Taper to nothing at the rim, where the lens sees worst.
					$weight = ($thetaMax - $theta) / $feather;
					if ($weight <= 0.0) {
						continue;
					}
					if ($weight > 1.0) {
						$weight = 1.0;
					}

					$lensX = $index === 1 ? -$x : $x;
					[$radius, $centreX, $centreY, $lensSpin] = $geometry[$index];
					$phi = atan2($y, $lensX) - $lensSpin;
					$r = $radius * $theta / $thetaMax;

					// Rows run down while world Y runs up, hence the minus on sin.
					$sx = (int)round($centreX + $r * cos($phi));
					$sy = (int)round($centreY - $r * sin($phi));
					if ($sx < 0 || $sy < 0 || $sx >= $sampleWidth || $sy >= $sampleHeight) {
						continue;
					}

					$c = imagecolorat($scaled, $sx, $sy);
					$sumR += (($c >> 16) & 0xFF) * $weight;
					$sumG += (($c >> 8) & 0xFF) * $weight;
					$sumB += ($c & 0xFF) * $weight;
					$sumW += $weight;
				}

				$colour = 0;
				if ($sumW > 0.0) {
					$colour = ((int)round($sumR / $sumW) << 16)
						| ((int)round($sumG / $sumW) << 8)
						| (int)round($sumB / $sumW);
				}
				imagesetpixel($out, $px, $py, $colour);
			}
		}

		return $out;
	}

	/**
	 * Convert an NV12 plane straight to an image at the requested size.
	 *
	 * Sampling the plane directly rather than materialising every pixel and
	 * scaling down: an X5's stitch is 2560x1280, so that is 3.2M GD pixel
	 * writes avoided for a thumbnail that needs a hundred thousand.
	 */
	public static function fromNv12(EmbeddedPreview $preview, int $width): \GdImage {
		$height = intdiv($width, 2);
		$out = imagecreatetruecolor($width, $height);
		if ($out === false) {
			throw new FormatError('could not allocate the output image');
		}

		$data = $preview->data;
		$sourceWidth = $preview->width;
		$sourceHeight = $preview->height;
		$chroma = $sourceWidth * $sourceHeight;

		for ($py = 0; $py < $height; ++$py) {
			$sy = (int)(($py + 0.5) * $sourceHeight / $height);
			$lumaRow = $sy * $sourceWidth;
			$chromaRow = $chroma + ($sy >> 1) * $sourceWidth;

			for ($px = 0; $px < $width; ++$px) {
				$sx = (int)(($px + 0.5) * $sourceWidth / $width);
				$luma = \ord($data[$lumaRow + $sx]);
				$pair = $chromaRow + (($sx >> 1) << 1);
				$u = \ord($data[$pair]) - 128;
				$v = \ord($data[$pair + 1]) - 128;

				// BT.601, which is what the cameras measured so far encode against.
				$r = self::clamp($luma + 1.402 * $v);
				$g = self::clamp($luma - 0.344136 * $u - 0.714136 * $v);
				$b = self::clamp($luma + 1.772 * $u);
				imagesetpixel($out, $px, $py, ($r << 16) | ($g << 8) | $b);
			}
		}

		return $out;
	}

	private static function clamp(float $value): int {
		return (int)max(0, min(255, (int)$value));
	}
}
