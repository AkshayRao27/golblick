<?php

declare(strict_types=1);

// SPDX-License-Identifier: AGPL-3.0-or-later

namespace OCA\Golblick\Render;

/**
 * GPano metadata for a panorama the app serves, so a viewer that reads it
 * opens where someone chose (ViewStore). gpano.py in the library writes the
 * same fields for the CLI.
 *
 * Memories' sphere view is Photo Sphere Viewer, which reads the XMP from the
 * image itself and starts at InitialViewHeadingDegrees and
 * InitialViewPitchDegrees when both are there (5.15: getXmpData, and the
 * initial position only when neither is missing). It takes the heading as a
 * turn from the middle of the image to the right, as ViewStore's longitude
 * is. The field of view is left out: it's horizontal there and vertical in
 * golblick's viewer, and converting needs the window's shape.
 */
final class Gpano {
	private const NAMESPACE = "http://ns.adobe.com/xap/1.0/\0";

	/** $jpeg with an XMP segment saying it's a full equirectangular sphere that opens at $longitude, $latitude. */
	public static function withInitialView(string $jpeg, float $longitude, float $latitude): string {
		if (!str_starts_with($jpeg, "\xFF\xD8") || !function_exists('getimagesizefromstring')) {
			return $jpeg;
		}
		$size = @getimagesizefromstring($jpeg);
		if ($size === false) {
			return $jpeg;
		}
		[$width, $height] = $size;
		$heading = fmod(fmod($longitude, 360.0) + 360.0, 360.0);
		$xmp = '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
			. '<rdf:Description rdf:about="" xmlns:GPano="http://ns.google.com/photos/1.0/panorama/">'
			. '<GPano:ProjectionType>equirectangular</GPano:ProjectionType>'
			. '<GPano:UsePanoramaViewer>True</GPano:UsePanoramaViewer>'
			. sprintf('<GPano:FullPanoWidthPixels>%d</GPano:FullPanoWidthPixels>', $width)
			. sprintf('<GPano:FullPanoHeightPixels>%d</GPano:FullPanoHeightPixels>', $height)
			. sprintf('<GPano:CroppedAreaImageWidthPixels>%d</GPano:CroppedAreaImageWidthPixels>', $width)
			. sprintf('<GPano:CroppedAreaImageHeightPixels>%d</GPano:CroppedAreaImageHeightPixels>', $height)
			. '<GPano:CroppedAreaLeftPixels>0</GPano:CroppedAreaLeftPixels>'
			. '<GPano:CroppedAreaTopPixels>0</GPano:CroppedAreaTopPixels>'
			. sprintf('<GPano:InitialViewHeadingDegrees>%.2F</GPano:InitialViewHeadingDegrees>', $heading)
			. sprintf('<GPano:InitialViewPitchDegrees>%.2F</GPano:InitialViewPitchDegrees>', $latitude)
			. '</rdf:Description></rdf:RDF></x:xmpmeta>';
		$segment = "\xFF\xE1" . pack('n', 2 + \strlen(self::NAMESPACE) + \strlen($xmp)) . self::NAMESPACE . $xmp;

		// After the JFIF segment, if there is one: some readers expect it first.
		$at = 2;
		if (substr($jpeg, 2, 2) === "\xFF\xE0") {
			$at = 4 + unpack('n', substr($jpeg, 4, 2))[1];
		}

		return substr($jpeg, 0, $at) . $segment . substr($jpeg, $at);
	}
}
