<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Insta360;

/**
 * Record 0x0300 -- the inertial log, and which way is up in it.
 *
 * This is what lets a panorama be levelled for PITCH as well as roll. The
 * calibration string gives the sensor's mounting angle, which is a constant of
 * the camera body, so a shot taken with the camera tilted forward stays tilted
 * however carefully that is applied. The accelerometer says which way the
 * ground was.
 *
 * A direct port of src/golblick/vendors/insta360/imu.py, kept close enough
 * to read side by side. docs/formats/insta360-agent-notes.md owns the measured facts.
 *
 * ⚠️ Two encodings, and the camera does not announce which. An entry is a
 * 64-bit millisecond timecode followed by six values -- three accelerometer
 * axes in g, then three angular velocities -- stored either as six uint16
 * biased by 0x8000, or as six float64. The stride is NOT a property of the
 * camera model: of 379 OneR stills carrying this record, 285 use one form and
 * 94 the other. So the decoder tries both and keeps the one that divides the
 * record exactly and whose timecodes rise, refusing when none fits or both do.
 * That is the same discipline the trailer's padding search uses.
 *
 * ⚠️ Most files carry no such record: 965 of 1,415 in one library, all OneR.
 */
final class Imu {
	/** Stride in bytes => [unpack format for the six values, scale, bias]. */
	private const LAYOUTS = [
		20 => ['v6', 0.001, 32768.0],   // six uint16, biased
		56 => ['e6', 1.0, 0.0],         // six little-endian float64
	];

	private const TIMECODE_BYTES = 8;

	/**
	 * How much of a video's record levels its opening frame: imu.py's
	 * OPENING_SAMPLES, which says why. Pass it as $first for a video.
	 */
	public const OPENING_SAMPLES = 1500;

	/**
	 * How each camera's inertial axes sit relative to the render's, as rows of
	 * a map applied to the acceleration vector.
	 *
	 * 🔴 Measured per camera, never borrowed. Upright, an X5 reads gravity
	 * along -x and a OneR along +x, so lending one camera's mapping to another
	 * hangs the panorama upside down.
	 *
	 * 🔴 The X5's map is a REFLECTION, determinant -1. That is not a mistake
	 * and must not be "corrected" by flipping a sign back; it says the stored
	 * triple, as this code labels it, is not right-handed on that camera.
	 *
	 * ⛔ The X3 is deliberately absent. Its readings cannot be reconciled with
	 * the camera's attitude -- two sessions that both render level give median
	 * readings 26 degrees apart -- so it is refused rather than guessed.
	 * history/08_IMU_AXES.md has the evidence.
	 */
	private const AXES = [
		'Insta360 X5' => [[0.0, 0.0, -1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]],
		// 🔴 Corrected 2026-09-29. The previous map for this camera was chosen
		// by matching the calibration's body-up, a proxy that misleads here.
		// Scored against Insta360 Studio's own levelled exports over 358
		// stills, this map gives a median error of 1.2 degrees where the old
		// one gave 9.1, and 1.0 where the old one gave 61.5 on the files using
		// the other inertial encoding. imu.py owns the evidence.
		'Insta360 OneR' => [[-1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]],
		// 🔴 Measured 2026-09-29, after this camera had been refused outright.
		// The same map as the X5. 38 stills over five sessions against Studio's
		// levelled exports: 0.83 degrees median, every file within 5, where the
		// mounting angle alone leaves 46 to 53. imu.py owns the evidence and
		// why the earlier refusal was wrong.
		'Insta360 X3' => [[0.0, 0.0, -1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]],
	];

