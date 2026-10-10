<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Service;

use OCA\Golblick\AppInfo\Application;
use OCP\Config\IUserConfig;

/**
 * Each user's own choices, set on their personal settings page: what a 360
 * photo or video does when it opens in Memories.
 *
 * Memories shows a 360 video as a flat, stretched rectangle and plays it
 * straight away, which is the least useful way to meet one, so videos open as
 * a sphere unless the user says otherwise. A 360 photo shown flat is still a
 * readable picture, so photos stay flat with the sphere button by default.
 */
final class Preferences {
	public const CHOICES = [
		'open_video' => ['sphere', 'paused', 'play'],
		'open_photo' => ['flat', 'sphere'],
	];

	public function __construct(
		private IUserConfig $userConfig,
	) {
	}

	/** @return array{open_video: string, open_photo: string} */
	public function all(string $user): array {
		$out = [];
		foreach (self::CHOICES as $name => $choices) {
			$value = $this->userConfig->getValueString($user, Application::APP_ID, $name, $choices[0]);
			$out[$name] = \in_array($value, $choices, true) ? $value : $choices[0];
		}

		return $out;
	}

	public function set(string $user, string $name, string $value): void {
		if (!\in_array($value, self::CHOICES[$name] ?? [], true)) {
			throw new \InvalidArgumentException("$name must be one of " . implode(', ', self::CHOICES[$name] ?? []));
		}
		$this->userConfig->setValueString($user, Application::APP_ID, $name, $value);
	}
}
