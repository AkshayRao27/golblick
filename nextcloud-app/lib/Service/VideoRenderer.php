<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Service;

use OCA\Files_Versions\Versions\IVersionManager;
use OCA\Golblick\Insta360\Calibration;
use OCA\Golblick\Insta360\FormatError;
use OCA\Golblick\Insta360\Imu;
use OCA\Golblick\Insta360\Keyframes;
use OCA\Golblick\Insta360\LensProfile;
use OCA\Golblick\Insta360\Protobuf;
use OCA\Golblick\Insta360\Trailer;
use OCA\Golblick\Render\FrameCode;
use OCA\Golblick\Render\Orientation;
use OCA\Golblick\Render\RemapTables;
use OCA\Golblick\Render\SeamPlan;
use OCP\Files\File;
use OCP\Files\Folder;
use OCP\IUser;
use OCP\IUserSession;
use OCP\Server;
use Psr\Log\LoggerInterface;

/**
 * Renders a stitched copy of an Insta360 video with ffmpeg, in the background.
 *
 * A clip renders at about a fifth of real time on four cores, so a render
 * outlives the cron run that starts it: ffmpeg is started detached, at the
 * lowest priority, and leaves a pid file and, when it exits, a status file
 * (VideoStore's naming). The job checks those on its next runs.
 *
 * The projection is computed once, as remap tables (RemapTables); ffmpeg
 * scales each lens down to the output's density, remaps it, blends the two
 * through the table's mask and encodes H.264 that browsers can play. Levelled
 * once, from the first seconds of the inertial record, as the thumbnail is;
 * the horizon is not followed through the clip.
 *
 * The camera doesn't match a video's lenses to each other, so they hand over
 * in two bands, as in the desktop player: detail across the narrow one, the
 * lenses blurred across a wider one, so a brightness step between them fades
 * out instead of showing as a line (RemapTables, twoBands()).
 *
 * Where the lenses hand over is planned once per clip from a few frames
 * (SeamPlan): each lens aimed so a subject near the camera lines up, and the
 * cut routed round what still disagrees -- or the bisector, when the plan
 * can't show a clear gain on frames it wasn't chosen on.
 *
 * With a GPU worker that can stitch, the plan and tables are made here as
 * always and the per-frame work goes to the worker instead (StitchQueue).
 */
final class VideoRenderer {
	/**
	 * How far the wide band's blur reaches, degrees: a box this wide, and
	 * bilinear back up; video.BLUR in the library.
	 */
	private const BLUR_DEGREES = 3.0;

	/** 20 Mbit/s at 3840x1920, in proportion for other widths. */
	private const BITS_PER_PIXEL_SECOND = 20e6 / (3840 * 1920);

	/** The video bitrate of a copy $width wide; a baked copy is encoded at the same. */
	public static function bitrate(int $width): int {
		return (int)round(self::BITS_PER_PIXEL_SECOND * $width * intdiv($width, 2));
	}

	/** How clearly the guarded field of view has to win; render.PICK_MARGIN in the library. */
	private const PICK_MARGIN = 0.15;

	/** Lens size the guard check decodes at: about 8 MB a lens in GD. */
	private const GUARD_PROBE_SIZE = 1440;

	/**
	 * Frames, and the lens size, the seam plan is chosen and checked on: four
	 * frames to choose on and four to check against. 720 chose the same plans
	 * as 1440 in the library.
	 */
	private const SEAM_PROBE_FRAMES = 8;
	private const SEAM_PROBE_SIZE = 720;

	public function __construct(
		private VideoDecoder $decoder,
		private VideoStore $store,
		private Settings $settings,
		private IUserSession $session,
		private LoggerInterface $logger,
		private StitchQueue $stitch,
		private MotionStore $motion,
	) {
	}

