<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Render;

use OCA\Golblick\Insta360\Calibration;
use OCA\Golblick\Insta360\FormatError;
use OCA\Golblick\Insta360\LensProfile;

/**
 * The projection as tables, for ffmpeg's remap filter to apply to every frame of a video.
 *
 * A port of render.remap_tables() in the parent library, which owns the
 * reasoning and has the test; the arithmetic per direction is the same as
 * Equirectangular::fromLensPair, written out plainly because this runs once
 * per video rather than once per pixel of every preview.
 *
 * Writes five PGM files into a directory: x0, y0, x1, y1 (16-bit) say which
 * pixel of each lens's OWN frame lands at each output pixel -- the lenses of
 * a OneR or X3 video are separate streams, and the X5's are separate streams
 * of one file -- and mask (8-bit) says how much of each output pixel comes
 * from lens 1. ffmpeg's remap takes the nearest pixel, so the lenses are
 * scaled down to the output's density first ({@see lensSizeFor}), which is
 * what keeps nearest sampling from shimmering.
 *
 * The hand-over is the plain cross-fade about the bisector, not a routed
 * seam: a route is chosen from one frame's content, and a video's moves.
 */
final class RemapTables {
	/** The same feather rule as photos; see render.equirectangular(). */
	private const FEATHER_DEGREES = 3.0;

	/**
	 * How big to scale each lens before remapping to $width.
	 *
	 * Matched to the output's angular density with 15% to spare: a lens circle
	 * of radius R spans half its field of view, so R / (fov/2) pixels a degree
	 * against the output's width / 360. On a 10-second OneR clip at 3840 this
	 * took the fine detail from 4.80 to 3.66 against 4.04 for golblick's own
	 * bilinear render -- the nearest-pixel excess is aliasing, which shimmers
	 * in motion -- at the same CPU cost.
	 */
	public static function lensSizeFor(Calibration $calibration, int $nativeLensSize, int $width, ?string $model): int {
		[$fieldOfView] = LensProfile::for($model);
		$scale = $calibration->scaleFor(2 * $nativeLensSize);
		$radius = $calibration->lenses[0][0] * $scale;
		$wanted = 1.15 * ($width / 360.0) * ($fieldOfView / 2.0) / $radius * $nativeLensSize;
		$size = (int)min($nativeLensSize, ceil($wanted));

		return max(64, $size + ($size % 2));
	}

