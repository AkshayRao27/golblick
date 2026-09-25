<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Kugelblick\Render;

/**
 * Rotations that decide which way is up in a render.
 *
 * Two routes, and they are not equivalent:
 *
 *  - {@see fromRoll} corrects the sensor's MOUNTING ANGLE from the calibration
 *    string. It needs nothing else, so it works on every file that has a
 *    trailer -- but the mounting angle is a constant of the camera body, so a
 *    shot taken with the camera tilted forward is still tilted afterwards.
 *  - {@see level} uses the accelerometer, so it knows how the camera was
 *    actually held and fixes pitch as well as roll. It replaces the first
 *    rather than composing with it, because the gravity vector is already
 *    expressed in the render's frame.
 *
 * Ported from render.py in the parent library, which owns the conventions.
 */
final class Orientation {
	/**
	 * A rotation of the scene, in degrees, as Ry(yaw) . Rx(pitch) . Rz(roll).
	 *
	 * @return array<int, array<int, float>> a 3x3 matrix
	 */
	public static function rotation(float $yaw, float $pitch, float $roll): array {
		$y = deg2rad($yaw);
		$p = deg2rad($pitch);
		$r = deg2rad($roll);
		$cy = cos($y);
		$sy = sin($y);
		$cp = cos($p);
		$sp = sin($p);
		$cr = cos($r);
		$sr = sin($r);

		$ry = [[$cy, 0.0, $sy], [0.0, 1.0, 0.0], [-$sy, 0.0, $cy]];
		$rx = [[1.0, 0.0, 0.0], [0.0, $cp, -$sp], [0.0, $sp, $cp]];
		$rz = [[$cr, -$sr, 0.0], [$sr, $cr, 0.0], [0.0, 0.0, 1.0]];

		return self::multiply(self::multiply($ry, $rx), $rz);
	}

	/** The mounting-angle correction: a roll and nothing else. */
	public static function fromRoll(float $roll): array {
		return self::rotation(0.0, 0.0, $roll);
	}

	/**
	 * The rotation that lifts $up to the top of the frame.
	 *
	 * The SHORTEST such rotation, so it adds no spin of its own. Which way the
	 * levelled panorama should then face is a separate question, and one
	 * gravity cannot answer -- so no yaw is applied here.
	 *
	 * @param array{float, float, float} $up which way is up, in the render's frame
	 * @return array<int, array<int, float>>
	 */
	public static function level(array $up): array {
		$norm = sqrt($up[0] ** 2 + $up[1] ** 2 + $up[2] ** 2);
		if ($norm < 1e-9) {
			throw new \InvalidArgumentException('up vector has no direction');
		}
		$v = [$up[0] / $norm, $up[1] / $norm, $up[2] / $norm];

		// Rodrigues, rotating v onto +y.
		$axis = [
			$v[1] * 0.0 - $v[2] * 1.0,
			$v[2] * 0.0 - $v[0] * 0.0,
			$v[0] * 1.0 - $v[1] * 0.0,
		];
		$sine = sqrt($axis[0] ** 2 + $axis[1] ** 2 + $axis[2] ** 2);
		$cosine = $v[1];

		if ($sine < 1e-9) {
			// Already vertical, one way or the other.
			return $cosine > 0
				? [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
				: [[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]];
		}

		$cross = [
			[0.0, -$axis[2], $axis[1]],
			[$axis[2], 0.0, -$axis[0]],
			[-$axis[1], $axis[0], 0.0],
		];
		$square = self::multiply($cross, $cross);
		$factor = (1 - $cosine) / ($sine ** 2);

		$out = [];
		for ($i = 0; $i < 3; ++$i) {
			for ($j = 0; $j < 3; ++$j) {
				$out[$i][$j] = ($i === $j ? 1.0 : 0.0) + $cross[$i][$j] + $square[$i][$j] * $factor;
			}
		}

		return $out;
	}

	/** @return array<int, array<int, float>> */
	private static function multiply(array $a, array $b): array {
		$out = [];
		for ($i = 0; $i < 3; ++$i) {
			for ($j = 0; $j < 3; ++$j) {
				$out[$i][$j] = $a[$i][0] * $b[0][$j] + $a[$i][1] * $b[1][$j] + $a[$i][2] * $b[2][$j];
			}
		}

		return $out;
	}
}
