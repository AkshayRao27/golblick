<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Service;

use OCA\Golblick\Insta360\Calibration;
use OCA\Golblick\Insta360\EmbeddedPreview;
use OCA\Golblick\Insta360\FormatError;
use OCA\Golblick\Insta360\Imu;
use OCA\Golblick\Insta360\Keyframes;
use OCA\Golblick\Insta360\LensProfile;
use OCA\Golblick\Insta360\Protobuf;
use OCA\Golblick\Insta360\Trailer;
use OCA\Golblick\Preview\Insta360;
use OCP\App\IAppManager;
use OCP\Files\File;
use OCP\ServerVersion;

/**
 * A summary of one file that is safe to paste into a public GitHub issue: the
 * app's counterpart of `golblick report`, in the same layout. Three kinds of
 * issue use it: a problem with a photo or with a video from a camera golblick
 * has been tested with, and a camera it has not been tested with.
 *
 * It leaves out the file's name (Insta360 names carry the date and time), its
 * folder and the camera's serial number. Where the CLI says what a render
 * would do, this says what this app does with the file, which differs: an X5
 * is shown from the camera's own panorama here, and never re-stitched.
 *
 * Every step reports its own failure and the report carries on, because the
 * files people report are the ones that fail somewhere.
 */
final class CameraReport {
	private const NAMES = [Trailer::METADATA => 'metadata', Trailer::PREVIEW => 'preview', Trailer::IMU => 'imu', Trailer::FRAMES => 'frames'];

	public function __construct(
		private IAppManager $appManager,
		private ServerVersion $serverVersion,
		private Insta360 $provider,
		private VideoStore $videos,
	) {
	}

