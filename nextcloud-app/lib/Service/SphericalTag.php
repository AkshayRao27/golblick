<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Service;

/**
 * Marks an MP4 as a 360 video, the way Insta360 Studio's exports are marked.
 *
 * Google's spherical video metadata, version 1: an XMP document in a `uuid`
 * box at the end of the video track. Players and indexers that know 360
 * video read it (exiftool reports it as XMP-GSpherical, ProjectionType
 * equirectangular), so a stitched copy says what it is instead of relying on
 * this app to say so. ffmpeg can carry the tag through from an input that has
 * one, but can't create one, hence writing the box here.
 *
 * The copies are written with the movie header in front (+faststart), so the
 * new box pushes the media data back and every chunk offset has to move with
 * it. Refuses, leaving the file as it was, on anything it doesn't fully
 * understand: 64-bit box sizes, no video track, or offsets that would no longer
 * fit in 32 bits.
 */
final class SphericalTag {
	private const UUID = "\xff\xcc\x82\x63\xf8\x55\x4a\x93\x88\x14\x58\x7a\x02\x52\x1f\xdd";

	private const XMP = "<?xml version=\"1.0\"?><rdf:SphericalVideo"
		. " xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\""
		. " xmlns:GSpherical=\"http://ns.google.com/videos/1.0/spherical/\">"
		. '<GSpherical:Spherical>true</GSpherical:Spherical>'
		. '<GSpherical:Stitched>true</GSpherical:Stitched>'
		. '<GSpherical:StitchingSoftware>golblick</GSpherical:StitchingSoftware>'
		. '<GSpherical:ProjectionType>equirectangular</GSpherical:ProjectionType>'
		. '<GSpherical:StereoMode>mono</GSpherical:StereoMode>'
		. '</rdf:SphericalVideo>';

	/** Tag the MP4 at $path in place; true if it is tagged afterwards. */
	public static function add(string $path): bool {
		$in = @fopen($path, 'rb');
		if ($in === false) {
			return false;
		}
		try {
			$length = filesize($path);
			$moov = null;
			$mdat = null;
			for ($at = 0; $at + 8 <= $length;) {
				fseek($in, $at);
				$head = fread($in, 8);
				if ($head === false || \strlen($head) !== 8) {
					return false;
				}
				[, $size] = unpack('N', $head);
				$type = substr($head, 4, 4);
				if ($size === 1) {
					// A 64-bit size: fine for mdat, which is only skipped.
					$big = fread($in, 8);
					if ($big === false || \strlen($big) !== 8) {
						return false;
					}
					[, $size] = unpack('J', $big);
					if ($type === 'moov') {
						return false;
					}
				} elseif ($size === 0) {
					$size = $length - $at;
				}
				if ($size < 8) {
					return false;
				}
				if ($type === 'moov') {
					$moov = [$at, $size];
				} elseif ($type === 'mdat') {
					$mdat ??= $at;
				}
				$at += $size;
			}
			if ($moov === null || $mdat === null) {
				return false;
			}
			fseek($in, $moov[0]);
			$box = fread($in, $moov[1]);
			if ($box === false || \strlen($box) !== $moov[1]) {
				return false;
			}
		} finally {
			fclose($in);
		}

		$tag = pack('N', 8 + 16 + \strlen(self::XMP)) . 'uuid' . self::UUID . self::XMP;
		$video = null;
		$offsets = [];
		foreach (self::children($box, 8, \strlen($box)) as [$type, $start, $size]) {
			if ($type !== 'trak') {
				continue;
			}
			$isVideo = false;
			foreach (self::descend($box, $start, $size) as [$inner, $innerStart, $innerSize]) {
				if ($inner === 'hdlr' && substr($box, $innerStart + 16, 4) === 'vide') {
					$isVideo = true;
				} elseif ($inner === 'stco' || $inner === 'co64') {
					$offsets[] = [$inner, $innerStart];
				} elseif ($inner === 'uuid' && substr($box, $innerStart + 8, 16) === self::UUID) {
					return true;   // already tagged
				}
			}
			if ($isVideo && $video === null) {
				$video = [$start, $size];
			}
		}
		if ($video === null) {
			return false;
		}

		// The media data moves back by the tag's length only if it comes after.
		$shift = $mdat > $moov[0] ? \strlen($tag) : 0;
		if ($shift > 0) {
			foreach ($offsets as [$type, $start]) {
				[, $count] = unpack('N', substr($box, $start + 12, 4));
				$width = $type === 'co64' ? 8 : 4;
				for ($i = 0; $i < $count; ++$i) {
					$at = $start + 16 + $i * $width;
					if ($width === 4) {
						[, $value] = unpack('N', substr($box, $at, 4));
						if ($value + $shift > 0xFFFFFFFF) {
							return false;
						}
						$box = substr_replace($box, pack('N', $value + $shift), $at, 4);
					} else {
						[, $value] = unpack('J', substr($box, $at, 8));
						$box = substr_replace($box, pack('J', $value + $shift), $at, 8);
					}
				}
			}
		}

		[$trakStart, $trakSize] = $video;
		$box = substr_replace($box, pack('N', $trakSize + \strlen($tag)), $trakStart, 4);
		$box = substr($box, 0, $trakStart + $trakSize) . $tag . substr($box, $trakStart + $trakSize);
		$box = substr_replace($box, pack('N', \strlen($box)), 0, 4);

		$temporary = "$path.tagging";
		$in = @fopen($path, 'rb');
		$out = @fopen($temporary, 'wb');
		if ($in === false || $out === false) {
			return false;
		}
		try {
			$ok = stream_copy_to_stream($in, $out, $moov[0]) === $moov[0]
				&& fwrite($out, $box) === \strlen($box);
			fseek($in, $moov[0] + $moov[1]);
			$rest = $length - $moov[0] - $moov[1];
			$ok = $ok && stream_copy_to_stream($in, $out) === $rest;
		} finally {
			fclose($in);
			fclose($out);
		}
		if (!$ok || !rename($temporary, $path)) {
			@unlink($temporary);
			return false;
		}

		return true;
	}

	/**
	 * Direct children of the box spanning [$start, $end) in $data, as
	 * [type, start, size]. Stops at anything malformed or 64-bit sized.
	 *
	 * @return list<array{string, int, int}>
	 */
	private static function children(string $data, int $start, int $end): array {
		$out = [];
		for ($at = $start; $at + 8 <= $end;) {
			[, $size] = unpack('N', substr($data, $at, 4));
			if ($size < 8 || $at + $size > $end) {
				break;
			}
			$out[] = [substr($data, $at + 4, 4), $at, $size];
			$at += $size;
		}

		return $out;
	}

	/**
	 * Every box inside the trak at $start, depth first, through the containers
	 * that lead to the handler and the chunk offset tables.
	 *
	 * @return list<array{string, int, int}>
	 */
	private static function descend(string $data, int $start, int $size): array {
		$out = [];
		foreach (self::children($data, $start + 8, $start + $size) as $child) {
			$out[] = $child;
			if (\in_array($child[0], ['mdia', 'minf', 'stbl'], true)) {
				array_push($out, ...self::descend($data, $child[1], $child[2]));
			}
		}

		return $out;
	}
}