	/**
	 * Which way is up, as a unit vector in the render's own frame.
	 *
	 * @param string $record the raw 0x0300 payload
	 * @param string $model  the camera model, from the metadata record
	 * @return array{float, float, float}
	 */
	/**
	 * Where a camera's VIDEO record differs from its stills': imu.py's
	 * _VIDEO_AXES, which has the measurement (44 X5 videos against the
	 * camera's own stitch, 3.7 degrees median; the still map scores 87).
	 */
	private const VIDEO_AXES = [
		'Insta360 X5' => [[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
	];

	public static function gravityUp(string $record, string $model, ?int $first = null, bool $video = false): array {
		$axes = ($video ? (self::VIDEO_AXES[$model] ?? null) : null) ?? self::AXES[$model] ?? null;
		if ($axes === null) {
			throw new FormatError(sprintf(
				'the inertial axis mapping for "%s" has not been measured (only %s); '
					. 'levelling it would be a guess',
				$model,
				implode(', ', array_keys(self::AXES)),
			));
		}

		$vector = self::gravity($record, $first);
		$length = sqrt($vector[0] ** 2 + $vector[1] ** 2 + $vector[2] ** 2);
		if ($length < 0.5) {
			throw new FormatError(sprintf(
				'accelerometer reads %.3f g, too little to be gravity', $length
			));
		}

		$unit = [$vector[0] / $length, $vector[1] / $length, $vector[2] / $length];

		$out = [];
		foreach ($axes as $row) {
			$out[] = $row[0] * $unit[0] + $row[1] * $unit[1] + $row[2] * $unit[2];
		}

		return [$out[0], $out[1], $out[2]];
	}

	/**
	 * The accelerometer's median reading over the whole record, in g.
	 *
	 * The median rather than the mean, and over every sample rather than the
	 * one nearest the shutter: a still's log is short, and a hand shake at one
	 * end of it should not tilt the horizon.
	 *
	 * @return array{float, float, float}
	 */
	public static function gravity(string $record, ?int $first = null): array {
		$samples = self::entries($record, $first);
		if ($samples === []) {
			throw new FormatError('inertial record is empty');
		}

		$out = [];
		for ($axis = 0; $axis < 3; ++$axis) {
			$column = array_column($samples, $axis);
			sort($column);
			$n = \count($column);
			$middle = intdiv($n, 2);
			$out[] = $n % 2 === 1
				? $column[$middle]
				: ($column[$middle - 1] + $column[$middle]) / 2;
		}

		return [$out[0], $out[1], $out[2]];
	}

	/**
	 * The acceleration triples in the record, whichever encoding it uses.
	 *
	 * @return list<array{float, float, float}>
	 */
	public static function entries(string $record, ?int $keep = null): array {
		$fits = [];
		foreach (array_keys(self::LAYOUTS) as $stride) {
			$decoded = self::decode($record, $stride, $keep);
			if ($decoded !== null) {
				$fits[$stride] = $decoded;
			}
		}

		if ($fits === []) {
			throw new FormatError(sprintf(
				'inertial record of %d bytes matches no known entry stride (%s)',
				\strlen($record),
				implode(', ', array_keys(self::LAYOUTS)),
			));
		}
		if (\count($fits) > 1) {
			// Refuse rather than pick: a wrong stride yields plausible numbers.
			throw new FormatError(sprintf(
				'inertial record is ambiguous -- strides %s both fit',
				implode(' and ', array_keys($fits)),
			));
		}

		return reset($fits);
	}

	/**
	 * Read the record at one candidate stride, or null if it does not fit.
	 *
	 * @return list<array{float, float, float}>|null
	 */
	private static function decode(string $record, int $stride, ?int $keep): ?array {
		$length = \strlen($record);
		if ($stride > $length || $length % $stride !== 0) {
			return null;
		}

		[$format, $scale, $bias] = self::LAYOUTS[$stride];
		$samples = [];
		$previous = null;

		for ($offset = 0; $offset < $length; $offset += $stride) {
			// 64-bit little-endian signed; PHP's 'q' is machine order, and
			// every platform this runs on is little-endian, but be explicit.
			$time = unpack('P', substr($record, $offset, self::TIMECODE_BYTES));
			if ($time === false) {
				return null;
			}
			$timecode = $time[1];

			// A wrong stride slices the payload of one entry as the timecode
			// of the next, which does not stay ordered for long.
			if ($previous !== null && $timecode <= $previous) {
				return null;
			}
			$previous = $timecode;

			// Past $keep, only the timecodes are checked, so a stride is accepted
			// or refused on the whole record exactly as imu.py does, while
			// memory stays bounded by what is kept.
			if ($keep !== null && \count($samples) >= $keep) {
				continue;
			}
			$six = unpack($format, substr($record, $offset + self::TIMECODE_BYTES, $stride - self::TIMECODE_BYTES));
			if ($six === false) {
				return null;
			}

			$samples[] = [
				($six[1] - $bias) * $scale,
				($six[2] - $bias) * $scale,
				($six[3] - $bias) * $scale,
			];
		}

		return $samples;
	}
}
