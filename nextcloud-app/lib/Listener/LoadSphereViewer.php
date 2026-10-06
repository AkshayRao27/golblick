<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Listener;

use OCA\Golblick\AppInfo\Application;
use OCA\Golblick\Service\Settings;
use OCP\AppFramework\Services\IInitialState;
use OCP\AppFramework\Http\Events\BeforeTemplateRenderedEvent;
use OCP\EventDispatcher\Event;
use OCP\EventDispatcher\IEventListener;
use OCP\Util;

/**
 * Loads the sphere viewer into the pages of the apps it adds a button to.
 *
 * This is the whole integration from the server's side: nothing in Files,
 * Photos or Memories is changed or configured. The script works out where it
 * is and adds its button there; see `src/main.ts`. Which of its buttons it
 * adds is an admin setting, passed to the page as initial state.
 *
 * @template-implements IEventListener<Event>
 */
final class LoadSphereViewer implements IEventListener {
	private const APPS = ['files', 'photos', 'memories'];

	public function __construct(
		private Settings $settings,
		private IInitialState $initialState,
	) {
	}

	public function handle(Event $event): void {
		if (!($event instanceof BeforeTemplateRenderedEvent) || !$event->isLoggedIn()) {
			return;
		}
		if (!in_array($event->getResponse()->getApp(), self::APPS, true)) {
			return;
		}

		$files = $this->settings->flag('sphere_files');
		$buttons = $this->settings->flag('sphere_buttons');
		if (!$files && !$buttons) {
			return;
		}
		$this->initialState->provideInitialState('config', ['files' => $files, 'buttons' => $buttons]);
		Util::addScript(Application::APP_ID, 'golblick-main');
	}
}
