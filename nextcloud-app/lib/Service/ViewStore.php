<?php

declare(strict_types=1);

// SPDX-License-Identifier: AGPL-3.0-or-later

namespace OCA\Golblick\Service;

use OCA\Golblick\Insta360\FormatError;
use OCA\Golblick\Insta360\Imu;
use OCA\Golblick\Insta360\LensProfile;
use OCA\Golblick\Insta360\Protobuf;
use OCA\Golblick\Insta360\Trailer;
use OCA\Golblick\Render\Orientation;
use OCP\Files\File;
use OCP\Files\IAppData;
use OCP\Files\NotFoundException;
use OCP\Files\SimpleFS\ISimpleFolder;

/**
 * Where a sphere opens: the direction someone chose for a photo or a clip,
 * or else the middle of its panorama, which is the middle of Insta360
 * Studio's export of it.
 *
 * A view belongs to the photo, or to the clip for a video, so every file of a
 * clip and its stitched copy open the same way. It is kept in the app's data
 * as `views/<file id>.json`, never written into the original. Angles are in
 * the panorama's own terms, degrees: `longitude` from its middle column,
 * rising to the right, `latitude` up from its horizon, and `fov`, the
 * viewer's vertical field of view, or null for the viewer's default.
 *
 * A photo's panorama already faces Studio's way (Orientation::face), so its
 * default is the middle. A clip's stitched copy doesn't: changing the copy
 * would also change how its steadying track is read, and copies take hours
 * to make. So a clip's default is where its forward direction sits in the
 * copy, worked out from the same reading of gravity the copy was levelled
 * with, and kept with the view so it isn't read again from the clip.
 */
final class ViewStore {
	public function __construct(
		private IAppData $appData,
	) {
	}

	/**
	 * The view for $subject (a photo, or a clip's master file), and whether it
	 * was chosen rather than the default.
	 *
	 * @return array{longitude: float, latitude: float, fov: ?float, chosen: bool}
	 */
	public function get(File $subject, bool $video): array {
		$stored = $this->read($subject);
		if (isset($stored['view'])) {
			return $stored['view'] + ['chosen' => true];
		}
		if (!$video) {
			return ['longitude' => 0.0, 'latitude' => 0.0, 'fov' => null, 'chosen' => false];
		}
		$default = $stored['default'] ?? null;
		if (!\is_array($default) || ($default['etag'] ?? null) !== $subject->getEtag()
			|| ($default['rule'] ?? null) !== self::FORWARD_RULE) {
			$default = ['etag' => $subject->getEtag(), 'rule' => self::FORWARD_RULE,
				'longitude' => $this->clipForward($subject)];
			$this->write($subject, ['default' => $default] + $stored);
		}

		return ['longitude' => (float)$default['longitude'], 'latitude' => 0.0, 'fov' => null, 'chosen' => false];
	}

	public function set(File $subject, float $longitude, float $latitude, ?float $fov): void {
		$longitude = fmod(fmod($longitude + 180.0, 360.0) + 360.0, 360.0) - 180.0;
		if (!is_finite($longitude) || !is_finite($latitude) || abs($latitude) > 90.0
			|| ($fov !== null && (!is_finite($fov) || $fov < 10.0 || $fov > 120.0))) {
			throw new \InvalidArgumentException('longitude, latitude (-90 to 90) and fov (10 to 120, or none) must be numbers');
		}
		$this->write($subject, ['view' => ['longitude' => round($longitude, 2), 'latitude' => round($latitude, 2),
			'fov' => $fov === null ? null : round($fov, 1)]] + $this->read($subject));
	}

	/** Back to the default. */
	public function clear(File $subject): void {
		$stored = $this->read($subject);
		unset($stored['view']);
		$this->write($subject, $stored);
	}

	/**
	 * Where the clip's forward direction sits in its stitched copy: the copy
	 * is levelled from gravity at the start of the clip (VideoRenderer), and
	 * Studio's exports are centred on LensProfile::PHOTO_FORWARD. 0 when the
	 * clip carries no reading to work it out from.
	 */
	/** Bumped when clipForward() changes, so stored defaults are worked out again. 3: an X5's tracks paired by field 80. */
	private const FORWARD_RULE = 3;

	private function clipForward(File $clip): float {
		try {
			$handle = $clip->fopen('r');
			if ($handle === false) {
				return 0.0;
			}
			try {
				$trailer = Trailer::read($handle, [Trailer::METADATA, Trailer::IMU]);
			} finally {
				fclose($handle);
			}
			$metadata = $trailer->get(Trailer::METADATA);
			$record = $trailer->get(Trailer::IMU);
			$model = $metadata === null ? null : Protobuf::firstText(Protobuf::fields($metadata), Protobuf::MODEL);
			if ($record === null || $model === null) {
				return 0.0;
			}
			$m = Orientation::level(Imu::gravityUp($record, $model, Imu::OPENING_SAMPLES));
		} catch (FormatError|\InvalidArgumentException $e) {
			return 0.0;
		}
		$f = LensProfile::PHOTO_FORWARD;
		$x = $m[0][0] * $f[0] + $m[0][1] * $f[1] + $m[0][2] * $f[2];
		$z = $m[2][0] * $f[0] + $m[2][1] * $f[1] + $m[2][2] * $f[2];

		return hypot($x, $z) < 0.2 ? 0.0 : round(rad2deg(atan2($x, $z)), 2);
	}

	private function read(File $subject): array {
		try {
			$data = json_decode($this->folder()->getFile($subject->getId() . '.json')->getContent(), true);
		} catch (NotFoundException $e) {
			return [];
		}

		return \is_array($data) ? $data : [];
	}

	private function write(File $subject, array $data): void {
		$folder = $this->folder();
		$name = $subject->getId() . '.json';
		if ($data === [] && $folder->fileExists($name)) {
			$folder->getFile($name)->delete();
			return;
		}
		try {
			$folder->getFile($name)->putContent(json_encode($data));
		} catch (NotFoundException $e) {
			$folder->newFile($name, json_encode($data));
		}
	}

	private function folder(): ISimpleFolder {
		try {
			return $this->appData->getFolder('views');
		} catch (NotFoundException $e) {
			return $this->appData->newFolder('views');
		}
	}
}
