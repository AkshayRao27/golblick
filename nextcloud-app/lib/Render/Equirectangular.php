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
	 * @param \GdImage $source the dual-fisheye frame
	 * @return \GdImage an equirectangular frame, $width x $width/2
	 */
	public static function fromLensPair(
		\GdImage $source,
		Calibration $calibration,
		int $width,
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
		$spin = deg2rad($calibration->relativeSpin());
		$roll = deg2rad($calibration->bodyRoll());
		$cosRoll = cos($roll);
		$sinRoll = sin($roll);

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

				// Undo the sensor's mounting angle: a roll about the lens
				// axis, which is what puts a OneR render the right way up.
				// This is the *transpose* of the rotation -- for each output
				// direction we want the camera-frame direction that belongs
				// there, not the other way round. Applying it the other way
				// round turns a -91 degree roll into +91, i.e. 182 degrees
				// out, which renders upside down rather than merely askew.
				$rx = $x * $cosRoll + $y * $sinRoll;
				$ry = -$x * $sinRoll + $y * $cosRoll;
				$x = $rx;
				$y = $ry;

				// Pick the lens the ray is nearer the axis of. A hard seam is
				// fine at this size; feathering is for an export.
				$index = $z >= 0 ? 0 : 1;
				$lensX = $index === 1 ? -$x : $x;
				$lensZ = $index === 1 ? -$z : $z;

				[$radius, $centreX, $centreY, $lensSpin] = $geometry[$index];
				$theta = acos(max(-1.0, min(1.0, $lensZ)));
				$phi = atan2($y, $lensX) - $lensSpin;
				$r = $radius * $theta / $thetaMax;

				// Rows run down while world Y runs up, hence the minus on sin.
				$sx = (int)round($centreX + $r * cos($phi));
				$sy = (int)round($centreY - $r * sin($phi));

				$colour = 0;
				if ($sx >= 0 && $sy >= 0 && $sx < $sampleWidth && $sy < $sampleHeight) {
					$colour = imagecolorat($scaled, $sx, $sy) & 0xFFFFFF;
				}
				imagesetpixel($out, $px, $py, $colour);
			}
		}

		if ($scaled !== $source) {
			imagedestroy($scaled);
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
