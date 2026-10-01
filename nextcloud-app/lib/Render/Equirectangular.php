<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Render;

use OCA\Golblick\Insta360\Calibration;
use OCA\Golblick\Insta360\LensProfile;
use OCA\Golblick\Insta360\EmbeddedPreview;
use OCA\Golblick\Insta360\FormatError;

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
	 *
	 * 🔴 It is a cross-fade about the BISECTOR of the two lenses, not a taper
	 * from each lens's own rim. Tapering from the rim leaves both weights
	 * saturated at one across the middle of the overlap, so the output there
	 * is a straight 50/50 average of two views separated by parallax and near
	 * objects come out transparent. That covered 17.9% of every OneR sphere.
	 */
	private const FEATHER_DEGREES = 3.0;

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
		?string $model = null,
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
		// Neither the rim angle nor the lens's departure from the equidistant
		// model is in the file; both are measured per camera. See LensProfile.
		[$fieldOfView, $radial] = LensProfile::for($model);
		$thetaMax = deg2rad($fieldOfView) / 2.0;
		$radialRad = array_map('deg2rad', $radial);
		$radialLast = count($radialRad) - 1;
		$perStep = (180.0 / M_PI) / LensProfile::RADIAL_STEP;
		// A few PIXELS, so the hand-over does not stair-step at small sizes,
		// but never below a minimum ANGLE. 🔴 Hiding the photometric step
		// between two lenses is a question about angle, and treating it as
		// pixels alone makes the cross-fade narrower as resolution rises --
		// backwards. At 4096 wide that gave 0.35 degrees and the seam showed
		// as a hard line across a boat deck. See render.equirectangular() in
		// the parent library, which owns the choice and the measurements.
		$feather = deg2rad(min(self::FEATHER_DEGREES, max(1.5, 4.0 * 180.0 / $height)));
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
				// Applied in the lens's own frame, after lens 1 is turned round.
				Orientation::tilt(...$calibration->tilt($index)),
				$radialRad,                 // measured correction, radians
			];
		}
		// Each lens's tilt as scalars for the pixel loop. Calibration refuses
		// anything but a pair, so both exist.
		[[$a00, $a01, $a02], [$a10, $a11, $a12], [$a20, $a21, $a22]] = $geometry[0][4];
		[[$b00, $b01, $b02], [$b10, $b11, $b12], [$b20, $b21, $b22]] = $geometry[1][4];

		// Choose where the lenses hand over before rendering; see Seam. Null
		// means it declined and the bisector is used, which is also the path
		// for anything that is not a two-lens pair.
		$delta = (count($geometry) === 2 && $width >= Seam::MIN_OUTPUT_WIDTH)
			? Seam::route($scaled, $sampleWidth, $sampleHeight, $geometry, $thetaMax, $feather, $m)
			: null;

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
				// Each lens's own-frame ray: lens 1 turned round, then the
				// lens's tilt undone (R transposed). The better-placed lens is
				// the one with the smaller angle off its own axis; hand over
				// across a band about the bisector, see FEATHER_DEGREES for
				// why not from the rim.
				// Unrolled, with the matrices hoisted: array lookups in this
				// loop cost more than the arithmetic.
				$az = $a02 * $x + $a12 * $y + $a22 * $z;
				$bz = -$b02 * $x + $b12 * $y - $b22 * $z;
				$ta = acos($az > 1.0 ? 1.0 : ($az < -1.0 ? -1.0 : $az));
				$tb = acos($bz > 1.0 ? 1.0 : ($bz < -1.0 ? -1.0 : $bz));
				if ($radialLast >= 0) {
					// Where each lens actually recorded this direction: linear
					// in the table, held flat past its end, as numpy.interp.
					$k = $ta * $perStep;
					$i = (int)$k;
					$ta += $i >= $radialLast ? $radialRad[$radialLast]
						: $radialRad[$i] + ($radialRad[$i + 1] - $radialRad[$i]) * ($k - $i);
					$k = $tb * $perStep;
					$i = (int)$k;
					$tb += $i >= $radialLast ? $radialRad[$radialLast]
						: $radialRad[$i] + ($radialRad[$i + 1] - $radialRad[$i]) * ($k - $i);
				}
				$rays = [
					[$a00 * $x + $a10 * $y + $a20 * $z, $a01 * $x + $a11 * $y + $a21 * $z, $az, $ta],
					[-$b00 * $x + $b10 * $y - $b20 * $z, -$b01 * $x + $b11 * $y - $b21 * $z, $bz, $tb],
				];
				$closest = min(
					$ta <= $thetaMax ? $ta : $thetaMax + $feather,
					$tb <= $thetaMax ? $tb : $thetaMax + $feather,
				);
				$shareA = null;
				if ($delta !== null) {
					$offset = Seam::offsetAt($delta, atan2($y, $x));
					// d = theta_0 - theta_1 with SIGNED z; $closest above is the
					// unsigned distance to the nearer lens and is not this.
					$d = 2.0 * acos(max(-1.0, min(1.0, $z))) - M_PI;
					$shareA = ($feather - ($d - $offset)) / (2.0 * $feather);
					$shareA = $shareA < 0.0 ? 0.0 : ($shareA > 1.0 ? 1.0 : $shareA);
				}
				for ($index = 0; $index < 2; ++$index) {
					[$qx, $qy, $qz, $theta] = $rays[$index];
					if ($theta > $thetaMax) {
						continue;   // outside this lens's image circle entirely
					}
					if ($shareA !== null) {
						$weight = $index === 0 ? $shareA : 1.0 - $shareA;
					} else {
						$weight = ($closest + $feather - $theta) / $feather;
						if ($weight > 1.0) {
							$weight = 1.0;
						}
					}
					if ($weight <= 0.0) {
						continue;
					}
					// Still taper at the rim: inside the overlap this is
					// already 1 wherever the cross-fade is not 0, so it only
					// matters for a lens with no partner.
					$rim = ($thetaMax - $theta) / $feather;
					if ($rim <= 0.0) {
						continue;
					}
					$weight *= $rim > 1.0 ? 1.0 : $rim;

					[$radius, $centreX, $centreY, $lensSpin] = $geometry[$index];
					$phi = atan2($qy, $qx) - $lensSpin;
					$r = $radius * $theta / $thetaMax;

					// Rows run down while world Y runs up, hence the minus on sin.
					$fx = $centreX + $r * cos($phi);
					$fy = $centreY - $r * sin($phi);
					$sx = (int)floor($fx);
					$sy = (int)floor($fy);
					if ($sx < 0 || $sy < 0 || $sx >= $sampleWidth || $sy >= $sampleHeight) {
						continue;
					}

					// Bilinear. The projection lands between source pixels
					// everywhere, and nearest-neighbour was the larger of the
					// two resolution losses: scored against a 3x render boxed
					// down to the target, RMSE falls from 5.28 to 3.26 at the
					// same output size. Matches render._sample() in the parent
					// library, which owns the choice.
					$tx = $fx - $sx;
					$ty = $fy - $sy;
					$sx1 = $sx + 1 < $sampleWidth ? $sx + 1 : $sx;
					$sy1 = $sy + 1 < $sampleHeight ? $sy + 1 : $sy;

					$w00 = (1.0 - $tx) * (1.0 - $ty) * $weight;
					$w10 = $tx * (1.0 - $ty) * $weight;
					$w01 = (1.0 - $tx) * $ty * $weight;
					$w11 = $tx * $ty * $weight;

					$c00 = imagecolorat($scaled, $sx, $sy);
					$c10 = imagecolorat($scaled, $sx1, $sy);
					$c01 = imagecolorat($scaled, $sx, $sy1);
					$c11 = imagecolorat($scaled, $sx1, $sy1);

					$sumR += (($c00 >> 16) & 0xFF) * $w00 + (($c10 >> 16) & 0xFF) * $w10
						+ (($c01 >> 16) & 0xFF) * $w01 + (($c11 >> 16) & 0xFF) * $w11;
					$sumG += (($c00 >> 8) & 0xFF) * $w00 + (($c10 >> 8) & 0xFF) * $w10
						+ (($c01 >> 8) & 0xFF) * $w01 + (($c11 >> 8) & 0xFF) * $w11;
					$sumB += ($c00 & 0xFF) * $w00 + ($c10 & 0xFF) * $w10
						+ ($c01 & 0xFF) * $w01 + ($c11 & 0xFF) * $w11;
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
		// Choose where the lenses hand over before rendering; see Seam. Null
		// means it declined and the bisector is used, which is also the path
		// for anything that is not a two-lens pair.
		$delta = (count($geometry) === 2 && $width >= Seam::MIN_OUTPUT_WIDTH)
			? Seam::route($scaled, $sampleWidth, $sampleHeight, $geometry, $thetaMax, $feather, $m)
			: null;

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
