<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Controller;

use OCA\Golblick\Service\Preferences;
use OCP\AppFramework\Controller;
use OCP\AppFramework\Http;
use OCP\AppFramework\Http\Attribute\FrontpageRoute;
use OCP\AppFramework\Http\Attribute\NoAdminRequired;
use OCP\AppFramework\Http\JSONResponse;
use OCP\IRequest;

/** The personal settings page's backend: the signed-in user's own choices, CSRF-checked. */
final class PreferencesController extends Controller {
	public function __construct(
		string $appName,
		IRequest $request,
		private Preferences $preferences,
		private ?string $userId,
	) {
		parent::__construct($appName, $request);
	}

	#[NoAdminRequired]
	#[FrontpageRoute(verb: 'PUT', url: '/preferences')]
	public function save(?string $open_video = null, ?string $open_photo = null): JSONResponse {
		if ($this->userId === null) {
			return new JSONResponse([], Http::STATUS_UNAUTHORIZED);
		}
		try {
			foreach (['open_video' => $open_video, 'open_photo' => $open_photo] as $name => $value) {
				if ($value !== null) {
					$this->preferences->set($this->userId, $name, $value);
				}
			}
		} catch (\InvalidArgumentException $e) {
			return new JSONResponse(['error' => $e->getMessage()], Http::STATUS_BAD_REQUEST);
		}

		return new JSONResponse(['preferences' => $this->preferences->all($this->userId)]);
	}
}
