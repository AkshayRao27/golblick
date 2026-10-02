<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Middleware;

use OCA\Golblick\Preview\Insta360;
use OCP\AppFramework\Controller;
use OCP\AppFramework\Http;
use OCP\AppFramework\Http\DataDownloadResponse;
use OCP\AppFramework\Http\Response;
use OCP\AppFramework\Middleware;
use OCP\Files\File;
use OCP\Files\IAppData;
use OCP\Files\IRootFolder;
use OCP\Files\NotFoundException;
use OCP\IAppConfig;
use OCP\IRequest;
use OCP\IUserSession;
use Psr\Log\LoggerInterface;

/**
 * Makes zooming in Memories show the panorama instead of the lens pair.
 *
 * WHY THIS EXISTS
 * ---------------
 * When the viewer is zoomed past the preview's resolution, Memories (9.0.1 and
 * earlier) swaps in `/api/image/decodable/{id}`, which for an image/jpeg is the
 * original file, byte for byte. For a .insp that is the two fisheye circles, so
 * every zoom turned a panorama into a lens pair. The fix belongs in Memories,
 * and until a release carries one this replaces that single response: the
 * Memories controller still runs and still decides whether the caller may see
 * the file, and only a 200 for a .insp that this app can render is rewritten.
 *
 * ⚠️ It keys on Memories' class and method names, which are not API. If either
 * changes, this stops matching and zoom shows the lens pair again -- the same
 * graceful failure as the preview provider's ordering dependency.
 *
 * ⚠️ Deliberately NOT done for WebDAV. files_photospheres loads its sphere from
 * the WebDAV download, and rewriting that would hand sync clients and
 * downloads a panorama in place of the original.
 */
final class MemoriesZoom extends Middleware {
	private const CONTROLLER = 'OCA\Memories\Controller\ImageController';
	private const METHOD = 'decodable';

	/**
	 * Width of the zoom image, set with `occ config:app:set golblick zoom_width`.
	 *
	 * ⚠️ The render costs about 2.2 microseconds per output pixel on a OneR,
	 * whatever the source: measured 5.7 s at 1920 wide, 11 s at 3072 and 19 s at
	 * 4096. It is paid once per photo, on its first zoom, and then cached. 4096
	 * is the most the preview provider renders, and an X5 stops at 2560, its own
	 * stitch.
	 */
	private const DEFAULT_WIDTH = 4096;

	public function __construct(
		private IRequest $request,
		private IRootFolder $rootFolder,
		private IUserSession $userSession,
		private IAppData $appData,
		private IAppConfig $appConfig,
		private LoggerInterface $logger,
	) {
	}

	public function afterController(Controller $controller, string $methodName, Response $response): Response {
		if ($methodName !== self::METHOD
			|| !is_a($controller, self::CONTROLLER)
			|| $response->getStatus() !== Http::STATUS_OK) {
			return $response;
		}

		try {
			$file = $this->file((int)$this->request->getParam('id'));
			if ($file === null || strcasecmp($file->getExtension(), 'insp') !== 0) {
				return $response;
			}

			$jpeg = $this->panorama($file);
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

	/**
	 * Rendering a full-width panorama takes seconds, so the result is kept in
	 * app data under the file's etag: a changed file gets a new entry, and the
	 * stale one is dropped when it is replaced.
	 */
	private function panorama(File $file): ?string {
		$folder = $this->cacheFolder();
		$width = max(1024, min(4096, (int)$this->appConfig->getValueString('golblick', 'zoom_width', (string)self::DEFAULT_WIDTH)));
		$prefix = $file->getId() . '-';
		$name = $prefix . $file->getEtag() . '-' . $width . '.jpg';

		try {
			return $folder->getFile($name)->getContent();
		} catch (NotFoundException $e) {
		}

		$image = (new Insta360())->getThumbnail($file, $width, intdiv($width, 2));
		if ($image === null || !($image->resource() instanceof \GdImage)) {
			return null;
		}
		ob_start();
		imagejpeg($image->resource(), null, 90);
		$jpeg = (string)ob_get_clean();

		foreach ($folder->getDirectoryListing() as $old) {
			if (str_starts_with($old->getName(), $prefix)) {
				$old->delete();
			}
		}
		$folder->newFile($name, $jpeg);

		return $jpeg;
	}

	private function cacheFolder(): \OCP\Files\SimpleFS\ISimpleFolder {
		try {
			return $this->appData->getFolder('zoom');
		} catch (NotFoundException $e) {
			return $this->appData->newFolder('zoom');
		}
	}
}
