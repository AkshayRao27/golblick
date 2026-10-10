<?php

declare(strict_types=1);

namespace OCA\Golblick\Render;

use OCA\Golblick\Insta360\Calibration;

/**
 * One hand-over for a whole video: a parallax per azimuth, then a route.
 *
 * A port of render.plan_seam() in the parent library, which owns the
 * reasoning and the measurements; the two run the same algorithm on purpose.
 * In short: aim both lenses at a common point at the distance that makes them
 * agree, so a subject near the camera lines up across the seam, then route
 * the cut round what still disagrees. Chosen on every other probe frame and
 * checked on the rest, and declined unless it clears the photo routing's
 * margin on frames it never saw.
 *
 * $parallax is degrees per azimuth column, $offset radians of d per column,
 * $direction the unit baseline from lens 0 to lens 1 in the camera frame.
 */
final class SeamPlan {
	/** render.DEPTH_LEVELS */
	public const LEVELS = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.5, 11.0];
	private const INNER = 4.0;
	private const OUTER = 12.0;
	private const BAND = 3.0;
	private const JUMP = 0.65;
	private const GAIN = 0.10;
	private const RUN = 8;
	private const NEAR_WHITE = 245.0;
	private const PER_COLUMN = 2;
	private const STEP = 0.25;
	private const FEATHER = 1.5;

	/**
	 * @param float[] $direction
	 * @param float[]|null $parallax
	 * @param float[] $offset
	 */
	private function __construct(
		public readonly array $direction,
		public readonly ?array $parallax,
		public readonly array $offset,
	) {
	}

	/**
	 * @param list<array{\GdImage, \GdImage}> $frames each lens in its own frame, square, all one size
	 * @param float[]|null $baseline lens 0 to lens 1, any unit; null plans the route only
	 */
	public static function choose(array $frames, Calibration $calibration, ?string $model, bool $guards,
		?array $baseline): ?self {
		if (\count($frames) < 2) {
			return null;
		}
		$lenses = RemapTables::lenses($calibration, imagesx($frames[0][0]), $model, $guards);
		$thetaMax = $lenses['thetaMax'];
		$feather = deg2rad(self::FEATHER);
		$half = 2.0 * $thetaMax - M_PI;
		$room = $half - 2.0 * $feather;
		if ($room <= 0.0) {
			return null;
		}
		$direction = null;
		if ($baseline !== null) {
			$norm = sqrt($baseline[0] ** 2 + $baseline[1] ** 2 + $baseline[2] ** 2);
			$direction = $norm > 0.0 ? [$baseline[0] / $norm, $baseline[1] / $norm, $baseline[2] / $norm] : null;
		}
		$ring = self::ring($half);
		$choose = [];
		$check = [];
		foreach ($frames as $k => $frame) {
			if ($k % 2 === 0) {
				$choose[] = $frame;
			} else {
				$check[] = $frame;
			}
		}

		$profile = null;
		if ($direction !== null) {
			$grids = [];
			foreach ($choose as $frame) {
				$grids[] = self::parallaxGrid($frame, $lenses, $ring, $direction);
			}
			$path = self::cheapestParallax(self::meanFinite($grids));
			$chosen = array_map(static fn (int $level): float => self::LEVELS[$level], $path);
			if (max($chosen) > 0.0) {
				$profile = $chosen;
			}
		}

		$middle = intdiv(Seam::ROWS - 1, 2);
		$flat = self::routed($choose, $lenses, $ring, null, $direction, $room, $feather);
		if ($flat === null) {
			return null;
		}
		$best = null;
		foreach ($profile !== null ? [null, $profile] : [null] as $candidate) {
			$grid = $candidate === null ? $flat : self::routed($choose, $lenses, $ring, $candidate, $direction, $room, $feather);
			if ($grid === null) {
				continue;
			}
			foreach ([null, Seam::cheapestCycle($grid)] as $route) {
				if ($candidate === null && $route === null) {
					continue;
				}
				$score = self::ratio($grid, $flat[$middle], $route, $middle);
				if ($score !== null && ($best === null || $score < $best[0])) {
					$best = [$score, $candidate, $route];
				}
			}
		}
		if ($best === null) {
			return null;
		}
		[, $profile, $route] = $best;

		// Routing's margin and floor, on frames the choice never saw.
		$straight = self::routed($check, $lenses, $ring, null, $direction, $room, $feather);
		if ($straight === null) {
			return null;
		}
		$sum = 0.0;
		$n = 0;
		foreach ($straight[$middle] as $value) {
			if (!is_infinite($value)) {
				$sum += $value;
				++$n;
			}
		}
		if ($n === 0 || $sum / $n < Seam::FLOOR) {
			return null;
		}
		$checked = $profile === null ? $straight : self::routed($check, $lenses, $ring, $profile, $direction, $room, $feather);
		$verified = $checked === null ? null : self::ratio($checked, $straight[$middle], $route, $middle);
		if ($verified === null || $verified >= Seam::MARGIN) {
			return null;
		}

		$offset = array_fill(0, Seam::COLUMNS, 0.0);
		if ($route !== null) {
			for ($c = 0; $c < Seam::COLUMNS; ++$c) {
				$s = 0.0;
				for ($k = -4; $k <= 4; ++$k) {
					$s += $route[($c + $k + Seam::COLUMNS) % Seam::COLUMNS];
				}
				$offset[$c] = $s / 9.0 / (Seam::ROWS - 1) * (2.0 * $room) - $room;
			}
		}

		return new self($profile !== null ? $direction : [0.0, 0.0, 0.0], $profile, $offset);
	}

	/** Full strength within INNER degrees of the bisector, gone by OUTER. */
	public static function taper(float $d): float {
		$inner = deg2rad(self::INNER);
		$outer = deg2rad(self::OUTER);

		return max(0.0, min(1.0, ($outer - abs($d)) / ($outer - $inner)));
	}

	/**
	 * Lens $index's direction for camera-frame ray (x, y, z) aimed at a point
	 * with $parallax radians, already tapered: half along the baseline for
	 * lens 0, half against it for lens 1. render._aimed() has the derivation.
	 *
	 * @param float[] $direction
	 * @return array{float, float, float}
	 */
	public static function aim(float $x, float $y, float $z, float $parallax, array $direction, int $index): array {
		$s = ($index === 0 ? 0.5 : -0.5) * $parallax;
		$x += $s * $direction[0];
		$y += $s * $direction[1];
		$z += $s * $direction[2];
		$norm = sqrt($x * $x + $y * $y + $z * $z);

		return [$x / $norm, $y / $norm, $z / $norm];
	}

	/**
	 * The plan's parallax (radians, tapered) at a camera-frame direction with
	 * offset $d and azimuth $phi; zero without one.
	 */
	public function parallaxAt(float $d, float $phi): float {
		if ($this->parallax === null) {
			return 0.0;
		}

		return deg2rad(Seam::offsetAt($this->parallax, $phi)) * self::taper($d);
	}

	/** render._ring(): rays round the seam, evenly in azimuth and in d. */
	private static function ring(float $half): array {
		$around = Seam::COLUMNS * self::PER_COLUMN;
		$steps = (int)floor(rad2deg($half) / self::STEP);
		$rays = [];
		for ($j = -$steps; $j <= $steps; ++$j) {
			$d = deg2rad($j * self::STEP);
			$c = cos($d / 2);
			$z = -sin($d / 2);
			for ($i = 0; $i < $around; ++$i) {
				$phi = ($i + 0.5) * (2 * M_PI / $around) - M_PI;
				$rays[] = [$c * cos($phi), $c * sin($phi), $z, $d, $phi,
					((int)(($phi + M_PI) / (2 * M_PI) * Seam::COLUMNS)) % Seam::COLUMNS];
			}
		}

		return $rays;
	}

	/**
	 * Both lenses' luma at one ring ray, aimed at $parallax radians; null if
	 * either lens cannot see it.
	 *
	 * @return array{float, float}|null
	 */
	private static function pair(array $frame, array $lenses, array $ray, float $parallax, ?array $direction): ?array {
		$grey = [];
		foreach ([0, 1] as $index) {
			[$x, $y, $z] = $parallax === 0.0 || $direction === null ? $ray
				: self::aim($ray[0], $ray[1], $ray[2], $parallax, $direction, $index);
			[$u, $v, $theta] = RemapTables::locate($lenses, $index, $x, $y, $z);
			if ($theta > $lenses['thetaMax']) {
				return null;
			}
			$grey[$index] = self::luma($frame[$index], $u, $v);
		}

		return $grey;
	}

	/** Bilinear luma at index-space (u, v), clamped as render._sample. */
	private static function luma(\GdImage $image, float $u, float $v): float {
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
		$total = 0.0;
		foreach ([[$x0, $y0, (1 - $fx) * (1 - $fy)], [$x1, $y0, $fx * (1 - $fy)],
			[$x0, $y1, (1 - $fx) * $fy], [$x1, $y1, $fx * $fy]] as [$x, $y, $weight]) {
			$rgb = imagecolorat($image, $x, $y);
			$total += ((($rgb >> 16) & 0xFF) * 0.299 + (($rgb >> 8) & 0xFF) * 0.587 + ($rgb & 0xFF) * 0.114) * $weight;
		}

		return $total;
	}

	/** render._parallax_cost() for every level: mean |a - b| per column near the bisector. */
	private static function parallaxGrid(array $frame, array $lenses, array $ring, array $direction): array {
		$band = deg2rad(self::BAND);
		$grid = [];
		foreach (self::LEVELS as $row => $level) {
			$total = array_fill(0, Seam::COLUMNS, 0.0);
			$count = array_fill(0, Seam::COLUMNS, 0);
			foreach ($ring as $ray) {
				if (abs($ray[3]) >= $band) {
					continue;
				}
				$grey = self::pair($frame, $lenses, $ray, deg2rad($level) * self::taper($ray[3]), $direction);
				if ($grey === null || $grey[0] >= self::NEAR_WHITE || $grey[1] >= self::NEAR_WHITE) {
					continue;
				}
				$total[$ray[5]] += abs($grey[0] - $grey[1]);
				++$count[$ray[5]];
			}
			for ($c = 0; $c < Seam::COLUMNS; ++$c) {
				$grid[$row][$c] = $count[$c] >= self::PER_COLUMN * 4 ? $total[$c] / $count[$c] : INF;
			}
		}

		return $grid;
	}

	/** Routing's widened cost over $frames, lenses aimed by $profile; render.plan_seam's routed(). */
	private static function routed(array $frames, array $lenses, array $ring, ?array $profile, ?array $direction,
		float $room, float $feather): ?array {
		$grids = [];
		foreach ($frames as $frame) {
			$total = array_fill(0, Seam::ROWS, array_fill(0, Seam::COLUMNS, 0.0));
			$count = array_fill(0, Seam::ROWS, array_fill(0, Seam::COLUMNS, 0));
			$seen = 0;
			foreach ($ring as $ray) {
				if (abs($ray[3]) >= $room) {
					continue;
				}
				$parallax = $profile === null ? 0.0 : deg2rad(Seam::offsetAt($profile, $ray[4])) * self::taper($ray[3]);
				$grey = self::pair($frame, $lenses, $ray, $parallax, $direction);
				if ($grey === null) {
					continue;
				}
				$row = (int)(($ray[3] + $room) / (2.0 * $room) * (Seam::ROWS - 1));
				$total[$row][$ray[5]] += abs($grey[0] - $grey[1]);
				++$count[$row][$ray[5]];
				++$seen;
			}
			if ($seen < 1000) {
				continue;
			}
			$grid = [];
			for ($r = 0; $r < Seam::ROWS; ++$r) {
				for ($c = 0; $c < Seam::COLUMNS; ++$c) {
					$grid[$r][$c] = $count[$r][$c] > 0 ? $total[$r][$c] / $count[$r][$c] : INF;
				}
			}
			$grids[] = Seam::widen($grid, $feather, $room);
		}

		return $grids === [] ? null : self::meanFinite($grids);
	}

	/** Mean along a route (or the bisector row) over the mean along the bisector, where both are finite. */
	private static function ratio(array $grid, array $straight, ?array $route, int $middle): ?float {
		$a = 0.0;
		$b = 0.0;
		$n = 0;
		for ($c = 0; $c < Seam::COLUMNS; ++$c) {
			$along = $grid[$route === null ? $middle : $route[$c]][$c];
			if (is_infinite($along) || is_infinite($straight[$c])) {
				continue;
			}
			$a += $along;
			$b += $straight[$c];
			++$n;
		}

		return $n > 0 && $b > 0.0 ? $a / $b : null;
	}

	/** @param list<array<int, array<int, float>>> $grids */
	private static function meanFinite(array $grids): array {
		$out = [];
		foreach ($grids[0] as $r => $row) {
			foreach ($row as $c => $unused) {
				$sum = 0.0;
				$n = 0;
				foreach ($grids as $grid) {
					if (!is_infinite($grid[$r][$c])) {
						$sum += $grid[$r][$c];
						++$n;
					}
				}
				$out[$r][$c] = $n > 0 ? $sum / $n : INF;
			}
		}

		return $out;
	}

	/**
	 * render._cheapest_parallax(): a level per column, any jump at a cost,
	 * blind-zone columns held at zero, then spikes narrower than RUN opened away.
	 *
	 * @return int[]
	 */
	private static function cheapestParallax(array $grid): array {
		$rows = \count(self::LEVELS);
		$columns = Seam::COLUMNS;
		$work = [];
		for ($c = 0; $c < $columns; ++$c) {
			$base = is_infinite($grid[0][$c]) ? 0.0 : $grid[0][$c];
			$last = 0;
			$best = 0;
			$bestCost = INF;
			for ($r = 0; $r < $rows; ++$r) {
				$value = $grid[$r][$c];
				$finite = !is_infinite($value);
				$work[$r][$c] = ($finite ? $value : 1e3) + ($r > 0 ? self::GAIN * $base : 0.0);
				if ($finite) {
					$last = $r;
					if ($value < $bestCost) {
						$bestCost = $value;
						$best = $r;
					}
				}
			}
			if ($best === $last && $last > 0) {
				for ($r = 1; $r < $rows; ++$r) {
					$work[$r][$c] = 1e3;
				}
			}
		}
		$step = [];
		for ($a = 0; $a < $rows; ++$a) {
			for ($b = 0; $b < $rows; ++$b) {
				$step[$a][$b] = self::JUMP * abs(self::LEVELS[$a] - self::LEVELS[$b]);
			}
		}

		$sweep = static function (array $initial) use ($work, $step, $rows, $columns): array {
			$cost = $initial;
			$back = [];
			for ($c = 1; $c < $columns; ++$c) {
				$next = [];
				for ($to = 0; $to < $rows; ++$to) {
					$best = INF;
					$from = 0;
					for ($f = 0; $f < $rows; ++$f) {
						$value = $cost[$f] + $step[$f][$to];
						if ($value < $best) {
							$best = $value;
							$from = $f;
						}
					}
					$back[$c][$to] = $from;
					$next[$to] = $best + $work[$to][$c];
				}
				$cost = $next;
			}

			return [$cost, $back];
		};
		$unwind = static function (array $back, int $end) use ($columns): array {
			$path = array_fill(0, $columns, 0);
			$path[$columns - 1] = $end;
			for ($c = $columns - 1; $c > 0; --$c) {
				$path[$c - 1] = $back[$c][$path[$c]];
			}

			return $path;
		};
		$argmin = static function (array $values): int {
			$best = 0;
			foreach ($values as $i => $value) {
				if ($value < $values[$best]) {
					$best = $i;
				}
			}

			return $best;
		};

		$initial = [];
		for ($r = 0; $r < $rows; ++$r) {
			$initial[$r] = $work[$r][0];
		}
		[$cost, $back] = $sweep($initial);
		$start = $unwind($back, $argmin($cost))[0];
		$pinned = array_fill(0, $rows, INF);
		$pinned[$start] = $work[$start][0];
		[$cost, $back] = $sweep($pinned);
		$closing = [];
		for ($r = 0; $r < $rows; ++$r) {
			$closing[$r] = $cost[$r] + $step[$r][$start];
		}
		$path = $unwind($back, $argmin($closing));

		$eroded = [];
		for ($c = 0; $c < $columns; ++$c) {
			$low = PHP_INT_MAX;
			for ($k = 0; $k < self::RUN; ++$k) {
				$low = min($low, $path[($c + $k) % $columns]);
			}
			$eroded[$c] = $low;
		}
		$opened = [];
		for ($c = 0; $c < $columns; ++$c) {
			$high = 0;
			for ($k = 0; $k < self::RUN; ++$k) {
				$high = max($high, $eroded[($c - $k + $columns) % $columns]);
			}
			$opened[$c] = $high;
		}

		return $opened;
	}
}
