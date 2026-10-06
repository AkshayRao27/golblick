<?php

declare(strict_types=1);

/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

namespace OCA\Golblick\Service;

use OCP\App\IAppManager;
use OCP\Files\IMimeTypeDetector;
use OCP\Files\IMimeTypeLoader;
use OCP\IConfig;
use OCP\IDBConnection;
use OCP\Util;

/**
 * What the admin page reports about the install, and the one fix it offers.
 *
 * The install has a manual step that fails silently: without the `.insp`
 * mapping nothing happens at all, and nothing says why. Each check here is a
 * cause that was met for real, not a list of everything that could go wrong.
 */
final class SetupCheck {
	public const MAPPING_FILE = 'mimetypemapping.json';

	/** The renderer refuses frames it cannot decode within the limit; see AGENT-NOTES § Memory. */
	private const COMFORTABLE_MEMORY = 512 * 1024 * 1024;

	public function __construct(
		private IMimeTypeDetector $detector,
		private IMimeTypeLoader $mimeTypes,
		private IDBConnection $db,
		private IAppManager $appManager,
		private IConfig $config,
	) {
	}

	/**
	 * @return list<array{id: string, level: 'ok'|'warn'|'error'|'info', title: string, detail: string}>
	 */
	public function run(): array {
		$checks = [];

		$mapped = $this->detector->detectPath('x.insp') === 'image/jpeg';
		$wrong = $this->inspRows(false);
		if (!$mapped) {
			$checks[] = $this->item('mapping', 'error', '.insp is not mapped to image/jpeg',
				'Nextcloud does not treat .insp files as images, so the app never sees them. "Register .insp files" below adds the mapping to config/' . self::MAPPING_FILE . ' and updates the files Nextcloud already knows about.');
		} elseif ($wrong > 0) {
			$checks[] = $this->item('mapping', 'warn', "$wrong .insp files still have an old file type",
				'The mapping is in place, but these files were indexed before it was. "Register .insp files" updates them.');
		} else {
			$checks[] = $this->item('mapping', 'ok', '.insp files are treated as images',
				$this->inspRows(true) . ' .insp files are known to Nextcloud.');
		}

		$gd = function_exists('gd_info') ? gd_info() : [];
		$checks[] = ($gd['JPEG Support'] ?? false)
			? $this->item('gd', 'ok', 'PHP has GD (Graphics Draw) with JPEG support', (string)($gd['GD Version'] ?? ''))
			: $this->item('gd', 'error', 'PHP has no GD (Graphics Draw) with JPEG support', 'The app requires GD for rendering JPEG previews.');

		$limit = Util::computerFileSize((string)ini_get('memory_limit'));
		if ($limit === false || $limit < 0 || $limit >= self::COMFORTABLE_MEMORY) {
			$checks[] = $this->item('memory', 'ok', 'PHP memory limit: ' . ini_get('memory_limit'), 'Measured for the web server where previews are rendered.');
		} else {
			$checks[] = $this->item('memory', 'warn', 'PHP memory limit: ' . ini_get('memory_limit'),
				'Most previews need little memory, but a photo that has to be rendered from its full-resolution frame needs up to about 300 MB on a 72-megapixel camera. 512M or more avoids such files being refused and falling back to displaying a fisheye pair (rather than crashing).');
		}

		$checks[] = $this->memoriesCheck();

		if (extension_loaded('imagick')) {
			// Asking for the format list is safe without the RAW coder (it
			// returns nothing); reading a DNG is what crashes. Measured.
			$raw = count(\Imagick::queryFormats('DNG')) > 0;
			$checks[] = $raw
				? $this->item('imagick_raw', 'ok', 'ImageMagick can read RAW files', 'golblick doesn\'t use ImageMagick itself, but an Insta360 camera shooting RAW, for example, saves a DNG next to each .insp, and Memories and Camera RAW Previews open those with ImageMagick. Without its RAW coder, ImageMagick crashes the PHP process on a DNG.')
				: $this->item('imagick_raw', 'warn', 'ImageMagick cannot read RAW files',
					'golblick doesn\'t use ImageMagick itself, but an Insta360 camera shooting RAW, for example, saves a DNG next to each .insp, and Memories and Camera RAW Previews open those with ImageMagick. On some systems, including Nextcloud AIO, ImageMagick without its RAW coder crashes the PHP process on a DNG. On AIO, set NEXTCLOUD_ADDITIONAL_APKS to "imagemagick imagemagick-raw". You can ignore this if you keep no RAW files.');
		}

		$x = $this->config->getSystemValueInt('preview_max_x', 4096);
		$y = $this->config->getSystemValueInt('preview_max_y', 4096);
		$checks[] = $this->item('preview_max', 'info', "Nextcloud's preview size limit: {$x} × {$y}",
			'Thumbnails and the Files viewer are limited to the size set in config.php (preview_max_x, preview_max_y). Zooming in Memories and the sphere view use the full-size panorama below instead.');

		return $checks;
	}