	/**
	 * Start rendering $file, a video's master file, and return the entry name.
	 *
	 * @param bool $gpu whether the GPU worker may stitch it, if it can
	 * @return array{name: string, deadline: int, guards: bool, seam: string, duration: float, gpu: bool, steadied: bool}
	 *         guards: whether lens guards were detected; seam: how the lenses hand over; duration: the clip's length
	 *         in seconds; gpu: whether the worker is stitching it; steadied: whether that copy will come out steadied
	 * @throws FormatError if the file can't be rendered; nothing is left running
	 */
	public function start(File $file, bool $gpu = true): array {
		// Planning reads frames and builds tables for up to a minute of CPU,
		// and this runs from cron, so at the lowest priority like the stitch.
		// Not in a web server's process, which would stay niced for good.
		if (\PHP_SAPI === 'cli' && \function_exists('proc_nice')) {
			@proc_nice(19);
		}
		$ffmpeg = $this->decoder->binary();
		$root = $this->store->root();
		if ($ffmpeg === null || $root === null || !$this->store->isUsable()) {
			throw new FormatError('ffmpeg or a local data directory is missing');
		}
		$width = $this->settings->videoWidth();
		$name = $this->store->nameOf($file);

		$inputs = $this->inputs($file);
		$probe = $this->probe($ffmpeg, $inputs[0]);
		$streams = $probe['streams'];
		$lenses = \count($inputs) === 2 ? [[0, 0], [1, 0]] : [[0, 0], [0, 1]];
		if (\count($inputs) === 1 && \count($streams) < 2) {
			throw new FormatError('the video has one picture stream and no second lens file');
		}
		$native = $streams[0]['width'];
		$free = @disk_free_space($root);
		if ($free !== false && $free < filesize($inputs[0]) + 2 * 1024 ** 3) {
			throw new FormatError('not enough free space in the data directory');
		}

		[$calibration, $model, $orientation, $baseline] = $this->geometry($file);
		$guards = $this->lensGuards($inputs, $lenses, $calibration, $model, $probe['duration']);
		[$plan, $seam] = $this->seamPlan($inputs, $lenses, $calibration, $model, $guards, $baseline, $probe['duration']);
		$lensSize = RemapTables::lensSizeFor($calibration, $native, $width, $model, $guards);
		$tables = "$root/$name.tables";
		if (!is_dir($tables) && !mkdir($tables, 0770, true)) {
			throw new FormatError('could not create the table directory');
		}
		RemapTables::write($tables, $calibration, $lensSize, $width, $orientation, $model, $guards, $plan);

		$bitrate = self::bitrate($width);
		if ($gpu && $this->stitch->canStitch($inputs)) {
			$track = $this->settings->flag('video_bake') ? $this->motion->track($file) : null;
			try {
				$this->stitch->start($name, $tables, $inputs, $lensSize, $width, $bitrate, $probe, $track,
					$this->motion->shutter($file, $orientation));
				VideoStore::removeDirectory($tables);

				return ['name' => $name, 'deadline' => time() + max(3600, (int)(12 * $probe['duration'])), 'guards' => $guards,
					'seam' => $seam, 'duration' => (float)$probe['duration'], 'gpu' => true, 'steadied' => $track !== null];
			} catch (FormatError $e) {
				$this->logger->warning("golblick: stitching $name on the CPU: could not hand it to the GPU worker: " . $e->getMessage(), ['app' => 'golblick']);
			}
		}

		// Memory, not speed, sets the thread counts: with ffmpeg's defaults a
		// render peaked at 4 GB, and an AIO host may have 4 GB for everything.
		// Measurements in AGENT-NOTES.md, "Video spheres" (Pipeline).
		$command = [$ffmpeg, '-nostdin', '-v', 'error', '-y'];
		foreach ($inputs as $input) {
			array_push($command, '-threads', '1', '-i', $input);
		}
		$table = [];
		foreach (['x0', 'y0', 'x1', 'y1', 'mask', 'wide'] as $index => $map) {
			array_push($command, '-i', "$tables/$map.pgm");
			$table[$map] = (\count($inputs) + $index) . ':v';
		}
		$filter = sprintf('[%d:v:%d]scale=%d:%3$d:flags=area[l0];', $lenses[0][0], $lenses[0][1], $lensSize)
			. sprintf('[%d:v:%d]scale=%d:%3$d:flags=area[l1];', $lenses[1][0], $lenses[1][1], $lensSize)
			. self::twoBands($table, $width)
			. '[blended]format=yuv420p,' . FrameCode::filter($width) . '[out]';
		array_push($command,
			'-filter_threads', '1', '-filter_complex', $filter, '-map', '[out]', '-map', '0:a:0?',
			'-c:v', 'libx264', '-preset', 'veryfast', '-threads', '2', '-x264-params', 'sliced-threads=1:rc-lookahead=0',
			'-b:v', (string)$bitrate,
			'-maxrate', (string)(int)($bitrate * 1.5), '-bufsize', (string)(2 * $bitrate),
			'-c:a', 'copy', '-movflags', '+faststart');
		if ($probe['created'] !== null) {
			array_push($command, '-metadata', 'creation_time=' . $probe['created']);
		}
		// How far it has got, for the settings page: -v error keeps the log
		// to errors, and -progress reports regardless. Every 5 s, not the
		// default half second, so an hour's render leaves 200 KB, not 2 MB.
		array_push($command, '-progress', "$root/$name.progress", '-stats_period', '5');
		array_push($command, '-f', 'mp4', "$root/$name.part.mp4");

		$quoted = implode(' ', array_map('escapeshellarg', $command));
		$base = escapeshellarg("$root/$name");
		// The pid file holds ffmpeg's own pid (nice execs it), so abandon() stops
		// the encoder and not just the shell; the status file appears only once
		// ffmpeg has exited, with its exit code.
		$script = "nice -n 19 $quoted > $base.log 2>&1 & echo \$! > $base.pid; wait \$!; echo \$? > $base.status";
		@unlink("$root/$name.status");
		exec('nohup sh -c ' . escapeshellarg($script) . ' > /dev/null 2>&1 < /dev/null &');

		// Twelve times the clip's length, an hour at least: four cores run at about a fifth of real time.
		return ['name' => $name, 'deadline' => time() + max(3600, (int)(12 * $probe['duration'])), 'guards' => $guards,
			'seam' => $seam, 'duration' => (float)$probe['duration'], 'gpu' => false, 'steadied' => false];
	}

