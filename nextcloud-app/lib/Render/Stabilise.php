<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Render;

use OCA\Golblick\Insta360\Imu;

/**
 * The rotation that steadies each frame of a 360 video, from its gyroscope.
 *
 * A port of src/golblick/stabilise.py, which says what it does and how it
 * was scored; kept close enough to read side by side, and checked to agree
 * with it to rounding on real clips. The one difference is memory: this
 * decodes the inertial record as it integrates, instead of holding every
 * sample, because a half-hour clip has some 1.8 million of them.
 *
 * Quaternions are [w, x, y, z]; rotations are in the render's frame (y up,
 * z forward) and the column convention.
 */
final class Stabilise {
	public const UP_WINDOW = 2.0;
	public const FOLLOW = 2.0;
	public const STILL = 0.1;
	public const BIN = 0.01;

	/**
	 * Per frame, the rotation from a frame rendered at $reference to the
	 * steadied view.
	 *
	 * @param string $record the raw 0x0300 payload
	 * @param array<int, array<int, float>> $axes Imu::motionAxes
	 * @param list<float> $frameTimes Imu::frameTimes
	 * @param array<int, array<int, float>> $reference the orientation the frames were rendered with
	 * @return list<array{float, float, float, float}>
	 */
	public static function track(string $record, int $stride, array $axes, array $frameTimes, array $reference,
		float $upWindow = self::UP_WINDOW, float $follow = self::FOLLOW): array {
		$attitudes = self::attitudes($record, $stride, $axes, $frameTimes, $upWindow);

		$steps = [];
		for ($i = 1; $i < \count($frameTimes); ++$i) {
			$steps[] = $frameTimes[$i] - $frameTimes[$i - 1];
		}
		sort($steps);
		$step = $steps === [] ? 1.0 : $steps[intdiv(\count($steps), 2)];

		$headings = [];
		foreach ($attitudes as $q) {
			$headings[] = 2.0 * atan2($q[2], $q[0]);
		}
		$smooth = self::smoothTrend(self::unwrap($headings), $follow / $step);
		$ref = self::quaternion($reference);
		$inverseRef = [$ref[0], -$ref[1], -$ref[2], -$ref[3]];

		$out = [];
		foreach ($attitudes as $k => $q) {
			$h = $smooth[$k];
			$steady = self::multiply([cos($h / 2.0), 0.0, -sin($h / 2.0), 0.0], $q);
			$out[] = self::multiply($steady, $inverseRef);
		}

		// The first frame faces where the render's does: no twist at frame 0.
		$twist = 2.0 * atan2($out[0][2], $out[0][0]);
		$align = [cos($twist / 2.0), 0.0, -sin($twist / 2.0), 0.0];
		foreach ($out as $k => $q) {
			$out[$k] = self::normalise(self::multiply($align, $q));
		}

		return $out;
	}

