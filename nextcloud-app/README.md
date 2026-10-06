# 360 photo previews for Nextcloud

Shows Insta360 `.insp` photos as panoramas in Nextcloud, and lets you look around them as a sphere. Without it, Nextcloud doesn't recognise `.insp` at all: by default, Files shows a generic icon and Memories leaves them out of the timeline.

## 🚩 Please read this before you proceed

This is barely even an alpha of a fully vibe-coded app, tested on throwaway Nextcloud instances in Docker. Read the [main README's warning](../README.md#-please-read-this-before-you-proceed) first, and try it on a test instance before your real one.

## How it works

The app reads the camera's data from the end of each `.insp` file and renders the preview in plain PHP, using the GD library Nextcloud already requires. It doesn't need the Python tool from this repository, and doesn't run any external programs. The sphere view runs in the browser, using JavaScript that ships with the app. [AGENT-NOTES.md](AGENT-NOTES.md), written mainly for coding agents, has the implementation details: performance, memory use, and how it shares JPEG previews with Nextcloud's own provider.

## What installing it changes

The app needs one line added to Nextcloud's config, which tells Nextcloud that `.insp` files are JPEG images. That is what makes them show up, and it has side effects:

- **Zooming in Memories needed a workaround.** When you zoom past the preview's size, Memories loads the original file, and for a `.insp` that is the two fisheye circles. The app swaps that one image for a full-size panorama, so zooming stays a panorama. It doesn't change the file or what you get when you download it. The first zoom on each photo makes the server render that panorama, which takes up to about 20 seconds on a OneR photo; Memories shows the preview meanwhile, and later zooms take under a second. To make it faster at the cost of detail, pick a smaller panorama size on the app's settings page (1024 to 4096 pixels wide, default 4096), or have the panoramas rendered ahead of time there. X5 photos stop at 2560, the size of the panorama the camera stores.
- **Files the app can't read go to Nextcloud's normal JPEG preview**, which shows the fisheye pair. On a large photo it may also run out of memory. In the test library this was 6 files out of 1,438, all damaged or exported without the camera's data.

## Viewing a photo as a sphere

A **View as sphere** button opens the photo full-window as a sphere you can drag around, with the mouse wheel or a pinch to zoom. Escape closes it. You'll find it:

- in Files, in a `.insp` file's actions menu
- in the image viewer that Files and Photos open, next to the edit button
- in Memories, in the viewer's top bar

It opens straight away with the preview, then sharpens once the full-size panorama is ready. That's the same image Memories zooms into, so the first time for a photo can take up to about 20 seconds (see above).

The buttons in the image viewer and in Memories are a stopgap. Neither app has a way for other apps to add buttons, so golblick inserts them into the page itself. If a later version of either app changes its layout, the button may stop appearing until golblick catches up; nothing else breaks, and each app's button can be switched off on the settings page. Memories releases after 9.1.0-alpha.2 have their own sphere view. On those, a `.insp` gets Memories' "View panorama" button instead of golblick's once it has been re-indexed (`occ memories:index --force`), and golblick makes that view show the stitched panorama. The button doesn't appear on public share links.

## Requirements, and what's been tested

| | |
|---|---|
| Cameras | Insta360 OneR, X3 and X5 photos (`.insp`). No video yet |
| Nextcloud | 33 to 35. Tested on 33 and 35.0.0; 34 is assumed to work |
| Memories | Tested with 9.0.1 |
| PHP | Tested on 8.4 and 8.5 |
| Server setups | Tested on the official `nextcloud` Docker image (Debian, Apache with PHP built in) and on a local copy of Nextcloud AIO v14.2.0 (Alpine, PHP-FPM) running the same images as a real AIO install. On AIO, read the note below if you keep RAW photos |
| Server requirements | none beyond what Nextcloud already needs (PHP with GD) |

### Nextcloud AIO and RAW photos

AIO installs ImageMagick without RAW support, and that build crashes on DNG files instead of refusing them: the PHP process reading the file dies. In my testing, opening a DNG in the Memories viewer crashed it every time. This happens with or without golblick, but you'll notice it sooner with golblick installed: when an Insta360 camera shoots in RAW it saves a DNG next to each `.insp`, so browsing your 360 photos in Memories leads you straight to them.

The fix is to add the `imagemagick-raw` package. In AIO that's the `NEXTCLOUD_ADDITIONAL_APKS` setting on the mastercontainer, as described in [AIO's documentation](https://github.com/nextcloud/all-in-one#how-to-add-os-packages-permanently-to-the-nextcloud-container). It defaults to `imagemagick`, so set it to `imagemagick imagemagick-raw`. With that package installed, DNG and NEF files open in Memories and get previews, and nothing has crashed since.

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

2. Tell Nextcloud that `.insp` is a JPEG. The easiest way is **Administration settings → Golblick (360° Photos) → Register .insp files**. It adds this to `config/mimetypemapping.json`, keeping anything else already in the file, and updates the `.insp` files Nextcloud already knows about:

   ```json
   {
       "insp": ["image/jpeg"]
   }
   ```

   To do it manually instead, add those lines to the file (create it if it doesn't exist), then run `occ maintenance:mimetype:update-db --repair-filecache`. That command goes through every file Nextcloud knows about, so on a large instance it can take a while.

   Without the mapping, nothing changes. Some apps (Nextcloud's own Maps app, for example) write this file as soon as they're installed. golblick only writes it when you click the button, so nothing in your config changes without you seeing it.

3. Check the rest of the setup on the same settings page. It lists anything that would stop the app working.

4. If you use Memories, run `occ memories:index` so the photos appear in the timeline straight away, rather than at its next background run.

Previews are generated the first time each photo is viewed, or ahead of time if you run Preview Generator. Each takes about half a second.

## Settings

**Administration settings → Golblick (360° Photos)** has:

- a setup check: whether `.insp` is registered, GD, PHP's memory limit, whether the Memories zoom fix can attach, and whether ImageMagick can read RAW files (see [Nextcloud AIO and RAW photos](#nextcloud-aio-and-raw-photos))
- the size of the full-size panorama used for zooming and the sphere view, and a button to clear the ones already made
- rendering those panoramas in the background, newest photos first, off by default because it costs about 19 seconds of CPU per OneR photo at full size
- switches for the Memories zoom fix and for each "View as sphere" button, in case an update to Memories or the image viewer breaks one

Once `.insp` counts as JPEG, every app that works on photos treats these files as photos too. An app that reads the original file, such as one that runs face or object recognition, gets the two fisheye circles rather than a panorama.

## Licence

AGPL-3.0-or-later, like the rest of the repository; the full text is in [COPYING](COPYING).

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
