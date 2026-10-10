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

	/** The share of timecodes that may repeat the one before (imu.py, _REPEATS_ALLOWED). */
	private const REPEATS_ALLOWED = 0.001;

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
	 * ⚠️ So are the OneR's and the X3's: it is the vendor's convention. It
	 * matters for rotation as well as gravity, because the gyroscope shares
	 * these axes and an angular velocity changes sign under a reflection
	 * (motionAxes).
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

	/**
	 * Seconds per raw timecode unit, by entry stride: imu.py's _CLOCK, which
	 * says how it was measured. Milliseconds in the 56-byte form,
	 * microseconds in the 20-byte one.
	 */
	public const CLOCK = [20 => 1e-6, 56 => 1e-3];

	/**
	 * The map that turns the gyroscope's readings into the render's frame, in
	 * radians per second: the gravity map, negated where it is a reflection,
	 * because an angular velocity is an axial vector. imu.py's motion() has
	 * the measurement against Insta360 Studio.
	 *
	 * @return array<int, array<int, float>>
	 */
	public static function motionAxes(string $model): array {
		$axes = self::VIDEO_AXES[$model] ?? self::AXES[$model] ?? null;
		if ($axes === null) {
			throw new FormatError(sprintf(
				'the inertial axis mapping for "%s" has not been measured; stabilising it would be a guess', $model));
		}

		return $axes;
	}

	/** -1.0 where the map is a reflection, else 1.0. */
	public static function handedness(array $axes): float {
		[[$a, $b, $c], [$d, $e, $f], [$g, $h, $i]] = $axes;

		return $a * ($e * $i - $f * $h) - $b * ($d * $i - $f * $g) + $c * ($d * $h - $e * $g) < 0 ? -1.0 : 1.0;
	}

	/**
	 * The record's entry stride, checked exactly as entries() checks it but
	 * keeping nothing, so a half-hour record costs no memory.
	 */
	public static function stride(string $record): int {
		$fits = [];
		foreach (array_keys(self::LAYOUTS) as $stride) {
			if (self::decode($record, $stride, 0) !== null) {
				$fits[] = $stride;
			}
		}
		if (\count($fits) !== 1) {
			throw new FormatError(sprintf('inertial record of %d bytes fits %d of the known strides, not one',
				\strlen($record), \count($fits)));
		}

		return $fits[0];
	}

	/**
	 * When each video frame was captured, in seconds from the record's first
	 * sample: imu.py's motion(), which says how the rule was measured. Frame 0
	 * is metadata field 24, which must fall inside the record and on (or
	 * within half a frame of) an entry of the frame log, 0x0400; the frames
	 * after it follow at the log's spacing.
	 *
	 * @return list<float>
	 */
	public static function frameTimes(string $record, int $stride, string $log, int $first): array {
		$length = \strlen($record);
		$start = unpack('P', $record, 0)[1];
		$end = unpack('P', $record, $length - $stride)[1];
		if ($first < $start || $first > $end) {
			throw new FormatError("the first frame's time falls outside the inertial record");
		}
		if (\strlen($log) < 32 || \strlen($log) % 16 !== 0) {
			throw new FormatError('no readable frame log (0x0400)');
		}
		$stamps = [];
		for ($at = 0; $at < \strlen($log); $at += 16) {
			$stamps[] = unpack('P', $log, $at)[1];
		}
		$steps = [];
		for ($i = 1; $i < \count($stamps); ++$i) {
			if ($stamps[$i] <= $stamps[$i - 1]) {
				throw new FormatError("the frame log's timecodes do not rise");
			}
			$steps[] = $stamps[$i] - $stamps[$i - 1];
		}
		sort($steps);
		$spacing = $steps[intdiv(\count($steps), 2)];
		$nearest = 0;
		foreach ($stamps as $i => $stamp) {
			if (abs($stamp - $first) < abs($stamps[$nearest] - $first)) {
				$nearest = $i;
			}
		}
		if (abs($stamps[$nearest] - $first) > $spacing / 2) {
			throw new FormatError("the first frame's time is not in the frame log");
		}
		$shift = $first - $stamps[$nearest];
		$unit = self::CLOCK[$stride];
		$out = [];
		for ($i = $nearest; $i < \count($stamps); ++$i) {
			$out[] = ($stamps[$i] + $shift - $start) * $unit;
		}

		return $out;
	}

	/** One entry's timecode and six values, decoded: [timecode, ax, ay, az, gx, gy, gz]. */
	public static function entryAt(string $record, int $stride, int $offset): array {
		[$format, $scale, $bias] = self::LAYOUTS[$stride];
		$entry = unpack('Pt/' . $format . 'v', $record, $offset);

		return [$entry['t'],
			($entry['v1'] - $bias) * $scale, ($entry['v2'] - $bias) * $scale, ($entry['v3'] - $bias) * $scale,
			($entry['v4'] - $bias) * $scale, ($entry['v5'] - $bias) * $scale, ($entry['v6'] - $bias) * $scale];
	}

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
		$repeats = 0;
		$allowed = (int)floor(intdiv($length, $stride) * self::REPEATS_ALLOWED);

		for ($offset = 0; $offset < $length; $offset += $stride) {
			// 64-bit little-endian signed; PHP's 'q' is machine order, and
			// every platform this runs on is little-endian, but be explicit.
			$time = unpack('P', substr($record, $offset, self::TIMECODE_BYTES));
			if ($time === false) {
				return null;
			}
			$timecode = $time[1];

			// A wrong stride slices the payload of one entry as the timecode
			// of the next, which does not stay ordered for long. A timecode
			// repeated now and then is the camera's clock (imu.py, _decode).
			if ($previous !== null && $timecode < $previous) {
				return null;
			}
			if ($previous !== null && $timecode === $previous && ++$repeats > $allowed) {
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
