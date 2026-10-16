<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Migration;

use OCA\Golblick\BackgroundJob\VideoRender;
use OCP\Migration\IOutput;
use OCP\Migration\IRepairStep;
use Psr\Container\ContainerInterface;
use Psr\Log\LoggerInterface;

/**
 * Deletes the cached thumbnails of the copies saved next to their clips, so
 * they're made again without the frame-number strip (Preview\SphericalCopy).
 *
 * Nextcloud keeps a preview until the file changes, and has no public way to
 * drop one: core does it through its own PreviewService when a file is
 * written. Rewriting every copy to get there would mean gigabytes of writes,
 * so this uses that service directly. It's Nextcloud's internal API, so if it
 * isn't there or fails, this logs it and does nothing: the old thumbnails
 * then stay until each copy is made again.
 */
final class RefreshCopyThumbnails implements IRepairStep {
	public function __construct(
		private VideoRender $job,
		private ContainerInterface $container,
		private LoggerInterface $logger,
	) {
	}

	public function getName(): string {
		return 'Refresh the thumbnails of stitched videos saved next to their clips';
	}

	public function run(IOutput $output): void {
		$class = 'OC\\Preview\\PreviewService';
		if (!class_exists($class)) {
			$output->info('golblick: no preview service to refresh thumbnails with; skipped');
			return;
		}
		$deleted = $copies = 0;
		try {
			$service = $this->container->get($class);
			foreach ($this->job->besideCopies() as $copy) {
				$copies++;
				foreach ($service->getAvailablePreviewsForFile($copy->getId()) as $preview) {
					$service->deletePreview($preview);
					$deleted++;
				}
			}
		} catch (\Throwable $e) {
			$this->logger->warning('golblick: could not refresh the thumbnails of saved copies', ['app' => 'golblick', 'exception' => $e]);
			$output->warning('golblick: could not refresh the thumbnails of saved copies: ' . $e->getMessage());
			return;
		}
		$output->info("golblick: deleted $deleted cached previews of $copies saved copies");
	}
}