	/**
	 * @return array{report: string, model: ?string, firmware: ?string, tested: ?bool, video: bool}
	 *         the report; the values an issue title is made from; whether
	 *         golblick has been tested with this camera (null when the file was
	 *         not readable as one), which picks the issue form; and whether the
	 *         file is a video, which picks between the photo and video forms
	 */
	public function build(File $file): array {
		$model = $firmware = $tested = null;
		$video = false;
		$lines = [sprintf('golblick app %s, Nextcloud %s, PHP %s',
			$this->appManager->getAppVersion('golblick'), $this->serverVersion->getVersionString(), PHP_VERSION)];
		$add = static function (string $label, string $text) use (&$lines): void {
			$lines[] = sprintf('%-12s %s', $label, $text);
		};
		$failed = static fn (string $label, \Throwable $e) => $add($label, 'failed: ' . (new \ReflectionClass($e))->getShortName() . ': ' . $e->getMessage());

		$extension = strtolower($file->getExtension());
		$add('file', ($extension === '' ? '(no extension)' : '.' . $extension) . ', ' . self::human($file->getSize()));

		try {
			$handle = $file->fopen('r');
			if ($handle === false) {
				throw new \RuntimeException('could not open the file');
			}
		} catch (\Throwable $e) {
			$failed('file', $e);

			return ['report' => implode("\n", $lines), 'model' => $model, 'firmware' => $firmware, 'tested' => $tested, 'video' => $video];
		}

		try {
			// By content, as the CLI does: an MP4 has "ftyp" at byte 4.
			$video = substr((string)fread($handle, 8), 4, 4) === 'ftyp';
			rewind($handle);
			if (!Trailer::looksLikeOurs($handle)) {
				$add('vendor', 'none recognises this file');
				$add('content', self::sniff($handle, (int)$file->getSize()));

				return ['report' => implode("\n", $lines), 'model' => $model, 'firmware' => $firmware, 'tested' => $tested, 'video' => $video];
			}
			$add('vendor', 'insta360');
			try {
				$trailer = Trailer::read($handle);
			} catch (\Throwable $e) {
				$failed('trailer', $e);

				return ['report' => implode("\n", $lines), 'model' => $model, 'firmware' => $firmware, 'tested' => $tested, 'video' => $video];
			}
		} finally {
			fclose($handle);
		}

		$fields = [];
		$metadata = $trailer->get(Trailer::METADATA);
		if ($metadata !== null) {
			try {
				$fields = Protobuf::fields($metadata);
			} catch (\Throwable $e) {
				$failed('metadata', $e);
			}
		}
		$model = Protobuf::firstText($fields, Protobuf::MODEL);
		$add('model', $model ?? '-');
		$firmware = Protobuf::firstText($fields, Protobuf::FIRMWARE);
		$add('firmware', $firmware ?? '-');
		// "Tested" means a measured lens profile, the same test the CLI makes.
		$tested = LensProfile::isMeasured($model);
		$add('tested', $tested ? 'yes' : 'no: golblick has not been tested with this camera');

		// By id, not file order, so this and the CLI's report line up.
		$sizes = $trailer->recordSizes();
		ksort($sizes);
		$first = true;
		foreach ($sizes as $id => $size) {
			$lines[] = sprintf('%-12s 0x%04x %-16s %9d bytes', $first ? 'records' : '', $id,
				self::NAMES[$id] ?? sprintf('unknown_%04x', $id), $size);
			$first = false;
		}

		$calibration = null;
		$text = Protobuf::firstText($fields, Protobuf::CALIBRATION_EQUIDISTANT);
		if ($text === null) {
			$add('calibration', 'no equidistant calibration');
		} else {
			try {
				$calibration = Calibration::parse($text);
				$add('calibration', 'equidistant, read');
			} catch (\Throwable $e) {
				$failed('calibration', $e);
			}
		}

		[$fieldOfView, $radial] = LensProfile::for($model);
		$add('lens', LensProfile::isMeasured($model)
			? sprintf('measured: field of view %g degrees', $fieldOfView)
				. (LensProfile::guardFactor($model) !== null ? sprintf(', divided by %g with lens guards', LensProfile::guardFactor($model)) : '')
				. ($radial ? sprintf(', radial correction (%d terms)', \count($radial)) : '')
			: sprintf('not measured for this camera; assuming %g degrees', $fieldOfView));

		if ($video) {
			$this->videoLines($file, $trailer, $fields, $model, $add, $failed);
			$add('memory', 'PHP limit ' . ini_get('memory_limit'));

			return ['report' => implode("\n", $lines), 'model' => $model, 'firmware' => $firmware, 'tested' => $tested, 'video' => $video];
		}

		$preview = null;
		$payload = $trailer->get(Trailer::PREVIEW);
		if ($payload === null) {
			$add('preview', 'none');
		} else {
			try {
				$preview = EmbeddedPreview::parse($payload);
				$size = $preview->width > 0 ? [$preview->width, $preview->height] : (@getimagesizefromstring($preview->data) ?: [0, 0]);
				$add('preview', sprintf('%dx%d %s %s', $size[0], $size[1], $preview->encoding,
					$preview->isStitched ? 'equirectangular' : 'dual-fisheye'));
			} catch (\Throwable $e) {
				$failed('preview', $e);
			}
		}

		if ($preview !== null && $preview->isStitched) {
			$add('panorama', "the camera's own, as stored");
		} elseif ($calibration === null) {
			$add('panorama', 'none: the lens geometry is unknown, so Nextcloud shows its own preview of the lens pair');
		} else {
			$add('panorama', 'stitched from the lens pair');
			try {
				$add('levelling', $this->provider->levelling($file, $trailer, $fields, $calibration)[1]);
			} catch (\Throwable $e) {
				$failed('levelling', $e);
			}
		}

		$add('memory', 'PHP limit ' . ini_get('memory_limit'));

		return ['report' => implode("\n", $lines), 'model' => $model, 'firmware' => $firmware, 'tested' => $tested, 'video' => $video];
	}

