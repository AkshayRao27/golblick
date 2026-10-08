<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Insta360;

/**
 * The opening frame of a OneR or X3 video, as compressed keyframes.
 *
 * A port of src/golblick/vendors/insta360/keyframe.py, which has the
 * measurements: a master's records 0x0200 and 0x0500 hold frame 0 of lens 0
 * and lens 1, a proxy's hold one frame with both lenses (the same bytes
 * twice), each behind a 22-byte header that is not decoded. Only the header's
 * length is relied on, and a start code must follow it.
 */
final class Keyframes {
	public const LENS_PAIR = 'lens-pair';
	public const DUAL_FISHEYE = 'dual-fisheye';

	private const HEADER = 22;
	private const START = "\x00\x00\x00\x01";

	/** @param list<string> $streams Annex B, one per lens or one with both */
	private function __construct(
		public readonly string $codec,
		public readonly string $layout,
		public readonly array $streams,
	) {
	}

	public static function isKeyframe(string $record): bool {
		return substr($record, self::HEADER, 4) === self::START;
	}

	public static function parse(string $lens0, ?string $lens1): self {
		if (!self::isKeyframe($lens0)) {
			throw new FormatError('record 0x0200 is not a video keyframe');
		}
		$stream0 = substr($lens0, self::HEADER);
		$codec = self::codec($stream0);
		if ($lens1 === null) {
			throw new FormatError('record 0x0500, the second keyframe, is missing');
		}
		if ($lens1 === $lens0) {
			return new self($codec, self::DUAL_FISHEYE, [$stream0]);
		}
		if (!self::isKeyframe($lens1)) {
			throw new FormatError('record 0x0500 is not a video keyframe');
		}
		$stream1 = substr($lens1, self::HEADER);
		if (self::codec($stream1) !== $codec) {
			throw new FormatError('the two keyframes are in different codecs');
		}

		return new self($codec, self::LENS_PAIR, [$stream0, $stream1]);
	}

	/** The codec, from the type of the first NAL unit, which is a parameter set. */
	private static function codec(string $stream): string {
		$first = \ord($stream[4] ?? "\0");
		if ((($first >> 1) & 0x3F) === 32) {
			return 'hevc';
		}
		if (($first & 0x1F) === 7) {
			return 'h264';
		}
		throw new FormatError(sprintf('keyframe starts with NAL byte 0x%02x, not a parameter set of a known codec', $first));
	}
}
