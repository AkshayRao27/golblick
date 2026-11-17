# Changelog

The Nextcloud app's changes. Versions before 0.8.1 are in the [releases on GitHub](https://github.com/AkshayRao27/golblick/releases), which also cover the command-line tool and the desktop viewer.

## 0.9.2 - 2026-11-17

### Added

- Files offers **Play as sphere** on any 360° MP4, such as an export from Insta360 Studio, not only on golblick's own copies, and clicking one plays it as a sphere. New uploads are picked up in the background; for videos already on the server, run `occ files:scan --all --generate-metadata=golblick-sphere` once. See [360° videos from other software](README.md#360-videos-from-other-software).

### Changed

- The settings section is now called **Golblick (360° Photos & Videos)**. The personal page groups its choices under two headings, one for opening files in Memories and one for links you share from Memories, and the section headings on both settings pages are now smaller than the page title instead of larger.

### Fixed

- On Nextcloud 33 and 34 the sphere view never worked on a public share link: every request it made failed with a server error, because the app called a method that only exists from Nextcloud 35.
- Links shared from Memories (`/apps/memories/s/…`) now get the sphere button in Memories' viewer, for visitors and signed-in users alike, under the same **Public share links** switch as Files' links. Before, golblick wasn't loaded on those pages at all. A 360° video there opens straight into the sphere by default; the person who shares the link can change that, and the same for photos, on their personal settings page. Memories' album links still get nothing.
- A 360° MP4 on a public share link, such as an export from Insta360 Studio, now plays in the sphere. It used to open as a still picture from its thumbnail.

## 0.9.1 - 2026-11-13

### Added

- The setup check counts the `.insp` photos that Memories hasn't marked as panoramas. Memories 10 and later mark a photo when they index it and don't go back over photos indexed before the upgrade, so those have no "View panorama" until they're re-indexed, and in Memories' Android app that button is the only way to see them as a sphere. The check says which command fixes it.

### Changed

- The personal settings page says its choices apply in a browser. Memories' Android app, from version 1.17, doesn't run golblick's script: photos open as a sphere from Memories' own "View panorama", and videos play flat. See [In the Memories Android app](README.md#in-the-memories-android-app).

## 0.9.0 - 2026-11-01

### Fixed

- X5 videos were stitched with the two lenses' calibrations crossed. An X5 records lens 1 in its first video track, and its files say so; the app now reads that, so each lens's calibration is applied to its own picture. The difference is small, a degree or two in how the copy is levelled. Every clip is stitched once more after the upgrade, newest first, which puts X5 clips near the front; copies from other cameras come out the same. Until an X5 clip's new copy is done, its old copy opens facing backwards and the player steadies it wrongly, and a view you chose on an X5 clip is half a turn out once it's remade.
- After an upgrade that re-stitches clips, the previous copy now keeps playing until the new one is done. Since 0.8 it didn't, unless a copy was saved next to the clip.

### Changed

- Copies stitched on the server's CPU now play without the wobble that fast movement leaves within each frame: the player takes it out as it plays, as the GPU worker does when it stitches. It applies to copies made from this version on, which after the upgrade is every clip as it's stitched again.
- The GPU worker is version 4, which reads which track holds which lens. It restarts on the new version by itself after the upgrade; until it has, X5 clips are stitched on the server's CPU.

## 0.8.1 - 2026-10-26

### Changed

- Works alongside [360 Raw Viewer](https://apps.nextcloud.com/apps/files_360viewer), which registers `.insv` videos as `video/x-insv`. golblick now makes thumbnails for and stitches clips registered that way too, and its setup check no longer offers to replace that registration. With both apps installed, a click on a clip in Files opens 360 Raw Viewer, and golblick's **Play as sphere** is in the clip's actions menu.
- The app's licence is now named `AGPL-3.0-or-later` in its metadata, as the app store requires. The licence itself hasn't changed.
