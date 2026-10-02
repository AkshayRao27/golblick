# 360 photo previews for Nextcloud

Shows Insta360 `.insp` photos as panoramas in Nextcloud. Without it, Nextcloud doesn't recognise `.insp` at all: by default, Files shows a generic icon and Memories leaves them out of the timeline.

## 🚩 Please read this before you proceed

This is barely even an alpha of a fully vibe-coded app, tested on throwaway Nextcloud instances in Docker. Read the [main README's warning](../README.md#-please-read-this-before-you-proceed) first, and try it on a test instance before your real one.

## How it works

The app reads the camera's data from the end of each `.insp` file and renders the preview in plain PHP, using the GD library Nextcloud already requires. It doesn't need the Python tool from this repository, and doesn't run any external programs. [AGENT-NOTES.md](AGENT-NOTES.md), written mainly for coding agents, has the implementation details: performance, memory use, and how it shares JPEG previews with Nextcloud's own provider.

## What installing it changes

The app needs one line added to Nextcloud's config, which tells Nextcloud that `.insp` files are JPEG images. That is what makes them show up, and it has side effects:

- **Zooming in Memories shows the two fisheye circles.** When you zoom past the preview's resolution, Memories loads the original file, and the original is the lens pair, not a panorama. Seen with Memories 8.1.0 from the app store. A fix for Memories is written and works on a test instance, but it isn't in any release yet.
- **No interactive sphere view.** The previews are flat panoramas, and Memories shows no panorama button for `.insp` files. A sphere viewer for Memories is written too, in the same state as the zoom fix. Both also need Memories to learn that `.insp` files are panoramas, which nothing tells it yet.
- **Files the app can't read go to Nextcloud's normal JPEG preview**, which shows the fisheye pair. On a large photo it may also run out of memory. In the test library this was 6 files out of 1,438, all damaged or exported without the camera's data.

## Requirements, and what's been tested

| | |
|---|---|
| Cameras | Insta360 OneR, X3 and X5 photos (`.insp`). No video yet |
| Nextcloud | 33 to 35. Tested on 33 and 35; 34 is assumed to work |
| Server requirements | none beyond what Nextcloud already needs (PHP with GD) |

## What the previews look like

Each preview is a full equirectangular panorama with the horizon levelled. On an X5 the app uses the panorama the camera already made. On a OneR or X3 it builds one from the two lenses and levels it using the camera's motion sensor.

Things close to the camera, within a metre or two, can show a visible break where the two lenses meet, because each lens sees them from a slightly different position. [docs/accuracy.md](../docs/accuracy.md) has the details.

## Using it with files_photospheres

[files_photospheres](https://apps.nextcloud.com/apps/files_photospheres) can be installed alongside this app; tested together on Nextcloud 33. It doesn't generate previews, so `.insp` thumbnails still come from here. It opens a JPEG as a sphere only when the file carries panorama metadata, which `.insp` files don't, so clicking a `.insp` in Files opens the normal image viewer showing the flat panorama preview. A panorama made with `golblick render` does carry that metadata, and files_photospheres opens it as a sphere you can drag around.

## Install

1. Copy this folder into your Nextcloud's `custom_apps/` directory as `golblick`, and enable it:

   ```sh
   occ app:enable golblick
   ```

2. Tell Nextcloud that `.insp` is a JPEG. Add this to `config/mimetypemapping.json`, creating the file if it doesn't exist, or merging it in if it does:

   ```json
   {
       "insp": ["image/jpeg"]
   }
   ```

   Without it, nothing changes. Some apps (Nextcloud's own Maps app, for example) write this file for you when they're installed. golblick doesn't, so that nothing in your config changes without you seeing it.

3. Update the file types of files Nextcloud already knows about:

   ```sh
   occ maintenance:mimetype:update-db --repair-filecache
   occ files:scan --all          # only needed for files already indexed
   ```
   Both commands work through every file Nextcloud knows about, so on a large instance they can take a while.

4. If you use Memories, run `occ memories:index` so the photos appear in the timeline straight away, rather than at its next background run.

Previews are generated the first time each photo is viewed, or ahead of time if you run Preview Generator. Each takes about half a second.

Once `.insp` counts as JPEG, every app that works on photos treats these files as photos too. An app that reads the original file, such as one that runs face or object recognition, gets the two fisheye circles rather than a panorama.

## Licence

AGPL-3.0-or-later, like the rest of the repository; the full text is in [COPYING](COPYING).
