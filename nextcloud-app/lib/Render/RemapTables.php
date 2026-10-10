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

	/** The ring disagreement() samples; the same as render.BAND_* in the library. */
	private const BAND_AROUND = 720;
	private const BAND_ACROSS = 13;
	private const BAND_DEGREES = 6.0;

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
	public static function lensSizeFor(Calibration $calibration, int $nativeLensSize, int $width, ?string $model,
		bool $guards = false): int {
		[$fieldOfView] = LensProfile::for($model, true, $guards);
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
		array $orientation, ?string $model, bool $guards = false): void {
		$height = intdiv($width, 2);
		$lenses = self::lenses($calibration, $lensSize, $model, $guards);
		$thetaMax = $lenses['thetaMax'];
		$feather = deg2rad(min(self::FEATHER_DEGREES, max(1.5, 4.0 * 180.0 / $height)));
		$m = $orientation;

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
					for ($index = 0; $index < 2; ++$index) {
						[$u, $v, $thetas[$index]] = self::locate($lenses, $index, $x, $y, $z);
						$coords[$index] = [$u, $v];
					}

					for ($index = 0; $index < 2; ++$index) {
						$seen = $thetas[$index] <= $thetaMax;
						$rows['x' . $index][] = $seen ? max(0, min($last, (int)round($coords[$index][0]))) : 0;
						$rows['y' . $index][] = $seen ? max(0, min($last, (int)round($coords[$index][1]))) : 0;
					}
					$mask .= \chr((int)round(255.0 * self::share($thetas, $thetaMax, $feather)));
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

	/** Lens balance: the seam strip, around and across, and the ladder of correction weights. */
	public const STRIP_AROUND = 720;
	public const STRIP_ACROSS = 16;
	public const LADDER = 64;

	/** How far from the seam the balance correction reaches before it fades to nothing, degrees. */
	private const BALANCE_REACH = 60.0;

	/**
	 * Tables for evening out the lenses, frame by frame, inside ffmpeg.
	 *
	 * The camera leaves a video's lenses unmatched, and not by a single factor:
	 * on an X3 clip lens 1 read 1.2 to 1.4 times lens 0 along the sky and 0.85
	 * to 1.03 along the ground, which is glare from the sun on one lens added
	 * to the picture, not exposure. So the difference is taken where it shows,
	 * along the seam, and spread from there:
	 *
	 * - s0x, s0y, s1x, s1y remap each lens into a strip that runs once round
	 *   the seam (STRIP_AROUND) and across the band both lenses see
	 *   (STRIP_ACROSS), so the two strips show the same directions. ffmpeg
	 *   takes their difference, averages it across, blurs it around the circle
	 *   and over a few frames.
	 * - fx, fy (a quarter of the output size; it is smooth) say, for each
	 *   output pixel, which point round the seam it is level with and how much
	 *   of the correction applies there.
	 *
	 * Each lens moves half the difference h towards the other, fading from all
	 * of it at the seam to none BALANCE_REACH degrees in. That is applied once,
	 * to the blended frame: (1 - s)(a + h) + s(b - h) is the plain blend plus
	 * (1 - 2s)h, where s is the mask's share for lens 1, so the weight here is
	 * fade * (1 - 2s), from -1 to 1. One full-size pass instead of one per lens
	 * took a 3840 render from 1.72 GB to 1.47 GB, and looks the same. It is a row of a ladder ffmpeg builds from the
	 * difference (geq), row j carrying 2j / (LADDER - 1) - 1 of it; the field
	 * is upscaled bilinearly, which smooths the rungs.
	 */
	public static function writeBalance(string $directory, Calibration $calibration, int $lensSize, int $width,
		array $orientation, ?string $model, bool $guards = false): void {
		$lenses = self::lenses($calibration, $lensSize, $model, $guards);
		$band = rad2deg($lenses['thetaMax']) - 91.0;   // a degree inside each rim
		if ($band <= 0.0) {
			throw new FormatError('the lenses do not overlap, so there is nothing to compare');
		}
		$last = $lensSize - 1;

		$files = [];
		foreach (['s0x', 's0y', 's1x', 's1y'] as $name) {
			$files[$name] = self::open("$directory/$name.pgm", sprintf("P5 %d %d 65535\n", self::STRIP_AROUND, self::STRIP_ACROSS));
		}
		try {
			for ($j = 0; $j < self::STRIP_ACROSS; ++$j) {
				$polar = deg2rad(90.0 - $band + ($j + 0.5) / self::STRIP_ACROSS * 2.0 * $band);
				$rows = ['s0x' => [], 's0y' => [], 's1x' => [], 's1y' => []];
				for ($k = 0; $k < self::STRIP_AROUND; ++$k) {
					$azimuth = 2.0 * M_PI * ($k + 0.5) / self::STRIP_AROUND;
					$x = sin($polar) * cos($azimuth);
					$y = sin($polar) * sin($azimuth);
					$z = cos($polar);
					for ($index = 0; $index < 2; ++$index) {
						[$u, $v] = self::locate($lenses, $index, $x, $y, $z);
						$rows["s{$index}x"][] = max(0, min($last, (int)round($u)));
						$rows["s{$index}y"][] = max(0, min($last, (int)round($v)));
					}
				}
				foreach ($rows as $name => $values) {
					fwrite($files[$name], pack('n*', ...$values));
				}
			}
		} finally {
			foreach ($files as $handle) {
				fclose($handle);
			}
		}

		$fieldWidth = intdiv($width, 4);
		$fieldHeight = intdiv($fieldWidth, 2);
		$reach = deg2rad(self::BALANCE_REACH);
		$thetaMax = $lenses['thetaMax'];
		// The full output's feather, so the share matches the mask.
		$feather = deg2rad(min(self::FEATHER_DEGREES, max(1.5, 4.0 * 180.0 / intdiv($width, 2))));
		$m = $orientation;
		$files = [
			'fx' => self::open("$directory/fx.pgm", "P5 $fieldWidth $fieldHeight 65535\n"),
			'fy' => self::open("$directory/fy.pgm", "P5 $fieldWidth $fieldHeight 65535\n"),
		];
		try {
			for ($py = 0; $py < $fieldHeight; ++$py) {
				$latitude = M_PI / 2 - ($py + 0.5) / $fieldHeight * M_PI;
				$rows = ['fx' => [], 'fy' => []];
				for ($px = 0; $px < $fieldWidth; ++$px) {
					$longitude = ($px + 0.5) / $fieldWidth * 2 * M_PI - M_PI;
					$ox = cos($latitude) * sin($longitude);
					$oy = sin($latitude);
					$oz = cos($latitude) * cos($longitude);
					// The transpose, as in write(): the camera-frame direction.
					$x = $m[0][0] * $ox + $m[1][0] * $oy + $m[2][0] * $oz;
					$y = $m[0][1] * $ox + $m[1][1] * $oy + $m[2][1] * $oz;
					$z = $m[0][2] * $ox + $m[1][2] * $oy + $m[2][2] * $oz;
					$azimuth = atan2($y, $x);
					$k = (int)floor(($azimuth < 0 ? $azimuth + 2 * M_PI : $azimuth) / (2 * M_PI) * self::STRIP_AROUND);
					$fade = max(0.0, 1.0 - abs(acos(max(-1.0, min(1.0, $z))) - M_PI / 2) / $reach);
					$thetas = [self::locate($lenses, 0, $x, $y, $z)[2], self::locate($lenses, 1, $x, $y, $z)[2]];
					$weight = $fade * (1.0 - 2.0 * self::share($thetas, $thetaMax, $feather));
					$row = (int)round(($weight + 1.0) / 2.0 * (self::LADDER - 1));
					$rows['fx'][] = min(self::STRIP_AROUND - 1, $k);
					$rows['fy'][] = max(0, min(self::LADDER - 1, $row));
				}
				fwrite($files['fx'], pack('n*', ...$rows['fx']));
				fwrite($files['fy'], pack('n*', ...$rows['fy']));
			}
		} finally {
			foreach ($files as $handle) {
				fclose($handle);
			}
		}
	}

	/** The pair's geometry at $lensSize, each lens in its own frame. */
	private static function lenses(Calibration $calibration, int $lensSize, ?string $model,
		bool $guards = false, ?float $fieldOfView = null): array {
		[$profileDegrees, $radial] = LensProfile::for($model, true, $guards);
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
	private static function locate(array $lenses, int $index, float $x, float $y, float $z): array {
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
