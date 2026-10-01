<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\AppInfo;

use OCA\Golblick\Preview\Insta360;
use OCP\AppFramework\App;
use OCP\AppFramework\Bootstrap\IBootContext;
use OCP\AppFramework\Bootstrap\IBootstrap;
use OCP\AppFramework\Bootstrap\IRegistrationContext;

final class Application extends App implements IBootstrap {
	public const APP_ID = 'golblick';

	public function __construct() {
		parent::__construct(self::APP_ID);
	}

	public function register(IRegistrationContext $context): void {
		// The regex is deliberately longer than core's for the same mimetype;
		// see OCA\Golblick\Preview\Insta360 for why that matters.
		$context->registerPreviewProvider(Insta360::class, '/^image\/jpeg$/');
	}

	public function boot(IBootContext $context): void {
	}
}
