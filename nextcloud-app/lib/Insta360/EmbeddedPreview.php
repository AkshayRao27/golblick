<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Insta360;

/**
 * Record 0x0200 -- the camera's own full-size preview.
 *
 * What it contains depends on the camera, and the difference matters more than
 * the size: an X5 stores an equirectangular NV12 stitch, a OneR and X3 store
 * the dual-fisheye pair as JPEG. So one of them needs projecting and the other
 * does not.
 *
 * This is the right source for a *thumbnail*. The full-resolution frame in
 * front of the trailer is twenty times the pixels on a OneR, which is what an
 * export wants and a preview does not.
 */
final class EmbeddedPreview {
	public const JPEG = 'jpeg';
	public const NV12 = 'nv12';

	/** Fixed header in front of the NV12 pixel data; dimensions sit at offset 16. */
	private const NV12_HEADER = 40;

	public string $encoding;
	public int $width;
	public int $height;
	public bool $isStitched;
	public string $data;

	private function __construct(string $encoding, int $width, int $height, bool $stitched, string $data) {
		$this->encoding = $encoding;
		$this->width = $width;
		$this->height = $height;
		$this->isStitched = $stitched;
		$this->data = $data;
	}

	public static function parse(string $payload): self {
		if (str_starts_with($payload, "\xff\xd8")) {
			// The lens pair. Dimensions come from the JPEG decoder later, so
			// they are not read here.
			return new self(self::JPEG, 0, 0, false, $payload);
		}

		if (\strlen($payload) < self::NV12_HEADER) {
			throw new FormatError('preview record is too small for its header');
		}

		$header = unpack('Vwidth/Vheight', substr($payload, 16, 8));
		$width = $header['width'];
		$height = $header['height'];
		$pixels = substr($payload, self::NV12_HEADER);
		$expected = intdiv($width * $height * 3, 2);

		// The header declares its own geometry, so this is checkable rather
		// than assumed. A buffer that decodes to garbage is worse than an error.
		if ($width <= 0 || $height <= 0 || \strlen($pixels) !== $expected) {
			throw new FormatError("preview declares {$width}x{$height} but carries " . \strlen($pixels) . ' bytes');
		}

		return new self(self::NV12, $width, $height, true, $pixels);
	}
}
