<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Middleware;

use OCA\Golblick\Render\Gpano;
use OCA\Golblick\Service\PanoramaStore;
use OCA\Golblick\Service\Settings;
use OCA\Golblick\Service\ViewStore;
use OCP\AppFramework\Controller;
use OCP\AppFramework\Http;
use OCP\AppFramework\Http\DataDownloadResponse;
use OCP\AppFramework\Http\Response;
use OCP\AppFramework\Middleware;
use OCP\Files\File;
use OCP\Files\IRootFolder;
use OCP\IRequest;
use OCP\IUserSession;
use Psr\Log\LoggerInterface;

/**
 * Makes zooming in Memories, and its sphere view, show the panorama instead of
 * the lens pair.
 *
 * Both load `/api/image/decodable/{id}`, which for an image/jpeg is the
 * original file: for a .insp, the two fisheye circles. This replaces that one
 * response. The Memories controller still runs and decides whether the caller
 * may see the file; only a 200 for a .insp this app can render is rewritten.
 *
 * It keys on Memories' class and method names, which are not API: if either
 * changes, zoom and the sphere show the lens pair again. Never do the same
 * for WebDAV, which would hand sync clients and downloads a panorama in place
 * of the original. AGENT-NOTES.md, "Memories zoom".
 */
final class MemoriesZoom extends Middleware {
	private const CONTROLLER = 'OCA\Memories\Controller\ImageController';
	private const METHOD = 'decodable';

	public function __construct(
		private IRequest $request,
		private IRootFolder $rootFolder,
		private IUserSession $userSession,
		private PanoramaStore $store,
		private Settings $settings,
		private ViewStore $views,
		private LoggerInterface $logger,
	) {
	}

	public function afterController(Controller $controller, string $methodName, Response $response): Response {
		if ($methodName !== self::METHOD
			|| !is_a($controller, self::CONTROLLER)
			|| $response->getStatus() !== Http::STATUS_OK
			|| !$this->settings->flag('memories_zoom')) {
			return $response;
		}

		try {
			$file = $this->file((int)$this->request->getParam('id'));
			if ($file === null || !PanoramaStore::isCandidate($file)) {
				return $response;
			}

			$jpeg = $this->store->get($file);
			if ($jpeg === null) {
				return $response;
			}
			// Memories' sphere view opens where the metadata says. Only a
			// chosen view needs saying: by default it opens in the middle,
			// which is already the right way. The browser keeps this image
			// for a day under a URL keyed on the file, so a newly chosen view
			// reaches Memories once that has run out.
			$view = $this->views->get($file, false);
			if ($view['chosen']) {
				$jpeg = Gpano::withInitialView($jpeg, $view['longitude'], $view['latitude']);
			}

			$replaced = new DataDownloadResponse($jpeg, $file->getName() . '.jpg', 'image/jpeg');
			$replaced->cacheFor(3600 * 24, false, false);

			return $replaced;
		} catch (\Throwable $e) {
			$this->logger->warning('golblick: could not replace the Memories zoom image',
				['app' => 'golblick', 'exception' => $e]);

			return $response;
		}
	}

	/**
	 * Memories has already resolved this id under the caller's permissions and
	 * answered 200, so looking it up again exposes nothing new. A public share
	 * has no user, hence the fallback to the root.
	 */
	private function file(int $id): ?File {
		$user = $this->userSession->getUser();
		$folder = $user === null ? $this->rootFolder : $this->rootFolder->getUserFolder($user->getUID());
		$node = $folder->getFirstNodeById($id);

		return $node instanceof File ? $node : null;
	}
}
