<?php

declare(strict_types=1);

// SPDX-License-Identifier: AGPL-3.0-or-later

namespace OCA\Golblick\Service;

use OCP\App\IAppManager;
use OCP\IConfig;

/**
 * The compose file that starts the GPU worker next to this server, with this
 * server's folders filled in, for the admin page to show.
 *
 * The worker needs three folders as the Docker HOST sees them, and PHP only
 * knows them as this server sees them. On Nextcloud AIO the mapping is fixed:
 * the app lives in the nextcloud_aio_nextcloud volume, and the data directory
 * is the nextcloud_aio_nextcloud_data volume unless the mastercontainer was
 * given NEXTCLOUD_DATADIR, which compose reads from a .env file. Anywhere else
 * the paths are given as seen here, which is right on a server without
 * containers and has to be translated by hand inside one.
 *
 * The data directory is mounted read-only, for the GPU stitch to read clips
 * from (StitchQueue); the worker writes only into the video folder.
 */
final class WorkerCompose {
	private const AIO_APP = '/var/www/html/';
	private const AIO_APP_HOST = '/var/lib/docker/volumes/nextcloud_aio_nextcloud/_data/';
	private const AIO_DATA_HOST = '${NEXTCLOUD_DATADIR:-/var/lib/docker/volumes/nextcloud_aio_nextcloud_data/_data}';

	public function __construct(
		private IAppManager $apps,
		private VideoStore $store,
		private IConfig $config,
	) {
	}

	public static function isAio(): bool {
		return (string)getenv('THIS_IS_AIO') !== '';
	}

	/** @return array{aio: bool, yaml: string}|null null when there's no video folder to give the worker */
	public function build(): ?array {
		$videos = $this->store->root();
		if ($videos === null) {
			return null;
		}
		$worker = rtrim($this->apps->getAppPath('golblick'), '/') . '/worker';
		$data = rtrim($this->config->getSystemValueString('datadirectory', ''), '/');
		$aio = self::isAio();
		if ($aio) {
			$aioData = rtrim((string)getenv('NEXTCLOUD_DATA_DIR'), '/') ?: '/mnt/ncdata';
			if (str_starts_with($worker, self::AIO_APP)) {
				$worker = self::AIO_APP_HOST . substr($worker, \strlen(self::AIO_APP));
			}
			if (str_starts_with($videos, "$aioData/")) {
				$videos = self::AIO_DATA_HOST . substr($videos, \strlen($aioData));
			}
			if ($data === $aioData) {
				$data = self::AIO_DATA_HOST;
			}
		}
		$stitch = StitchQueue::DATA;
		$user = \function_exists('posix_geteuid') ? posix_geteuid() . ':' . posix_getegid() : '33:33';

		return ['aio' => $aio, 'yaml' => <<<YAML
			services:
			  golblick-worker:
			    image: radialapps/go-vod
			    runtime: nvidia
			    restart: unless-stopped
			    user: "$user"   # the user Nextcloud runs as
			    entrypoint: ["/bin/bash", "/golblick/golblick-worker.sh", "/jobs"]
			    environment:
			      NVIDIA_DRIVER_CAPABILITIES: compute,video,utility
			    healthcheck:   # the image's own checks are for the transcoder, which isn't running here
			      test: ["CMD-SHELL", "test -n \"$$(find /jobs/worker.json -mmin -1)\""]
			      start_period: 90s
			    deploy:
			      resources:
			        reservations:
			          devices: [{ driver: nvidia, count: 1, capabilities: [gpu] }]
			    volumes:
			      - type: bind
			        source: $worker
			        target: /golblick
			        read_only: true
			        bind: { create_host_path: false }
			      - type: bind
			        source: $videos
			        target: /jobs
			        bind: { create_host_path: false }
			      - type: bind   # read-only: the GPU stitch reads the clips from here
			        source: $data
			        target: $stitch
			        read_only: true
			        bind: { create_host_path: false }

			YAML];
	}
}
