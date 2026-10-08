<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Http;

use OCP\AppFramework\Http;
use OCP\AppFramework\Http\ICallbackResponse;
use OCP\AppFramework\Http\IOutput;
use OCP\AppFramework\Http\Response;

/**
 * A local file, served with byte ranges, so a <video> element can seek.
 *
 * Browsers fetch video in ranges and refuse to seek in a response that
 * doesn't honour them. One range only (that is all a video element asks for);
 * anything else gets the whole file, and a range past the end gets 416.
 *
 * @template-extends Response<int, array<string, mixed>>
 */
final class RangeFileResponse extends Response implements ICallbackResponse {
	private const CHUNK = 1 << 20;

	private int $start = 0;
	private int $end;

	public function __construct(
		private string $path,
		string $contentType,
		?string $range,
	) {
		parent::__construct();
		$size = (int)filesize($path);
		$this->end = $size - 1;
		$this->addHeader('Content-Type', $contentType);
		$this->addHeader('Accept-Ranges', 'bytes');

		if ($range !== null && preg_match('/^bytes=(\d*)-(\d*)$/', trim($range), $m) && ($m[1] !== '' || $m[2] !== '')) {
			if ($m[1] === '') {
				$start = max(0, $size - (int)$m[2]);   // the last n bytes
				$end = $size - 1;
			} else {
				$start = (int)$m[1];
				$end = $m[2] === '' ? $size - 1 : min((int)$m[2], $size - 1);
			}
			if ($start > $end || $start >= $size) {
				$this->setStatus(Http::STATUS_REQUEST_RANGE_NOT_SATISFIABLE);
				$this->addHeader('Content-Range', "bytes */$size");
				$this->end = -1;

				return;
			}
			$this->start = $start;
			$this->end = $end;
			$this->setStatus(Http::STATUS_PARTIAL_CONTENT);
			$this->addHeader('Content-Range', "bytes $start-$end/$size");
		}
		$this->addHeader('Content-Length', (string)max(0, $this->end - $this->start + 1));
	}

	public function callback(IOutput $output): void {
		if ($this->end < $this->start) {
			return;
		}
		$handle = fopen($this->path, 'rb');
		if ($handle === false) {
			return;
		}
		fseek($handle, $this->start);
		$left = $this->end - $this->start + 1;
		while ($left > 0 && !feof($handle)) {
			$chunk = fread($handle, min(self::CHUNK, $left));
			if ($chunk === false || $chunk === '') {
				break;
			}
			$output->setOutput($chunk);
			$left -= \strlen($chunk);
		}
		fclose($handle);
	}
}
