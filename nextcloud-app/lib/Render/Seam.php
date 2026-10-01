<?php

declare(strict_types=1);

namespace OCA\Golblick\Render;

use OCA\Golblick\Insta360\Calibration;

/**
 * Where the two lenses should hand over.
 *
 * Leaving the hand-over on the bisector -- the great circle equidistant from
 * both lenses -- cuts straight through whatever happens to sit there. For a
 * subject about a metre from the camera the two lenses put it at visibly
 * different angles, so the halves do not line up and no blend width closes it.
 *
 * Route it instead: parametrise the seam by d = theta_0 - theta_1 against the
 * azimuth about the lens axis, where d = 0 is the bisector, and pick the offset
 * per azimuth that keeps to territory the lenses already agree on -- which is
 * where nothing is close enough for parallax to separate the views. That is a
 * minimum-cost path and a dynamic program finds it, with nothing in it that can
 * fail silently.
 *
 * A port of the same thing in render._seam_offset() in the parent library,
 * which owns the choice; the two run the same algorithm deliberately.
 */
final class Seam {
	public const COLUMNS = 256;
	private const ROWS = 48;

	/**
	 * Width of the probe render the seam is chosen from.
	 *
	 * 🔴 It has to be this big. Measured across nine frames, a grid built at
	 * 2048 wide improves every one of them and never by less than 7 per cent;
	 * at 1024 one frame loses 25 per cent and at 512 two lose up to 30. The
	 * cost landscape holds many near-equal paths, so a thin grid picks one by
	 * noise, and a badly placed seam is worse than not moving it at all.
	 *
	 * ⚠️ An earlier 384 saw about half a sample per bin against a 512 x 64 grid,
	 * left it mostly empty, and made the port DECLINE on a frame the library
	 * routed. The band is only about 11 per cent of the sphere, so the useful
	 * sample count is a ninth of the probe's pixels.
	 */
	private const PROBE_WIDTH = 2048;

	/** Below this output width the seam is not visible and is not worth the pass. */
	public const MIN_OUTPUT_WIDTH = 1024;

	/**
	 * Below this mean disagreement (0-255) the lenses already agree along the
	 * bisector, so there is nothing to route around and the straight seam is
	 * the better answer for being the simpler one.
	 */
	private const FLOOR = 2.0;

	/** Route only for a material gain, not for a rounding difference. */
	private const MARGIN = 0.9;

	/**
	 * @param array<int, array{float, float, float, float, array<int, array<int, float>>, float[]}> $geometry
	 * @param array<int, array<int, float>> $m transposed orientation
	 * @return float[]|null one offset in radians per azimuth column, or null to
	 *                      hand over on the bisector
	 */
	public static function route(
		\GdImage $scaled,
		int $sampleWidth,
		int $sampleHeight,
		array $geometry,
		float $thetaMax,
		float $feather,
		array $m,
	): ?array {
		$room = (2.0 * $thetaMax - M_PI) - 2.0 * $feather;
		if ($room <= 0.0) {
			return null;
		}

		$grid = self::cost($scaled, $sampleWidth, $sampleHeight, $geometry, $thetaMax, $room, $m);
		if ($grid === null) {
			return null;
		}
		$wide = self::widen($grid, $feather, $room);
		$path = self::cheapestCycle($wide);
		if ($path === null) {
			return null;
		}

		// 🔴 The test needs a margin AND a floor. Asking only whether the route
		// is cheaper than the straight line can never decline: the search
		// minimises over connected paths and the bisector is one of them, so
		// its optimum is always at least as good. Without both, a featureless
		// scene gets a seam that wanders after noise, for nothing.
		$middle = intdiv(self::ROWS - 1, 2);
		$routed = self::meanAlong($wide, $path);
		$straight = self::meanAlong($wide, array_fill(0, self::COLUMNS, $middle));
		if ($routed === null || $straight === null || $straight < self::FLOOR) {
			return null;
		}
		if ($routed >= self::MARGIN * $straight) {
			return null;
		}

		// Smooth a little: the grid is coarse and a jagged seam is its own artefact.
		$smooth = [];
		for ($c = 0; $c < self::COLUMNS; ++$c) {
			$sum = 0.0;
			for ($k = -4; $k <= 4; ++$k) {
				$sum += $path[($c + $k + self::COLUMNS) % self::COLUMNS];
			}
			$smooth[$c] = $sum / 9.0;
		}

		$delta = [];
		for ($c = 0; $c < self::COLUMNS; ++$c) {
			$delta[$c] = $smooth[$c] / (self::ROWS - 1) * (2.0 * $room) - $room;
		}
		return $delta;
	}