	/**
	 * The filters that stitch [l0] and [l1] through the tables into [blended].
	 *
	 * The narrow band's blend, plus the lenses blurred (an area scale down to
	 * BLUR_DEGREES a pixel and bilinear back up) and blended across the wide
	 * band, less the same blended across the narrow one: (mask - wide) times
	 * the blurred difference, written with maskedmerge, which takes no signed
	 * weight, and blend's grain modes, centred on 128.
	 *
	 * @param array<string, string> $table input labels of the tables, by name
	 */
	private static function twoBands(array $table, int $width): string {
		$small = (int)round(360 / self::BLUR_DEGREES);
		$blur = sprintf('scale=%d:%d:flags=area,scale=%d:%d:flags=bilinear', $small, intdiv($small, 2), $width, intdiv($width, 2));

		return "[l0][{$table['x0']}][{$table['y0']}]remap,format=gbrp,split[a][a2];"
			. "[l1][{$table['x1']}][{$table['y1']}]remap,format=gbrp,split[b][b2];"
			. "[a2]$blur,split[la][la2];[b2]$blur,split[lb][lb2];"
			. "[{$table['mask']}]format=gbrp,split[m][m2];[{$table['wide']}]format=gbrp[w];"
			. '[a][b][m]maskedmerge[fine];[la][lb][w]maskedmerge[across];[la2][lb2][m2]maskedmerge[cut];'
			. '[across][cut]blend=all_mode=grainextract[lift];[fine][lift]blend=all_mode=grainmerge[blended];';
	}

	/**
	 * Where a render stands: running, done (ffmpeg exited 0 and left a file),
	 * failed (with the end of its log), or lost (no process and no status, as
	 * after a restart).
	 *
	 * @return array{state: string, detail: string}
	 */
	public function status(string $name): array {
		$base = $this->store->root() . "/$name";
		if (is_file("$base.status")) {
			$code = trim((string)file_get_contents("$base.status"));
			if ($code === '0' && is_file("$base.part.mp4") && filesize("$base.part.mp4") > 0) {
				return ['state' => 'done', 'detail' => ''];
			}
			$log = is_file("$base.log") ? trim((string)file_get_contents("$base.log", false, null, max(0, (int)filesize("$base.log") - 400))) : '';

			return ['state' => 'failed', 'detail' => "ffmpeg exited $code: $log"];
		}
		$pid = is_file("$base.pid") ? (int)file_get_contents("$base.pid") : 0;
		if ($pid > 0 && is_dir("/proc/$pid")) {
			return ['state' => 'running', 'detail' => ''];
		}

		return ['state' => 'lost', 'detail' => 'the render stopped without finishing'];
	}

