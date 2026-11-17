/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * Asks Files to fetch golblick's mark on 360 MP4s (lib/Listener/MarkSphericalVideo.php)
 * with every file it lists, so main.ts can offer "Play as sphere" on them.
 *
 * Loaded as an init script, ahead of Files' own code, because Files lists the
 * folder with the properties registered by then; main.ts runs too late for
 * the first listing. Init scripts hold up the page, so this doesn't import
 * @nextcloud/files: its registerDavProperty comes with a WebDAV client, about
 * 50 KB. It adds to the list Files' own init script has already made, in the
 * scope @nextcloud/files 4.0 keeps on window (the version main.ts registers its
 * actions through), and does nothing if that list isn't there.
 */
const SPHERE_PROPERTY = 'nc:metadata-golblick-sphere';

const scope = (window as { _nc_files_scope?: Record<string, { davProperties?: string[] }> })._nc_files_scope?.v4_0;
if (scope?.davProperties && !scope.davProperties.includes(SPHERE_PROPERTY)) {
  scope.davProperties.push(SPHERE_PROPERTY);
}
