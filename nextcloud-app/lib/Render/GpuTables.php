<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Render;

use OCA\Golblick\Insta360\FormatError;

/**
 * RemapTables' tables laid out again for the GPU worker's stitch (worker/stitch.cl).
 *
 * ffmpeg's program_opencl runs a kernel once per plane of its output, and the
 * stitch writes NV12, so it runs once for the luma plane and once for the
 * half-size interleaved chroma plane, handing the kernel the same plane of
 * every input. So each table goes in as P016: plane 0 holds one table at full
 * size, for the luma pass, and plane 1 two tables at half size side by side,
 * for the chroma pass. Which table sits where is the contract with
 * stitch.cl:
 *
 *   ta: x0 | x0, y0      tb: y0 | x1, y1      tc: x1 | mask, -
 *   td: y1 | -, -        te: mask | -, -
 *   fa: fx | fx, fy      fb: fy | -, -        (the balance field, a quarter size)
 *
 * Halving takes every other entry, not an average: a lens writes 0 where it
 * doesn't see, and an average would mix that in. The mask is widened from 8
 * to 16 bits. Each file is read and written a row at a time, so a 3840 table
 * never sits in PHP's memory as an array.
 */
final class GpuTables {
	/** @return array<string, string> the files written, by name, with each one's size as WxH */
	public static function write(string $tables, string $directory, int $lensSize, int $stripSize): array {
		$layout = [
			'ta' => ['x0', 'x0', 'y0'],
			'tb' => ['y0', 'x1', 'y1'],
			'tc' => ['x1', 'mask', null],
			'td' => ['y1', null, null],
			'te' => ['mask', null, null],
			'fa' => ['fx', 'fx', 'fy'],
			'fb' => ['fy', null, null],
		];
		$sizes = [];
		foreach ($layout as $name => [$full, $first, $second]) {
			$sizes[$name] = self::pack("$tables/$full.pgm", $first === null ? null : "$tables/$first.pgm",
				$second === null ? null : "$tables/$second.pgm", "$directory/$name.p016");
		}
		foreach (['s0x', 's0y', 's1x', 's1y'] as $name) {
			self::rescale("$tables/$name.pgm", "$directory/$name.pgm", $stripSize / $lensSize, $stripSize - 1);
		}

		return $sizes;
	}

	/**
	 * The steadying track for stitch.cl: plane 0 as worker/steady.cl reads it
	 * (BakeQueue::trackImage, with as many empty rows again under it, since
	 * P016's second plane is half as tall), and plane 1 the same quaternions as
	 * two pixels a frame, (w, x) above (y, z), half as many frames a row.
	 *
	 * @param list<array{int, int, int, int}> $frames each frame's quaternion as BakeQueue::quaternions() gives it
	 * @return string the size, as WxH
	 */
	public static function writeTrack(array $frames, int $columns, string $path): string {
		$rows = max(1, intdiv(\count($frames) + $columns - 1, $columns));
		$identity = [65535, 32768, 32768, 32768];
		$handle = self::create($path);
		try {
			for ($block = 0; $block < $rows; $block++) {
				for ($c = 0; $c < 4; $c++) {
					$row = [];
					for ($col = 0; $col < $columns; $col++) {
						$row[] = ($frames[$block * $columns + $col] ?? $identity)[$c];
					}
					fwrite($handle, pack('v*', ...$row));
				}
			}
			fwrite($handle, str_repeat("\0", 2 * $columns * 4 * $rows));
			$half = intdiv($columns, 2);
			for ($pair = 0; $pair < 2 * $rows; $pair++) {
				foreach ([[0, 1], [2, 3]] as [$a, $b]) {
					$row = [];
					for ($col = 0; $col < $half; $col++) {
						$quat = $frames[$pair * $half + $col] ?? $identity;
						$row[] = $quat[$a];
						$row[] = $quat[$b];
					}
					fwrite($handle, pack('v*', ...$row));
				}
			}
		} finally {
			fclose($handle);
		}

		return $columns . 'x' . (8 * $rows);
	}