	/** @return list<array{float, float, float, float}> body to world at each frame time */
	private static function attitudes(string $record, int $stride, array $axes, array $frames, float $upWindow): array {
		$length = \strlen($record);
		$count = intdiv($length, $stride);
		$unit = Imu::CLOCK[$stride];
		$sign = Imu::handedness($axes);
		[[$a0, $a1, $a2], [$b0, $b1, $b2], [$c0, $c1, $c2]] = $axes;

		$start = Imu::entryAt($record, $stride, 0)[0];
		$last = Imu::entryAt($record, $stride, $length - $stride)[0];
		$bins = (int)(($last - $start) * $unit / self::BIN) + 1;
		$sx = array_fill(0, $bins, 0.0);
		$sy = array_fill(0, $bins, 0.0);
		$sz = array_fill(0, $bins, 0.0);
		$weight = array_fill(0, $bins, 0.0);

		$q0 = 1.0;
		$q1 = $q2 = $q3 = 0.0;
		$atFrames = [];
		$k = 0;
		$frameCount = \count($frames);
		$previous = 0.0;
		for ($i = 0; $i < $count; ++$i) {
			[$timecode, $ax, $ay, $az, $gx, $gy, $gz] = Imu::entryAt($record, $stride, $i * $stride);
			$t = ($timecode - $start) * $unit;
			if ($i > 0) {
				$dt = $t - $previous;
				if ($dt > 0) {
					$wx = $sign * ($a0 * $gx + $a1 * $gy + $a2 * $gz);
					$wy = $sign * ($b0 * $gx + $b1 * $gy + $b2 * $gz);
					$wz = $sign * ($c0 * $gx + $c1 * $gy + $c2 * $gz);
					$rate = sqrt($wx * $wx + $wy * $wy + $wz * $wz);
					if ($rate > 0) {
						$half = $rate * $dt / 2.0;
						$s = sin($half) / $rate;
						$d0 = cos($half);
						$d1 = $wx * $s;
						$d2 = $wy * $s;
						$d3 = $wz * $s;
						[$q0, $q1, $q2, $q3] = [
							$q0 * $d0 - $q1 * $d1 - $q2 * $d2 - $q3 * $d3,
							$q0 * $d1 + $q1 * $d0 + $q2 * $d3 - $q3 * $d2,
							$q0 * $d2 - $q1 * $d3 + $q2 * $d0 + $q3 * $d1,
							$q0 * $d3 + $q1 * $d2 - $q2 * $d1 + $q3 * $d0,
						];
						$n = sqrt($q0 * $q0 + $q1 * $q1 + $q2 * $q2 + $q3 * $q3);
						$q0 /= $n;
						$q1 /= $n;
						$q2 /= $n;
						$q3 /= $n;
					}
				}
			}
			$previous = $t;
			while ($k < $frameCount && $frames[$k] <= $t) {
				$atFrames[] = [$q0, $q1, $q2, $q3];
				++$k;
			}
			$g = sqrt($ax * $ax + $ay * $ay + $az * $az);
			if (abs($g - 1.0) < self::STILL) {
				$ux = ($a0 * $ax + $a1 * $ay + $a2 * $az) / $g;
				$uy = ($b0 * $ax + $b1 * $ay + $b2 * $az) / $g;
				$uz = ($c0 * $ax + $c1 * $ay + $c2 * $az) / $g;
				$b = (int)($t / self::BIN);
				$sx[$b] += (1 - 2 * ($q2 * $q2 + $q3 * $q3)) * $ux + 2 * ($q1 * $q2 - $q0 * $q3) * $uy
					+ 2 * ($q1 * $q3 + $q0 * $q2) * $uz;
				$sy[$b] += 2 * ($q1 * $q2 + $q0 * $q3) * $ux + (1 - 2 * ($q1 * $q1 + $q3 * $q3)) * $uy
					+ 2 * ($q2 * $q3 - $q0 * $q1) * $uz;
				$sz[$b] += 2 * ($q1 * $q3 - $q0 * $q2) * $ux + 2 * ($q2 * $q3 + $q0 * $q1) * $uy
					+ (1 - 2 * ($q1 * $q1 + $q2 * $q2)) * $uz;
				$weight[$b] += 1.0;
			}
		}
		while ($k < $frameCount) {
			$atFrames[] = [$q0, $q1, $q2, $q3];
			++$k;
		}

		if (max($weight) <= 0) {
			throw new \InvalidArgumentException("the accelerometer never reads close to 1 g, so up can't be found");
		}
		$sigma = $upWindow / self::BIN;
		$mx = self::smooth($sx, $weight, $sigma);
		$my = self::smooth($sy, $weight, $sigma);
		$mz = self::smooth($sz, $weight, $sigma);

		$out = [];
		foreach ($frames as $k => $time) {
			$b = min(max((int)($time / self::BIN), 0), $bins - 1);
			$out[] = self::normalise(self::multiply(self::levelQuaternion([$mx[$b], $my[$b], $mz[$b]]), $atFrames[$k]));
		}

		return $out;
	}

	/** stabilise.py's _smooth with presummed values: weighted and normalised, three boxes. */
	private static function smooth(array $sums, array $weights, float $sigma): array {
		$width = self::width($sigma);
		for ($pass = 0; $pass < 3; ++$pass) {
			$sums = self::box($sums, $width);
			$weights = self::box($weights, $width);
		}
		$out = [];
		foreach ($sums as $i => $n) {
			$out[] = $weights[$i] > 0 ? $n / $weights[$i] : 0.0;
		}

		return $out;
	}

	/** stabilise.py's _smooth_trend: extended by point reflection through a line fitted to each end. */
	private static function smoothTrend(array $values, float $sigma): array {
		$n = \count($values);
		if ($n < 3) {
			return $values;
		}
		$width = self::width($sigma);
		$pad = min(3 * $width, $n - 1);
		$span = min($n, $width);
		$first = self::lineAt(\array_slice($values, 0, $span), 0.0);
		$last = self::lineAt(\array_slice($values, $n - $span), $span - 1.0);
		$extended = [];
		for ($j = $pad; $j >= 1; --$j) {
			$extended[] = 2 * $first - $values[$j];
		}
		foreach ($values as $v) {
			$extended[] = $v;
		}
		for ($j = 1; $j <= $pad; ++$j) {
			$extended[] = 2 * $last - $values[$n - 1 - $j];
		}
		$count = array_fill(0, \count($extended), 1.0);
		for ($pass = 0; $pass < 3; ++$pass) {
			$extended = self::box($extended, $width);
			$count = self::box($count, $width);
		}
		$out = [];
		for ($i = 0; $i < $n; ++$i) {
			$out[] = $extended[$pad + $i] / $count[$pad + $i];
		}

		return $out;
	}

