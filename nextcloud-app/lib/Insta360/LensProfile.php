<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Insta360;

/**
 * What the file does not say about the lenses, per camera model, measured.
 *
 * The field of view each lens sees, and a correction to the equidistant model
 * sampled every RADIAL_STEP degrees out from the axis. Ported from
 * vendors/insta360/lens.py in the parent library, which owns the values and
 * how they were measured; keep the two tables identical.
 */
final class LensProfile {
	public const RADIAL_STEP = 2.0;

	/** Used for a camera nobody has measured. */
	public const DEFAULT_FIELD_OF_VIEW = 194.0;

	/**
	 * Where a still opens, in the render's frame: PHOTO_FORWARD in the
	 * library's insta360 module, which has the measurements against Insta360
	 * Studio's exports. The same on the OneR, X3 and X5, and for their videos.
	 */
	public const PHOTO_FORWARD = [0.0, 0.0, -1.0];

	/**
	 * model => [field of view, radial, lens guard divisor (or null)]. See
	 * lens.py for what each was measured against. A video uses the same angle:
	 * it differs from a still only by the sensor crop, which
	 * Calibration::forVideo() applies to the geometry.
	 *
	 * @var array<string, array{0: float, 1: float[], 2?: ?float}>
	 */
	private const PROFILES = [
		'Insta360 OneR' => [194.0, [
			0.000, 0.030, 0.039, 0.031, 0.010, -0.021, -0.058, -0.100, -0.144, -0.187,
			-0.227, -0.262, -0.290, -0.311, -0.321, -0.322, -0.311, -0.289, -0.254, -0.207,
			-0.148, -0.077, 0.005, 0.097, 0.199, 0.309, 0.425, 0.547, 0.670, 0.795,
			0.917, 1.034, 1.144, 1.242, 1.326, 1.392, 1.435, 1.451, 1.436, 1.385,
			1.293, 1.155, 0.965, 0.717, 0.438, 0.159, -0.119, -0.398, -0.677, -0.956,
			-1.235,
		]],
		'Insta360 X3' => [192.0, [
			0.000, -0.171, -0.328, -0.474, -0.609, -0.736, -0.856, -0.969, -1.076, -1.177,
			-1.273, -1.361, -1.443, -1.518, -1.584, -1.640, -1.687, -1.722, -1.745, -1.754,
			-1.750, -1.731, -1.697, -1.647, -1.580, -1.498, -1.400, -1.286, -1.159, -1.018,
			-0.865, -0.704, -0.536, -0.364, -0.192, -0.024, 0.135, 0.279, 0.403, 0.500,
			0.562, 0.580, 0.547, 0.452, 0.322, 0.193, 0.063, -0.067, -0.197, -0.326,
			-0.456,
		]],
		'Insta360 X5' => [197.5, [], 1.0225],
	];

	/** Models whose radial curve comes from each file's MEI calibration: radial_from_file in lens.py. */
	public const RADIAL_FROM_FILE = ['Insta360 X5'];

	/** Whether $model has measured values, rather than the default every other camera gets. */
	public static function isMeasured(?string $model): bool {
		return isset(self::PROFILES[$model ?? '']);
	}

	/**
	 * @param bool $guards clip-on lens guards fitted, which narrow the field of view
	 * @param float[]|null $fileRadial the file's own curve (Calibration::$radial), used where the model takes it
	 * @return array{float, float[]} field of view in degrees, radial correction in degrees
	 */
	public static function for(?string $model, bool $guards = false, ?array $fileRadial = null): array {
		$profile = self::PROFILES[$model ?? ''] ?? [self::DEFAULT_FIELD_OF_VIEW, []];
		$degrees = $profile[0];
		if ($guards && isset($profile[2])) {
			$degrees /= $profile[2];
		}

		$radial = $fileRadial !== null && \in_array($model, self::RADIAL_FROM_FILE, true) ? $fileRadial : $profile[1];

		return [$degrees, $radial];
	}

	/** Whether lens guards are modelled for $model, i.e. whether detecting them means anything. */
	public static function hasGuards(?string $model): bool {
		return isset(self::PROFILES[$model ?? ''][2]);
	}

	/** The divisor a lens guard applies to the field of view, if measured. */
	public static function guardFactor(?string $model): ?float {
		return self::PROFILES[$model ?? ''][2] ?? null;
	}
}
