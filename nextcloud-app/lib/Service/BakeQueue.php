<?php

declare(strict_types=1);

// SPDX-License-Identifier: AGPL-3.0-or-later

namespace OCA\Golblick\Service;

use OCA\Golblick\Insta360\FormatError;
use OCP\Files\File;

/**
 * Hands finished copies to the GPU worker (worker/golblick-worker.sh), which
 * bakes the steadying into them, so they play steady in any player and when
 * downloaded, not only in this app's sphere.
 *
 * The worker is a separate container with the GPU: this server's PHP can't use
 * one, and on Nextcloud AIO couldn't load NVIDIA's libraries at all (Alpine).
 * The two share the video folder (VideoStore::root) and nothing else: a job is
 * a folder `<name>.bake/` next to `<name>.mp4`, and `worker.json` there is the
 * worker's heartbeat. The worker has no access to anything else here.
 */
final class BakeQueue {
	/** A worker whose heartbeat is older than this is taken to be gone. */
	private const ALIVE = 60;
	/** Frames per row of the track image; worker/steady.cl reads the width from the image. */
	public const COLUMNS = 4096;

	public function __construct(
		private VideoStore $store,
		private MotionStore $motion,
	) {
	}

	/**
	 * The worker's last heartbeat, with whether it is recent enough to send it work.
	 *
	 * @return array{alive: bool, seen: int, device: string, encoder: string, stitch: bool}|null stitch: whether
	 *         it can stitch, which needs CUDA and the data directory (a version 1 worker has neither)
	 */
	public function worker(): ?array {
		$root = $this->store->root();
		$heartbeat = $root === null ? false : @file_get_contents("$root/worker.json");
		$data = $heartbeat === false ? null : json_decode($heartbeat, true);
		if (!\is_array($data) || !\is_int($data['seen'] ?? null)) {
			return null;
		}

		return [
			'alive' => time() - $data['seen'] <= self::ALIVE,
			'seen' => $data['seen'],
			'device' => (string)($data['device'] ?? ''),
			'encoder' => (string)($data['encoder'] ?? ''),
			'stitch' => ($data['stitch'] ?? false) === true,
		];
	}

	/**
	 * Ask the worker to bake the finished copy $name of $clip. False, with
	 * nothing written, when there's no live worker or no track for the clip.
	 */
	public function start(string $name, File $clip, int $width): bool {
		$root = $this->store->root();
		if ($root === null || !($this->worker()['alive'] ?? false) || !is_file("$root/$name.mp4")) {
			return false;
		}
		$track = $this->motion->track($clip);
		if ($track === null) {
			return false;
		}

		$dir = "$root/$name.bake";
		VideoStore::removeDirectory($dir);
		if (!mkdir($dir, 0770)) {
			throw new FormatError('could not create the bake folder');
		}
		$rows = intdiv($track['frames'] + self::COLUMNS - 1, self::COLUMNS);
		if (file_put_contents("$dir/track.raw", self::trackImage($track, $rows)) === false
			|| file_put_contents("$dir/job", "rows=$rows\nbitrate=" . VideoRenderer::bitrate($width) . "\n") === false
			|| !touch("$dir/ready")) {
			VideoStore::removeDirectory($dir);
			throw new FormatError('could not write the bake job');
		}

		return true;
	}

	/**
	 * Where a bake stands: waiting or running, done (a baked copy is there),
	 * failed (with ffmpeg's last words) or lost (the job or the worker is gone).
	 *
	 * @return array{state: 'running'|'done'|'failed'|'lost', detail: string}
	 */
	public function status(string $name): array {
		$dir = $this->store->root() . "/$name.bake";
		if (!is_dir($dir)) {
			return ['state' => 'lost', 'detail' => 'the bake folder is gone'];
		}
		$code = @file_get_contents("$dir/status");
		if ($code === false) {
			return ($this->worker()['alive'] ?? false)
				? ['state' => 'running', 'detail' => '']
				: ['state' => 'lost', 'detail' => 'the GPU worker stopped sending its heartbeat'];
		}
		if (trim($code) === '0' && is_file("$dir/baked.mp4")) {
			return ['state' => 'done', 'detail' => ''];
		}
		$log = trim((string)@file_get_contents("$dir/log"));

		return ['state' => 'failed', 'detail' => 'the GPU worker exited ' . trim($code) . ($log === '' ? '' : ': ' . substr($log, -300))];
	}

	/** Put the baked copy in place of the copy it was made from. */
	public function finish(string $name): void {
		$root = $this->store->root();
		$baked = "$root/$name.bake/baked.mp4";
		// Untagged it's still a steady video, just not marked as 360.
		SphericalTag::add($baked);
		if (!rename($baked, "$root/$name.mp4")) {
			throw new FormatError('could not move the baked copy into place');
		}
		VideoStore::removeDirectory("$root/$name.bake");
	}

	public function abandon(string $name): void {
		VideoStore::removeDirectory($this->store->root() . "/$name.bake");
	}

	/**
	 * The track as worker/steady.cl reads it: 16-bit grey, COLUMNS frames a
	 * row, each frame's quaternion (w, x, y, z) on four rows as (c + 1) / 2;
	 * frames past the end don't turn.
	 */
	private static function trackImage(array $track, int $rows): string {
		$quaternions = self::quaternions($track);
		$identity = [65535, 32768, 32768, 32768];
		$image = '';
		for ($block = 0; $block < $rows; $block++) {
			for ($c = 0; $c < 4; $c++) {
				$row = [];
				for ($col = 0; $col < self::COLUMNS; $col++) {
					$row[] = ($quaternions[$block * self::COLUMNS + $col] ?? $identity)[$c];
				}
				$image .= pack('v*', ...$row);
			}
		}

		return $image;
	}

	/**
	 * Each frame's quaternion (w, x, y, z) as the kernels read it, each part
	 * c stored as (c + 1) / 2 in 16 bits.
	 *
	 * @return list<array{int, int, int, int}>
	 */
	public static function quaternions(array $track): array {
		$q = array_values(unpack('v*', base64_decode($track['q'], true) ?: ''));
		$frames = [];
		for ($k = 0; $k < $track['frames'] && isset($q[4 * $k + 3]); $k++) {
			// Little-endian int16, which unpack reads unsigned.
			$quat = array_map(static fn (int $v): float => ($v >= 32768 ? $v - 65536 : $v) / 32767, \array_slice($q, 4 * $k, 4));
			$norm = sqrt(array_sum(array_map(static fn (float $c): float => $c * $c, $quat))) ?: 1.0;
			$frames[] = array_map(static fn (float $c): int => (int)round(($c / $norm + 1) / 2 * 65535), $quat);
		}

		return $frames;
	}
}
