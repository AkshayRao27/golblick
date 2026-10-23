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
 * Writes six PGM files into a directory: x0, y0, x1, y1 (16-bit) say which
 * pixel of each lens's OWN frame lands at each output pixel -- the lenses of
 * a OneR or X3 video are separate streams, and the X5's are separate streams
 * of one file -- and mask (8-bit) says how much of each output pixel comes
 * from lens 1. wide (8-bit) is lens 1's share across a wider band, for the
 * lenses blurred: the copy is the mask's blend plus (mask - wide) times the
 * blurred lenses' difference (VideoRenderer::start has the filters), so a
 * brightness step between the lenses fades out across COARSE_DEGREES while
 * detail is cut across the narrow band, as in the desktop player. Where only
 * one lens sees, or near either rim, wide is the mask, so nothing is added.
 * ffmpeg's remap takes the nearest pixel, so the lenses are
 * scaled down to the output's density first ({@see lensSizeFor}), which is
 * what keeps nearest sampling from shimmering.
 *
 * The hand-over is the cross-fade about the bisector unless a SeamPlan, chosen
 * once for the whole clip, aims the lenses and routes the cut: a seam chosen
 * per frame would have to follow the content, and these are written once.
 */
final class RemapTables {
	/** The same feather rule as photos; see render.equirectangular(). */
	private const FEATHER_DEGREES = 3.0;

	/** The wide band, in the same measure as the feather; scene.SEAM_COARSE in the library. */
	private const COARSE_DEGREES = 6.0;

	/** The ring disagreement() samples; the same as render.BAND_* in the library. */
	private const BAND_AROUND = 720;
	private const BAND_ACROSS = 13;
	private const BAND_DEGREES = 6.0;

