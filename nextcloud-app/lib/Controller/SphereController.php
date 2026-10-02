<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Controller;

use OCA\Golblick\Service\PanoramaStore;
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
 * What the sphere viewer in `src/` asks the server for.
 *
 * Only for a signed-in user's own files and files shared with them: the id is
 * resolved inside the user's folder, so an id from anywhere else is a 404.
 * Public share links are not covered.
 */
final class SphereController extends Controller {
	public function __construct(
		string $appName,
		IRequest $request,
		private IRootFolder $rootFolder,
		private IUserSession $userSession,
		private PanoramaStore $store,
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

		return new JSONResponse([
			'sphere' => $file !== null && PanoramaStore::isCandidate($file),
			'etag' => $file?->getEtag(),
		]);
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

	private function file(int $id): ?File {
		$user = $this->userSession->getUser();
		if ($user === null) {
			return null;
		}
		$node = $this->rootFolder->getUserFolder($user->getUID())->getFirstNodeById($id);

		return $node instanceof File ? $node : null;
	}
}
