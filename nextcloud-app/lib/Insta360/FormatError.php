<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Insta360;

/**
 * The file was recognised but could not be parsed.
 *
 * Raised in preference to returning a partial or guessed result: a reader that
 * cannot prove it understood a layout should say so, and the preview provider
 * then declines the file rather than producing a plausible-looking wrong
 * thumbnail.
 */
final class FormatError extends \RuntimeException {
}
