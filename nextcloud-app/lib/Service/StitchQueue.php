<?php

declare(strict_types=1);

// SPDX-License-Identifier: AGPL-3.0-or-later

namespace OCA\Golblick\Service;

use OCA\Golblick\Insta360\FormatError;
use OCA\Golblick\Render\GpuTables;
use OCA\Golblick\Render\RemapTables;
use OCA\Golblick\Render\Stabilise;
use OCP\IConfig;

/**
 * Hands a clip to the GPU worker to stitch, in place of the CPU stitch
 * VideoRenderer runs itself.
 *
 * The plan is still made here (field of view, seam plan, levelling, the
 * tables); the worker does the per-frame work, which is nearly all of it:
 * decoding, stitching, steadying, evening the lenses out, encoding. The CPU
 * stitch can hold a small server's cores for hours; AGENT-NOTES.md,
 * "Video spheres" (Stitching on the GPU worker), has the measurements.
 *
 * A job is a folder `<name>.stitch/` in the video folder: the packed tables
 * (GpuTables), the clip's paths as the worker sees them, `job`, and `ready`
 * last. The worker reads the clips from Nextcloud's data directory, mounted
 * read-only at /data, so only clips stored under it can go to the GPU.
 *
 * With steadying baked in (the video_bake setting) the copy comes out
 * steadied, in the same pass and with one resampling where stitching then
 * baking took two; otherwise it's stitched only, and the player steadies it.
 */
final class StitchQueue {
	/** Where the worker's compose file mounts the data directory. */
	public const DATA = '/data';
	/** The balance strip is made from lenses this size: it only reads a 720-pixel band. */
	private const STRIP_SIZE = 512;

	public function __construct(
		private VideoStore $store,
		private BakeQueue $bake,
		private IConfig $config,
	) {
	}

	/** Whether a live worker can stitch, and sees all of $inputs (local paths). */
	public function canStitch(array $inputs): bool {
		return ($this->bake->worker()['stitch'] ?? false) && ($this->bake->worker()['alive'] ?? false)
			&& \count(array_filter($inputs, fn (string $path): bool => $this->workerPath($path) === null)) === 0;
	}

	/**
	 * Write the job for $name from the tables RemapTables wrote into $tables.
	 *
	 * @param list<string> $inputs local paths, as VideoRenderer reads them
	 * @param array{rate: string, matrix: string, range: string, duration: float, created: ?string} $probe
	 * @param array|null $track the steadying track to bake in (MotionStore::track), or null for none
	 * @param string|null $shutter each frame's turns across its readout (MotionStore::shutter), or null to
	 *        leave the rolling shutter in. Optional for the worker: one that predates it ignores it
	 * @throws FormatError with nothing left behind
	 */
	public function start(string $name, string $tables, array $inputs, int $lensSize, int $width, int $bitrate,
		array $probe, ?array $track, ?string $shutter = null): void {
		// Written beside and renamed into place, so the worker never sees a
		// job half written, or rewritten under it: a table that changes while
		// the worker reads it puts a band across every frame of the copy.
		$final = $this->store->root() . "/$name.stitch";
		$dir = "$final.part";
		VideoStore::removeDirectory($dir);
		VideoStore::removeDirectory($final);
		if (!mkdir($dir, 0770)) {
			throw new FormatError('could not create the stitch folder');
		}
		try {
			$paths = array_map(fn (string $path): string => $this->workerPath($path) ?? throw new FormatError("$path is outside the data directory"), $inputs);
			$sizes = GpuTables::write($tables, $dir, $lensSize, self::STRIP_SIZE);
			$trackSize = GpuTables::writeTrack($track === null ? [] : BakeQueue::quaternions($track), BakeQueue::COLUMNS, "$dir/track.p016");
			$job = [
				'width' => $width,
				'lens' => $lensSize,
				'strip' => self::STRIP_SIZE,
				'around' => RemapTables::STRIP_AROUND,
				'ladder' => RemapTables::LADDER,
				'bitrate' => $bitrate,
				'mark' => $track === null ? 0 : 1,
				'matrix' => $probe['matrix'],
				'range' => $probe['range'],
				'rate' => $probe['rate'],
				'duration' => sprintf('%.3f', $probe['duration']),
				'track' => $trackSize,
				'field' => $sizes['fa'],
			] + ($probe['created'] === null ? [] : ['created' => $probe['created']]);
			if ($shutter !== null) {
				$job['shutter'] = GpuTables::writeTrack($shutter, BakeQueue::COLUMNS, "$dir/shutter.p016");
				$job['samples'] = Stabilise::SHUTTER_SAMPLES;
			}
			$text = '';
			foreach ($job as $key => $value) {
				$text .= "$key=$value\n";
			}
			if (file_put_contents("$dir/inputs", implode("\n", $paths) . "\n") === false
				|| file_put_contents("$dir/job", $text) === false || !touch("$dir/ready") || !rename($dir, $final)) {
				throw new FormatError('could not write the stitch job');
			}
		} catch (\Throwable $e) {
			VideoStore::removeDirectory($dir);
			throw $e instanceof FormatError ? $e : new FormatError($e->getMessage());
		}
	}

	/**
	 * Where a stitch stands, as VideoRenderer::status() and BakeQueue::status() say it.
	 *
	 * @return array{state: 'running'|'done'|'failed'|'lost', detail: string}
	 */
	public function status(string $name): array {
		$dir = $this->store->root() . "/$name.stitch";
		if (!is_dir($dir)) {
			return ['state' => 'lost', 'detail' => 'the stitch folder is gone'];
		}
		$code = @file_get_contents("$dir/status");
		if ($code === false) {
			return ($this->bake->worker()['alive'] ?? false)
				? ['state' => 'running', 'detail' => '']
				: ['state' => 'lost', 'detail' => 'the GPU worker stopped sending its heartbeat'];
		}
		if (trim($code) === '0' && is_file("$dir/stitched.mp4")) {
			return ['state' => 'done', 'detail' => ''];
		}
		$log = trim((string)@file_get_contents("$dir/log"));

		return ['state' => 'failed', 'detail' => 'the GPU worker exited ' . trim($code) . ($log === '' ? '' : ': ' . substr($log, -300))];
	}

	/** The -progress file of a running stitch, for VideoRenderer::progress(). */
	public function progressFile(string $name): string {
		return $this->store->root() . "/$name.stitch/progress";
	}

	/** Put the stitched copy in place as $name.mp4. */
	public function finish(string $name): void {
		$root = $this->store->root();
		$stitched = "$root/$name.stitch/stitched.mp4";
		// Untagged it's still a working copy, as with the CPU stitch.
		SphericalTag::add($stitched);
		if (!rename($stitched, "$root/$name.mp4")) {
			throw new FormatError('could not move the stitched copy into place');
		}
		VideoStore::removeDirectory("$root/$name.stitch");
	}

	public function abandon(string $name): void {
		VideoStore::removeDirectory($this->store->root() . "/$name.stitch");
	}

	/** $path as the worker sees it, or null if it isn't under the data directory. */
	private function workerPath(string $path): ?string {
		$data = realpath($this->config->getSystemValueString('datadirectory', ''));
		$real = realpath($path);
		if ($data === false || $real === false || !str_starts_with($real, "$data/") || str_contains($real, "\n")) {
			return null;
		}

		return self::DATA . substr($real, \strlen($data));
	}
}