	/**
	 * Adds the mapping (keeping whatever else the file holds) and updates the
	 * .insp files already in the file cache.
	 *
	 * ⚠️ `\OC::$configDir` is private API. It is the directory core reads the
	 * mapping from (OC\Files\Type\Detection), and the Maps app writes the same
	 * file the same way. There is no public equivalent.
	 *
	 * @return array{written: bool, rows: int}
	 */
	public function register(): array {
		$dir = rtrim((string)\OC::$configDir, '/');
		$path = $dir . '/' . self::MAPPING_FILE;

		$map = [];
		if (file_exists($path)) {
			$map = json_decode((string)file_get_contents($path), true);
			if (!is_array($map)) {
				throw new \RuntimeException("config/" . self::MAPPING_FILE . " exists but is not valid JSON. Fix it manually; it was left untouched.");
			}
		}

		$written = false;
		if (isset($map['insp'])) {
			if (($map['insp'][0] ?? null) !== 'image/jpeg') {
				throw new \RuntimeException('config/' . self::MAPPING_FILE . ' already maps .insp to ' . json_encode($map['insp'], JSON_UNESCAPED_SLASHES) . '. Change it manually if you want this app to handle them; it was left untouched.');
			}
		} else {
			if (!is_writable(file_exists($path) ? $path : $dir)) {
				throw new \RuntimeException("The web server cannot write to config/" . self::MAPPING_FILE . '. Add "insp": ["image/jpeg"] to it manually.');
			}
			$map['insp'] = ['image/jpeg'];
			$tmp = $path . '.golblick-' . bin2hex(random_bytes(4));
			if (file_put_contents($tmp, json_encode($map, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n") === false || !rename($tmp, $path)) {
				@unlink($tmp);
				throw new \RuntimeException('Could not write config/' . self::MAPPING_FILE . '.');
			}
			$written = true;
		}

		$rows = $this->mimeTypes->updateFilecache('insp', $this->mimeTypes->getId('image/jpeg'));

		return ['written' => $written, 'rows' => $rows];
	}

	/**
	 * .insp files in users' files (not trash, versions or app data), either
	 * those already typed image/jpeg or those that are not.
	 */
	public function inspRows(bool $asJpeg): int {
		$jpeg = $this->mimeTypes->getId('image/jpeg');
		$qb = $this->db->getQueryBuilder();
		$qb->select($qb->func()->count('fileid'))
			->from('filecache')
			->where($qb->expr()->iLike('name', $qb->createNamedParameter('%.insp')))
			->andWhere($qb->expr()->like('path', $qb->createNamedParameter('files/%')))
			->andWhere($asJpeg
				? $qb->expr()->eq('mimetype', $qb->createNamedParameter($jpeg))
				: $qb->expr()->neq('mimetype', $qb->createNamedParameter($jpeg)));
		$result = $qb->executeQuery();
		$count = (int)$result->fetchOne();
		$result->closeCursor();

		return $count;
	}

	private function memoriesCheck(): array {
		if (!$this->appManager->isEnabledForAnyone('memories')) {
			return $this->item('memories', 'info', 'Memories is not enabled', 'The zoom fix only applies to Memories. Files and Photos work without it.');
		}
		$version = $this->appManager->getAppVersion('memories');
		$class = 'OCA\Memories\Controller\ImageController';
		if (class_exists($class) && method_exists($class, 'decodable')) {
			return $this->item('memories', 'ok', "Memories $version: the zoom fix can attach",
				'Zooming in Memories shows the panorama instead of the fisheye pair.');
		}

		return $this->item('memories', 'warn', "Memories $version: the zoom fix cannot attach",
			"This Memories version no longer has the class or method the fix looks for ($class::decodable), so zooming in shows the fisheye pair. Previews are not affected.");
	}

	/** @return array{id: string, level: 'ok'|'warn'|'error'|'info', title: string, detail: string} */
	private function item(string $id, string $level, string $title, string $detail): array {
		return ['id' => $id, 'level' => $level, 'title' => $title, 'detail' => $detail];
	}
}