	/**
	 * The lines that matter for a video, in place of a photo's preview and
	 * panorama: the opening frame and the motion record, as the CLI reports
	 * them, then what this app has made of the clip.
	 *
	 * @param array<int, list<int|string>> $fields
	 */
	private function videoLines(File $file, Trailer $trailer, array $fields, ?string $model, callable $add, callable $failed): void {
		$payload = $trailer->get(Trailer::PREVIEW);
		try {
			if ($payload !== null && Keyframes::isKeyframe($payload)) {
				$frame = Keyframes::parse($payload, $trailer->get(Trailer::SECOND_KEYFRAME));
				$add('opening', sprintf('%s keyframe, %s', $frame->codec, $frame->layout));
			} elseif ($payload !== null) {
				// An X5 stores its own stitch of the opening frame instead.
				$preview = EmbeddedPreview::parse($payload);
				$size = $preview->width > 0 ? [$preview->width, $preview->height] : (@getimagesizefromstring($preview->data) ?: [0, 0]);
				$add('opening', sprintf('%dx%d %s %s', $size[0], $size[1], $preview->encoding,
					$preview->isStitched ? 'equirectangular' : 'dual-fisheye'));
			} else {
				$add('opening', 'none');
			}
		} catch (\Throwable $e) {
			$failed('opening', $e);
		}

		try {
			$record = $trailer->get(Trailer::IMU);
			$log = $trailer->get(Trailer::FRAMES);
			$first = $fields[Protobuf::FIRST_FRAME][0] ?? null;
			if ($record === null) {
				throw new FormatError('no inertial record (0x0300) in the trailer');
			}
			if (!\is_int($first)) {
				throw new FormatError('no first-frame time (metadata field 24)');
			}
			if ($log === null) {
				throw new FormatError('no readable frame log (0x0400)');
			}
			// What steadying needs, so this fails where the player would.
			Imu::motionAxes((string)$model);
			$stride = Imu::stride($record);
			$frames = Imu::frameTimes($record, $stride, $log, $first, Imu::frameOffset($fields));
			$samples = intdiv(\strlen($record), $stride);
			$span = (unpack('P', $record, \strlen($record) - $stride)[1] - unpack('P', $record, 0)[1]) * Imu::CLOCK[$stride];
			$frameSpan = \count($frames) > 1 ? end($frames) - $frames[0] : 0.0;
			$add('motion', sprintf('%d samples over %.1f s%s, %d frames%s', $samples, $span,
				$span > 0 ? sprintf(' (%.0f per second)', ($samples - 1) / $span) : '',
				\count($frames), $frameSpan > 0 ? sprintf(' (%.2f per second)', (\count($frames) - 1) / $frameSpan) : ''));
		} catch (\Throwable $e) {
			$failed('motion', $e);
		}

		// What only the app knows: whether there is a stitched copy to play.
		$master = VideoStore::master($file);
		if ($master === null) {
			$add('stitched', 'no: not the main file of a clip');
		} elseif ($this->videos->ready($master) !== null) {
			$add('stitched', VideoStore::beside($master) !== null ? 'yes, saved beside the clip' : 'yes');
		} else {
			$add('stitched', 'not yet');
		}
	}

	/**
	 * Whether the file's top-level MP4 boxes, index included, end exactly
	 * where the file does: the other half of a clip recorded as two files
	 * (an Insta360 _10_) ends in a padding box of zeros and is not damaged.
	 *
	 * @param resource $handle
	 */
	private static function mp4Complete($handle, int $size): bool {
		rewind($handle);
		if (substr((string)fread($handle, 8), 4, 4) !== 'ftyp') {
			return false;
		}
		$offset = 0;
		$moov = false;
		while ($offset < $size) {
			fseek($handle, $offset);
			$header = (string)fread($handle, 16);
			if (\strlen($header) < 8) {
				return false;
			}
			$length = unpack('N', $header)[1];
			$kind = substr($header, 4, 4);
			if ($length === 1 && \strlen($header) === 16) {
				$length = unpack('J', $header, 8)[1];
			} elseif ($length === 0) {
				$length = $size - $offset;
			}
			if ($length < 8 || !ctype_alnum($kind)) {
				return false;
			}
			$moov = $moov || $kind === 'moov';
			$offset += $length;
		}

		return $offset === $size && $moov;
	}

	/**
	 * What an unrecognised file looks like, from its first and last bytes; the
	 * same cases the CLI reports.
	 *
	 * @param resource $handle
	 */
	private static function sniff($handle, int $size): string {
		if (self::mp4Complete($handle, $size)) {
			return 'a complete MP4 with no camera data after it; a clip recorded as two files keeps it in the other one';
		}
		rewind($handle);
		$head = (string)fread($handle, 3);
		fseek($handle, max(0, $size - 65536));
		$tail = '';
		while (!feof($handle) && ($chunk = fread($handle, 8192)) !== false && $chunk !== '') {
			$tail .= $chunk;
		}
		$zeros = \strlen($tail) - \strlen(rtrim($tail, "\0"));
		if ($zeros >= 1024) {
			$amount = $zeros === \strlen($tail) ? 'at least ' . self::human($zeros) : self::human($zeros);

			return "the last $amount are zeros: damaged or incompletely copied";
		}
		if ($head === "\xff\xd8\xff") {
			return str_ends_with($tail, "\xff\xd9")
				? 'a complete JPEG with no camera data after it'
				: 'begins like a JPEG, but does not end like one';
		}

		return 'begins with ' . bin2hex($head) . ', not a JPEG';
	}

	/** The CLI's own format: B under 1 KiB, then one decimal. */
	private static function human(int|float $size): string {
		if (abs($size) < 1024) {
			return (int)$size . ' B';
		}
		foreach (['KiB', 'MiB', 'GiB', 'TiB'] as $unit) {
			$size /= 1024;
			if (abs($size) < 1024 || $unit === 'TiB') {
				return sprintf('%.1f %s', $size, $unit);
			}
		}

		return sprintf('%.1f TiB', $size);
	}
}
