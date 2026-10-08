<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Preview;

use OCA\Golblick\Insta360\Calibration;
use OCA\Golblick\Insta360\EmbeddedPreview;
use OCA\Golblick\Insta360\FormatError;
use OCA\Golblick\Insta360\Imu;
use OCA\Golblick\Insta360\Keyframes;
use OCA\Golblick\Insta360\Protobuf;
use OCA\Golblick\Insta360\Trailer;
use OCA\Golblick\Render\Equirectangular;
use OCA\Golblick\Render\Orientation;
use OCA\Golblick\Service\VideoDecoder;
use OCP\Files\File;
use OCP\Files\FileInfo;
use OCP\Files\Folder;
use OCP\IImage;
use OCP\Image;
use OCP\Preview\IProviderV2;
use Psr\Log\LoggerInterface;

/**
 * Panoramic thumbnails for Insta360 videos: the clip's opening frame.
 *
 * WHY A TYPE OF ITS OWN
 * ---------------------
 * An .insv is an MP4, but mapping it to video/mp4 would put it in Memories'
 * timeline and in the Viewer, which play it as it is: one fisheye on a OneR,
 * the first of two on an X5. Until golblick can serve a stitched video, these
 * files get a type nothing else claims, so they show this thumbnail in Files
 * and nothing tries to play them. The app's setup check registers the mapping.
 *
 * WHERE THE PICTURE COMES FROM, by camera (docs/formats/insta360-agent-notes.md):
 * - X5: record 0x0200 is the camera's own stitched, levelled panorama of the
 *   opening frame, NV12, 1280x640. Plain PHP, as for X5 stills.
 * - OneR, X3: records 0x0200 and 0x0500 are the opening frame's keyframes, one
 *   per lens, compressed; ffmpeg decodes them (VideoDecoder) and they are
 *   projected like a still. Levelled from the first seconds of the inertial
 *   record, as `golblick render` does.
 * - A OneR or X3 second-lens file (_10_) carries no trailer, so it shows the
 *   same frame, read from its _00_ partner in the same folder.
 */
final class Insta360Video implements IProviderV2 {
	public const MIME = 'application/x-insta360-insv';

	private const MAX_WIDTH = 4096;

	public function __construct(
		private VideoDecoder $decoder,
	) {
	}

	public function getMimeType(): string {
		return '/^application\/x-insta360-insv$/';
	}

	public function isAvailable(FileInfo $file): bool {
		return strcasecmp($file->getExtension(), 'insv') === 0;
	}

	public function getThumbnail(File $file, int $maxX, int $maxY): ?IImage {
		try {
			$source = $this->withTrailer($file);
			if ($source === null) {
				return null;
			}
			$handle = $source->fopen('r');
			if ($handle === false) {
				return null;
			}
			try {
				if (!Trailer::looksLikeOurs($handle)) {
					return null;
				}
				$trailer = Trailer::read($handle, [Trailer::METADATA, Trailer::PREVIEW]);
				$rendered = $this->render($trailer, $handle, min(max(64, min($maxX, $maxY * 2)), self::MAX_WIDTH));
			} finally {
				fclose($handle);
			}

			ob_start();
			imagepng($rendered, null, 6);
			$image = new Image();
			$image->loadFromData((string)ob_get_clean());

			return $image->valid() ? $image : null;
		} catch (FormatError $e) {
			\OC::$server->get(LoggerInterface::class)->debug(
				'golblick: declined ' . $file->getPath() . ': ' . $e->getMessage(),
				['app' => 'golblick']
			);

			return null;
		} catch (\Throwable $e) {
			\OC::$server->get(LoggerInterface::class)->warning(
				'golblick: failed to preview ' . $file->getPath(),
				['app' => 'golblick', 'exception' => $e]
			);

			return null;
		}
	}

	/** The file itself, or for a second-lens file its partner, which carries the trailer. */
	private function withTrailer(File $file): ?File {
		if (!preg_match('/^(VID_\d{8}_\d{6})_10_(\d+\.insv)$/i', $file->getName(), $m)) {
			return $file;
		}
		try {
			$partner = $file->getParent()->get($m[1] . '_00_' . $m[2]);
		} catch (\Throwable $e) {
			return null;
		}

		return $partner instanceof File && !($partner instanceof Folder) ? $partner : null;
	}

	/** @param resource $handle */
	private function render(Trailer $trailer, $handle, int $width): \GdImage {
		$first = $trailer->get(Trailer::PREVIEW);
		if ($first === null) {
			throw new FormatError('no record 0x0200');
		}

		if (!Keyframes::isKeyframe($first)) {
			$preview = EmbeddedPreview::parse($first);
			if (!$preview->isStitched) {
				throw new FormatError('the preview record holds neither keyframes nor a stitched frame');
			}

			return Equirectangular::fromNv12($preview, min($width, $preview->width));
		}

		$keyframes = Keyframes::parse($first, $trailer->fetch($handle, Trailer::SECOND_KEYFRAME));
		$metadata = $trailer->get(Trailer::METADATA);
		if ($metadata === null) {
			throw new FormatError('no metadata record (0x0101), so the lens geometry is unknown');
		}
		$fields = Protobuf::fields($metadata);
		$text = Protobuf::firstText($fields, Protobuf::CALIBRATION_EQUIDISTANT);
		if ($text === null) {
			throw new FormatError('no equidistant calibration');
		}
		$calibration = Calibration::parse($text);
		$model = Protobuf::firstText($fields, Protobuf::MODEL);

		$orientation = Orientation::fromRoll($calibration->bodyRoll());
		$imu = $trailer->fetch($handle, Trailer::IMU);
		if ($imu !== null && $model !== null) {
			try {
				$orientation = Orientation::level(Imu::gravityUp($imu, $model, Imu::OPENING_SAMPLES, true));
			} catch (FormatError $e) {
				// An unmeasured camera or an unreadable record: the mounting angle still applies.
			}
		}
		unset($imu);

		$pair = $this->decoder->lensPair($keyframes, $width);

		return Equirectangular::fromLensPair($pair, $calibration, $width, $orientation, $model);
	}
}
