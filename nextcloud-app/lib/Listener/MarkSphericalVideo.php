<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Listener;

use OCA\Golblick\Service\VideoStore;
use OCP\EventDispatcher\Event;
use OCP\EventDispatcher\IEventListener;
use OCP\Files\File;
use OCP\FilesMetadata\Event\MetadataBackgroundEvent;
use OCP\FilesMetadata\Event\MetadataLiveEvent;
use OCP\FilesMetadata\Event\MetadataNamedEvent;

/**
 * Marks 360 MP4s in Nextcloud's file metadata, so Files can offer "Play as
 * sphere" on them without opening each file (see `src/main.ts`).
 *
 * Which MP4 is a 360 video is in its movie header, often at the end of a
 * file of several gigabytes, so an upload only asks for a background job and
 * the header is read there. Files already on the server are marked by
 * `occ files:scan --all --generate-metadata=golblick-sphere`, which raises
 * only this app's named event and leaves other apps' extractors alone.
 *
 * @template-implements IEventListener<Event>
 */
final class MarkSphericalVideo implements IEventListener {
	public const KEY = 'golblick-sphere';
	private const TYPES = ['video/mp4', 'video/quicktime'];

	public function handle(Event $event): void {
		if ($event instanceof MetadataNamedEvent) {
			if ($event->getName() !== self::KEY) {
				return;
			}
		} elseif ($event instanceof MetadataLiveEvent) {
			if ($event->getNode() instanceof File && \in_array($event->getNode()->getMimetype(), self::TYPES, true)) {
				$event->requestBackgroundJob();
			}
			return;
		} elseif (!($event instanceof MetadataBackgroundEvent)) {
			return;
		}

		$node = $event->getNode();
		$metadata = $event->getMetadata();
		if ($node instanceof File && \in_array($node->getMimetype(), self::TYPES, true) && VideoStore::isSphericalVideo($node)) {
			$metadata->setBool(self::KEY, true);
		} elseif ($metadata->hasKey(self::KEY)) {
			$metadata->unset(self::KEY);
		}
	}
}
