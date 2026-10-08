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
use OCA\Golblick\Insta360\Protobuf;
use OCA\Golblick\Insta360\Trailer;
use OCA\Golblick\Render\Orientation;
use OCA\Golblick\Render\RemapTables;
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
 */
final class VideoRenderer {
	/** 20 Mbit/s at 3840x1920, in proportion for other widths. */
	private const BITS_PER_PIXEL_SECOND = 20e6 / (3840 * 1920);

	public function __construct(
		private VideoDecoder $decoder,
		private VideoStore $store,
		private Settings $settings,
	) {
	}

	/**
	 * Start rendering $file, a video's master file, and return the entry name.
	 *
	 * @return array{name: string, deadline: int}
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

		[$calibration, $model, $orientation] = $this->geometry($file);
		$lensSize = RemapTables::lensSizeFor($calibration, $native, $width, $model);
		$tables = "$root/$name.tables";
		if (!is_dir($tables) && !mkdir($tables, 0770, true)) {
			throw new FormatError('could not create the table directory');
		}
		RemapTables::write($tables, $calibration, $lensSize, $width, $orientation, $model);

		$bitrate = (int)round(self::BITS_PER_PIXEL_SECOND * $width * intdiv($width, 2));
		// 🔴 Memory, not speed, sets these. With ffmpeg's defaults (threads from
		// the host's core count) a render peaked at 4 GB and was killed on a
		// 3 GB container, and a production AIO box has 4 GB for everything.
		// One decoder thread per lens, sliced x264 threads and no lookahead:
		// 0.72 GB at 2880 wide and 1.15 GB at 3840, measured on a OneR clip;
		// the rest is the frame size itself, and fewer threads didn't move it.
		$command = [$ffmpeg, '-nostdin', '-v', 'error', '-y'];
		foreach ($inputs as $input) {
			array_push($command, '-threads', '1', '-i', $input);
		}
		$first = \count($inputs);
		foreach (['x0', 'y0', 'x1', 'y1', 'mask'] as $table) {
			array_push($command, '-i', "$tables/$table.pgm");
		}
		[$x0, $y0, $x1, $y1, $mask] = range($first, $first + 4);
		$filter = sprintf(
			'[%1$d:v:%2$d]scale=%9$d:%9$d:flags=area[l0];[%3$d:v:%4$d]scale=%9$d:%9$d:flags=area[l1];'
			. '[l0][%5$d:v][%6$d:v]remap,format=gbrp[a];[l1][%7$d:v][%8$d:v]remap,format=gbrp[b];'
			. '[%10$d:v]format=gbrp[m];[a][b][m]maskedmerge,format=yuv420p[out]',
			$lenses[0][0], $lenses[0][1], $lenses[1][0], $lenses[1][1], $x0, $y0, $x1, $y1, $lensSize, $mask,
		);
		array_push($command,
			'-filter_threads', '1', '-filter_complex', $filter, '-map', '[out]', '-map', '0:a:0?',
			'-c:v', 'libx264', '-preset', 'veryfast', '-threads', '2', '-x264-params', 'sliced-threads=1:rc-lookahead=0',
			'-b:v', (string)$bitrate,
			'-maxrate', (string)(int)($bitrate * 1.5), '-bufsize', (string)(2 * $bitrate),
			'-c:a', 'copy', '-movflags', '+faststart', '-f', 'mp4', "$root/$name.part.mp4");

		$quoted = implode(' ', array_map('escapeshellarg', $command));
		$base = escapeshellarg("$root/$name");
		// The pid file holds ffmpeg's own pid (nice execs it), so abandon() stops
		// the encoder and not just the shell; the status file appears only once
		// ffmpeg has exited, with its exit code.
		$script = "nice -n 19 $quoted > $base.log 2>&1 & echo \$! > $base.pid; wait \$!; echo \$? > $base.status";
		@unlink("$root/$name.status");
		exec('nohup sh -c ' . escapeshellarg($script) . ' > /dev/null 2>&1 < /dev/null &');

		// Twelve times the clip's length, an hour at least: four cores run at about a fifth of real time.
		return ['name' => $name, 'deadline' => time() + max(3600, (int)(12 * $probe['duration']))];
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
		if (!rename("$base.part.mp4", "$base.mp4")) {
			throw new FormatError('could not move the finished video into place');
		}
		$this->cleanUp($name, false);
		$this->store->dropOthers($fileId, $name);
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
			'-show_entries', 'stream=width,height:format=duration', '-of', 'json', $path])), $out, $code);
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

		return ['streams' => $streams, 'duration' => (float)($info['format']['duration'] ?? 0)];
	}

	/** @return array{Calibration, ?string, array} */
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

		return [$calibration, $model, $orientation];
	}
}
