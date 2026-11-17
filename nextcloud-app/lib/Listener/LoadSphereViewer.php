<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Listener;

use OCA\Golblick\AppInfo\Application;
use OCA\Files_Sharing\Event\BeforeTemplateRenderedEvent as PublicShareRenderedEvent;
use OCA\Golblick\Service\Preferences;
use OCA\Golblick\Service\Settings;
use OCP\AppFramework\Http\Events\BeforeTemplateRenderedEvent;
use OCP\AppFramework\Http\Template\PublicTemplateResponse;
use OCP\AppFramework\Services\IInitialState;
use OCP\Constants;
use OCP\EventDispatcher\Event;
use OCP\EventDispatcher\IEventListener;
use OCP\IRequest;
use OCP\IUserSession;
use OCP\Share\Exceptions\ShareNotFound;
use OCP\Share\IManager as IShareManager;
use OCP\Share\IShare;
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
 * Memories has share links of its own (/apps/memories/s/<token>), rendered by
 * its own controller, which doesn't fire Files' event. They are ordinary link
 * shares, so the page gets the Memories button through the same token and the
 * same checks. That holds for a signed-in visitor too: a link share isn't in
 * their files, so only the token reaches it. Memories' album links
 * (/apps/memories/a/<token>) aren't shares and get nothing.
 *
 * A signed-in user's choice of what 360 photos and videos do when they open
 * in Memories comes along too (Preferences); on a share link nobody's
 * choice applies, and photos and videos open as Memories shows them.
 *
 * @template-implements IEventListener<Event>
 */
final class LoadSphereViewer implements IEventListener {
	private const APPS = ['files', 'photos', 'memories'];
	/** Memories' share-link page (its appinfo/routes.php, Public#showShare); the router lowercases it. */
	private const MEMORIES_SHARE_ROUTE = 'memories.public.showshare';

	public function __construct(
		private Settings $settings,
		private IInitialState $initialState,
		private Preferences $preferences,
		private IUserSession $session,
		private IRequest $request,
		private IShareManager $shareManager,
	) {
	}

	public function handle(Event $event): void {
		if ($event instanceof PublicShareRenderedEvent) {
			$this->handlePublic($event);
			return;
		}
		if (!($event instanceof BeforeTemplateRenderedEvent)) {
			return;
		}
		if ($event->getResponse() instanceof PublicTemplateResponse && $event->getResponse()->getApp() === 'memories') {
			$this->handleMemoriesShare();
			return;
		}
		if (!$event->isLoggedIn()) {
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
		$user = $this->session->getUser();
		if ($config['memories'] && $user !== null) {
			$this->initialState->provideInitialState('preferences', $this->preferences->all($user->getUID()));
		}
		$this->load($config);
	}

	private function handlePublic(PublicShareRenderedEvent $event): void {
		$share = $event->getShare();
		if ($event->getScope() !== null || !$this->visitorsMaySee($share)) {
			return;
		}

		$this->load([
			'files' => $this->settings->flag('sphere_files'),
			'viewer' => $this->settings->flag('sphere_viewer'),
			'memories' => false,
			'share' => $share->getToken(),
		]);
	}

	/**
	 * Memories' share page. Its password prompt is core's template, so this
	 * runs only once the share is unlocked, and the token comes from the route.
	 */
	private function handleMemoriesShare(): void {
		$token = $this->request->getParam('token');
		$route = $this->request->getParam('_route');
		if (!\is_string($route) || strtolower($route) !== self::MEMORIES_SHARE_ROUTE || !\is_string($token)) {
			return;
		}
		try {
			$share = $this->shareManager->getShareByToken($token);
		} catch (ShareNotFound) {
			return;
		}
		if (!$this->visitorsMaySee($share)) {
			return;
		}

		$this->load([
			'files' => false,
			'viewer' => false,
			'memories' => $this->settings->flag('sphere_memories'),
			'share' => $share->getToken(),
		]);
	}

	/** The rule PublicSphereController applies to every file it serves. */
	private function visitorsMaySee(IShare $share): bool {
		return $this->settings->flag('sphere_public')
			&& ($share->getPermissions() & Constants::PERMISSION_READ) !== 0 && $share->canSeeContent();
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