	/** One P016 file: $full as plane 0, $first and $second halved and interleaved as plane 1 (zero where null). */
	private static function pack(string $full, ?string $first, ?string $second, string $path): string {
		$out = self::create($path);
		try {
			[$in, $width, $height, $wide] = self::open($full);
			for ($y = 0; $y < $height; $y++) {
				fwrite($out, pack('v*', ...self::row($in, $width, $wide)));
			}
			fclose($in);

			$half = intdiv($width, 2);
			$sources = [];
			foreach ([$first, $second] as $source) {
				$sources[] = $source === null ? null : self::open($source);
			}
			$zero = array_fill(0, $half, 0);
			for ($y = 0; $y < intdiv($height, 2); $y++) {
				$columns = [];
				foreach ($sources as $source) {
					if ($source === null) {
						$columns[] = $zero;
						continue;
					}
					[$handle, $w, $h, $sourceWide] = $source;
					if ($w !== $width || $h !== $height) {
						throw new FormatError("the tables for $path differ in size");
					}
					$row = self::row($handle, $w, $sourceWide);
					self::row($handle, $w, $sourceWide);   // every other row
					$columns[] = array_values(array_filter($row, static fn (int $k): bool => $k % 2 === 0, ARRAY_FILTER_USE_KEY));
				}
				$pairs = [];
				for ($x = 0; $x < $half; $x++) {
					$pairs[] = $columns[0][$x];
					$pairs[] = $columns[1][$x];
				}
				fwrite($out, pack('v*', ...$pairs));
			}
			foreach ($sources as $source) {
				if ($source !== null) {
					fclose($source[0]);
				}
			}
		} finally {
			fclose($out);
		}

		return $width . 'x' . $height;
	}

	/** A 16-bit PGM with every entry scaled by $factor, at most $max: lens positions for a smaller lens. */
	private static function rescale(string $from, string $to, float $factor, int $max): void {
		[$in, $width, $height, $wide] = self::open($from);
		$out = self::create($to);
		try {
			fwrite($out, "P5 $width $height 65535\n");
			for ($y = 0; $y < $height; $y++) {
				fwrite($out, pack('n*', ...array_map(static fn (int $v): int => min($max, (int)round($v * $factor)), self::row($in, $width, $wide))));
			}
		} finally {
			fclose($in);
			fclose($out);
		}
	}

	/**
	 * A PGM as RemapTables writes it: the header on one line, then 8- or
	 * 16-bit (big-endian) entries.
	 *
	 * @return array{resource, int, int, bool} the handle at the first entry, width, height, and whether entries are 16-bit
	 */
	private static function open(string $path): array {
		$handle = @fopen($path, 'rb');
		$header = $handle === false ? false : fgets($handle, 64);
		if ($header === false || !preg_match('/^P5 (\d+) (\d+) (255|65535)\n$/', $header, $m)) {
			throw new FormatError("could not read the table $path");
		}

		return [$handle, (int)$m[1], (int)$m[2], $m[3] === '65535'];
	}

	/** @return list<int> one row, in 16-bit units: an 8-bit table is widened so 255 becomes 65535 */
	private static function row($handle, int $width, bool $wide): array {
		$bytes = $wide ? 2 * $width : $width;
		$data = '';
		while (\strlen($data) < $bytes && !feof($handle)) {
			$chunk = fread($handle, $bytes - \strlen($data));
			if ($chunk === false || $chunk === '') {
				break;
			}
			$data .= $chunk;
		}
		if (\strlen($data) !== $bytes) {
			throw new FormatError('a table ended early');
		}

		return $wide ? array_values(unpack('n*', $data)) : array_map(static fn (int $v): int => 257 * $v, array_values(unpack('C*', $data)));
	}

	/** @return resource */
	private static function create(string $path) {
		$handle = @fopen($path, 'wb');
		if ($handle === false) {
			throw new FormatError("could not write $path");
		}

		return $handle;
	}
}
