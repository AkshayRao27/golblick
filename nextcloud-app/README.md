# 360 photo previews for Nextcloud

Shows Insta360 `.insp` photos as panoramas in Nextcloud, and lets you look around them as a sphere. Without it, Nextcloud doesn't recognise `.insp` at all: by default, Files shows a generic icon and Memories leaves them out of the timeline.

## 🚩 Please read this before you proceed

This is barely even an alpha of a fully vibe-coded app, tested on throwaway Nextcloud instances in Docker. Read the [main README's warning](../README.md#-please-read-this-before-you-proceed) first, and try it on a test instance before your real one.

## How it works

The app reads the camera's data from the end of each `.insp` file and renders the preview in plain PHP, using the GD library Nextcloud already requires. It doesn't need the Python tool from this repository, and doesn't run any external programs. The sphere view runs in the browser, using JavaScript that ships with the app. [AGENT-NOTES.md](AGENT-NOTES.md), written mainly for coding agents, has the implementation details: performance, memory use, and how it shares JPEG previews with Nextcloud's own provider.

## What installing it changes

The app needs one line added to Nextcloud's config, which tells Nextcloud that `.insp` files are JPEG images. That is what makes them show up, and it has side effects:

- **Zooming in Memories needed a workaround.** When you zoom past the preview's size, Memories loads the original file, and for a `.insp` that is the two fisheye circles. The app swaps that one image for a full-size panorama, so zooming stays a panorama. It doesn't change the file or what you get when you download it. The first zoom on each photo makes the server render that panorama, which takes up to about 20 seconds on a OneR photo; Memories shows the preview meanwhile, and later zooms take under a second. To make it faster at the cost of detail, set a smaller width (1024 to 4096, default 4096): `occ config:app:set golblick zoom_width --value=2048`. X5 photos stop at 2560, the size of the panorama the camera stores.
- **Files the app can't read go to Nextcloud's normal JPEG preview**, which shows the fisheye pair. On a large photo it may also run out of memory. In the test library this was 6 files out of 1,438, all damaged or exported without the camera's data.

## Viewing a photo as a sphere

A **View as sphere** button opens the photo full-window as a sphere you can drag around, with the mouse wheel or a pinch to zoom. Escape closes it. You'll find it:

- in Files, in a `.insp` file's actions menu
- in the image viewer that Files and Photos open, next to the edit button
- in Memories, in the viewer's top bar

It opens straight away with the preview, then sharpens once the full-size panorama is ready. That's the same image Memories zooms into, so the first time for a photo can take up to about 20 seconds (see above).

The buttons in the image viewer and in Memories are a stopgap. Neither app lets another app add a button, so golblick adds them to the page from outside. If a later version of either app changes its layout, the button may stop appearing until golblick catches up; nothing else breaks. Memories releases after 9.1.0-alpha.2 have their own sphere view. On those, a `.insp` gets Memories' "View panorama" button instead of golblick's once it has been re-indexed (`occ memories:index --force`), and golblick makes that view show the stitched panorama. The button doesn't appear on public share links.

## Requirements, and what's been tested

| | |
|---|---|
| Cameras | Insta360 OneR, X3 and X5 photos (`.insp`). No video yet |
| Nextcloud | 33 to 35. Tested on 33 and 35.0.0; 34 is assumed to work |
| Memories | Tested with 9.0.1 |
| PHP | Tested on 8.4 and 8.5 |
| Server requirements | none beyond what Nextcloud already needs (PHP with GD) |

## What the previews look like

Each preview is a full equirectangular panorama with the horizon levelled. On an X5 the app uses the panorama the camera already made. On a OneR or X3 it builds one from the two lenses and levels it using the camera's motion sensor.

Things close to the camera, within a metre or two, can show a visible break where the two lenses meet, because each lens sees them from a slightly different position. [docs/accuracy.md](../docs/accuracy.md) has the details.

## Using it with files_photospheres

[files_photospheres](https://apps.nextcloud.com/apps/files_photospheres) can be installed alongside this app; tested with 1.33.1 on Nextcloud 33 and 1.35.0 on Nextcloud 35. It doesn't generate previews, so `.insp` thumbnails still come from here. It shows its sphere button only for files that carry panorama metadata, which `.insp` files don't, so it doesn't offer its button for them; use golblick's **View as sphere** instead. Adding the metadata wouldn't help: files_photospheres wraps the downloaded original around the sphere, and for a `.insp` that is the two fisheye circles. A panorama made with `golblick render` does carry the metadata, and files_photospheres opens it as a sphere you can drag around.

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

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
