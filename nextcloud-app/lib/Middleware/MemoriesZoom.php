<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Middleware;

use OCA\Golblick\Service\PanoramaStore;
use OCA\Golblick\Service\Settings;
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
 * WHY THIS EXISTS
 * ---------------
 * When the viewer is zoomed past the preview's resolution, Memories swaps in
 * `/api/image/decodable/{id}`, which for an image/jpeg is the original file,
 * byte for byte. For a .insp that is the two fisheye circles, so every zoom
 * turned a panorama into a lens pair. Memories' own sphere view (after
 * 9.1.0-alpha.2) loads the same URL, so without this a .insp goes onto the
 * sphere as a sideways lens pair. This replaces that single response: the
 * Memories controller still runs and still decides whether the caller may see
 * the file, and only a 200 for a .insp that this app can render is rewritten.
 *
 * ⚠️ It keys on Memories' class and method names, which are not API. If either
 * changes, this stops matching and both zoom and the sphere show the lens pair
 * again -- the same graceful failure as the preview provider's ordering
 * dependency.
 *
 * ⚠️ Deliberately NOT done for WebDAV. files_photospheres loads its sphere from
 * the WebDAV download, and rewriting that would hand sync clients and
 * downloads a panorama in place of the original.
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
