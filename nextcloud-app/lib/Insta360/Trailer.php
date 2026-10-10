<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Insta360;

/**
 * Reader for the binary trailer Insta360 appends to .insp, .insv and .lrv files.
 *
 * A port of the Python reader in src/golblick/vendors/insta360/trailer.py,
 * kept deliberately close to it so the two can be compared line for line. The
 * format write-up in docs/formats/insta360-agent-notes.md owns the layout; this file does
 * not restate it.
 *
 * Reads only the trailer, never the whole file. That matters more here than in
 * the CLI: a preview provider runs over a whole library, and an X5 still is 24
 * MB of which the trailer is the last few.
 *
 * ⚠️ Unlike the Python reader, it does not load the trailer in one piece. A
 * video's trailer runs to 83 MB (X5) and a thumbnail needs one or two of its
 * records, so the records are located by seeking from footer to footer, and
 * only the payloads asked for are read. The proofs are the same: the walk must
 * land exactly on the trailer's start, and an X5 video's index must agree with
 * every record's own footer and end exactly where the index begins.
 */
final class Trailer {
	public const MAGIC = '8db42d694ccc418790edff439fe026bf';

	public const METADATA = 0x0101;
	public const PREVIEW = 0x0200;
	public const IMU = 0x0300;
	/** In a video, one 16-byte entry per frame: timecode on the inertial clock, then exposure. */
	public const FRAMES = 0x0400;
	/** In a OneR or X3 video, the keyframe of lens 1; PREVIEW holds lens 0's. See Keyframes. */
	public const SECOND_KEYFRAME = 0x0500;

	/**
	 * Padding widths to try between the last record and the trailer footer.
	 * Nothing in the format announces it, so the reader keeps whichever makes
	 * the record walk land exactly on the trailer boundary -- that check is
	 * the parser's correctness proof.
	 */
	private const CANDIDATE_PADS = [32, 0, 16, 8, 64];

	/**
	 * Real trailers carry about a dozen records (an X5 video's index has 31
	 * slots). The walk reads one footer per step from the stream, and a wrong
	 * pad width can read noise as a long run of tiny records, so a walk this
	 * long is treated as not closing. It can only make the reader refuse.
	 */
	private const MAX_RECORDS = 64;

	private const RECORD_FOOTER = 6;
	private const INDEX_ENTRY = 10;

	/** @var array<int, array{int, int}> record id => [start in the file, size] */
	private array $locations;

	/** @var array<int, string> record id => payload, for the records that were read */
	private array $records;

	/** Where the trailer starts, i.e. the length of the frame in front of it. */
	private int $offset;

	private function __construct(array $locations, array $records, int $offset) {
		$this->locations = $locations;
		$this->records = $records;
		$this->offset = $offset;
	}

	/**
	 * A record's payload, or null if the file has no such record.
	 *
	 * @throws \LogicException for a record that exists but was not asked for in read()
	 */
	public function get(int $recordId): ?string {
		if (!isset($this->locations[$recordId])) {
			return null;
		}
		if (!\array_key_exists($recordId, $this->records)) {
			throw new \LogicException(sprintf('record 0x%04x was located but not read; ask for it in Trailer::read', $recordId));
		}

		return $this->records[$recordId];
	}

	/**
	 * A record's payload, read now from $handle, which must be the file read() was given.
	 *
	 * @param resource $handle
	 */
	public function fetch($handle, int $recordId): ?string {
		if (\array_key_exists($recordId, $this->records)) {
			return $this->records[$recordId];
		}
		if (!isset($this->locations[$recordId])) {
			return null;
		}
		[$at, $length] = $this->locations[$recordId];
		fseek($handle, $at);
		$payload = self::readExactly($handle, $length);
		if (\strlen($payload) !== $length) {
			throw new FormatError(sprintf('short read of record 0x%04x', $recordId));
		}

		return $this->records[$recordId] = $payload;
	}

	public function has(int $recordId): bool {
		return isset($this->locations[$recordId]);
	}