	/**
	 * How many seconds of the clip a running render has written, from the
	 * last block ffmpeg's -progress wrote; null before the first one, or for
	 * a render started without it.
	 */
	public function progress(string $name): ?float {
		$path = is_dir($this->store->root() . "/$name.stitch") ? $this->stitch->progressFile($name) : $this->store->root() . "/$name.progress";
		$size = @filesize($path);
		if ($size === false || $size === 0) {
			return null;
		}
		$tail = (string)@file_get_contents($path, false, null, max(0, $size - 2048));
		// "N/A" until the first frame is out, so only a number counts.
		if (!preg_match_all('/^out_time_us=(\d+)$/m', $tail, $matches)) {
			return null;
		}

		return (int)end($matches[1]) / 1e6;
	}

	/** Stop a render that is still going, and remove its work files. */
	public function abandon(string $name): void {
		$base = $this->store->root() . "/$name";
		$pid = is_file("$base.pid") ? (int)file_get_contents("$base.pid") : 0;
		if ($pid > 0 && is_dir("/proc/$pid")) {
			exec('kill -TERM ' . $pid . ' 2>/dev/null');
		}
		$this->cleanUp($name, true);
	}

	/** Move a finished render into place. */
	public function finish(string $name, int $fileId): void {
		$base = $this->store->root() . "/$name";
		// Untagged is still a working copy, so a refusal here isn't a failure.
		SphericalTag::add("$base.part.mp4");
		if (!rename("$base.part.mp4", "$base.mp4")) {
			throw new FormatError('could not move the finished video into place');
		}
		$this->cleanUp($name, false);
		$this->store->dropOthers($fileId, $name);
	}

	/**
	 * Move the finished copy $name of $master out of the app's data and into
	 * the clip's folder, as an ordinary file (VideoStore::BESIDE), through the
	 * storage layer so the file cache, quota, sharing and previews all apply.
	 * An existing copy of the same name is replaced, and its old renders
	 * dropped from its versions (dropVersions()): it's an older render of the
	 * same clip. Left where it was, still playable from Files, if the folder
	 * can't take it. $user is who the job opened $master as.
	 *
	 * @throws FormatError
	 */
	public function publish(File $master, string $name, ?IUser $user = null): void {
		$path = $this->store->root() . "/$name.mp4";
		$source = @fopen($path, 'rb');
		if ($source === false) {
			throw new FormatError('the stitched copy is missing');
		}
		try {
			$folder = $master->getParent();
			$target = VideoStore::besideName($master);
			if ($folder->nodeExists($target)) {
				$node = $folder->get($target);
				if (!$node instanceof File) {
					throw new FormatError("$target exists next to the clip and isn't a file");
				}
				$node->putContent($source);
				$this->dropVersions($node, $user);
			} else {
				$folder->newFile($target, $source);
			}
		} catch (FormatError $e) {
			throw $e;
		} catch (\Throwable $e) {
			throw new FormatError('could not save the copy next to the clip: ' . $e->getMessage());
		} finally {
			if (\is_resource($source)) {
				fclose($source);
			}
		}
		$this->store->markBeside($name);
		@unlink($path);
	}