	/**
	 * Mean |lensA - lensB| binned by (offset from the bisector, azimuth).
	 *
	 * @return array<int, array<int, float>>|null rows of columns, INF where the
	 *                                            seam cannot go
	 */
	private static function cost(
		\GdImage $scaled,
		int $sampleWidth,
		int $sampleHeight,
		array $geometry,
		float $thetaMax,
		float $room,
		array $m,
	): ?array {
		$total = array_fill(0, self::ROWS, array_fill(0, self::COLUMNS, 0.0));
		$count = array_fill(0, self::ROWS, array_fill(0, self::COLUMNS, 0));
		$seen = 0;

		$width = self::PROBE_WIDTH;
		$height = intdiv($width, 2);
		[$m00, $m01, $m02] = [$m[0][0], $m[0][1], $m[0][2]];
		[$m10, $m11, $m12] = [$m[1][0], $m[1][1], $m[1][2]];
		[$m20, $m21, $m22] = [$m[2][0], $m[2][1], $m[2][2]];

		for ($py = 0; $py < $height; ++$py) {
			$latitude = M_PI / 2 - ($py + 0.5) / $height * M_PI;
			$cosLat = cos($latitude);
			$sinLat = sin($latitude);
			for ($px = 0; $px < $width; ++$px) {
				$longitude = ($px + 0.5) / $width * 2 * M_PI - M_PI;
				$rx = $cosLat * sin($longitude);
				$ry = $sinLat;
				$rz = $cosLat * cos($longitude);
				$x = $m00 * $rx + $m10 * $ry + $m20 * $rz;
				$y = $m01 * $rx + $m11 * $ry + $m21 * $rz;
				$z = $m02 * $rx + $m12 * $ry + $m22 * $rz;

				$d = 2.0 * acos(max(-1.0, min(1.0, $z))) - M_PI;
				if (abs($d) >= $room) {
					continue;
				}

				$grey = [];
				foreach ([0, 1] as $index) {
					// Own-frame ray, as in Equirectangular: turned round for
					// lens 1, then the lens's tilt undone.
					$ox = $index === 1 ? -$x : $x;
					$oz = $index === 1 ? -$z : $z;
					$t = $geometry[$index][4];
					$qx = $t[0][0] * $ox + $t[1][0] * $y + $t[2][0] * $oz;
					$qy = $t[0][1] * $ox + $t[1][1] * $y + $t[2][1] * $oz;
					$qz = $t[0][2] * $ox + $t[1][2] * $y + $t[2][2] * $oz;
					$theta = self::corrected(acos(max(-1.0, min(1.0, $qz))), $geometry[$index][5]);
					if ($theta > $thetaMax) {
						continue 2;
					}
					[$radius, $centreX, $centreY, $lensSpin] = $geometry[$index];
					$phi = atan2($qy, $qx) - $lensSpin;
					$r = $radius * $theta / $thetaMax;
					$fx = $centreX + $r * cos($phi);
					$fy = $centreY - $r * sin($phi);
					$sx = (int)floor($fx);
					$sy = (int)floor($fy);
					if ($sx < 0 || $sy < 0 || $sx >= $sampleWidth || $sy >= $sampleHeight) {
						continue 2;
					}
					// Bilinear, to match the library. Nearest-neighbour here
					// still routes but picks a measurably worse seam: 20 per
					// cent median gain against 26.
					$tx = $fx - $sx;
					$ty = $fy - $sy;
					$sx1 = $sx + 1 < $sampleWidth ? $sx + 1 : $sx;
					$sy1 = $sy + 1 < $sampleHeight ? $sy + 1 : $sy;
					$grey[$index] = 0.0;
					foreach ([[$sx, $sy, (1 - $tx) * (1 - $ty)], [$sx1, $sy, $tx * (1 - $ty)],
						[$sx, $sy1, (1 - $tx) * $ty], [$sx1, $sy1, $tx * $ty]] as [$qx, $qy, $w]) {
						if ($w === 0.0) {
							continue;
						}
						$c = imagecolorat($scaled, $qx, $qy);
						$grey[$index] += ((($c >> 16) & 0xFF) * 0.299
							+ (($c >> 8) & 0xFF) * 0.587
							+ ($c & 0xFF) * 0.114) * $w;
					}
				}

				$azimuth = atan2($y, $x);
				$row = (int)(($d + $room) / (2.0 * $room) * (self::ROWS - 1));
				$column = ((int)(($azimuth + M_PI) / (2 * M_PI) * self::COLUMNS)) % self::COLUMNS;
				if ($row < 0 || $row >= self::ROWS || $column < 0) {
					continue;
				}
				$total[$row][$column] += abs($grey[0] - $grey[1]);
				++$count[$row][$column];
				++$seen;
			}
		}

		if ($seen < 1000) {
			return null;
		}
		$grid = [];
		for ($r = 0; $r < self::ROWS; ++$r) {
			$grid[$r] = [];
			for ($c = 0; $c < self::COLUMNS; ++$c) {
				$grid[$r][$c] = $count[$r][$c] > 0 ? $total[$r][$c] / $count[$r][$c] : INF;
			}
		}
		return $grid;
	}

