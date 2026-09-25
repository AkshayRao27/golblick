<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Kugelblick\Insta360;

/**
 * The equidistant lens calibration, field 5 of the metadata record.
 *
 * Only this model is read. It is the one every camera carries and the only one
 * whose interior is confirmed; the richer models exist on one camera and their
 * parameter meanings are inferred from shape. docs/formats/insta360.md owns
 * the detail.
 */
final class Calibration {
	/** @var list<list<float>> six values per lens: radius, cx, cy, roll, pitch, yaw */
	public array $lenses;

	/** @var list<float> trailing global values; the first two are the reference frame */
	public array $globals;

	private function __construct(array $lenses, array $globals) {
		$this->lenses = $lenses;
		$this->globals = $globals;
	}

	public static function parse(string $text): self {
		$parts = explode('_', trim($text));
		if (\count($parts) < 2) {
			throw new FormatError('calibration string has too few parts');
		}
		$values = array_map('floatval', $parts);

		$count = (int)$values[0];
		if ($count !== 2) {
			// Everything downstream is a back-to-back pair. Refuse rather than
			// render half a rig.
			throw new FormatError("expected 2 lenses, got {$count}");
		}
		if (\count($values) !== 1 + 6 * $count + 3) {
			throw new FormatError('field 5 is not 1 + 6n + 3 values');
		}

		$lenses = [];
		for ($i = 0; $i < $count; ++$i) {
			$lenses[] = \array_slice($values, 1 + $i * 6, 6);
		}

		return new self($lenses, \array_slice($values, 1 + 6 * $count));
	}

	/**
	 * The frame the parameters are quoted against, which is usually not the
	 * image size and is per camera -- so it is read, never assumed.
	 */
	public function referenceWidth(): float {
		$width = $this->globals[0] ?? 0.0;
		if ($width <= 0) {
			throw new FormatError('calibration carries no usable reference width');
		}

		return $width;
	}

	public function scaleFor(int $width): float {
		return $width / $this->referenceWidth();
	}

	/**
	 * Relative rotation between the sensors, degrees, signed the short way.
	 *
	 * Lens 1 is physically half a turn round; a OneR states that in the yaw
	 * and an X3 and X5 leave it implicit, so it is taken modulo 180.
	 */
	public function relativeSpin(): float {
		$difference = $this->lenses[1][5] - $this->lenses[0][5];

		return fmod(fmod($difference + 90.0, 180.0) + 180.0, 180.0) - 90.0;
	}

	/**
	 * Roll carrying a render from lens 0's sensor frame into the body frame.
	 *
	 * The absolute yaw is the sensor's mounting angle, which differs by 90
	 * degrees between a OneR and an X3 or X5 -- without this a OneR renders on
	 * its side. See docs/formats/insta360.md.
	 */
	public function bodyRoll(): float {
		return fmod(fmod(90.0 - $this->lenses[0][5] + 180.0, 360.0) + 360.0, 360.0) - 180.0;
	}
}
