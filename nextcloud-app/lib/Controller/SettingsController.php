<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Controller;

use OCA\Golblick\Service\PanoramaStore;
use OCA\Golblick\Service\Settings;
use OCA\Golblick\Service\SetupCheck;
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
		]);
	}

	#[FrontpageRoute(verb: 'PUT', url: '/settings')]
	public function save(?int $zoom_width = null, ?bool $memories_zoom = null, ?bool $sphere_files = null,
		?bool $sphere_viewer = null, ?bool $sphere_memories = null, ?bool $sphere_public = null, ?bool $prerender = null): JSONResponse {
		try {
			if ($zoom_width !== null) {
				$this->settings->setZoomWidth($zoom_width);
			}
			foreach (['memories_zoom' => $memories_zoom, 'sphere_files' => $sphere_files,
				'sphere_viewer' => $sphere_viewer, 'sphere_memories' => $sphere_memories, 'sphere_public' => $sphere_public,
				'prerender' => $prerender] as $name => $value) {
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
	public function register(): JSONResponse {
		try {
			return new JSONResponse($this->check->register());
		} catch (\RuntimeException $e) {
			return new JSONResponse(['error' => $e->getMessage()], Http::STATUS_CONFLICT);
		}
	}

	#[FrontpageRoute(verb: 'POST', url: '/settings/cache/clear')]
	public function clearCache(): JSONResponse {
		return new JSONResponse(['removed' => $this->store->clear()]);
	}
}