	/**
	 * Delete a replaced copy's versions: they're older renders, worth nothing,
	 * and with the default retention they stay until versions reach their
	 * space limit. Don't write past the versions app instead: AGENT-NOTES.md,
	 * "Video spheres" (Copies next to the clips), says why.
	 *
	 * Deleting checks the current user's permissions and this runs from cron,
	 * so it acts as the user the job opened the clip as, for the length of the
	 * call. IVersionManager belongs to the versions app, not the public API;
	 * without that app there are no versions to drop.
	 */
	private function dropVersions(File $node, ?IUser $user): void {
		if ($user === null || !interface_exists(IVersionManager::class)) {
			return;
		}
		$previous = $this->session->getUser();
		$this->session->setVolatileActiveUser($user);
		try {
			$versions = Server::get(IVersionManager::class);
			foreach ($versions->getVersionsForFile($user, $node) as $version) {
				// The list includes the current content, as the version at its mtime.
				if ((int)$version->getTimestamp() !== $node->getMTime()) {
					$versions->deleteVersion($version);
				}
			}
		} catch (\Throwable $e) {
			$this->logger->warning('golblick: could not drop the old versions of ' . $node->getPath() . ': ' . $e->getMessage(), ['app' => 'golblick']);
		} finally {
			$this->session->setVolatileActiveUser($previous);
		}
	}

	private function cleanUp(string $name, bool $withVideo): void {
		$base = $this->store->root() . "/$name";
		foreach (['.pid', '.status', '.log', '.progress'] as $suffix) {
			@unlink($base . $suffix);
		}
		if ($withVideo) {
			@unlink("$base.part.mp4");
		}
		VideoStore::removeDirectory("$base.tables");
	}

	/**
	 * Local paths of the files to read: a OneR or X3 clip's two lens files,
	 * or an X5's one file with both lenses as streams.
	 *
	 * @return list<string>
	 */
	private function inputs(File $file): array {
		$paths = [$this->localPath($file)];
		$handle = $file->fopen('r');
		if ($handle === false) {
			throw new FormatError('could not open the video');
		}
		try {
			$trailer = Trailer::read($handle, [Trailer::PREVIEW]);
			$keyframes = Keyframes::isKeyframe((string)$trailer->get(Trailer::PREVIEW));
		} finally {
			fclose($handle);
		}
		if (!$keyframes) {
			return $paths;
		}
		// A OneR or X3: the other lens is the _10_ file of the same name.
		if (!preg_match('/^(VID_\d{8}_\d{6})_00_(\d+\.insv)$/i', $file->getName(), $m)) {
			throw new FormatError('not the first lens file of a clip');
		}
		try {
			$partner = $file->getParent()->get($m[1] . '_10_' . $m[2]);
		} catch (\Throwable $e) {
			throw new FormatError('the second lens file (_10_) is not next to this one');
		}
		if (!$partner instanceof File || $partner instanceof Folder) {
			throw new FormatError('the second lens file (_10_) is not a file');
		}
		$paths[] = $this->localPath($partner);

		return $paths;
	}

	private function localPath(File $file): string {
		$storage = $file->getStorage();
		if (!$storage->isLocal() || $file->isEncrypted()) {
			throw new FormatError('only files on local, unencrypted storage can be rendered');
		}
		$path = $storage->getLocalFile($file->getInternalPath());
		if (!\is_string($path) || !is_file($path)) {
			throw new FormatError('the file has no local path');
		}

		return $path;
	}

