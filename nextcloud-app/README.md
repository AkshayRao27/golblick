# 360 photos and videos for Nextcloud

Shows Insta360 `.insp` photos as panoramas in Nextcloud, and lets you look around them as a sphere. Without it, Nextcloud doesn't recognise `.insp` at all: by default, Files shows a generic icon and Memories leaves them out of the timeline.

Videos are optional. Switched on, the server stitches each `.insv` clip into an ordinary 360° MP4 in the background, plays it as a sphere steadied by the camera's motion sensor, and can put it in Memories' timeline. See [Videos](#videos).

## 🚩 Please read this before you proceed

This is an alpha of a fully vibe-coded app. Read the [main README's warning](../README.md#-please-read-this-before-you-proceed) first, and try it on a test instance before your real one.

It has been tested on test instances in Docker: the official `nextcloud` image, and a copy of Nextcloud AIO running the same images as a real install. The photo side has also been running on my own Nextcloud AIO server since version 0.1.0. Video support is newer: it ran on the test instances first, and on my server since 0.5.0.

## What installing it changes

The app needs one line added to Nextcloud's config, which tells Nextcloud that `.insp` files are JPEG images. That is what makes them show up, and it has side effects:

- **Zooming in Memories needed a workaround.** When you zoom past the preview's size, Memories loads the original file, and for a `.insp` that is the two fisheye circles. The app swaps that one image for a full-size panorama, so zooming stays a panorama. It doesn't change the file or what you get when you download it. The first zoom on each photo makes the server render that panorama, which takes up to about 20 seconds on a OneR photo; Memories shows the preview meanwhile, and later zooms take under a second. To make it faster at the cost of detail, pick a smaller panorama size on the app's settings page (1024 to 4096 pixels wide, default 4096), or have the panoramas rendered ahead of time there. X5 photos stop at 2560, the size of the panorama the camera stores.
- **Every app that works on photos treats `.insp` as a photo.** An app that reads the original file, such as one that runs face or object recognition, gets the two fisheye circles rather than a panorama.
- **Files the app can't read go to Nextcloud's normal JPEG preview**, which shows the fisheye pair. On a large photo it may also run out of memory. In the test library this was 6 files out of 1,438, all damaged or exported without the camera's data.

## Requirements, and what's been tested

| | |
|---|---|
| Cameras | Insta360 OneR, X3 and X5: photos (`.insp`) and videos (`.insv`) |
| Nextcloud | 33 to 35. Photos tested on 33 and 35.0.0, videos on 35.0.0; 34 is assumed to work |
| Memories | Tested with 9.0.1 and 10.0.0 |
| PHP | Tested on 8.4 and 8.5 |
| Server setups | Tested on the official `nextcloud` Docker image (Debian, Apache with PHP built in) and on Nextcloud AIO v14.2.0 (Alpine, PHP-FPM). On AIO, read [the note on RAW photos](#nextcloud-aio-and-raw-photos) |
| For photos | Nothing beyond what Nextcloud already needs (PHP with GD) |
| For videos | ffmpeg on the server: Nextcloud AIO has it, the official Docker image doesn't. Background jobs set to **Cron** (AIO already is), since stitching runs as a background job; see [Nextcloud's background jobs documentation](https://docs.nextcloud.com/server/latest/admin_manual/configuration_server/background_jobs_configuration.html). The data directory on local disk, not object storage. About 1 GB of free memory while a clip is being stitched |
| For steady downloads | Optional: an NVIDIA GPU, Docker Compose and NVIDIA's container toolkit. See [Steady copies, with a GPU](#steady-copies-with-a-gpu) |

## Install

1. Download `golblick-nextcloud-<version>.tar.gz` from the newest release on the [releases page](https://github.com/AkshayRao27/golblick/releases), unpack it into your Nextcloud's `custom_apps/` folder, which creates `custom_apps/golblick`, and enable it. `occ` is Nextcloud's command-line tool, run as the web server's user from the Nextcloud folder; in the official Docker image, that's `docker exec --user www-data <container> php occ`.

   ```sh
   tar -xzf golblick-nextcloud-<version>.tar.gz -C /path/to/nextcloud/custom_apps
   chown -R www-data:www-data /path/to/nextcloud/custom_apps/golblick
   sudo -u www-data php occ app:enable golblick
   ```

   On Nextcloud AIO, the apps folder lives inside a container, so run these on the host instead:

   ```sh
   sudo docker exec -i nextcloud-aio-nextcloud tar -xzf - -C /var/www/html/custom_apps < golblick-nextcloud-<version>.tar.gz
   sudo docker exec nextcloud-aio-nextcloud chown -R www-data:www-data /var/www/html/custom_apps/golblick
   sudo docker exec --user www-data nextcloud-aio-nextcloud php occ app:enable golblick
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

To upgrade, replace the `custom_apps/golblick` folder with the one from the newer archive and run `occ upgrade`.

## Viewing a photo as a sphere

A **View as sphere** button opens the photo full-window as a sphere you can drag around, with the mouse wheel or a pinch to zoom. Escape closes it. You'll find it:

- in Files, in a `.insp` file's actions menu
- in the image viewer that Files and Photos open, next to the edit button
- in Memories, in the viewer's top bar

It opens straight away with the preview, then sharpens once the full-size panorama is ready. That's the same image Memories zooms into, so the first time for a photo can take up to about 20 seconds (see above).

The buttons in the image viewer and in Memories are a stopgap. Neither app has a way for other apps to add buttons, so golblick inserts them into the page itself. If a later version of either app changes its layout, the button may stop appearing until golblick catches up; nothing else breaks, and each app's button can be switched off on the settings page. Memories 10 has its own sphere view. On those, a `.insp` gets Memories' "View panorama" button instead of golblick's once it has been re-indexed (`occ memories:index --force`), and golblick makes that view show the stitched panorama.

Visitors to a public share link get the Files and image viewer buttons too, as long as the share lets them see its files and, if it has a password, once they've entered it. The first time someone opens a photo as a sphere the server renders its full-size panorama, so a visitor can make it do that for every `.insp` in a shared folder. If that's a concern, switch it off under **Public share links** on the settings page.

## Videos

Each step is a switch on **Administration settings → Golblick (360° Photos)**, and each one builds on the one before. Stop at whichever step gives you what you want.

1. **Register .insv files**, in the setup check. Each `.insv` then shows a thumbnail of its opening frame as a panorama in Files. An X5 stores that frame stitched; a OneR or X3 stores both lenses' opening frame in the `_00_` file, and decoding it needs ffmpeg.
2. **Stitch videos in the background**, in the Videos section. The server makes a stitched copy of each clip, newest first, one at a time, with ffmpeg at the lowest priority. Clicking a video in Files then plays that copy as a sphere you can look around in while it plays; until it's ready, you see the opening frame. Every file of a clip (`_00_`, `_10_` and the low-resolution `LRV_` copy) plays the same video.
3. **Save each stitched copy next to its clip**, to see the videos in Memories. See [In Memories](#in-memories).
4. Optionally, **Bake steadying into each copy**, so the copies play steady in any player and when downloaded. That needs a GPU; see [Steady copies, with a GPU](#steady-copies-with-a-gpu).

### Stitching

Stitching is slow, needs memory, and the copies are big. At the default 2880 × 1440, each second of video takes about 12 CPU-seconds, so a five-minute clip takes 15 minutes or more on four cores. A render needs about 1 GB of memory, and the copies take about 5 GB per hour of video. At 3840 × 1920, which you can pick under **Video size**, it's 18 CPU-seconds, 1.5 GB and 9 GB. 3840 looks sharper but is harder to play: in Firefox decoding video on the CPU, the sphere player managed about 19 frames a second of a 30 fps copy, against about 25 at 2880.

The camera doesn't match a video's two lenses to each other the way it does for photos, so the stitching evens them out along the seam as the clip plays; where glare has washed one lens out completely, the seam can still show. For each clip it also decides, from a few of its frames, where and how the two lenses meet: on an X3 or X5, which record how far apart their lenses sit, it can line up someone who stays close to the camera, such as whoever is holding it, and on any camera it can move the seam to where the lenses agree. If that doesn't clearly help on frames it didn't choose from, it keeps the plain seam.

The copies live in the app's data folder until they're saved next to their clips. **Delete stitched videos** frees the space; with stitching on, they're made again.

### Steadying

The sphere player steadies the video as it plays, from the camera's own motion sensor: the horizon stays level, and the view follows where the camera turns without the shake. The server works out the steadying the first time a clip is played, in a fraction of a second (about 3 seconds for a 30-minute clip). Two buttons in the player's controls change it: one switches steadying off, for the camera's own movement, and the other locks the direction, so the view keeps facing where the video opens instead of turning with the camera, like Direction Lock in Insta360 Studio. It doesn't remove the wobble that fast movement leaves within a single frame. Copies saved next to their clips are steadied too, as long as the clip is still beside them, and so are videos on public share links.

To turn each frame by the right amount in every browser, each stitched copy carries its frame numbers in a thin strip along the bottom edge. The player never shows it, but played flat it shows as a flickering line along the bottom, and in another 360° player as a small spot straight below the camera. Thumbnails of the copies saved next to their clips leave it out.

### In Memories

With **Save each stitched copy next to its clip** on, each finished copy moves into the clip's folder as an ordinary MP4 named after the clip, ending in `.360.mp4`, marked as a 360° video the same way Insta360 Studio marks its exports. Memories lists it like any other video, under the day the clip was recorded, and any player that understands 360° video, such as [VLC](https://www.videolan.org/vlc/), plays it as one. Memories on its own would play it as a flat, stretched rectangle, so by default it opens as a sphere instead. Each user can change that on their personal settings page (see [Settings](#settings)), and the sphere button in Memories' viewer is there either way. Clicking the copy in Files plays it as a sphere.

The copies count against that folder's storage, about 125 MB for every GB of clips at 2880 wide and 220 MB at 3840, and are synced to desktop clients like any other file. On Windows and macOS, Insta360's own software plays the clips, so a desktop there doesn't need the copies: add `*.360.mp4` to the client's ignored files (**Edit Ignored Files** in the client's settings). A client that uses virtual files, as the macOS one does by default, only downloads a copy if it's opened. Insta360 has no software for Linux, so on a Linux desktop the copies are the way to watch the clips.

When a copy is made again, the old one is replaced without being kept as a file version. Deleting a copy doesn't bring it back. To remove them all, use **Delete copies saved next to clips** in the Videos section: they go to the trash bin, and with stitching and saving still on they're made again. Changing the video size doesn't need it: each clip is stitched again at the new size and its copy replaced, and the old one plays until then.

### Steady copies, with a GPU

The copies can also have the steadying baked in, so they play steady in any app and when downloaded, the way Insta360 Studio's stabilised exports do. That needs a GPU, which Nextcloud's PHP can't use, so a small worker does it in a container of its own next to Nextcloud. It runs from the app's `worker/` folder in the image of the Memories transcoder (`radialapps/go-vod`), which already has ffmpeg with OpenCL and NVIDIA's video encoder, and it needs only the GPU and the app's video folder. It has been tried with NVIDIA cards only.

1. Install NVIDIA's container toolkit and set it up for Docker (`nvidia-ctk runtime configure --runtime=docker`), as described in [NVIDIA's install guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
2. Open the Videos section of the app's settings page. Under **Set up the GPU worker**, it shows a `compose.yaml` with this server's folders filled in.
   - On Nextcloud AIO, if you gave the mastercontainer `NEXTCLOUD_DATADIR`, put the same line in a file named `.env` next to `compose.yaml`.
   - Elsewhere, the paths are as Nextcloud sees them. If Nextcloud runs in a container, change each to the same folder's path on the host.
3. Save it on the Docker host in a folder of its own, and run `docker compose up -d` there. If either folder isn't where the file says, it refuses to start, rather than letting Docker create an empty folder owned by root.
4. Reload the settings page after a minute: the Videos section says whether the worker is running. Then switch on **Bake steadying into each copy**.

Each finished copy then goes to the worker before it's saved next to its clip. On the GPU it was tried on (a GeForce RTX 2070 Super), that takes under half the clip's length, against several times its length to stitch. If the worker isn't running or fails, the copy is kept as stitched and the player steadies it as before. In the player, a baked copy still has both buttons: switching steadying off shows the camera's own movement again. Baking resamples the picture once more, so a baked copy is very slightly softer. Copies stitched before baking was switched on aren't changed, and neither are copies that finished while the worker wasn't running, so if you want baked copies, start the worker and switch baking on before switching on stitching.

Upgrading the app replaces its folder, and the worker's view of it with it. From 0.5.1 the worker notices, exits and is started again by Docker on the new folder. With 0.5.0, run `docker compose restart` in the worker's folder after each upgrade, or bakes fail and copies are saved unbaked.

## Settings

**Administration settings → Golblick (360° Photos)** has:

- a setup check: whether `.insp` is registered, whether `.insv` videos are (optional) and ffmpeg is installed, GD, PHP's memory limit, whether the Memories zoom fix can attach, and whether ImageMagick can read RAW files (see [Nextcloud AIO and RAW photos](#nextcloud-aio-and-raw-photos))
- the size of the full-size panorama used for zooming and the sphere view, and a button to clear the ones already made
- rendering those panoramas in the background, newest photos first, off by default because it costs about 19 seconds of CPU per OneR photo at full size
- switches for the Memories zoom fix and for each "View as sphere" button, in case an update to Memories or the image viewer breaks one
- the Videos section: the switches described under [Videos](#videos), the video size, how far stitching has got, whether the GPU worker is running, **Delete stitched videos** and **Delete copies saved next to clips**

**Personal settings → Golblick (360° Photos)** lets each user choose what happens when a 360° video or photo opens in Memories. A video can open as a sphere (the default), show flat without playing, or play flat as Memories does on its own. A photo can show flat with the sphere button (the default) or open as a sphere. In the sphere, the left and right arrow keys go on to the previous or next item.

## Nextcloud AIO and RAW photos

AIO installs ImageMagick without RAW support, and that build crashes on DNG files instead of refusing them: the PHP process reading the file dies. In my testing, opening a DNG in the Memories viewer crashed it every time. This happens with or without golblick, but you'll notice it sooner with golblick installed: when an Insta360 camera shoots in RAW it saves a DNG next to each `.insp`, so browsing your 360 photos in Memories leads you straight to them.

The fix is to add the `imagemagick-raw` package. In AIO that's the `NEXTCLOUD_ADDITIONAL_APKS` setting on the mastercontainer, as described in [AIO's documentation](https://github.com/nextcloud/all-in-one#how-to-add-os-packages-permanently-to-the-nextcloud-container). It defaults to `imagemagick`, so set it to `imagemagick imagemagick-raw`. With that package installed, DNG and NEF files open in Memories and get previews, and nothing has crashed since.

## What the previews look like

Each preview is a full equirectangular panorama with the horizon levelled. On an X5 the app uses the panorama the camera already made. On a OneR or X3 it builds one from the two lenses and levels it using the camera's motion sensor.

Things close to the camera, within a metre or two, can show a visible break where the two lenses meet, because each lens sees them from a slightly different position. [docs/accuracy.md](../docs/accuracy.md) has the details.

## Using it with files_photospheres

[files_photospheres](https://apps.nextcloud.com/apps/files_photospheres) can be installed alongside this app; tested with 1.33.1 on Nextcloud 33 and 1.35.0 on Nextcloud 35. It doesn't generate previews, so `.insp` thumbnails still come from here. It shows its sphere button only for files that carry panorama metadata, which `.insp` files don't, so it doesn't offer its button for them; use golblick's **View as sphere** instead. Adding the metadata wouldn't help: files_photospheres wraps the downloaded original around the sphere, and for a `.insp` that is the two fisheye circles. A panorama made with `golblick render` does carry the metadata, and files_photospheres opens it as a sphere you can drag around.

## How it works

The app reads the camera's data from the end of each file. Photo previews are rendered in plain PHP with the GD library Nextcloud already requires: no Python, no external programs. Videos need ffmpeg, both for the opening-frame thumbnails of OneR and X3 clips and for stitching. The sphere view runs in the browser. [AGENT-NOTES.md](AGENT-NOTES.md), written mainly for coding agents, has the implementation details: performance, memory use, and how it shares JPEG previews with Nextcloud's own provider.

## Reporting a problem, or an untested camera

In Files, the actions menu of a `.insp` or `.insv` file has **Report to golblick**. It shows a summary of the file and what the app does with it, without the file's name, its folder or the camera's serial number, and a button that opens an issue on GitHub with the summary filled in, so you only add what you saw. Which issue depends on the camera:

- For the Insta360 OneR, X3 and X5, which golblick has been tested with, it's a [photo problem](https://github.com/AkshayRao27/golblick/issues/new?template=photo-problem.yml) (the photo looks wrong or won't open) or a [video problem](https://github.com/AkshayRao27/golblick/issues/new?template=video-problem.yml) (the video looks wrong or won't play).
- For any other camera, it's an [untested camera](https://github.com/AkshayRao27/golblick/issues/new?template=untested-camera.yml), which is worth reporting whether it looks right or not.

The entry is switched on and off together with the Files "View as sphere" entry on the settings page. For a clip the camera saved as two files, report the one with `_00_` in its name: the other one carries none of the camera's data.

## Licence

AGPL-3.0-or-later, like the rest of the repository; the full text is in [COPYING](COPYING).

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
