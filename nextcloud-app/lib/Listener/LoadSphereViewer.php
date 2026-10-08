<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Listener;

use OCA\Golblick\AppInfo\Application;
use OCA\Files_Sharing\Event\BeforeTemplateRenderedEvent as PublicShareRenderedEvent;
use OCA\Golblick\Service\Settings;
use OCP\AppFramework\Http\Events\BeforeTemplateRenderedEvent;
use OCP\AppFramework\Services\IInitialState;
use OCP\Constants;
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
 * A public share link's page is the Files app and the Viewer again, for a
 * visitor who isn't signed in. It gets the same two buttons, through the
 * share's token (PublicSphereController), when the share lets visitors see
 * its files at all; not on the password prompt, which is the same event with
 * a scope.
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
		if ($event instanceof PublicShareRenderedEvent) {
			$this->handlePublic($event);
			return;
		}
		if (!($event instanceof BeforeTemplateRenderedEvent) || !$event->isLoggedIn()) {
			return;
		}
		if (!in_array($event->getResponse()->getApp(), self::APPS, true)) {
			return;
		}

		$config = [
			'files' => $this->settings->flag('sphere_files'),
			'viewer' => $this->settings->flag('sphere_viewer'),
			'memories' => $this->settings->flag('sphere_memories'),
			'share' => null,
		];
		$this->load($config);
	}

	private function handlePublic(PublicShareRenderedEvent $event): void {
		$share = $event->getShare();
		if ($event->getScope() !== null || !$this->settings->flag('sphere_public')
			|| ($share->getPermissions() & Constants::PERMISSION_READ) === 0 || !$share->canSeeContent()) {
			return;
		}

		$this->load([
			'files' => $this->settings->flag('sphere_files'),
			'viewer' => $this->settings->flag('sphere_viewer'),
			'memories' => false,
			'share' => $share->getToken(),
		]);
	}

	/** @param array{files: bool, viewer: bool, memories: bool, share: ?string} $config */
	private function load(array $config): void {
		if (!in_array(true, $config, true)) {
			return;
		}
		$this->initialState->provideInitialState('config', $config);
		Util::addScript(Application::APP_ID, 'golblick-main');
	}
}
