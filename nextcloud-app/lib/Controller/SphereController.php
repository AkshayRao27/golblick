<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Controller;

use OCA\Golblick\Service\CameraReport;
use OCA\Golblick\Http\RangeFileResponse;
use OCA\Golblick\Service\PanoramaStore;
use OCA\Golblick\Service\VideoStore;
use OCP\AppFramework\Controller;
use OCP\AppFramework\Http;
use OCP\AppFramework\Http\Attribute\FrontpageRoute;
use OCP\AppFramework\Http\Attribute\NoAdminRequired;
use OCP\AppFramework\Http\Attribute\NoCSRFRequired;
use OCP\AppFramework\Http\DataDisplayResponse;
use OCP\AppFramework\Http\JSONResponse;
use OCP\AppFramework\Http\Response;
use OCP\Files\File;
use OCP\Files\IRootFolder;
use OCP\IRequest;
use OCP\IUserSession;

/**
 * What the sphere viewer and the report dialog in `src/` ask the server for.
 *
 * Only for a signed-in user's own files and files shared with them: the id is
 * resolved inside the user's folder, so an id from anywhere else is a 404.
 * Public share links go through PublicSphereController instead.
 */
final class SphereController extends Controller {
	public function __construct(
		string $appName,
		IRequest $request,
		private IRootFolder $rootFolder,
		private IUserSession $userSession,
		private PanoramaStore $store,
		private CameraReport $report,
		private VideoStore $videos,
	) {
		parent::__construct($appName, $request);
	}

	/**
	 * Whether to offer the sphere button for this file. Cheap: it looks at
	 * the name only, so the viewers can ask on every slide.
	 */
	#[NoAdminRequired]
	#[NoCSRFRequired]
	#[FrontpageRoute(verb: 'GET', url: '/sphere/{fileId}/info', requirements: ['fileId' => '\d+'])]
	public function info(int $fileId): JSONResponse {
		$file = $this->file($fileId);

		return new JSONResponse(self::describe($file, $this->videos));
	}

	/**
	 * What info answers: a photo is a sphere; a video is one too (its thumbnail,
	 * at least), and says whether its stitched copy is ready to play. Shared
	 * with PublicSphereController.
	 */
	public static function describe(?File $file, VideoStore $videos): array {
		if ($file !== null && strcasecmp($file->getExtension(), 'insv') === 0) {
			$master = VideoStore::master($file);
			$ready = $master === null ? null : $videos->ready($master);

			// Versioned by the copy itself, not by the clip: the copy is made
			// again at another size, or after the cache is cleared, while the
			// clip is unchanged, and the player's URL is cached for a day.
			return [
				'sphere' => true,
				'etag' => $file->getEtag(),
				'video' => $ready !== null,
				'videoEtag' => $ready === null ? null : substr(md5(basename($ready) . ':' . (int)@filemtime($ready)), 0, 16),
			];
		}

		return [
			'sphere' => $file !== null && PanoramaStore::isCandidate($file),
			'etag' => $file?->getEtag(),
		];
	}

	/** A video's stitched copy, with byte ranges so the player can seek. */
	#[NoAdminRequired]
	#[NoCSRFRequired]
	#[FrontpageRoute(verb: 'GET', url: '/video/{fileId}', requirements: ['fileId' => '\d+'])]
	public function video(int $fileId): Response {
		$file = $this->file($fileId);
		$master = $file === null ? null : VideoStore::master($file);
		$path = $master === null ? null : $this->videos->ready($master);
		if ($path === null) {
			return new JSONResponse([], Http::STATUS_NOT_FOUND);
		}
		$response = new RangeFileResponse($path, 'video/mp4', $this->request->getHeader('Range') ?: null);
		$response->cacheFor(3600 * 24, false, false);

		return $response;
	}

	/** The full-size panorama, the same image Memories gets on zoom. */
	#[NoAdminRequired]
	#[NoCSRFRequired]
	#[FrontpageRoute(verb: 'GET', url: '/sphere/{fileId}', requirements: ['fileId' => '\d+'])]
	public function image(int $fileId): Response {
		$file = $this->file($fileId);
		$jpeg = $file === null ? null : $this->store->get($file);
		if ($jpeg === null) {
			return new JSONResponse([], Http::STATUS_NOT_FOUND);
		}

		// The client puts the etag in the URL, so a changed file is a new URL.
		$response = new DataDisplayResponse($jpeg, Http::STATUS_OK, ['Content-Type' => 'image/jpeg']);
		$response->cacheFor(3600 * 24, false, false);

		return $response;
	}

	/**
	 * The report for the Files action "Report to golblick": the same summary as the CLI's
	 * `golblick report`, without the file's name, folder or serial number.
	 */
	#[NoAdminRequired]
	#[FrontpageRoute(verb: 'GET', url: '/report/{fileId}', requirements: ['fileId' => '\d+'])]
	public function report(int $fileId): JSONResponse {
		$file = $this->file($fileId);
		if ($file === null) {
			return new JSONResponse([], Http::STATUS_NOT_FOUND);
		}

		return new JSONResponse($this->report->build($file));
	}

	private function file(int $id): ?File {
		$user = $this->userSession->getUser();
		if ($user === null) {
			return null;
		}
		$node = $this->rootFolder->getUserFolder($user->getUID())->getFirstNodeById($id);

		return $node instanceof File ? $node : null;
	}
}
