<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Service;

use OCA\Golblick\Insta360\Calibration;
use OCA\Golblick\Insta360\FormatError;
use OCA\Golblick\Insta360\Imu;
use OCA\Golblick\Insta360\Keyframes;
use OCA\Golblick\Insta360\LensProfile;
use OCA\Golblick\Insta360\Protobuf;
use OCA\Golblick\Insta360\Trailer;
use OCA\Golblick\Render\Orientation;
use OCA\Golblick\Render\RemapTables;
use OCA\Golblick\Render\SeamPlan;
use OCP\Files\File;
use OCP\Files\Folder;

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
 * The camera doesn't match a video's lenses to each other, so each frame is
 * also evened out along the seam (RemapTables::writeBalance, balance()).
 *
 * Where the lenses hand over is planned once per clip from a few frames
 * (SeamPlan): each lens aimed so a subject near the camera lines up, and the
 * cut routed round what still disagrees -- or the bisector, when the plan
 * can't show a clear gain on frames it wasn't chosen on.
 */
final class VideoRenderer {
	/** 20 Mbit/s at 3840x1920, in proportion for other widths. */
	private const BITS_PER_PIXEL_SECOND = 20e6 / (3840 * 1920);

	/** How clearly the guarded field of view has to win; render.PICK_MARGIN in the library. */
	private const PICK_MARGIN = 0.15;

	/** Lens size the guard check decodes at: about 8 MB a lens in GD. */
	private const GUARD_PROBE_SIZE = 1440;

	/**
	 * Frames, and the lens size, the seam plan is chosen and checked on. In
	 * the library 720 chose the same plans as 1440 on three clips; eight
	 * frames gives four to choose on and four to check against. About 5 s.
	 */
	private const SEAM_PROBE_FRAMES = 8;
	private const SEAM_PROBE_SIZE = 720;

	public function __construct(
		private VideoDecoder $decoder,
		private VideoStore $store,
		private Settings $settings,
	) {
	}

