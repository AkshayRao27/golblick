<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Kugelblick\Insta360;

/**
 * Reader for the binary trailer Insta360 appends to .insp files.
 *
 * A port of the Python reader in src/kugelblick/vendors/insta360/trailer.py,
 * kept deliberately close to it so the two can be compared line for line. The
 * format write-up in docs/formats/insta360.md owns the layout; this file does
 * not restate it.
 *
 * Reads only the trailer, never the whole file. That matters more here than in
 * the CLI: a preview provider runs over a whole library, and an X5 still is 24
 * MB of which the trailer is the last few.
 */
final class Trailer {
	public const MAGIC = '8db42d694ccc418790edff439fe026bf';

	public const METADATA = 0x0101;
	public const PREVIEW = 0x0200;

	/**
	 * Padding widths to try between the last record and the trailer footer.
	 * Nothing in the format announces it, so the reader keeps whichever makes
	 * the record walk land exactly on the trailer boundary -- that check is
	 * the parser's correctness proof.
	 */
	private const CANDIDATE_PADS = [32, 0, 16, 8, 64];

	/** @var array<int, string> record id => payload */
	private array $records;

	/** Where the trailer starts, i.e. the length of the frame in front of it. */
	private int $offset;

	private function __construct(array $records, int $offset) {
		$this->records = $records;
		$this->offset = $offset;
	}

	public function get(int $recordId): ?string {
		return $this->records[$recordId] ?? null;
	}

	public function has(int $recordId): bool {
		return isset($this->records[$recordId]);
	}

	/**
	 * Cheap test for "is this one of ours", without parsing anything.
	 *
	 * Detection is by content rather than by extension, so a renamed file is
	 * still recognised and an ordinary JPEG is never claimed.
	 */
	public static function looksLikeOurs($handle): bool {
		if (fseek($handle, -\strlen(self::MAGIC), SEEK_END) !== 0) {
			return false;
		}

		return self::readExactly($handle, \strlen(self::MAGIC)) === self::MAGIC;
	}

	/**
	 * Read exactly $length bytes, or fewer only at end of stream.
	 *
	 * ⚠️ Not the same as fread(). Nextcloud hands out **user-space stream
	 * wrappers**, and a single fread() on one returns at most one chunk --
	 * 8192 bytes by default -- however much was asked for. Reading a
	 * multi-megabyte trailer in one call therefore silently returns a
	 * fragment. That only shows up through the storage layer: the same code
	 * against a plain local path passes, because fread() on a real file does
	 * return what was asked for.
	 */
	private static function readExactly($handle, int $length): string {
		$out = '';
		while (\strlen($out) < $length) {
			$chunk = fread($handle, $length - \strlen($out));
			if ($chunk === false || $chunk === '') {
				break;
			}
			$out .= $chunk;
		}

		return $out;
	}

	/**
	 * The full-resolution frame the container wraps: everything in front of
	 * the trailer, which for a .insp is a complete JPEG of the lens pair.
	 *
	 * Only read when the camera embedded no preview of its own -- 25 of the
	 * 1,415 stills in one library. It is twenty times the pixels and costs
	 * about a second to decode, which is worth paying once for a cached
	 * thumbnail and is not worth paying by default.
	 */
	public function sourceFrame($handle): string {
		fseek($handle, 0);
		$frame = self::readExactly($handle, $this->offset);
		if (\strlen($frame) !== $this->offset) {
			throw new FormatError('short read of the container');
		}
		// The trailer is appended after the JPEG's own end marker, so the two
		// boundaries must coincide. If they do not, the trailer was misparsed.
		if (!str_starts_with($frame, "\xff\xd8") || !str_ends_with($frame, "\xff\xd9")) {
			throw new FormatError('the container is not a JPEG ending where the trailer begins');
		}

		return $frame;
	}

	/**
	 * @param resource $handle a seekable stream positioned anywhere
	 * @throws FormatError if the trailer cannot be parsed with certainty
	 */
	public static function read($handle): self {
		if (fseek($handle, 0, SEEK_END) !== 0) {
			throw new FormatError('stream is not seekable');
		}
		$fileSize = ftell($handle);

		if (!self::looksLikeOurs($handle)) {
			throw new FormatError('no Insta360 trailer magic');
		}

		fseek($handle, -(\strlen(self::MAGIC) + 8), SEEK_END);
		$footer = unpack('Vsize/Vversion', self::readExactly($handle, 8));
		$size = $footer['size'];
		if ($size <= 0 || $size > $fileSize) {
			throw new FormatError("trailer size {$size} is impossible in {$fileSize} bytes");
		}

		fseek($handle, $fileSize - $size);
		$blob = self::readExactly($handle, $size);
		if (\strlen($blob) !== $size) {
			throw new FormatError('short read of the trailer: ' . \strlen($blob) . " of {$size}");
		}

		$footerStart = $size - \strlen(self::MAGIC) - 8;
		foreach (self::CANDIDATE_PADS as $pad) {
			$end = $footerStart - $pad;
			if ($end < 0) {
				continue;
			}
			$records = self::walk($blob, $end, $stopped);
			if ($stopped === 0 && $records !== []) {
				return new self($records, $fileSize - $size);
			}
		}

		throw new FormatError('no padding width makes the record walk consume the trailer exactly');
	}

	/**
	 * Walk records backwards from $end; each record is *followed* by its footer.
	 *
	 * @return array<int, string>
	 */
	private static function walk(string $blob, int $end, ?int &$stopped): array {
		$records = [];
		$pos = $end;
		while ($pos >= 6) {
			$footer = unpack('vid/Vsize', substr($blob, $pos - 6, 6));
			$start = $pos - 6 - $footer['size'];
			// An all-zero footer is the pad, not a record. No record id of 0
			// has ever been observed, and treating it as the end of the walk
			// keeps the boundary check decisive.
			if ($start < 0 || $footer['id'] === 0) {
				break;
			}
			$records[$footer['id']] = substr($blob, $start, $footer['size']);
			$pos = $start;
		}
		$stopped = $pos;

		return $records;
	}
}
