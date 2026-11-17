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
	public function save(
		?string $open_video = null,
		?string $open_photo = null,
		?string $share_video = null,
		?string $share_photo = null,
	): JSONResponse {
		if ($this->userId === null) {
			return new JSONResponse([], Http::STATUS_UNAUTHORIZED);
		}
		$changes = array_filter(
			['open_video' => $open_video, 'open_photo' => $open_photo, 'share_video' => $share_video, 'share_photo' => $share_photo],
			static fn (?string $value): bool => $value !== null,
		);
		// All or nothing, so a request that is refused hasn't half-applied.
		foreach ($changes as $name => $value) {
			if (!\in_array($value, Preferences::CHOICES[$name], true)) {
				return new JSONResponse(['error' => "$name must be one of " . implode(', ', Preferences::CHOICES[$name])], Http::STATUS_BAD_REQUEST);
			}
		}
		foreach ($changes as $name => $value) {
			$this->preferences->set($this->userId, $name, $value);
		}

		return new JSONResponse(['preferences' => $this->preferences->all($this->userId)]);
	}
}