	/**
	 * Cost each candidate over the width the CROSS-FADE averages, not one row.
	 *
	 * 🔴 Without this the search minimises a slice far thinner than the blend,
	 * so the path dodges a near subject and the blend drags it straight back
	 * in. That alone was the difference between routing measuring as worthless
	 * and worthwhile.
	 *
	 * @param array<int, array<int, float>> $grid
	 * @return array<int, array<int, float>>
	 */
	private static function widen(array $grid, float $feather, float $room): array {
		$step = 2.0 * $room / (self::ROWS - 1);
		$span = max(1, (int)round(2.0 * $feather / $step));
		$half = intdiv($span, 2);
		$out = [];
		for ($r = 0; $r < self::ROWS; ++$r) {
			$out[$r] = [];
			for ($c = 0; $c < self::COLUMNS; ++$c) {
				if (is_infinite($grid[$r][$c])) {
					$out[$r][$c] = INF;
					continue;
				}
				$sum = 0.0;
				$n = 0;
				for ($k = -$half; $k < $span - $half; ++$k) {
					$rr = max(0, min(self::ROWS - 1, $r + $k));
					if (!is_infinite($grid[$rr][$c])) {
						$sum += $grid[$rr][$c];
						++$n;
					}
				}
				$out[$r][$c] = $n > 0 ? $sum / $n : INF;
			}
		}
		return $out;
	}

