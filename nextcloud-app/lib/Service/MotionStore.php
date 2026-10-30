<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Service;

use OCA\Golblick\Insta360\FormatError;
use OCA\Golblick\Insta360\Imu;
use OCA\Golblick\Insta360\Protobuf;
use OCA\Golblick\Insta360\Trailer;
use OCA\Golblick\Render\Orientation;
use OCA\Golblick\Render\Stabilise;
use OCP\Files\File;
use OCP\Files\IAppData;
use OCP\Files\NotFoundException;
use OCP\Files\SimpleFS\ISimpleFolder;
use Psr\Log\LoggerInterface;

/**
 * The rotation that steadies each frame of a clip's stitched copy, for the
 * sphere player to apply as it plays (Render/Stabilise).
 *
 * Nothing is re-rendered: the copy stays as it was made, levelled at its
 * opening, and the player turns the sphere frame by frame. So stabilisation
 * costs no CPU on the server beyond a few seconds per clip, applies to copies
 * made before it existed, and can be switched off in the player.
 *
 * Cached in the app's data, keyed on the clip's id and etag: 3 seconds and
 * under 100 MB for a half-hour clip, a fraction of a second for a short one.
 */
final class MotionStore {
	/**
	 * Bump when the algorithm changes, so tracks made by the old one are not served; and motionUrl's v in src/overlay.ts with it.
	 * 7: an X5's tracks paired by field 80, so its record is read with the photo axes.
	 */
	private const VERSION = 7;

	public function __construct(
		private IAppData $appData,
		private LoggerInterface $logger,
	) {
	}

	/**
	 * The clip whose inertial record steadies $file: its _00_ file for a clip,
	 * or the clip a copy was saved beside. Null for anything else, including
	 * Insta360 Studio's exports, which are stabilised already if at all.
	 */
	public static function clipFor(File $file): ?File {
		if (strcasecmp($file->getExtension(), 'insv') === 0) {
			return VideoStore::master($file);
		}
		$name = $file->getName();
		if (strlen($name) <= strlen(VideoStore::BESIDE)
			|| strcasecmp(substr($name, -strlen(VideoStore::BESIDE)), VideoStore::BESIDE) !== 0) {
			return null;
		}
		try {
			$clip = $file->getParent()->get(substr($name, 0, -strlen(VideoStore::BESIDE)) . '.insv');
		} catch (\Throwable $e) {
			return null;
		}

		return $clip instanceof File ? VideoStore::master($clip) : null;
	}

	/**
	 * The track for $clip, as the player takes it: `period` (seconds between
	 * frames), `frames`, `q`, base64 of little-endian int16 quaternions
	 * (w, x, y, z) scaled by 32767, and `turn`, base64 of int16 angles scaled
	 * by 32767 / pi: how far the following view has turned since frame 0,
	 * which the player undoes for Direction Lock. Null when the clip can't be
	 * stabilised: an unmeasured camera, no first-frame time, an unreadable
	 * record.
	 *
	 * @return array{period: float, frames: int, q: string, turn: string}|null
	 */
	public function track(File $clip): ?array {
		$name = sprintf('%d-%s-v%d.json', $clip->getId(), $clip->getEtag(), self::VERSION);
		$folder = $this->folder();
		try {
			$cached = json_decode($folder->getFile($name)->getContent(), true);
			if (\is_array($cached)) {
				return $cached === [] ? null : $cached;
			}
		} catch (NotFoundException $e) {
		}

		$track = $this->compute($clip);
		// A refusal is cached too, as an empty object, so it isn't worked out again on every play.
		$folder->newFile($name, json_encode($track ?? (object)[]));

		return $track;
	}

	/**
	 * How the camera turned while each frame of $clip was read, for the GPU
	 * stitch to undo its rolling shutter (Stabilise::shutterFor), in the frame
	 * of tables made with $orientation. Not cached: a clip is stitched once.
	 * Null when the camera's readout isn't known, or the record can't be read.
	 */
	public function shutter(File $clip, array $orientation): ?string {
		try {
			$read = $this->read($clip);
			if ($read === null) {
				return null;
			}
			[$fields, $model, $record, $stride, $frames] = $read;
			$turns = Stabilise::shutter($record, $stride, Imu::motionAxes($model), Imu::gains($fields, $stride), $frames,
				Imu::readout($fields, $model, $frames));
		} catch (FormatError|\InvalidArgumentException $e) {
			$this->logger->debug('golblick: rolling shutter left in for ' . $clip->getName() . ': ' . $e->getMessage());

			return null;
		}

		return $turns === null ? null : Stabilise::shutterFor($turns, $orientation);
	}

	/** @return array{array, string, string, int, list<float>}|null fields, model, record, stride, frame times */
	private function read(File $clip): ?array {
		$handle = $clip->fopen('r');
		if ($handle === false) {
			return null;
		}
		try {
			$trailer = Trailer::read($handle, [Trailer::METADATA, Trailer::IMU, Trailer::FRAMES]);
		} finally {
			fclose($handle);
		}
		$metadata = $trailer->get(Trailer::METADATA);
		$record = $trailer->get(Trailer::IMU);
		$log = $trailer->get(Trailer::FRAMES);
		if ($metadata === null || $record === null || $log === null) {
			return null;
		}
		$fields = Protobuf::fields($metadata);
		$model = Protobuf::firstText($fields, Protobuf::MODEL);
		$first = $fields[Protobuf::FIRST_FRAME][0] ?? null;
		if ($model === null || !\is_int($first)) {
			return null;
		}
		$stride = Imu::stride($record);

		return [$fields, $model, $record, $stride, Imu::frameTimes($record, $stride, $log, $first, Imu::frameOffset($fields))];
	}

	private function compute(File $clip): ?array {
		try {
			$read = $this->read($clip);
			if ($read === null) {
				return null;
			}
			[$fields, $model, $record, $stride, $frames] = $read;
			// The orientation VideoRenderer::geometry renders the copy with.
			$reference = Orientation::level(Imu::gravityUp($record, $model, Imu::OPENING_SAMPLES));
			$track = Stabilise::track($record, $stride, Imu::motionAxes($model), Imu::gains($fields, $stride), $frames, $reference);
		} catch (FormatError|\InvalidArgumentException $e) {
			$this->logger->debug('golblick: no stabilisation for ' . $clip->getName() . ': ' . $e->getMessage());

			return null;
		}

		$packed = '';
		foreach ($track['rotations'] as $q) {
			foreach ($q as $c) {
				$packed .= pack('v', ((int)round($c * 32767)) & 0xFFFF);
			}
		}
		// Only the angle matters, so wrap it into a half turn either way.
		$turns = '';
		foreach ($track['turns'] as $turn) {
			$wrapped = atan2(sin($turn), cos($turn));
			$turns .= pack('v', ((int)round($wrapped / M_PI * 32767)) & 0xFFFF);
		}
		$count = \count($frames);

		return [
			'period' => $count > 1 ? ($frames[$count - 1] - $frames[0]) / ($count - 1) : 1 / 30,
			'frames' => $count,
			'q' => base64_encode($packed),
			'turn' => base64_encode($turns),
		];
	}

	private function folder(): ISimpleFolder {
		try {
			return $this->appData->getFolder('motion');
		} catch (NotFoundException $e) {
			return $this->appData->newFolder('motion');
		}
	}
}
