<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Insta360;

/**
 * Just enough protobuf wire format to read record 0x0101.
 *
 * Insta360 publishes no schema, so this deliberately does not model the
 * message: it walks the wire format and hands back fields by number. A
 * firmware revision that adds or renumbers fields then degrades to "that field
 * is missing" rather than failing to parse.
 */
final class Protobuf {
	public const SERIAL = 1;
	public const MODEL = 2;
	public const CALIBRATION_EQUIDISTANT = 5;

	/**
	 * @return array<int, list<string|int>> field number => values, in order
	 */
	public static function fields(string $buffer): array {
		$out = [];
		$pos = 0;
		$length = \strlen($buffer);

		while ($pos < $length) {
			$key = self::varint($buffer, $pos);
			$number = $key >> 3;
			$wire = $key & 7;
			if ($number === 0) {
				throw new FormatError('field number 0 is not valid');
			}

			switch ($wire) {
				case 0:
					$value = self::varint($buffer, $pos);
					break;
				case 1:
					$value = substr($buffer, $pos, 8);
					$pos += 8;
					break;
				case 5:
					$value = substr($buffer, $pos, 4);
					$pos += 4;
					break;
				case 2:
					$size = self::varint($buffer, $pos);
					if ($pos + $size > $length) {
						throw new FormatError('length-delimited field runs past the buffer');
					}
					$value = substr($buffer, $pos, $size);
					$pos += $size;
					break;
				default:
					throw new FormatError("unsupported wire type {$wire}");
			}
			$out[$number][] = $value;
		}

		return $out;
	}

	public static function firstText(array $fields, int $number): ?string {
		foreach ($fields[$number] ?? [] as $value) {
			if (\is_string($value)) {
				return $value;
			}
		}

		return null;
	}

	private static function varint(string $buffer, int &$pos): int {
		$result = 0;
		$shift = 0;
		$length = \strlen($buffer);
		while (true) {
			if ($pos >= $length) {
				throw new FormatError('truncated varint');
			}
			$byte = \ord($buffer[$pos]);
			++$pos;
			$result |= ($byte & 0x7F) << $shift;
			if (($byte & 0x80) === 0) {
				return $result;
			}
			$shift += 7;
			if ($shift > 63) {
				throw new FormatError('varint too long');
			}
		}
	}
}
