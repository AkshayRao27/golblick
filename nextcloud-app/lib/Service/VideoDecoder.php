<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Service;

use OCA\Golblick\Insta360\FormatError;
use OCA\Golblick\Insta360\Keyframes;
use OCA\Golblick\Render\Equirectangular;
use OCP\IBinaryFinder;
use OCP\IConfig;
use OCP\ITempManager;

/**
 * Decodes a OneR or X3 video's stored keyframes with ffmpeg.
 *
 * The rest of the app runs no external programs; this is the one exception,
 * and only for the videos of those two cameras. Their opening frame is H.264
 * or HEVC, which PHP cannot decode. It is the same ffmpeg Nextcloud's own
 * video thumbnails use, found the same way (preview_ffmpeg_path, then the
 * binary finder), and without it those videos get no thumbnail while
 * everything else carries on.
 *
 * ffmpeg puts the lenses side by side itself (hstack) and scales them to the
 * size asked for, so PHP only ever holds the finished pair. Files, not pipes:
 * writing a 1.5 MB keyframe into ffmpeg while it writes a 10 MB PNG back can
 * deadlock on full pipe buffers.
 */
final class VideoDecoder {
	/** A keyframe decodes in well under a second; anything near this is stuck. */
	private const TIMEOUT_SECONDS = 60;

	private ?string $binary = null;
	private bool $looked = false;

	public function __construct(
		private IConfig $config,
		private IBinaryFinder $binaryFinder,
		private ITempManager $tempManager,
	) {
	}

	public function binary(): ?string {
		if (!$this->looked) {
			$this->looked = true;
			$configured = $this->config->getSystemValue('preview_ffmpeg_path', null);
			$found = \is_string($configured) ? $configured : $this->binaryFinder->findBinaryPath('ffmpeg');
			$this->binary = \is_string($found) && $found !== '' ? $found : null;
		}

		return $this->binary;
	}

	/**
	 * The lens pair, both fisheyes side by side as in a still, $width wide.
	 *
	 * @throws FormatError when ffmpeg is missing, fails, or the result would not fit in memory
	 */
	public function lensPair(Keyframes $keyframes, int $width): \GdImage {
		$binary = $this->binary();
		if ($binary === null) {
			throw new FormatError('ffmpeg is not installed, and the opening frame of this video needs it');
		}
		$width = max(2, $width - $width % 2);
		$lens = intdiv($width, 2);

		$temporary = [];
		try {
			$command = [$binary, '-v', 'error', '-nostdin', '-y'];
			foreach ($keyframes->streams as $stream) {
				$path = $this->temporaryFile('.' . $keyframes->codec);
				$temporary[] = $path;
				if (file_put_contents($path, $stream) !== \strlen($stream)) {
					throw new FormatError('could not write the keyframe to a temporary file');
				}
				array_push($command, '-f', $keyframes->codec, '-i', $path);
			}
			$filter = $keyframes->layout === Keyframes::LENS_PAIR
				? "[0:v]scale={$lens}:{$lens}:flags=area[a];[1:v]scale={$lens}:{$lens}:flags=area[b];[a][b]hstack"
				: "[0:v]scale={$width}:{$lens}:flags=area";
			$output = $this->temporaryFile('.png');
			$temporary[] = $output;
			array_push($command, '-filter_complex', $filter, '-frames:v', '1', '-f', 'image2', '-c:v', 'png', $output);

			$this->run($command);

			$png = (string)file_get_contents($output);
			Equirectangular::refuseIfTooBigToDecode($png);
			$image = @imagecreatefromstring($png);
			if ($image === false) {
				throw new FormatError('ffmpeg did not produce a readable image');
			}

			return $image;
		} finally {
			foreach ($temporary as $path) {
				@unlink($path);
			}
		}
	}

	/**
	 * One frame of each lens, $at seconds in, scaled to $size square: for
	 * scoring the lens geometry (VideoRenderer::lensGuards), not for display.
	 *
	 * @param list<string> $inputs the clip's files
	 * @param list<array{int, int}> $lenses [input, stream] for lens 0 and lens 1
	 * @return array{\GdImage, \GdImage}
	 * @throws FormatError when ffmpeg is missing or fails
	 */
	public function lensFrames(array $inputs, array $lenses, float $at, int $size): array {
		$binary = $this->binary();
		if ($binary === null) {
			throw new FormatError('ffmpeg is not installed');
		}
		$frames = [];
		$temporary = [];
		try {
			foreach ($lenses as [$input, $stream]) {
				$output = $this->temporaryFile('.png');
				$temporary[] = $output;
				$this->run([$binary, '-v', 'error', '-nostdin', '-y', '-threads', '1',
					'-ss', \sprintf('%.3f', $at), '-i', $inputs[$input], '-map', "0:v:$stream",
					'-frames:v', '1', '-vf', "scale=$size:$size", '-f', 'image2', '-c:v', 'png', $output]);
				$image = @imagecreatefrompng($output);
				if ($image === false) {
					throw new FormatError('ffmpeg did not produce a readable frame');
				}
				$frames[] = $image;
			}
		} finally {
			foreach ($temporary as $path) {
				@unlink($path);
			}
		}

		return [$frames[0], $frames[1]];
	}

	private function temporaryFile(string $suffix): string {
		$path = $this->tempManager->getTemporaryFile($suffix);
		if ($path === false) {
			throw new FormatError('could not create a temporary file');
		}

		return $path;
	}

	/** @param list<string> $command */
	private function run(array $command): void {
		$process = proc_open($command, [1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes);
		if (!\is_resource($process)) {
			throw new FormatError('could not start ffmpeg');
		}
		stream_set_blocking($pipes[1], false);
		stream_set_blocking($pipes[2], false);
		$errors = '';
		$deadline = microtime(true) + self::TIMEOUT_SECONDS;
		while (true) {
			$errors .= (string)stream_get_contents($pipes[2]);
			stream_get_contents($pipes[1]);
			$status = proc_get_status($process);
			if (!$status['running']) {
				break;
			}
			if (microtime(true) > $deadline) {
				proc_terminate($process, 9);
				proc_close($process);
				throw new FormatError('ffmpeg took longer than ' . self::TIMEOUT_SECONDS . ' seconds and was stopped');
			}
			usleep(20000);
		}
		$errors .= (string)stream_get_contents($pipes[2]);
		fclose($pipes[1]);
		fclose($pipes[2]);
		proc_close($process);
		// proc_close() after proc_get_status() has seen the exit returns -1, so take the code from the status.
		if ($status['exitcode'] !== 0) {
			throw new FormatError('ffmpeg could not decode the keyframes: ' . trim(substr($errors, 0, 300)));
		}
	}
}
