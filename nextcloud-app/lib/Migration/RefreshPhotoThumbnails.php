<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Migration;

use OCA\Golblick\AppInfo\Application;
use OCP\IAppConfig;
use OCP\IDBConnection;
use OCP\Migration\IOutput;
use OCP\Migration\IRepairStep;
use Psr\Container\ContainerInterface;
use Psr\Log\LoggerInterface;

/**
 * Deletes the cached thumbnails of .insp photos once, when upgrading to a
 * version whose panoramas are centred where Insta360 Studio's exports are
 * (Orientation::face): a thumbnail made before shows the other side in the
 * middle, and the sphere viewer opens on the thumbnail before the full
 * panorama arrives, so it would open facing one way and then jump.
 *
 * Through Nextcloud's internal PreviewService, as RefreshCopyThumbnails does
 * and for the same reason. Thumbnails are made again when next looked at.
 */
final class RefreshPhotoThumbnails implements IRepairStep {
	private const DONE = 'photo_thumbnails_faced';

	public function __construct(
		private IDBConnection $db,
		private IAppConfig $appConfig,
		private ContainerInterface $container,
		private LoggerInterface $logger,
	) {
	}

	public function getName(): string {
		return 'Refresh the thumbnails of 360° photos, whose panoramas are now turned to match Insta360 Studio\'s exports';
	}

	public function run(IOutput $output): void {
		if ($this->appConfig->getValueBool(Application::APP_ID, self::DONE)) {
			return;
		}
		$class = 'OC\\Preview\\PreviewService';
		if (!class_exists($class)) {
			$output->info('golblick: no preview service to refresh thumbnails with; skipped');
			return;
		}
		$deleted = $photos = 0;
		try {
			$service = $this->container->get($class);
			$qb = $this->db->getQueryBuilder();
			$qb->select('fileid')->from('filecache')->where($qb->expr()->iLike('name', $qb->createNamedParameter('%.insp')));
			$result = $qb->executeQuery();
			while (($id = $result->fetchOne()) !== false) {
				$photos++;
				foreach ($service->getAvailablePreviewsForFile((int)$id) as $preview) {
					$service->deletePreview($preview);
					$deleted++;
				}
			}
			$result->closeCursor();
		} catch (\Throwable $e) {
			$this->logger->warning('golblick: could not refresh the thumbnails of 360° photos', ['app' => 'golblick', 'exception' => $e]);
			$output->warning('golblick: could not refresh the thumbnails of 360° photos: ' . $e->getMessage());
			return;
		}
		$this->appConfig->setValueBool(Application::APP_ID, self::DONE, true);
		$output->info("golblick: deleted $deleted cached previews of $photos photos");
	}
}