	/**
	 * @return array{streams: list<array{width: int, height: int}>, duration: float, created: ?string, rate: string,
	 *         matrix: string, range: string} rate, matrix and range are the first lens's, for the GPU stitch
	 */
	private function probe(string $ffmpeg, string $path): array {
		$ffprobe = \dirname($ffmpeg) . '/ffprobe';
		if (!is_executable($ffprobe)) {
			throw new FormatError('ffprobe is not next to ffmpeg');
		}
		$out = [];
		exec(implode(' ', array_map('escapeshellarg', [$ffprobe, '-v', 'error', '-select_streams', 'v',
			'-show_entries', 'stream=width,height,pix_fmt,r_frame_rate,color_space,color_range:stream_tags=creation_time:format=duration:format_tags=creation_time',
			'-of', 'json', $path])), $out, $code);
		$info = json_decode(implode("\n", $out), true);
		if ($code !== 0 || !\is_array($info) || empty($info['streams'])) {
			throw new FormatError('ffprobe could not read the video');
		}
		$streams = array_map(static fn (array $s): array => ['width' => (int)$s['width'], 'height' => (int)$s['height']], $info['streams']);
		foreach ($streams as $stream) {
			if ($stream['width'] !== $stream['height'] || $stream['width'] !== $streams[0]['width']) {
				throw new FormatError('the lens streams are not square and alike');
			}
		}

		// When the clip was recorded: in the container's tags on a OneR or X3,
		// only in each stream's on an X5. ffmpeg doesn't carry it into a
		// filter graph's output, and without it Memories files the copy under
		// the day it was made.
		$created = $info['format']['tags']['creation_time'] ?? $info['streams'][0]['tags']['creation_time'] ?? null;

		// The cameras tag their lenses BT.709 or, on the OneR, BT.601, and full
		// range. Untagged is taken as BT.709, and full range only for the
		// pixel formats that say so.
		$first = $info['streams'][0];
		$matrix = \in_array($first['color_space'] ?? '', ['bt709', 'smpte170m', 'bt470bg'], true) ? $first['color_space'] : 'bt709';
		$rate = preg_match('#^[1-9]\d*/[1-9]\d*$#', (string)($first['r_frame_rate'] ?? '')) ? $first['r_frame_rate'] : '30000/1001';

		return ['streams' => $streams, 'duration' => (float)($info['format']['duration'] ?? 0),
			'created' => \is_string($created) && preg_match('/^\d{4}-\d\d-\d\dT[\d:.]+Z?$/', $created) ? $created : null,
			'rate' => $rate, 'matrix' => $matrix, 'range' => match ($first['color_range'] ?? '') {
				'pc' => 'pc',
				'tv' => 'tv',
				default => str_starts_with((string)($first['pix_fmt'] ?? ''), 'yuvj') ? 'pc' : 'tv',
			}];
	}

	/**
	 * Whether the lenses wore clip-on guards, which narrow what they see: a
	 * port of render.pick_field_of_view() in the library, which owns the
	 * reasoning. Three frames are scored at both fields of view, and the
	 * guarded one has to make the lenses agree clearly better. False when it
	 * can't tell, or the camera has no guards modelled.
	 *
	 * @param list<string> $inputs
	 * @param list<array{int, int}> $lenses
	 */
	private function lensGuards(array $inputs, array $lenses, Calibration $calibration, ?string $model,
		float $duration): bool {
		if (!LensProfile::hasGuards($model) || $duration <= 0) {
			return false;
		}
		[$bare] = LensProfile::for($model);
		[$guarded] = LensProfile::for($model, true);
		$ratios = [];
		$keyframes = $this->decoder->keyframeTimes($inputs[$lenses[0][0]], $lenses[0][1]);
		foreach (self::probeTimes([0.2 * $duration, 0.5 * $duration, 0.8 * $duration], $keyframes) as $at) {
			try {
				[$lens0, $lens1] = $this->decoder->lensFrames($inputs, $lenses, $at, self::GUARD_PROBE_SIZE);
			} catch (FormatError $e) {
				continue;
			}
			$withGuards = RemapTables::disagreement($lens0, $lens1, $calibration, $model, $guarded);
			$without = RemapTables::disagreement($lens0, $lens1, $calibration, $model, $bare);
			if ($withGuards !== null && $without !== null && $without > 0.0) {
				$ratios[] = $withGuards / $without;
			}
		}
		if ($ratios === []) {
			return false;
		}
		sort($ratios);
		$middle = intdiv(\count($ratios), 2);
		$median = \count($ratios) % 2 === 1 ? $ratios[$middle] : ($ratios[$middle - 1] + $ratios[$middle]) / 2.0;

		return $median < 1.0 - self::PICK_MARGIN;
	}

