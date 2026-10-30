# Changelog

The Nextcloud app's changes. Versions before 0.8.1 are in the [releases on GitHub](https://github.com/AkshayRao27/golblick/releases), which also cover the command-line tool and the desktop viewer.

## [Unreleased]

### Fixed

- X5 videos were stitched with the two lenses' calibrations crossed. An X5 records lens 1 in its first video track, and its files say so; the app now reads that, so each lens's calibration is applied to its own picture. The difference is small, a degree or two in how the copy is levelled. Every clip is stitched once more after the upgrade, newest first, which puts X5 clips near the front; copies from other cameras come out the same. Until an X5 clip's new copy is done, its old copy opens facing backwards and the player steadies it wrongly, and a view you chose on an X5 clip is half a turn out once it's remade.
- After an upgrade that re-stitches clips, the previous copy now keeps playing until the new one is done. Since 0.8 it didn't, unless a copy was saved next to the clip.

### Changed

- The GPU worker is version 4, which reads which track holds which lens. It restarts on the new version by itself after the upgrade; until it has, X5 clips are stitched on the server's CPU.

## 0.8.1 - 2026-10-26

### Changed

- Works alongside [360 Raw Viewer](https://apps.nextcloud.com/apps/files_360viewer), which registers `.insv` videos as `video/x-insv`. golblick now makes thumbnails for and stitches clips registered that way too, and its setup check no longer offers to replace that registration. With both apps installed, a click on a clip in Files opens 360 Raw Viewer, and golblick's **Play as sphere** is in the clip's actions menu.
- The app's licence is now named `AGPL-3.0-or-later` in its metadata, as the app store requires. The licence itself hasn't changed.