	private static function width(float $sigma): int {
		$width = (int)sqrt(4.0 * $sigma * $sigma + 1.0);

		return $width + 1 - $width % 2;
	}

	private static function lineAt(array $values, float $x): float {
		$n = \count($values);
		$meanX = ($n - 1) / 2.0;
		$meanY = array_sum($values) / $n;
		$spread = 0.0;
		$covariance = 0.0;
		foreach ($values as $i => $v) {
			$spread += ($i - $meanX) ** 2;
			$covariance += ($i - $meanX) * ($v - $meanY);
		}
		$slope = $spread > 0 ? $covariance / $spread : 0.0;

		return $meanY + $slope * ($x - $meanX);
	}

	/** Centred running sum over $width (odd) slots, by prefix sums. */
	private static function box(array $values, int $width): array {
		$half = intdiv($width, 2);
		$n = \count($values);
		$prefix = [0.0];
		$sum = 0.0;
		foreach ($values as $v) {
			$sum += $v;
			$prefix[] = $sum;
		}
		$out = [];
		for ($i = 0; $i < $n; ++$i) {
			$out[] = $prefix[min($n, $i + $half + 1)] - $prefix[max(0, $i - $half)];
		}

		return $out;
	}

	private static function unwrap(array $angles): array {
		$out = [];
		$offset = 0.0;
		$previous = null;
		foreach ($angles as $a) {
			if ($previous !== null) {
				$jump = $a - $previous;
				if ($jump > M_PI) {
					$offset -= 2 * M_PI;
				} elseif ($jump < -M_PI) {
					$offset += 2 * M_PI;
				}
			}
			$previous = $a;
			$out[] = $a + $offset;
		}

		return $out;
	}

	/** The shortest rotation taking $up to +y. */
	private static function levelQuaternion(array $up): array {
		[$x, $y, $z] = $up;
		$n = sqrt($x * $x + $y * $y + $z * $z);
		if ($n == 0) {
			return [1.0, 0.0, 0.0, 0.0];
		}
		$x /= $n;
		$y /= $n;
		$z /= $n;
		$w = 1.0 + $y;
		if ($w < 1e-9) {
			return [0.0, 1.0, 0.0, 0.0];
		}

		return self::normalise([$w, -$z, 0.0, $x]);
	}

	private static function multiply(array $a, array $b): array {
		return [
			$a[0] * $b[0] - $a[1] * $b[1] - $a[2] * $b[2] - $a[3] * $b[3],
			$a[0] * $b[1] + $a[1] * $b[0] + $a[2] * $b[3] - $a[3] * $b[2],
			$a[0] * $b[2] - $a[1] * $b[3] + $a[2] * $b[0] + $a[3] * $b[1],
			$a[0] * $b[3] + $a[1] * $b[2] - $a[2] * $b[1] + $a[3] * $b[0],
		];
	}

	private static function normalise(array $q): array {
		$n = sqrt($q[0] ** 2 + $q[1] ** 2 + $q[2] ** 2 + $q[3] ** 2);

		return [$q[0] / $n, $q[1] / $n, $q[2] / $n, $q[3] / $n];
	}

	/** A 3x3 rotation (column convention) as a unit quaternion. */
	private static function quaternion(array $m): array {
		[[$a, $b, $c], [$d, $e, $f], [$g, $h, $i]] = $m;
		$trace = $a + $e + $i;
		if ($trace > 0) {
			$s = sqrt($trace + 1.0) * 2;
			$q = [$s / 4, ($h - $f) / $s, ($c - $g) / $s, ($d - $b) / $s];
		} elseif ($a > $e && $a > $i) {
			$s = sqrt(1.0 + $a - $e - $i) * 2;
			$q = [($h - $f) / $s, $s / 4, ($b + $d) / $s, ($c + $g) / $s];
		} elseif ($e > $i) {
			$s = sqrt(1.0 + $e - $a - $i) * 2;
			$q = [($c - $g) / $s, ($b + $d) / $s, $s / 4, ($f + $h) / $s];
		} else {
			$s = sqrt(1.0 + $i - $a - $e) * 2;
			$q = [($d - $b) / $s, ($c + $g) / $s, ($f + $h) / $s, $s / 4];
		}

		return self::normalise($q);
	}
}