	/**
	 * One hand-over for the whole clip, or null for the bisector, and a word on
	 * which; SeamPlan has the reasoning. Frames spread over the clip, so a plan
	 * has to hold for all of it. Anything that goes wrong here costs the plan,
	 * never the render, and says why in the word, which the job logs.
	 *
	 * @param list<string> $inputs
	 * @param list<array{int, int}> $lenses
	 * @param float[]|null $baseline
	 * @return array{?SeamPlan, string}
	 */
	private function seamPlan(array $inputs, array $lenses, Calibration $calibration, ?string $model, bool $guards,
		?array $baseline, float $duration): array {
		if ($duration <= 0) {
			return [null, 'bisector'];
		}
		$frames = [];
		$wanted = [];
		for ($k = 0; $k < self::SEAM_PROBE_FRAMES; ++$k) {
			$wanted[] = $duration * (0.03 + 0.94 * $k / (self::SEAM_PROBE_FRAMES - 1));
		}
		$keyframes = $this->decoder->keyframeTimes($inputs[$lenses[0][0]], $lenses[0][1]);
		foreach (self::probeTimes($wanted, $keyframes) as $at) {
			try {
				$frames[] = $this->decoder->lensFrames($inputs, $lenses, $at, self::SEAM_PROBE_SIZE);
			} catch (FormatError $e) {
				continue;
			}
		}
		try {
			$plan = SeamPlan::choose($frames, $calibration, $model, $guards, $baseline);
		} catch (\Throwable $e) {
			return [null, 'bisector (seam plan failed: ' . $e->getMessage() . ')'];
		}

		return [$plan, $plan === null ? 'bisector' : ($plan->parallax !== null ? 'aimed and routed' : 'routed')];
	}

	/**
	 * $wanted moved to the nearest keyframe, where that's a frame not already
	 * taken: video.probe_times() in the library, which has the measurements.
	 * Planning wants frames spread through the clip, not exact moments, and an
	 * X5 keyframes every 2 seconds, so an exact moment can mean decoding 60
	 * full-size frames first. A moment whose nearest keyframe is taken keeps
	 * its own time.
	 *
	 * @param list<float> $wanted
	 * @param list<float> $keyframes
	 * @return list<float>
	 */
	public static function probeTimes(array $wanted, array $keyframes): array {
		$taken = [];
		$out = [];
		foreach ($wanted as $at) {
			$nearest = null;
			foreach ($keyframes as $k) {
				if ($nearest === null || abs($k - $at) < abs($nearest - $at)) {
					$nearest = $k;
				}
			}
			if ($nearest !== null && !\in_array($nearest, $taken, true)) {
				$taken[] = $nearest;
				$out[] = $nearest;
			} else {
				$out[] = $at;
			}
		}

		return $out;
	}

	/** @return array{Calibration, ?string, array, ?array} the last is lens 1's offset from lens 0, if stated */
	private function geometry(File $file): array {
		$handle = $file->fopen('r');
		if ($handle === false) {
			throw new FormatError('could not open the video');
		}
		try {
			$trailer = Trailer::read($handle, [Trailer::METADATA, Trailer::IMU]);
		} finally {
			fclose($handle);
		}
		$metadata = $trailer->get(Trailer::METADATA);
		if ($metadata === null) {
			throw new FormatError('no metadata record, so the lens geometry is unknown');
		}
		$fields = Protobuf::fields($metadata);
		$text = Protobuf::firstText($fields, Protobuf::CALIBRATION_EQUIDISTANT);
		if ($text === null) {
			throw new FormatError('no equidistant calibration');
		}
		$calibration = Calibration::parse($text)->withMei(Protobuf::firstText($fields, Protobuf::CALIBRATION_MEI));
		$crop = Protobuf::sensorCrop($fields);
		if ($crop !== null) {
			$calibration = $calibration->forVideo($crop);
		}
		$polynomial = Protobuf::firstText($fields, Protobuf::CALIBRATION_POLY);
		$baseline = $polynomial === null ? null : Calibration::lensOffset($polynomial);
		$model = Protobuf::firstText($fields, Protobuf::MODEL);
		$orientation = Orientation::fromRoll($calibration->bodyRoll());
		$imu = $trailer->get(Trailer::IMU);
		if ($imu !== null && $model !== null) {
			try {
				$orientation = Orientation::level(Imu::gravityUp($imu, $model, Imu::OPENING_SAMPLES, true));
			} catch (FormatError $e) {
				// An unmeasured camera: the mounting angle still applies.
			}
		}

		return [$calibration, $model, $orientation, $baseline];
	}
}
