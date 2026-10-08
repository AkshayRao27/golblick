<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Controller;

use OCA\Golblick\BackgroundJob\VideoRender;
use OCA\Golblick\Service\PanoramaStore;
use OCA\Golblick\Service\Settings;
use OCA\Golblick\Service\SetupCheck;
use OCA\Golblick\Service\VideoStore;
use OCP\AppFramework\Controller;
use OCP\AppFramework\Http;
use OCP\AppFramework\Http\Attribute\FrontpageRoute;
use OCP\AppFramework\Http\JSONResponse;
use OCP\IRequest;

/**
 * The admin page's backend. Admin-only and CSRF-checked: AppFramework applies
 * both to every method here because none opts out.
 */
final class SettingsController extends Controller {
	public function __construct(
		string $appName,
		IRequest $request,
		private Settings $settings,
		private SetupCheck $check,
		private PanoramaStore $store,
		private VideoStore $videos,
		private VideoRender $videoJob,
	) {
		parent::__construct($appName, $request);
	}

	#[FrontpageRoute(verb: 'GET', url: '/settings/status')]
	public function status(): JSONResponse {
		return new JSONResponse([
			'settings' => $this->settings->all(),
			'checks' => $this->check->run(),
			'cache' => $this->store->stats(),
			'insp' => $this->check->inspRows(true),
			'videos' => $this->videoStatus(),
		]);
	}

	/** What the video job has done and is doing, for the Videos section. */
	private function videoStatus(): array {
		$current = $this->videoJob->current();
		$failed = $this->videoJob->failed();
		$width = '-' . $this->settings->videoWidth();

		return [
			'usable' => $this->videos->isUsable(),
			'clips' => \count($this->videoJob->candidates()),
			'cache' => $this->videos->stats(),
			'rendering' => $current === null ? null : ['fileid' => $current['fileid'], 'started' => $current['started'] ?? null],
			'failed' => \count(array_filter(array_keys($failed), static fn (string $name): bool => str_ends_with($name, $width))),
		];
	}

	#[FrontpageRoute(verb: 'POST', url: '/settings/videos/clear')]
	public function clearVideos(): JSONResponse {
		$current = $this->videoJob->current();
		$removed = $this->videos->clear($current['name'] ?? null);
		$this->videoJob->forgetFailures();

		return new JSONResponse(['removed' => $removed]);
	}

	#[FrontpageRoute(verb: 'PUT', url: '/settings')]
	public function save(?int $zoom_width = null, ?bool $memories_zoom = null, ?bool $sphere_files = null,
		?bool $sphere_viewer = null, ?bool $sphere_memories = null, ?bool $sphere_public = null, ?bool $prerender = null,
		?int $video_width = null, ?bool $video_render = null): JSONResponse {
		try {
			if ($zoom_width !== null) {
				$this->settings->setZoomWidth($zoom_width);
			}
			if ($video_width !== null) {
				$this->settings->setVideoWidth($video_width);
			}
			foreach (['memories_zoom' => $memories_zoom, 'sphere_files' => $sphere_files,
				'sphere_viewer' => $sphere_viewer, 'sphere_memories' => $sphere_memories, 'sphere_public' => $sphere_public,
				'prerender' => $prerender, 'video_render' => $video_render] as $name => $value) {
				if ($value !== null) {
					$this->settings->setFlag($name, $value);
				}
			}
		} catch (\InvalidArgumentException $e) {
			return new JSONResponse(['error' => $e->getMessage()], Http::STATUS_BAD_REQUEST);
		}

		return new JSONResponse(['settings' => $this->settings->all()]);
	}

	#[FrontpageRoute(verb: 'POST', url: '/settings/register')]
	public function register(string $extension = 'insp'): JSONResponse {
		try {
			return new JSONResponse($this->check->register($extension));
		} catch (\RuntimeException $e) {
			return new JSONResponse(['error' => $e->getMessage()], Http::STATUS_CONFLICT);
		}
	}

	#[FrontpageRoute(verb: 'POST', url: '/settings/cache/clear')]
	public function clearCache(): JSONResponse {
		return new JSONResponse(['removed' => $this->store->clear()]);
	}
}