	/** @return array<int, int> record id => payload size in bytes */
	public function recordSizes(): array {
		return array_map(static fn (array $at): int => $at[1], $this->locations);
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
	 * @param list<int>|null $only the records to read; null reads all of them
	 * @throws FormatError if the trailer cannot be parsed with certainty
	 */
	public static function read($handle, ?array $only = null): self {
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

		$start = $fileSize - $size;
		$footerStart = $fileSize - \strlen(self::MAGIC) - 8;
		$locations = null;
		foreach (self::CANDIDATE_PADS as $pad) {
			$end = $footerStart - $pad;
			if ($end >= $start && ($locations = self::walk($handle, $start, $end)) !== null) {
				break;
			}
		}
		// Only once no walk closes, so a layout that already parsed is never
		// reinterpreted. An id-0 footer is what stopped the walks above.
		if ($locations === null) {
			foreach (self::CANDIDATE_PADS as $pad) {
				$end = $footerStart - $pad;
				if ($end >= $start && ($locations = self::index($handle, $start, $end)) !== null) {
					break;
				}
			}
		}
		if ($locations === null) {
			throw new FormatError('no padding width makes the record walk consume the trailer exactly, '
				. 'or ends on a consistent record index');
		}

		$records = [];
		foreach ($locations as $id => [$at, $length]) {
			if ($only !== null && !\in_array($id, $only, true)) {
				continue;
			}
			fseek($handle, $at);
			$records[$id] = self::readExactly($handle, $length);
			if (\strlen($records[$id]) !== $length) {
				throw new FormatError(sprintf('short read of record 0x%04x', $id));
			}
		}

		return new self($locations, $records, $start);
	}

	/** Six bytes at $at: a record footer's id and size. */
	private static function footerAt($handle, int $at): array {
		fseek($handle, $at);
		$bytes = self::readExactly($handle, self::RECORD_FOOTER);

		return \strlen($bytes) === self::RECORD_FOOTER ? unpack('vid/Vsize', $bytes) : ['id' => 0, 'size' => 0];
	}

	/**
	 * Walk records backwards from $end; each record is *followed* by its footer.
	 * Null unless the walk lands exactly on the trailer's start.
	 *
	 * @return array<int, array{int, int}>|null
	 */
	private static function walk($handle, int $start, int $end): ?array {
		$locations = [];
		$pos = $end;
		$steps = 0;
		while ($pos - $start >= self::RECORD_FOOTER) {
			$footer = self::footerAt($handle, $pos - self::RECORD_FOOTER);
			$recordStart = $pos - self::RECORD_FOOTER - $footer['size'];
			// An all-zero footer is the pad, not a record. Id 0 only appears as
			// the index of an X5 video trailer, which a walk cannot read, so
			// treating it as the end of the walk keeps the boundary check
			// decisive and leaves the index to index().
			if ($recordStart < $start || $footer['id'] === 0) {
				break;
			}
			if (++$steps > self::MAX_RECORDS) {
				return null;
			}
			// Walking backwards, so a repeated id ends up holding the earliest one.
			$locations[$footer['id']] = [$recordStart, $footer['size']];
			$pos = $recordStart;
		}

		return $pos === $start && $locations !== [] ? $locations : null;
	}

	/**
	 * An X5 video's indexed trailer, whose index record ends at $end, or null.
	 *
	 * The gaps between indexed records hold stale data, so nothing can be said
	 * to consume the trailer exactly. What replaces that proof: every entry must
	 * point at a record whose own footer repeats the entry's id and size, the
	 * records must not overlap, and the last of them must end exactly where the
	 * index begins.
	 *
	 * @return array<int, array{int, int}>|null
	 */
	private static function index($handle, int $start, int $end): ?array {
		if ($end - $start < self::RECORD_FOOTER) {
			return null;
		}
		$footer = self::footerAt($handle, $end - self::RECORD_FOOTER);
		$size = $footer['size'];
		$indexStart = $end - self::RECORD_FOOTER - $size;
		if ($footer['id'] !== 0 || $size === 0 || $size % self::INDEX_ENTRY !== 0 || $indexStart < $start) {
			return null;
		}
		fseek($handle, $indexStart);
		$index = self::readExactly($handle, $size);
		if (\strlen($index) !== $size) {
			return null;
		}

		$found = [];
		for ($pos = 0; $pos < $size; $pos += self::INDEX_ENTRY) {
			// The id is big-endian here, the opposite of the record footer's.
			$entry = unpack('nid/Vsize/Voffset', substr($index, $pos, self::INDEX_ENTRY));
			if ($entry['id'] === 0 && $entry['size'] === 0 && $entry['offset'] === 0) {
				continue;
			}
			$at = $start + $entry['offset'];
			$footerAt = $at + $entry['size'];
			if ($entry['id'] === 0 || $footerAt + self::RECORD_FOOTER > $indexStart) {
				return null;
			}
			$own = self::footerAt($handle, $footerAt);
			if ($own['id'] !== $entry['id'] || $own['size'] !== $entry['size']) {
				return null;
			}
			$found[] = [$entry['id'], $at, $entry['size']];
		}

		usort($found, static fn (array $a, array $b): int => $a[1] <=> $b[1]);
		for ($i = 1, $n = \count($found); $i < $n; ++$i) {
			if ($found[$i - 1][1] + $found[$i - 1][2] + self::RECORD_FOOTER > $found[$i][1]) {
				return null;
			}
		}
		$last = end($found);
		if ($last === false || $last[1] + $last[2] + self::RECORD_FOOTER !== $indexStart) {
			return null;
		}

		$locations = [];
		foreach ($found as [$id, $at, $length]) {
			$locations[$id] ??= [$at, $length];
		}

		return $locations;
	}
}
