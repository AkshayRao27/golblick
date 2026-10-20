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
 * Two encodings, and the camera does not announce which. An entry is a
 * 64-bit timecode (units by stride, CLOCK) followed by six values -- three accelerometer
 * axes in g, then three angular velocities -- stored either as six uint16
 * biased by 0x8000, or as six float64. The stride is not a property of the
 * camera model, so the decoder tries both and keeps the one that divides the
 * record exactly and whose timecodes rise, refusing when none fits or both do,
 * as the trailer's padding search does.
 *
 * Many stills carry no such record; see Preview\Insta360::burstImu.
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
	 * Measured per camera, never borrowed: upright, an X5 reads gravity along
	 * -x and a OneR along +x, so lending one camera's map to another hangs the
	 * panorama upside down. Each was measured against Insta360 Studio's
	 * levelled exports; docs/formats/insta360-agent-notes.md, "Route 2" and the sections after it, has the evidence.
	 *
	 * Every map here is a reflection (determinant -1). That is the vendor's
	 * convention, not a mistake: don't "correct" it by flipping a sign. It
	 * matters for rotation too, because the gyroscope shares these axes and an
	 * angular velocity changes sign under a reflection (motionAxes).
	 */
	private const AXES = [
		'Insta360 X5' => [[0.0, 0.0, -1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]],
		'Insta360 OneR' => [[-1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]],
		'Insta360 X3' => [[0.0, 0.0, -1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]],
	];

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
	 * Forms whose frame log stamps each frame late, as imu.py's _LATE_STAMPS (a
	 * test keeps the two equal): their frames are counted off from field 24 at
	 * the log's own spacing, plus field 28, less half each frame's exposure.
	 */
	public const LATE_STAMPS = [56];

	/** Metadata field 28 in ms, which LATE_STAMPS' frames are offset by; null if the file lacks it. */
	public static function frameOffset(array $fields): ?float {
		$value = $fields[Protobuf::FRAME_OFFSET][0] ?? null;
		if (!\is_string($value) || \strlen($value) !== 8) {
			return null;
		}
		$ms = unpack('e', $value)[1];

		return is_finite($ms) ? $ms : null;
	}

	/**
	 * Models whose rolling shutter has been measured, as imu.py's _READS_DOWN:
	 * each lens image is read down its rows, both lenses alike, over metadata
	 * field 25's time. Others get no correction until it is measured.
	 */
	public const READS_DOWN = ['Insta360 OneR', 'Insta360 X3', 'Insta360 X5'];

	/**
	 * How long the sensor took to read each frame, in seconds, as imu.py's
	 * Motion.readout: field 25 for a measured model, if it is shorter than a
	 * frame; 0, don't correct, otherwise.
	 *
	 * @param array<int, list<string|int>> $fields Protobuf::fields of the metadata record
	 * @param list<float> $frameTimes self::frameTimes
	 */
	public static function readout(array $fields, string $model, array $frameTimes): float {
		$value = $fields[Protobuf::READOUT][0] ?? null;
		if (!\in_array($model, self::READS_DOWN, true) || !\is_string($value) || \strlen($value) !== 8
			|| \count($frameTimes) < 2) {
			return 0.0;
		}
		$ms = unpack('e', $value)[1];
		$steps = [];
		for ($i = 1; $i < \count($frameTimes); ++$i) {
			$steps[] = $frameTimes[$i] - $frameTimes[$i - 1];
		}
		sort($steps);
		// A frame is read within its own period; anything else isn't a readout time.
		$spacing = $steps[intdiv(\count($steps), 2)];

		return is_finite($ms) && $ms > 0.0 && $ms < 1000.0 * $spacing ? $ms / 1000.0 : 0.0;
	}

	/**
	 * The map that turns the gyroscope's readings into the render's frame, in
	 * radians per second: the gravity map, negated where it is a reflection,
	 * because an angular velocity is an axial vector. docs/formats/insta360-agent-notes.md,
	 * "Stabilising video from the record", has the measurement against Insta360 Studio.
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

	/**
	 * What the decoded accelerometer and gyroscope values are multiplied by to
	 * be in g and radians per second, as imu.py's _gains: 1 for the 56-byte
	 * form, and field 65's full scale over 32768 for the 20-byte one, which
	 * LAYOUTS reads as thousandths (6.1% short for the gyroscope).
	 *
	 * @param array<int, list<string|int>> $fields Protobuf::fields of the metadata record
	 * @return array{float, float}
	 */
	public static function gains(array $fields, int $stride): array {
		if ($stride !== 20) {
			return [1.0, 1.0];
		}
		$scale = Protobuf::fullScale($fields);
		if ($scale === null) {
			throw new FormatError('no sensor full scale (metadata field 65), which the 20-byte form is counted in');
		}

		return [$scale[0] * 1000.0 / 32768.0, deg2rad($scale[1]) * 1000.0 / 32768.0];
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
	 * sample, as imu.py's motion() works it out (docs/formats/insta360-agent-notes.md, "When each frame was captured"
	 * and "Frame stamps in the 56-byte form come late"). Frame 0 is the entry
	 * of the frame log, 0x0400, nearest metadata field 24, which must fall
	 * inside the record and within half a frame of it. The 20-byte form's
	 * frames were captured at field 24's time and the log's spacing; the
	 * 56-byte form's at field 24's time, the log's spacing and $offset (field
	 * 28, self::frameOffset), less half each frame's exposure.
	 *
	 * @return list<float>
	 */
	public static function frameTimes(string $record, int $stride, string $log, int $first, ?float $offset = null): array {
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
		$exposures = [];
		for ($at = 0; $at < \strlen($log); $at += 16) {
			$stamps[] = unpack('P', $log, $at)[1];
			$exposures[] = unpack('e', $log, $at + 8)[1];
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
		if (!\in_array($stride, self::LATE_STAMPS, true)) {
			for ($i = $nearest; $i < \count($stamps); ++$i) {
				$out[] = ($stamps[$i] + $shift - $start) * $unit;
			}

			return $out;
		}
		if ($offset === null) {
			throw new FormatError('no frame time offset (metadata field 28)');
		}
		$count = \count($stamps) - $nearest;
		if ($count < 2) {
			throw new FormatError('the frame log ends at the first frame');
		}
		$period = ($stamps[\count($stamps) - 1] - $stamps[$nearest]) / ($count - 1);
		for ($k = 0; $k < $count; ++$k) {
			$i = $nearest + $k;
			if (!($exposures[$i] >= 0.0 && $exposures[$i] < 1.0)) {
				throw new FormatError("the frame log has an exposure that isn't a fraction of a second");
			}
			// Counting frames off at one period is only right if none is missing.
			if (abs($stamps[$i] - $stamps[$nearest] - $k * $period) > $period / 2) {
				throw new FormatError("the frame log isn't evenly spaced, so its frames can't be counted off from field 24");
			}
			$out[] = ($first - $start + $k * $period) * $unit + $offset / 1000 - $exposures[$i] / 2;
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

	/**
	 * Which way is up, as a unit vector in the render's own frame.
	 *
	 * @param string $record the raw 0x0300 payload
	 * @param string $model  the camera model, from the metadata record
	 * @return array{float, float, float}
	 */
	public static function gravityUp(string $record, string $model, ?int $first = null, bool $video = false): array {
		$axes = ($video ? (self::VIDEO_AXES[$model] ?? null) : null) ?? self::AXES[$model] ?? null;
		if ($axes === null) {
			throw new FormatError(sprintf(
				'the inertial axis mapping for "%s" has not been measured (only %s); levelling it would be a guess',
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