	/**
	 * @param array $orientation 3x3, as for Equirectangular::fromLensPair
	 * @param int $lensSize the size each lens is scaled to before remapping
	 */
	public static function write(string $directory, Calibration $calibration, int $lensSize, int $width,
		array $orientation, ?string $model): void {
		$height = intdiv($width, 2);
		[$fieldOfView, $radial] = LensProfile::for($model);
		$thetaMax = deg2rad($fieldOfView) / 2.0;
		$radialRad = array_map('deg2rad', $radial);
		$radialLast = \count($radialRad) - 1;
		$perStep = (180.0 / M_PI) / LensProfile::RADIAL_STEP;
		$feather = deg2rad(min(self::FEATHER_DEGREES, max(1.5, 4.0 * 180.0 / $height)));
		$scale = $calibration->scaleFor(2 * $lensSize);
		$spin = deg2rad($calibration->relativeSpin());
		$m = $orientation;

		$geometry = [];
		foreach ($calibration->lenses as $index => $lens) {
			$geometry[$index] = [
				$lens[0] * $scale,
				$lens[1] * $scale - $index * $lensSize,   // in the lens's own frame
				$lens[2] * $scale,
				$index === 1 ? $spin : 0.0,
				Orientation::tilt(...$calibration->tilt($index)),
			];
		}

		$files = [];
		foreach (['x0', 'y0', 'x1', 'y1'] as $name) {
			$files[$name] = self::open("$directory/$name.pgm", "P5 $width $height 65535\n");
		}
		$files['mask'] = self::open("$directory/mask.pgm", "P5 $width $height 255\n");
		$last = $lensSize - 1;

		try {
			for ($py = 0; $py < $height; ++$py) {
				$latitude = M_PI / 2 - ($py + 0.5) / $height * M_PI;
				$cosLat = cos($latitude);
				$sinLat = sin($latitude);
				$rows = ['x0' => [], 'y0' => [], 'x1' => [], 'y1' => []];
				$mask = '';
				for ($px = 0; $px < $width; ++$px) {
					$longitude = ($px + 0.5) / $width * 2 * M_PI - M_PI;
					$ox = $cosLat * sin($longitude);
					$oy = $sinLat;
					$oz = $cosLat * cos($longitude);
					// Rows are vectors in the library, so this is the transpose:
					// for each output direction, the camera-frame direction.
					$x = $m[0][0] * $ox + $m[1][0] * $oy + $m[2][0] * $oz;
					$y = $m[0][1] * $ox + $m[1][1] * $oy + $m[2][1] * $oz;
					$z = $m[0][2] * $ox + $m[1][2] * $oy + $m[2][2] * $oz;

					$thetas = [];
					$coords = [];
					foreach ($geometry as $index => [$radius, $centreX, $centreY, $lensSpin, $t]) {
						// Lens 1 faces the other way; then undo the lens's own tilt.
						[$lx, $ly, $lz] = $index === 1 ? [-$x, $y, -$z] : [$x, $y, $z];
						$qx = $t[0][0] * $lx + $t[1][0] * $ly + $t[2][0] * $lz;
						$qy = $t[0][1] * $lx + $t[1][1] * $ly + $t[2][1] * $lz;
						$qz = $t[0][2] * $lx + $t[1][2] * $ly + $t[2][2] * $lz;
						$theta = acos($qz > 1.0 ? 1.0 : ($qz < -1.0 ? -1.0 : $qz));
						if ($radialLast >= 0) {
							$k = $theta * $perStep;
							$i = (int)$k;
							$theta += $i >= $radialLast ? $radialRad[$radialLast]
								: $radialRad[$i] + ($radialRad[$i + 1] - $radialRad[$i]) * ($k - $i);
						}
						$phi = atan2($qy, $qx) - $lensSpin;
						$r = $radius * $theta / $thetaMax;
						$thetas[$index] = $theta;
						$coords[$index] = [$centreX + $r * cos($phi), $centreY - $r * sin($phi)];
					}

					$closest = min(
						$thetas[0] <= $thetaMax ? $thetas[0] : $thetaMax + $feather,
						$thetas[1] <= $thetaMax ? $thetas[1] : $thetaMax + $feather,
					);
					$weights = [];
					for ($index = 0; $index < 2; ++$index) {
						$theta = $thetas[$index];
						if ($theta > $thetaMax) {
							$weights[$index] = 0.0;
							$rows['x' . $index][] = 0;
							$rows['y' . $index][] = 0;
							continue;
						}
						$fade = ($closest + $feather - $theta) / $feather;
						$rim = ($thetaMax - $theta) / $feather;
						$weights[$index] = max(0.0, min(1.0, $fade)) * max(0.0, min(1.0, $rim));
						$rows['x' . $index][] = max(0, min($last, (int)round($coords[$index][0])));
						$rows['y' . $index][] = max(0, min($last, (int)round($coords[$index][1])));
					}
					$total = $weights[0] + $weights[1];
					$mask .= \chr($total > 0.0 ? (int)round(255.0 * $weights[1] / $total) : 0);
				}
				foreach ($rows as $name => $values) {
					fwrite($files[$name], pack('n*', ...$values));
				}
				fwrite($files['mask'], $mask);
			}
		} finally {
			foreach ($files as $handle) {
				fclose($handle);
			}
		}
	}

	/** @return resource */
	private static function open(string $path, string $header) {
		$handle = fopen($path, 'wb');
		if ($handle === false) {
			throw new FormatError("could not write $path");
		}
		fwrite($handle, $header);

		return $handle;
	}
}