	/**
	 * How big to scale each lens before remapping to $width.
	 *
	 * Matched to the output's angular density with 15% to spare: a lens circle
	 * of radius R spans half its field of view, so R / (fov/2) pixels a degree
	 * against the output's width / 360. Any finer, and remap's nearest-pixel
	 * sampling aliases, which shimmers in motion. AGENT-NOTES.md, "Video
	 * spheres" (Pipeline), has the measurement.
	 */
	public static function lensSizeFor(Calibration $calibration, int $nativeLensSize, int $width, ?string $model,
		bool $guards = false): int {
		[$fieldOfView] = LensProfile::for($model, $guards);
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
		array $orientation, ?string $model, bool $guards = false, ?SeamPlan $plan = null): void {
		$height = intdiv($width, 2);
		$lenses = self::lenses($calibration, $lensSize, $model, $guards);
		$thetaMax = $lenses['thetaMax'];
		$feather = deg2rad(min(self::FEATHER_DEGREES, max(1.5, 4.0 * 180.0 / $height)));
		$coarse = deg2rad(self::COARSE_DEGREES);
		$m = $orientation;

		$files = [];
		foreach (['x0', 'y0', 'x1', 'y1'] as $name) {
			$files[$name] = self::open("$directory/$name.pgm", "P5 $width $height 65535\n");
		}
		$files['mask'] = self::open("$directory/mask.pgm", "P5 $width $height 255\n");
		$files['wide'] = self::open("$directory/wide.pgm", "P5 $width $height 255\n");
		$last = $lensSize - 1;

		try {
			for ($py = 0; $py < $height; ++$py) {
				$latitude = M_PI / 2 - ($py + 0.5) / $height * M_PI;
				$cosLat = cos($latitude);
				$sinLat = sin($latitude);
				$rows = ['x0' => [], 'y0' => [], 'x1' => [], 'y1' => []];
				$mask = '';
				$wide = '';
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

					[$thetas, $coords, $share, $across] = self::through($lenses, $plan, $x, $y, $z, $feather);

					for ($index = 0; $index < 2; ++$index) {
						$seen = $thetas[$index] <= $thetaMax;
						$rows['x' . $index][] = $seen ? max(0, min($last, (int)round($coords[$index][0]))) : 0;
						$rows['y' . $index][] = $seen ? max(0, min($last, (int)round($coords[$index][1]))) : 0;
					}
					$mask .= \chr((int)round(255.0 * $share));
					$wide .= \chr((int)round(255.0 * self::wide($share, $across, $thetas, $thetaMax, $feather, $coarse)));
				}
				foreach ($rows as $name => $values) {
					fwrite($files[$name], pack('n*', ...$values));
				}
				fwrite($files['mask'], $mask);
				fwrite($files['wide'], $wide);
			}
		} finally {
			foreach ($files as $handle) {
				fclose($handle);
			}
		}
	}

	/**
	 * Lens 1's share across the wide band, folded back to $share where both
	 * lenses don't see or near either rim: render._wide() in the library.
	 *
	 * @param array{float, float} $thetas
	 */
	private static function wide(float $share, float $across, array $thetas, float $thetaMax, float $feather,
		float $coarse): float {
		if ($thetas[0] > $thetaMax || $thetas[1] > $thetaMax) {
			return $share;
		}
		$wide = 1.0 - max(0.0, min(1.0, ($coarse - $across) / (2.0 * $coarse)));
		$rim = max(0.0, min(1.0, ($thetaMax - max($thetas[0], $thetas[1])) / $feather));

		return $share - ($share - $wide) * $rim;
	}

	/** The pair's geometry at $lensSize, each lens in its own frame. */
	public static function lenses(Calibration $calibration, int $lensSize, ?string $model,
		bool $guards = false, ?float $fieldOfView = null): array {
		[$profileDegrees, $radial] = LensProfile::for($model, $guards, $calibration->radial);
		$fieldOfView ??= $profileDegrees;
		$scale = $calibration->scaleFor(2 * $lensSize);
		$spin = deg2rad($calibration->relativeSpin());
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
		$radialRad = array_map('deg2rad', $radial);

		return [
			'geometry' => $geometry,
			'thetaMax' => deg2rad($fieldOfView) / 2.0,
			'radial' => $radialRad,
			'radialLast' => \count($radialRad) - 1,
			'perStep' => (180.0 / M_PI) / LensProfile::RADIAL_STEP,
		];
	}

	/**
	 * Mean |lens 0 - lens 1| in grey over a ring about the bisector, at
	 * $fieldOfView: a port of render._band_disagreement(), which owns the
	 * reasoning. The lower it is, the better the two lenses' copies of the
	 * overlap agree, which is how a lens guard is told from none.
	 *
	 * @param \GdImage $lens0 lens 0 in its own frame, square
	 * @param \GdImage $lens1 lens 1 likewise, the same size
	 */
	public static function disagreement(\GdImage $lens0, \GdImage $lens1, Calibration $calibration,
		?string $model, float $fieldOfView): ?float {
		$lenses = self::lenses($calibration, imagesx($lens0), $model, false, $fieldOfView);
		$thetaMax = $lenses['thetaMax'];
		$images = [$lens0, $lens1];
		$total = 0.0;
		$count = 0;
		for ($j = 0; $j < self::BAND_ACROSS; $j++) {
			$d = deg2rad(-self::BAND_DEGREES + 2 * self::BAND_DEGREES * $j / (self::BAND_ACROSS - 1));
			$c = cos($d / 2);
			$z = -sin($d / 2);
			for ($i = 0; $i < self::BAND_AROUND; $i++) {
				$phi = $i * 2 * M_PI / self::BAND_AROUND;
				$x = $c * cos($phi);
				$y = $c * sin($phi);
				$grey = [];
				foreach ([0, 1] as $index) {
					[$u, $v, $theta] = self::locate($lenses, $index, $x, $y, $z);
					if ($theta > $thetaMax) {
						continue 2;
					}
					$grey[$index] = self::greyAt($images[$index], $u, $v);
				}
				$total += abs($grey[0] - $grey[1]);
				$count++;
			}
		}

		return 2 * $count >= self::BAND_AROUND * self::BAND_ACROSS ? $total / $count : null;
	}

	/** Bilinear grey (the mean of R, G and B) at index-space ($u, $v), as render._sample. */
	private static function greyAt(\GdImage $image, float $u, float $v): float {
		$w = imagesx($image) - 1;
		$h = imagesy($image) - 1;
		$x0 = (int)floor($u);
		$y0 = (int)floor($v);
		$fx = $u - $x0;
		$fy = $v - $y0;
		$x0 = max(0, min($w, $x0));
		$y0 = max(0, min($h, $y0));
		$x1 = min($w, $x0 + 1);
		$y1 = min($h, $y0 + 1);
		$at = static function (int $x, int $y) use ($image): float {
			$rgb = imagecolorat($image, $x, $y);

			return ((($rgb >> 16) & 0xFF) + (($rgb >> 8) & 0xFF) + ($rgb & 0xFF)) / 3.0;
		};

		return $at($x0, $y0) * (1 - $fx) * (1 - $fy) + $at($x1, $y0) * $fx * (1 - $fy)
			+ $at($x0, $y1) * (1 - $fx) * $fy + $at($x1, $y1) * $fx * $fy;
	}

	/**
	 * Where camera-frame direction (x, y, z) lands in one lens, and how far off
	 * that lens's axis it is.
	 *
	 * @return array{float, float, float} [x, y, theta]
	 */
	public static function locate(array $lenses, int $index, float $x, float $y, float $z): array {
		[$radius, $centreX, $centreY, $lensSpin, $t] = $lenses['geometry'][$index];
		// Lens 1 faces the other way; then undo the lens's own tilt.
		[$lx, $ly, $lz] = $index === 1 ? [-$x, $y, -$z] : [$x, $y, $z];
		$qx = $t[0][0] * $lx + $t[1][0] * $ly + $t[2][0] * $lz;
		$qy = $t[0][1] * $lx + $t[1][1] * $ly + $t[2][1] * $lz;
		$qz = $t[0][2] * $lx + $t[1][2] * $ly + $t[2][2] * $lz;
		$theta = acos($qz > 1.0 ? 1.0 : ($qz < -1.0 ? -1.0 : $qz));
		$radialLast = $lenses['radialLast'];
		if ($radialLast >= 0) {
			$radial = $lenses['radial'];
			$k = $theta * $lenses['perStep'];
			$i = (int)$k;
			$theta += $i >= $radialLast ? $radial[$radialLast]
				: $radial[$i] + ($radial[$i + 1] - $radial[$i]) * ($k - $i);
		}
		$phi = atan2($qy, $qx) - $lensSpin;
		$r = $radius * $theta / $lenses['thetaMax'];

		return [$centreX + $r * cos($phi), $centreY - $r * sin($phi), $theta];
	}

	/**
	 * Where camera-frame direction (x, y, z) lands in each lens, how much of
	 * it comes from lens 1, and how far past the hand-over it is (in the
	 * measure the feather is in): as render.remap_tables(), with or without a
	 * clip's seam plan. With one, each lens looks at the planned parallax and
	 * the hand-over follows the planned route; the weights are a photo's
	 * routed seam's.
	 *
	 * @return array{array{float, float}, array{array{float, float}, array{float, float}}, float, float}
	 */
	private static function through(array $lenses, ?SeamPlan $plan, float $x, float $y, float $z, float $feather): array {
		$thetaMax = $lenses['thetaMax'];
		$d = 0.0;
		$phi = 0.0;
		$parallax = 0.0;
		if ($plan !== null) {
			$d = 2.0 * acos(max(-1.0, min(1.0, $z))) - M_PI;
			$phi = atan2($y, $x);
			$parallax = $plan->parallaxAt($d, $phi);
		}
		$thetas = [];
		$coords = [];
		for ($index = 0; $index < 2; ++$index) {
			[$lx, $ly, $lz] = $parallax === 0.0 ? [$x, $y, $z] : SeamPlan::aim($x, $y, $z, $parallax, $plan->direction, $index);
			[$u, $v, $thetas[$index]] = self::locate($lenses, $index, $lx, $ly, $lz);
			$coords[$index] = [$u, $v];
		}
		if ($plan === null) {
			$across = min($thetas[0], $thetaMax + $feather) - min($thetas[1], $thetaMax + $feather);

			return [$thetas, $coords, self::share($thetas, $thetaMax, $feather), $across];
		}
		$across = $d - Seam::offsetAt($plan->offset, $phi);
		$toFirst = max(0.0, min(1.0, ($feather - $across) / (2.0 * $feather)));
		$weights = [];
		foreach ($thetas as $index => $theta) {
			$weights[$index] = $theta > $thetaMax ? 0.0
				: ($index === 0 ? $toFirst : 1.0 - $toFirst) * max(0.0, min(1.0, ($thetaMax - $theta) / $feather));
		}
		$total = $weights[0] + $weights[1];

		return [$thetas, $coords, $total > 0.0 ? $weights[1] / $total : 0.0, $across];
	}

	/**
	 * How much of an output pixel comes from lens 1, 0 to 1, from how far off
	 * each lens's axis it is: the cross-fade about the bisector, tapered at
	 * each rim.
	 *
	 * @param array{float, float} $thetas
	 */
	private static function share(array $thetas, float $thetaMax, float $feather): float {
		$closest = min(
			$thetas[0] <= $thetaMax ? $thetas[0] : $thetaMax + $feather,
			$thetas[1] <= $thetaMax ? $thetas[1] : $thetaMax + $feather,
		);
		$weights = [];
		foreach ($thetas as $index => $theta) {
			if ($theta > $thetaMax) {
				$weights[$index] = 0.0;
				continue;
			}
			$fade = ($closest + $feather - $theta) / $feather;
			$rim = ($thetaMax - $theta) / $feather;
			$weights[$index] = max(0.0, min(1.0, $fade)) * max(0.0, min(1.0, $rim));
		}
		$total = $weights[0] + $weights[1];

		return $total > 0.0 ? $weights[1] / $total : 0.0;
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
