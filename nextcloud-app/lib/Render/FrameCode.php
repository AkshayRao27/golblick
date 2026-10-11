<?php

declare(strict_types=1);

// SPDX-License-Identifier: AGPL-3.0-or-later

namespace OCA\Golblick\Render;

/**
 * Each frame's number, drawn into the bottom rows of a stitched copy, so the
 * player can turn the sphere for the frame it is actually drawing.
 *
 * 🔴 Why it's in the pixels: during playback Firefox's frame clock
 * (requestVideoFrameCallback, currentTime) runs a frame ahead of the picture
 * a texture upload gets on 10-46% of renders, and sometimes nine ahead, and
 * its VideoFrame carries no timestamp. Steadying by that clock flickers. The
 * shader reads this code from the same texture it draws, so the two agree in
 * every browser (src/sphere.ts).
 *
 * The strip is the bottom 16 rows, one macroblock row, which a sphere shrinks
 * to a cap 2 degrees across straight below the camera; the player doesn't
 * show it. 20 bits, each next to its complement, in 40 cells across: the pair
 * is what tells a code from a frame that doesn't carry one. Bits 0-18 are the
 * frame's number (to 4.8 hours at 30 frames a second) and bit 19 is set only
 * in a copy whose steadying is baked in, by the GPU worker (worker/steady.cl
 * draws the strip again there, in the same layout).
 */
final class FrameCode {
	public const BITS = 20;
	public const BAKED = 19;
	public const CELLS = 2 * self::BITS;
	public const ROWS = 16;

	/** The ffmpeg filters that draw it, to append to a chain on a $width x $width/2 frame. */
	public static function filter(int $width): string {
		$top = intdiv($width, 2) - self::ROWS;
		$filters = [sprintf('drawbox=x=0:y=%d:w=%d:h=%d:c=black:t=fill', $top, $width, self::ROWS)];
		for ($cell = 0; $cell < self::CELLS; $cell++) {
			$left = intdiv($cell * $width, self::CELLS);
			$right = intdiv(($cell + 1) * $width, self::CELLS);
			$bit = intdiv($cell, 2);
			// The even cell is white when the bit is set, the odd one when it
			// isn't; a render is never baked, so its flag is always clear.
			$enable = $bit === self::BAKED
				? ($cell % 2 === 0 ? null : '')
				: sprintf(":enable='eq(mod(floor(n/%d),2),%d)'", 1 << $bit, $cell % 2 === 0 ? 1 : 0);
			if ($enable !== null) {
				$filters[] = sprintf('drawbox=x=%d:y=%d:w=%d:h=%d:c=white:t=fill%s', $left, $top, $right - $left, self::ROWS, $enable);
			}
		}

		return implode(',', $filters);
	}
}
