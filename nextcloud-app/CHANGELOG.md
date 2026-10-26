# Changelog

The Nextcloud app's changes. Versions before 0.8.1 are in the [releases on GitHub](https://github.com/AkshayRao27/golblick/releases), which also cover the command-line tool and the desktop viewer.

## [Unreleased]

## 0.8.1 - 2026-10-26

### Changed

- Works alongside [360 Raw Viewer](https://apps.nextcloud.com/apps/files_360viewer), which registers `.insv` videos as `video/x-insv`. golblick now makes thumbnails for and stitches clips registered that way too, and its setup check no longer offers to replace that registration. With both apps installed, a click on a clip in Files opens 360 Raw Viewer, and golblick's **Play as sphere** is in the clip's actions menu.
- The app's licence is now named `AGPL-3.0-or-later` in its metadata, as the app store requires. The licence itself hasn't changed.
