<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Controller;

use OCA\Golblick\Service\PanoramaStore;
use OCA\Golblick\Service\Settings;
use OCP\AppFramework\Http;
use OCP\AppFramework\Http\Attribute\FrontpageRoute;
use OCP\AppFramework\Http\Attribute\NoCSRFRequired;
use OCP\AppFramework\Http\Attribute\PublicPage;
use OCP\AppFramework\Http\DataDisplayResponse;
use OCP\AppFramework\Http\JSONResponse;
use OCP\AppFramework\Http\Response;
use OCP\AppFramework\PublicShareController;
use OCP\Constants;
use OCP\Files\File;
use OCP\Files\Folder;
use OCP\Files\NotFoundException;
use OCP\IRequest;
use OCP\ISession;
use OCP\Share\Exceptions\ShareNotFound;
use OCP\Share\IManager;
use OCP\Share\IShare;

/**
 * SphereController's two answers for a public share link, for a file inside
 * the share behind `token`.
 *
 * Nextcloud's public-share middleware runs before every method here: it checks
 * the token, throttles guessing, and answers 404 for a password-protected share
 * that hasn't been unlocked in this browser. What is left is which file: the
 * shared file itself, or a file inside a shared folder, and only when the share
 * lets visitors see its content. That is the rule Nextcloud's own public
 * previews follow (`IShare::canSeeContent`: download allowed, or viewing
 * without download allowed by the admin), so a share that hides its files gets
 * no sphere either.
 */
final class PublicSphereController extends PublicShareController {
	private ?IShare $share = null;

	public function __construct(
		string $appName,
		IRequest $request,
		ISession $session,
		private IManager $shareManager,
		private PanoramaStore $store,
		private Settings $settings,
	) {
		parent::__construct($appName, $request, $session);
	}

	#[\Override]
	protected function getPasswordHash(): ?string {
		return $this->share?->getPassword();
	}

	#[\Override]
	public function isValidToken(): bool {
		try {
			$this->share = $this->shareManager->getShareByToken($this->getToken());

			return true;
		} catch (ShareNotFound) {
			return false;
		}
	}

	#[\Override]
	protected function isPasswordProtected(): bool {
		return $this->share?->isPasswordProtected() ?? false;
	}

	/** As SphereController::info, plus the file's path in the share for its public preview. */
	#[PublicPage]
	#[NoCSRFRequired]
	#[FrontpageRoute(verb: 'GET', url: '/s/{token}/sphere/{fileId}/info', requirements: ['fileId' => '\d+'])]
	public function info(string $token, int $fileId): JSONResponse {
		[$file, $path] = $this->file($fileId);
		$sphere = $file !== null && PanoramaStore::isCandidate($file);

		return new JSONResponse([
			'sphere' => $sphere,
			'etag' => $sphere ? $file->getEtag() : null,
			'path' => $sphere ? $path : null,
		]);
	}

	#[PublicPage]
	#[NoCSRFRequired]
	#[FrontpageRoute(verb: 'GET', url: '/s/{token}/sphere/{fileId}', requirements: ['fileId' => '\d+'])]
	public function image(string $token, int $fileId): Response {
		[$file] = $this->file($fileId);
		$jpeg = $file === null ? null : $this->store->get($file);
		if ($jpeg === null) {
			return new JSONResponse([], Http::STATUS_NOT_FOUND);
		}

		// One day, as Nextcloud caches public previews; the client puts the etag in the URL.
		$response = new DataDisplayResponse($jpeg, Http::STATUS_OK, ['Content-Type' => 'image/jpeg']);
		$response->cacheFor(3600 * 24, false, false);

		return $response;
	}

	/** @return array{0: ?File, 1: ?string} the file and its path inside the share */
	private function file(int $id): array {
		$share = $this->share;
		if ($share === null || !$this->settings->flag('sphere_public')
			|| ($share->getPermissions() & Constants::PERMISSION_READ) === 0 || !$share->canSeeContent()) {
			return [null, null];
		}
		try {
			$node = $share->getNode();
		} catch (NotFoundException) {
			return [null, null];
		}
		if ($node instanceof File) {
			return $node->getId() === $id ? [$node, '/'] : [null, null];
		}
		// Looked up inside the shared folder only, so an id from elsewhere in the owner's files is a 404.
		$file = $node instanceof Folder ? $node->getFirstNodeById($id) : null;

		return $file instanceof File ? [$file, $node->getRelativePath($file->getPath())] : [null, null];
	}
}