	/**
	 * Start rendering $file, a video's master file, and return the entry name.
	 *
	 * @return array{name: string, deadline: int, guards: bool, seam: string} guards: whether lens guards
	 *                                                                         were detected; seam: how the lenses hand over
	 * @throws FormatError if the file can't be rendered; nothing is left running
	 */
	public function start(File $file): array {
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
		RemapTables::writeBalance($tables, $calibration, $lensSize, $width, $orientation, $model, $guards, $plan);

		$bitrate = (int)round(self::BITS_PER_PIXEL_SECOND * $width * intdiv($width, 2));
		// 🔴 Memory, not speed, sets these. With ffmpeg's defaults (threads from
		// the host's core count) a render peaked at 4 GB and was killed on a
		// 3 GB container, and a production AIO box has 4 GB for everything.
		// One decoder thread per lens, sliced x264 threads and no lookahead:
		// 0.94 GB at 2880 wide and 1.47 GB at 3840, measured on a OneR clip, of
		// which the lens balance is 0.2 GB; the rest is the frame size itself,
		// and fewer threads didn't move it.
		$command = [$ffmpeg, '-nostdin', '-v', 'error', '-y'];
		foreach ($inputs as $input) {
			array_push($command, '-threads', '1', '-i', $input);
		}
		$table = [];
		foreach (['x0', 'y0', 'x1', 'y1', 'mask', 's0x', 's0y', 's1x', 's1y', 'fx', 'fy'] as $index => $map) {
			array_push($command, '-i', "$tables/$map.pgm");
			$table[$map] = (\count($inputs) + $index) . ':v';
		}
		$filter = sprintf('[%d:v:%d]scale=%d:%3$d:flags=area,split[l0][s0];', $lenses[0][0], $lenses[0][1], $lensSize)
			. sprintf('[%d:v:%d]scale=%d:%3$d:flags=area,split[l1][s1];', $lenses[1][0], $lenses[1][1], $lensSize)
			. self::balance($table, $width)
			. "[l0][{$table['x0']}][{$table['y0']}]remap,format=gbrp[a];[l1][{$table['x1']}][{$table['y1']}]remap,format=gbrp[b];"
			. "[{$table['mask']}]format=gbrp[m];[a][b][m]maskedmerge[blended];"
			. '[blended][correction]blend=all_mode=grainmerge,format=yuv420p[out]';
		array_push($command,
			'-filter_threads', '1', '-filter_complex', $filter, '-map', '[out]', '-map', '0:a:0?',
			'-c:v', 'libx264', '-preset', 'veryfast', '-threads', '2', '-x264-params', 'sliced-threads=1:rc-lookahead=0',
			'-b:v', (string)$bitrate,
			'-maxrate', (string)(int)($bitrate * 1.5), '-bufsize', (string)(2 * $bitrate),
			'-c:a', 'copy', '-movflags', '+faststart');
		if ($probe['created'] !== null) {
			array_push($command, '-metadata', 'creation_time=' . $probe['created']);
		}
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
			'seam' => $seam];
	}

	/**
	 * The filters that even the lenses out, frame by frame: from the lens
	 * streams [s0] and [s1], a [correction] to add to the blended frame,
	 * centred on 128 (blend's grain modes); RemapTables::writeBalance has the
	 * reasoning and the tables.
	 *
	 * Measured on four clips: on an X3 clip whose sun glare put lens 1 up to
	 * 40 levels above lens 0 along the sky, the step at the seam all but went;
	 * an X5's 5 to 7% barely needed it.
	 *
	 * - The difference, lens 1 minus lens 0, along the seam strip, with any
	 *   pixel near white in either lens counted as no difference: where glare
	 *   has washed a lens out there is nothing to match, and chasing it put a
	 *   white haze over the trees next to a blown sky.
	 * - Averaged across the strip, then blurred round the circle, about ten
	 *   degrees, twice. The strip is tiled three wide first so the blur wraps.
	 *   avgblur, not gblur: gblur returns black on an image one pixel high.
	 * - Averaged over nine frames, so a person walking past the seam moves it
	 *   slowly: on a clip with people and a hand close to the lens it moved
	 *   under a level a frame at the 99th percentile.
	 * - Half to each lens, at most 20 levels: a glare offset needed 15 to 20,
	 *   and anything far bigger is a washed-out lens, not an offset.
	 * - Laid out as a ladder of weights from -1 to 1 (geq; scale can't
	 *   interpolate between two rows) and spread over the frame through fx and
	 *   fy, at a quarter of the output size and upscaled.
	 *
	 * @param array<string, string> $table input labels of the tables, by name
	 */
	private static function balance(array $table, int $width): string {
		$around = RemapTables::STRIP_AROUND;
		$ladder = RemapTables::LADDER;
		$step = ($ladder - 1) / 2;
		// Quoted, so the commas inside stay part of the expression.
		$white = "'255*gte(val,250)'";
		$rung = static fn (string $c): string => "'clip(($c(X,Y)-128)/2,-20,20)*(Y/$step-1)+128'";

		return "[s0][{$table['s0x']}][{$table['s0y']}]remap,format=gbrp,split[t0][k0];"
			. "[s1][{$table['s1x']}][{$table['s1y']}]remap,format=gbrp,split[t1][k1];"
			. "[k0]lutrgb=r={$white}:g={$white}:b={$white}[w0];[k1]lutrgb=r={$white}:g={$white}:b={$white}[w1];"
			. '[w0][w1]blend=all_mode=lighten[white];'
			. '[t1][t0]blend=all_mode=grainextract,split[diff][grey];[grey]lutrgb=r=128:g=128:b=128[none];'
			. "[diff][none][white]maskedmerge,scale=$around:1:flags=area,split=3[d0][d1][d2];"
			. "[d0][d1][d2]hstack=inputs=3,avgblur=sizeX=12:sizeY=0,avgblur=sizeX=12:sizeY=0,crop=$around:1:$around:0,"
			. "tmix=frames=9,scale=$around:$ladder:flags=neighbor,"
			. sprintf('geq=r=%s:g=%s:b=%s[ladder];', $rung('r'), $rung('g'), $rung('b'))
			. sprintf('[ladder][%s][%s]remap,scale=%d:%d:flags=bilinear[correction];', $table['fx'], $table['fy'], $width, intdiv($width, 2));
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
	 * storage layer so the file cache, quota, versions and sharing all apply.
	 * An existing copy of the same name is replaced: it's an older render of
	 * the same clip. Left where it was, still playable from Files, if the
	 * folder can't take it.
	 *
	 * @throws FormatError
	 */
	public function publish(File $master, string $name): void {
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

	private function cleanUp(string $name, bool $withVideo): void {
		$base = $this->store->root() . "/$name";
		foreach (['.pid', '.status', '.log'] as $suffix) {
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

	/** @return array{streams: list<array{width: int, height: int}>, duration: float} */
	private function probe(string $ffmpeg, string $path): array {
		$ffprobe = \dirname($ffmpeg) . '/ffprobe';
		if (!is_executable($ffprobe)) {
			throw new FormatError('ffprobe is not next to ffmpeg');
		}
		$out = [];
		exec(implode(' ', array_map('escapeshellarg', [$ffprobe, '-v', 'error', '-select_streams', 'v',
			'-show_entries', 'stream=width,height:stream_tags=creation_time:format=duration:format_tags=creation_time',
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

		return ['streams' => $streams, 'duration' => (float)($info['format']['duration'] ?? 0),
			'created' => \is_string($created) && preg_match('/^\d{4}-\d\d-\d\dT[\d:.]+Z?$/', $created) ? $created : null];
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
		[$bare] = LensProfile::for($model, true);
		[$guarded] = LensProfile::for($model, true, true);
		$ratios = [];
		foreach ([0.2, 0.5, 0.8] as $share) {
			try {
				[$lens0, $lens1] = $this->decoder->lensFrames($inputs, $lenses, $share * $duration, self::GUARD_PROBE_SIZE);
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
		for ($k = 0; $k < self::SEAM_PROBE_FRAMES; ++$k) {
			$at = $duration * (0.03 + 0.94 * $k / (self::SEAM_PROBE_FRAMES - 1));
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
		$calibration = Calibration::parse($text);
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
