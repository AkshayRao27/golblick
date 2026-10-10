<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Settings;

use OCA\Golblick\AppInfo\Application;
use OCA\Golblick\Service\Preferences;
use OCP\AppFramework\Http\TemplateResponse;
use OCP\AppFramework\Services\IInitialState;
use OCP\Settings\ISettings;
use OCP\Util;

/** The personal page: what 360 photos and videos do when they open in Memories (`src/personal.ts`). */
final class Personal implements ISettings {
	public function __construct(
		private Preferences $preferences,
		private IInitialState $initialState,
		private ?string $userId,
	) {
	}

	public function getForm(): TemplateResponse {
		$this->initialState->provideInitialState('preferences', $this->preferences->all((string)$this->userId));
		Util::addScript(Application::APP_ID, 'golblick-personal');
		Util::addStyle(Application::APP_ID, 'admin');

		return new TemplateResponse(Application::APP_ID, 'personal');
	}

	public function getSection(): string {
		return Application::APP_ID;
	}

	public function getPriority(): int {
		return 10;
	}
}