	/**
	 * Minimum-cost closed path, one row per column, steps of at most one row.
	 *
	 * ⚠️ Cyclic because the azimuth wraps, connected because a seam that jumps
	 * is a tear. Two passes -- free start, then pinned to where that landed --
	 * rather than solving every start: measured against the exact answer the
	 * difference is 0.0% median and 3.9% worst, and the exact form needs a
	 * back-pointer table per start that does not fit here.
	 *
	 * @param array<int, array<int, float>> $grid
	 * @return int[]|null
	 */
	private static function cheapestCycle(array $grid): ?array {
		$work = [];
		for ($r = 0; $r < self::ROWS; ++$r) {
			for ($c = 0; $c < self::COLUMNS; ++$c) {
				$work[$r][$c] = is_infinite($grid[$r][$c]) ? 1e9 : $grid[$r][$c];
			}
		}

		$sweep = function (array $initial) use ($work): array {
			$cost = $initial;
			$back = [];
			for ($c = 1; $c < self::COLUMNS; ++$c) {
				$next = [];
				$choice = [];
				for ($r = 0; $r < self::ROWS; ++$r) {
					$best = $cost[$r];
					$from = $r;
					if ($r > 0 && $cost[$r - 1] < $best) {
						$best = $cost[$r - 1];
						$from = $r - 1;
					}
					if ($r + 1 < self::ROWS && $cost[$r + 1] < $best) {
						$best = $cost[$r + 1];
						$from = $r + 1;
					}
					$next[$r] = $best + $work[$r][$c];
					$choice[$r] = $from;
				}
				$cost = $next;
				$back[$c] = $choice;
			}
			return [$cost, $back];
		};

		$unwind = function (array $back, int $end): array {
			$path = array_fill(0, self::COLUMNS, 0);
			$path[self::COLUMNS - 1] = $end;
			for ($c = self::COLUMNS - 1; $c > 0; --$c) {
				$path[$c - 1] = $back[$c][$path[$c]];
			}
			return $path;
		};

		$first = [];
		for ($r = 0; $r < self::ROWS; ++$r) {
			$first[$r] = $work[$r][0];
		}
		[$cost, $back] = $sweep($first);
		$path = $unwind($back, (int)array_keys($cost, min($cost))[0]);

		$start = $path[0];
		$pinned = array_fill(0, self::ROWS, INF);
		$pinned[$start] = $work[$start][0];
		[$cost, $back] = $sweep($pinned);

		$end = null;
		foreach ([$start - 1, $start, $start + 1] as $candidate) {
			if ($candidate < 0 || $candidate >= self::ROWS || is_infinite($cost[$candidate])) {
				continue;
			}
			if ($end === null || $cost[$candidate] < $cost[$end]) {
				$end = $candidate;
			}
		}
		if ($end === null) {
			return null;
		}
		return $unwind($back, $end);
	}

	/** The offset to use at one azimuth, interpolated between grid columns. */
	/**
	 * Where a lens actually recorded a direction theta off its axis, given its
	 * measured correction in radians; see LensProfile. Matches the inline
	 * version in Equirectangular, which is unrolled for speed.
	 *
	 * @param float[] $radial
	 */
	public static function corrected(float $theta, array $radial): float {
		$last = count($radial) - 1;
		if ($last < 0) {
			return $theta;
		}
		$k = $theta * (180.0 / M_PI) / \OCA\Golblick\Insta360\LensProfile::RADIAL_STEP;
		$i = (int)$k;

		return $theta + ($i >= $last ? $radial[$last] : $radial[$i] + ($radial[$i + 1] - $radial[$i]) * ($k - $i));
	}

	public static function offsetAt(array $delta, float $azimuth): float {
		$position = (($azimuth + M_PI) / (2 * M_PI) * self::COLUMNS);
		$low = ((int)floor($position)) % self::COLUMNS;
		if ($low < 0) {
			$low += self::COLUMNS;
		}
		$high = ($low + 1) % self::COLUMNS;
		$fraction = $position - floor($position);
		return $delta[$low] * (1.0 - $fraction) + $delta[$high] * $fraction;
	}

	/**
	 * @param array<int, array<int, float>> $grid
	 * @param int[] $path
	 */
	private static function meanAlong(array $grid, array $path): ?float {
		$sum = 0.0;
		$n = 0;
		for ($c = 0; $c < self::COLUMNS; ++$c) {
			$value = $grid[$path[$c]][$c];
			if (!is_infinite($value)) {
				$sum += $value;
				++$n;
			}
		}
		return $n > 0 ? $sum / $n : null;
	}
}
