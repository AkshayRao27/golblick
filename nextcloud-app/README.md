# 360 photo previews for Nextcloud

Shows Insta360 `.insp` photos as panoramas in Nextcloud, and lets you look around them as a sphere. Without it, Nextcloud doesn't recognise `.insp` at all: by default, Files shows a generic icon and Memories leaves them out of the timeline. It can also give `.insv` videos a panoramic thumbnail in Files; see [Videos](#videos).

## 🚩 Please read this before you proceed

This is barely even an alpha of a fully vibe-coded app, tested on throwaway Nextcloud instances in Docker. Read the [main README's warning](../README.md#-please-read-this-before-you-proceed) first, and try it on a test instance before your real one.

## How it works

The app reads the camera's data from the end of each `.insp` file and renders the preview in plain PHP, using the GD library Nextcloud already requires. It doesn't need the Python tool from this repository, and doesn't run any external programs, with one exception: thumbnails of OneR and X3 videos need ffmpeg, if you register videos at all. The sphere view runs in the browser, using JavaScript that ships with the app. [AGENT-NOTES.md](AGENT-NOTES.md), written mainly for coding agents, has the implementation details: performance, memory use, and how it shares JPEG previews with Nextcloud's own provider.

## What installing it changes

The app needs one line added to Nextcloud's config, which tells Nextcloud that `.insp` files are JPEG images. That is what makes them show up, and it has side effects:

- **Zooming in Memories needed a workaround.** When you zoom past the preview's size, Memories loads the original file, and for a `.insp` that is the two fisheye circles. The app swaps that one image for a full-size panorama, so zooming stays a panorama. It doesn't change the file or what you get when you download it. The first zoom on each photo makes the server render that panorama, which takes up to about 20 seconds on a OneR photo; Memories shows the preview meanwhile, and later zooms take under a second. To make it faster at the cost of detail, pick a smaller panorama size on the app's settings page (1024 to 4096 pixels wide, default 4096), or have the panoramas rendered ahead of time there. X5 photos stop at 2560, the size of the panorama the camera stores.
- **Files the app can't read go to Nextcloud's normal JPEG preview**, which shows the fisheye pair. On a large photo it may also run out of memory. In the test library this was 6 files out of 1,438, all damaged or exported without the camera's data.

## Videos

Videos are optional. They play from Files, and in Memories once their stitched copies are saved next to the clips (see below).

1. **Register .insv files** in the setup check on the settings page. Each `.insv` then shows a thumbnail of its opening frame as a panorama in Files. An X5 stores that frame stitched; a OneR or X3 stores both lenses' opening frame in the `_00_` file, and decoding it needs ffmpeg, the same program Nextcloud uses for its own video thumbnails.
2. Switch on **Stitch videos in the background** in the Videos section. The server then makes a stitched copy of each clip, newest first, one at a time, with ffmpeg at the lowest priority. Clicking a video in Files plays that copy as a sphere you can look around in while it plays; until it's ready, you see the opening frame. Every file of a clip (`_00_`, `_10_` and the low-resolution `LRV_` copy) plays the same video.

Stitching is slow, needs memory, and the copies are big. At the default 2880 × 1440, each second of video takes about 12 CPU-seconds, a render needs about 1 GB of memory, and the copies take about 5 GB per hour of video; at 3840 × 1920, which you can pick instead, it's 18 CPU-seconds, 1.5 GB and 9 GB. The horizon is levelled once per clip, at its start, so a clip filmed while the camera tilts tilts with it. The camera doesn't match a video's two lenses to each other the way it does for photos, so the stitching evens them out along the seam as the clip plays; where glare has washed one lens out completely, the seam can still show. For each clip it also decides, from a few of its frames, where and how the two lenses meet: on an X3 or X5, which record how far apart their lenses sit, it can line up someone who stays close to the camera, such as whoever is holding it, and on any camera it can move the seam to where the lenses agree. If that doesn't clearly help on frames it didn't choose from, it keeps the plain seam. The copies live in the app's data folder, so this needs the data directory on local disk rather than object storage. Deleting them from the settings page frees the space; with stitching on, they're made again.

To see the videos in Memories, switch on **Save each stitched copy next to its clip**. Each finished copy then moves into the clip's folder as an ordinary MP4 named after the clip, ending in `.360.mp4`, marked as a 360° video the same way Insta360 Studio marks its exports. Memories lists it like any other video, under the day the clip was recorded, and any player that understands 360° video plays it as one. Memories on its own would play it as a flat, stretched rectangle, so by default it opens as a sphere instead. Each user can change that on their personal settings page (see [Settings](#settings)), and the sphere button in Memories' viewer is there either way. Clicking the copy in Files plays it as a sphere. The copies count against that folder's storage and are synced to desktop clients like any other file. Deleting one doesn't bring it back.

## Viewing a photo as a sphere

A **View as sphere** button opens the photo full-window as a sphere you can drag around, with the mouse wheel or a pinch to zoom. Escape closes it. You'll find it:

- in Files, in a `.insp` file's actions menu
- in the image viewer that Files and Photos open, next to the edit button
- in Memories, in the viewer's top bar

It opens straight away with the preview, then sharpens once the full-size panorama is ready. That's the same image Memories zooms into, so the first time for a photo can take up to about 20 seconds (see above).

The buttons in the image viewer and in Memories are a stopgap. Neither app has a way for other apps to add buttons, so golblick inserts them into the page itself. If a later version of either app changes its layout, the button may stop appearing until golblick catches up; nothing else breaks, and each app's button can be switched off on the settings page. Memories releases after 9.1.0-alpha.2 have their own sphere view. On those, a `.insp` gets Memories' "View panorama" button instead of golblick's once it has been re-indexed (`occ memories:index --force`), and golblick makes that view show the stitched panorama.

Visitors to a public share link get the Files and image viewer buttons too, as long as the share lets them see its files and, if it has a password, once they've entered it. The first time someone opens a photo as a sphere the server renders its full-size panorama, so a visitor can make it do that for every `.insp` in a shared folder. If that's a concern, switch it off under **Public share links** on the settings page.

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

- a setup check: whether `.insp` is registered, whether `.insv` videos are (optional) and ffmpeg is installed, GD, PHP's memory limit, whether the Memories zoom fix can attach, and whether ImageMagick can read RAW files (see [Nextcloud AIO and RAW photos](#nextcloud-aio-and-raw-photos))
- the size of the full-size panorama used for zooming and the sphere view, and a button to clear the ones already made
- rendering those panoramas in the background, newest photos first, off by default because it costs about 19 seconds of CPU per OneR photo at full size
- switches for the Memories zoom fix and for each "View as sphere" button, in case an update to Memories or the image viewer breaks one

**Personal settings → Golblick (360° Photos)** lets each user choose what happens when a 360° video or photo opens in Memories. A video can open as a sphere (the default), show flat without playing, or play flat as Memories does on its own. A photo can show flat with the sphere button (the default) or open as a sphere. In the sphere, the left and right arrow keys go on to the previous or next item.

Once `.insp` counts as JPEG, every app that works on photos treats these files as photos too. An app that reads the original file, such as one that runs face or object recognition, gets the two fisheye circles rather than a panorama.

## Reporting a problem, or an untested camera

In Files, a `.insp` file's actions menu has **Report to golblick**. It shows a summary of the file and what the app does with it, without the file's name, its folder or the camera's serial number, and a button that opens an issue on GitHub with the summary filled in, so you only add what you saw. Which issue depends on the camera:

- For the Insta360 OneR, X3 and X5, which golblick has been tested with, it's a [photo problem](https://github.com/AkshayRao27/golblick/issues/new?template=photo-problem.yml): the photo looks wrong or won't open.
- For any other camera, it's an [untested camera](https://github.com/AkshayRao27/golblick/issues/new?template=untested-camera.yml), which is worth reporting whether the photo looks right or not.

The entry is switched on and off together with the Files "View as sphere" entry on the settings page.

## Licence

AGPL-3.0-or-later, like the rest of the repository; the full text is in [COPYING](COPYING).

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
