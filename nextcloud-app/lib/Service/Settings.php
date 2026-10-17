<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Service;

use OCA\Golblick\AppInfo\Application;
use OCP\IAppConfig;
use OCP\IConfig;

/**
 * Every admin setting the app has, in one place, with its default.
 *
 * The switches exist because three parts of the app lean on things that are
 * not API: the zoom middleware keys on Memories' class and method names, and
 * the Viewer and Memories buttons find their place by class name. Each can be
 * turned off from the admin page if an update to those apps breaks it, without
 * touching the previews.
 */
final class Settings {
	public const ZOOM_WIDTHS = [1024, 2048, 3072, 4096];
	public const DEFAULT_ZOOM_WIDTH = 4096;

	/**
	 * Stitched video widths. H.264 wider than 4096 often won't play in a
	 * browser, and below 2880 looking around gets soft. 2880 by default for
	 * memory: a render peaks at 0.94 GB there and 1.47 GB at 3840, on servers
	 * that may have 4 GB for everything (VideoRenderer).
	 */
	public const VIDEO_WIDTHS = [2880, 3840];
	public const DEFAULT_VIDEO_WIDTH = 2880;

	private const FLAGS = [
		'memories_zoom' => true,
		'sphere_files' => true,
		'sphere_viewer' => true,
		'sphere_memories' => true,
		'sphere_public' => true,
		'prerender' => false,
		'video_render' => false,
		'video_beside' => false,
		'video_bake' => false,
	];

	public function __construct(
		private IAppConfig $appConfig,
		private IConfig $config,
	) {
	}

	/** Width of the full-size panorama behind zoom and the sphere view. */
	public function zoomWidth(): int {
		$configured = (int)$this->appConfig->getValueString(Application::APP_ID, 'zoom_width', (string)self::DEFAULT_ZOOM_WIDTH);

		return max(1024, min(4096, $configured));
	}

	public function setZoomWidth(int $width): void {
		if (!in_array($width, self::ZOOM_WIDTHS, true)) {
			throw new \InvalidArgumentException('zoom_width must be one of ' . implode(', ', self::ZOOM_WIDTHS));
		}
		$this->appConfig->setValueString(Application::APP_ID, 'zoom_width', (string)$width);
	}

	/** Width of the stitched copies of videos. */
	public function videoWidth(): int {
		$configured = (int)$this->appConfig->getValueString(Application::APP_ID, 'video_width', (string)self::DEFAULT_VIDEO_WIDTH);

		return in_array($configured, self::VIDEO_WIDTHS, true) ? $configured : self::DEFAULT_VIDEO_WIDTH;
	}

	public function setVideoWidth(int $width): void {
		if (!in_array($width, self::VIDEO_WIDTHS, true)) {
			throw new \InvalidArgumentException('video_width must be one of ' . implode(', ', self::VIDEO_WIDTHS));
		}
		$this->appConfig->setValueString(Application::APP_ID, 'video_width', (string)$width);
	}

	/**
	 * The hours in which video stitching may start, [from, to) in the
	 * server's time zone and wrapping past midnight when to < from, or null
	 * for any time.
	 *
	 * @return array{int, int}|null
	 */
	public function videoHours(): ?array {
		$value = $this->appConfig->getValueString(Application::APP_ID, 'video_hours', '');
		if (!preg_match('/^(\d{1,2})-(\d{1,2})$/', $value, $m)) {
			return null;
		}
		[$from, $to] = [(int)$m[1], (int)$m[2]];

		return $from <= 23 && $to <= 23 && $from !== $to ? [$from, $to] : null;
	}

	/** @param string $hours "from-to", whole hours 0 to 23, or "" for any time */
	public function setVideoHours(string $hours): void {
		if ($hours !== '' && (!preg_match('/^(\d{1,2})-(\d{1,2})$/', $hours, $m)
			|| (int)$m[1] > 23 || (int)$m[2] > 23 || (int)$m[1] === (int)$m[2])) {
			throw new \InvalidArgumentException('video_hours must be two different hours from 0 to 23, as from-to, or empty');
		}
		$this->appConfig->setValueString(Application::APP_ID, 'video_hours', $hours === '' ? '' : (int)$m[1] . '-' . (int)$m[2]);
	}

	/**
	 * The time zone the stitching hours are in: Nextcloud's default_timezone
	 * if set, else the TZ the server runs with (Nextcloud AIO sets it from the
	 * host), else UTC. PHP's own default is no help: Nextcloud sets it to UTC.
	 */
	public function timeZone(): \DateTimeZone {
		foreach ([$this->config->getSystemValueString('default_timezone', ''), (string)getenv('TZ')] as $name) {
			if ($name !== '' && \in_array($name, \DateTimeZone::listIdentifiers(), true)) {
				return new \DateTimeZone($name);
			}
		}

		return new \DateTimeZone('UTC');
	}

	/** Whether it's within the stitching hours now (always, with none set). */
	public function inVideoHours(?\DateTimeImmutable $now = null): bool {
		$hours = $this->videoHours();
		if ($hours === null) {
			return true;
		}
		$hour = (int)($now ?? new \DateTimeImmutable('now'))->setTimezone($this->timeZone())->format('G');
		[$from, $to] = $hours;

		return $from < $to ? $hour >= $from && $hour < $to : $hour >= $from || $hour < $to;
	}

	public function flag(string $name): bool {
		if (!array_key_exists($name, self::FLAGS)) {
			throw new \InvalidArgumentException("unknown setting $name");
		}
		$default = self::FLAGS[$name] ? 'yes' : 'no';

		return $this->appConfig->getValueString(Application::APP_ID, $name, $default) === 'yes';
	}

	public function setFlag(string $name, bool $on): void {
		if (!array_key_exists($name, self::FLAGS)) {
			throw new \InvalidArgumentException("unknown setting $name");
		}
		$this->appConfig->setValueString(Application::APP_ID, $name, $on ? 'yes' : 'no');
	}

	/** @return array<string, bool|int> */
	public function all(): array {
		$out = ['zoom_width' => $this->zoomWidth(), 'video_width' => $this->videoWidth(), 'video_hours' => $this->videoHours()];
		foreach (array_keys(self::FLAGS) as $name) {
			$out[$name] = $this->flag($name);
		}

		return $out;
	}
}
