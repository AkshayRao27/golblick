<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Insta360;

/**
 * The equidistant lens calibration, field 5 of the metadata record.
 *
 * Only this model is read. It is the one every camera carries and the only one
 * whose interior is confirmed; the richer models exist on one camera and their
 * parameter meanings are inferred from shape. docs/formats/insta360-agent-notes.md owns
 * the detail.
 */
final class Calibration {
	/** @var list<list<float>> six values per lens: radius, cx, cy, roll, pitch, yaw */
	public array $lenses;

	/** @var list<float> trailing global values; the first two are the reference frame */
	public array $globals;

	/** @var float[]|null the file's own radial curve, degrees every LensProfile::RADIAL_STEP (withMei) */
	public ?array $radial = null;

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
	 * This calibration with the radial curve of the file's MEI model (field
	 * 54), where it has one that reads. LensProfile uses it for the cameras
	 * whose curve comes from the file.
	 */
	public function withMei(?string $mei): self {
		$copy = clone $this;
		$copy->radial = $mei === null ? null
			: self::radialCorrection($mei, LensProfile::RADIAL_STEP, (int)(100 / LensProfile::RADIAL_STEP) + 1);

		return $copy;
	}

	/**
	 * The MEI model's radial curve as a correction to the equidistant model,
	 * degrees: xi, fx, fy are the first three values of each 19-value lens
	 * block and k1, k2, k3 the twelfth to fourteenth. Anchored to the
	 * equidistant model at 90 degrees, so only its shape counts, and the two
	 * lenses averaged. Port of Calibration.radial_correction() in the
	 * library, which has the measurement. Null when the string is not that
	 * shape or the curve does not read.
	 *
	 * @return float[]|null
	 */
	public static function radialCorrection(string $mei, float $step, int $count): ?array {
		$values = array_map('floatval', explode('_', trim($mei)));
		if (\count($values) !== 1 + 2 * 19 + 1 || (int)$values[0] !== 2) {
			return null;
		}
		$radius = static function (int $index, float $theta) use ($values): float {
			$b = 1 + 19 * $index;
			$m = sin($theta) / (cos($theta) + $values[$b]);
			$m2 = $m * $m;
			return ($values[$b + 1] + $values[$b + 2]) / 2
				* $m * (1 + $values[$b + 11] * $m2 + $values[$b + 12] * $m2 ** 2 + $values[$b + 13] * $m2 ** 3);
		};
		$anchors = [$radius(0, M_PI / 2), $radius(1, M_PI / 2)];
		if (!is_finite($anchors[0]) || !is_finite($anchors[1]) || $anchors[0] <= 0 || $anchors[1] <= 0) {
			return null;
		}
		$curve = [];
		for ($k = 0; $k < $count; ++$k) {
			$theta = deg2rad($k * $step);
			$mapped = (90.0 * $radius(0, $theta) / $anchors[0] + 90.0 * $radius(1, $theta) / $anchors[1]) / 2;
			$curve[] = round($mapped - $k * $step, 4);
		}
		for ($k = 1; $k < $count; ++$k) {
			if ($curve[$k] <= $curve[$k - 1] - $step) {
				return null;
			}
		}

		return $curve;
	}

	/**
	 * Where lens 1 sits relative to lens 0, from field 53, the polynomial
	 * model: the seventh to ninth values of each of its 16-value lens blocks.
	 * Only the direction is used and only the direction is verified (see
	 * calibration.Calibration.lens_offset in the library). Null when the
	 * string is not that shape -- a OneR carries no field 53 at all.
	 *
	 * @return array{float, float, float}|null
	 */
	public static function lensOffset(string $polynomial): ?array {
		$values = array_map('floatval', explode('_', trim($polynomial)));
		if (\count($values) !== 1 + 2 * 16 + 1 || (int)$values[0] !== 2) {
			return null;
		}
		$offset = [];
		for ($k = 0; $k < 3; ++$k) {
			$offset[] = $values[1 + 16 + 6 + $k] - $values[1 + 6 + $k];
		}

		return $offset;
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

	/**
	 * This calibration as it applies to a video's frames: the string describes
	 * the still sensor and a video keeps the centre of it, so each centre moves
	 * in by the margin, lens 1 also by lens 0's two, and the radius is kept.
	 * Port of Calibration.for_video() in the library, which has the
	 * measurement; only a centred square crop is understood.
	 *
	 * @param array{int, int, int, int, int, int} $crop Protobuf::sensorCrop()
	 */
	public function forVideo(array $crop): self {
		[$sourceW, $sourceH, $keptW, $keptH, $x, $y] = $crop;
		$referenceWidth = (int)$this->referenceWidth();
		$referenceHeight = (int)($this->globals[1] ?? 0);
		if ($sourceW !== $referenceHeight || $sourceH !== $referenceHeight || $referenceWidth !== 2 * $referenceHeight) {
			throw new FormatError("sensor crop from {$sourceW}x{$sourceH} does not match a {$referenceWidth}x{$referenceHeight} lens pair");
		}
		if ($keptW !== $keptH || $keptW <= 0 || $keptW > $sourceW || $x !== 0 || $y !== 0) {
			throw new FormatError('sensor crop is not the centred square crop that is understood');
		}
		$margin = ($sourceW - $keptW) / 2;
		$lenses = [];
		foreach ($this->lenses as $index => $lens) {
			$lens[1] -= $margin * (1 + 2 * $index);
			$lens[2] -= $margin;
			$lenses[] = $lens;
		}
		$globals = $this->globals;
		$globals[0] = (float)(2 * $keptW);
		$globals[1] = (float)$keptH;
		$cropped = new self($lenses, $globals);
		$cropped->radial = $this->radial;   // in degrees, so the crop leaves it alone

		return $cropped;
	}

	public function scaleFor(int $width): float {
		return $width / $this->referenceWidth();
	}

	/**
	 * Relative rotation between the sensors, degrees, signed the short way.
	 *
	 * A sum, not a difference: each lens states its yaw in its own frame, and
	 * lens 1 faces the other way, so its rotation about the shared axis reads
	 * with the opposite sense in lens 0's. Taken modulo 180.
	 * docs/formats/insta360-agent-notes.md, "Lens orientation differs between cameras",
	 * has the measurement.
	 */
	public function relativeSpin(): float {
		$sum = -($this->lenses[0][5] + $this->lenses[1][5]);

		return fmod(fmod($sum + 90.0, 180.0) + 180.0, 180.0) - 90.0;
	}

	/**
	 * The fourth and fifth values: a small rotation about the lens's own x and
	 * y axes, degrees, in that lens's own frame.
	 *
	 * @return array{float, float}
	 */
	public function tilt(int $index): array {
		return [(float)$this->lenses[$index][3], (float)$this->lenses[$index][4]];
	}

	/**
	 * Roll carrying a render from lens 0's sensor frame into the body frame.
	 *
	 * The absolute yaw is the sensor's mounting angle, which differs by 90
	 * degrees between a OneR and an X3 or X5 -- without this a OneR renders on
	 * its side. See docs/formats/insta360-agent-notes.md.
	 */
	public function bodyRoll(): float {
		return fmod(fmod(90.0 - $this->lenses[0][5] + 180.0, 360.0) + 360.0, 360.0) - 180.0;
	}
}
