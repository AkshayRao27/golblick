# Using the CLI

Everything here works on a plain Python install with no dependencies, except `render`, which needs numpy from the optional `render` extra, and also [ffmpeg](https://ffmpeg.org/) for a video. golblick isn't on PyPI, so it installs straight from GitHub. You need Python 3.10 or newer, git, and [uv](https://docs.astral.sh/uv/getting-started/installation/):

```sh
uv tool install 'golblick[render] @ git+https://github.com/AkshayRao27/golblick'   # with panorama rendering
uv tool install 'golblick @ git+https://github.com/AkshayRao27/golblick'           # without it, no dependencies
uv tool upgrade golblick                                                            # later, to update
```

For a video, `render` stitches the whole clip into a 360 MP4, steadied; see [Stitch a video](#stitch-a-video).

## Find clips whose master has gone missing

Insta360 cameras write two files for every clip: a full-quality master and a low-resolution proxy. For example:

```
VID_20260227_142557_00_005.insv    master, two HEVC fisheye streams
LRV_20260227_142557_01_005.lrv     proxy, one low-bitrate H.264 stream
```

The `.lrv` is the same two fisheye circles at low resolution, so while the `.insv` is there it's just taking up space. If the `.insv` gets deleted, though, the `.lrv` is all that's left of that clip, and nothing tells you. `triage` finds those clips. It goes by filename, so it's quick on a whole photo library, and it doesn't change or delete anything:

```sh
$ golblick triage ~/Photos/Trips
  13 clip(s), 2 photo(s)
    paired          8
    master only     0
    orphan proxy    5

  ORPHANED PROXIES -- the master is missing, so the low-resolution
  proxy is the only surviving copy of these clips:
       1.8 GiB  Feb 2026/LRV_20260228_112240_01_006.lrv
     956.7 MiB  Feb 2026/LRV_20260228_112240_01_007.lrv
     ...

  3.8 GiB exists only as proxy.
  Whether that was deliberate is not recorded in the files -- check before deleting.

  4.2 GiB of proxies duplicate a master that is still present.
```

`--json` gives the same report as JSON.

## Inspect a file

```sh
$ golblick probe IMG_20260314_090809_00_007.insp
  vendor      insta360
  trailer     version 3, 4.7 MiB at offset 7775494, pad 32
  records     5
    0x0300  imu                   2000 bytes
    0x0101  metadata              2956 bytes
    ...
  metadata
    model       Insta360 X5
    firmware    v1.10.7_build2
    dimensions  5888x2944
  calibration 4 model(s)
    field 5    equidistant   2 lenses x 6 params, reference 10752x5376, scale x0.547619
    field 111  mei-extended  2 lenses x 27 params, reference 10752x5376, scale x0.547619
```

Add `-v` to print the calibration parameters themselves. The full output also includes the camera's serial number, so leave it out of anything you post publicly.

## Report a problem, or a camera golblick hasn't been tested with

There are three kinds of report, and `report` works out which one applies. For the Insta360 OneR, X3 and X5, which golblick has been tested with, it's a problem with a photo or a video: it renders wrongly, or doesn't open or play. On a video, the report describes the opening frame and the motion record that steadying uses, and for a clip saved as two files it's the `_00_` file that carries the camera's data. Any other model is an untested camera, which is worth reporting whether the result looks right or not, because nobody has checked it yet.

`report` prints a summary of the file. It leaves out the file's name (Insta360 names carry the date and time), its folder and the camera's serial number, so you can paste it as it is:

```sh
$ golblick report IMG_20260314_090809_00_007.insp
```
```
golblick 0.4.0, Python 3.13.15
file         .insp, 26.8 MiB
vendor       insta360
model        Insta360 X5
firmware     v1.11.10_build1
tested       yes
...
preview      2560x1280 nv12 equirectangular
source       11904x5952 jpeg dual-fisheye
levelling    gravity, from this file's inertial record
```

After the report it prints a link to the right issue form on GitHub, with the report already filled in, so you only add what you saw. The `tested` line says which kind it is.

If golblick can't read part of the file, that line says what failed and the rest of the report carries on. For a file it doesn't recognise at all, it says what the file looks like instead, for example a plain JPEG with none of the camera's data, or a copy whose end is all zeros.

## Send photos to someone without your location

An original `.insp` holds where the photo was taken (twice: in the EXIF, and again in the camera's own data), when, and the camera's serial number. `share` writes copies without them:

```sh
$ golblick share IMG_20260314_090809_00_007.insp IMG_20260314_091102_00_008.insp
golblick-share/IMG_00000000_000000_00_001.insp  from IMG_20260314_090809_00_007.insp
  cleared: serial number, capture time, location (camera metadata), file name in camera metadata, description, date 0x0132, date 0x9003, date 0x9004, GPS (7 entries)
golblick-share/IMG_00000000_000000_00_002.insp  from IMG_20260314_091102_00_008.insp
  ...
```

Everything else stays exactly as the camera wrote it, so the copies render the same as the originals, in golblick and in Insta360 Studio. Before writing each copy, `share` searches all of it for the serial number, the coordinates and the date, and refuses if any of them is still there. It can't change what's in the picture, so look at the photos before you send them. `-o` picks the folder; it won't overwrite a copy that's already there.

## Get the camera's own preview

Insta360 stills carry the camera's own preview, which is larger and more useful than the 320×160 EXIF thumbnail:

```sh
$ golblick preview IMG_20260314_090809_00_007.insp -o preview.png
  2560x1280  nv12  equirectangular
```

What you get depends on the camera, and the command says which you got:

| Camera | Preview | Viewable as a panorama? |
|---|---|---|
| X5 | 2560×1280, stitched and horizon-levelled on the device | yes |
| X3, OneR | 1920×960, the dual-fisheye pair | no, it still needs stitching |

`golblick thumb` extracts the small EXIF thumbnail, with the same caveat: it is a stitch on an X5 and the fisheye pair everywhere else.

## Render a panorama

`render` projects the lens pair into an equirectangular image and writes the GPano XMP that tells a viewer it is a sphere rather than a wide photograph.

```sh
$ golblick render IMG_20260314_090809_00_007.insp -o pano.jpg -w 4096
  pano.jpg  (1.9 MiB)
    4096x2048  equirectangular  from 6080x3040
    field of view  194 degrees (the camera's measured value)
    lens model     equidistant, measured correction
    levelling      roll -91.11 degrees, from the calibration
                   this corrects the sensor mounting, not how the camera was held
    lens agreement +0.858  (a wrong convention scores about +0.02)
```

It projects from the full-resolution frame, not the embedded preview: on a OneR that is 6080×3040 rather than 1920×960. Output is JPEG unless the filename ends in `.png`.

Given a video and an `-o` ending in `.jpg` or `.png`, `render` renders only the clip's opening frame. On a OneR or X3 the camera stores that frame in the `_00_` file at full size, and decoding it needs ffmpeg. An X5 video stores a stitched panorama of its opening frame instead, so `golblick preview` already gives you one.

Two lines in that output are worth reading:

- **Lens agreement** scores the render against itself, by correlating the two lenses where they overlap. Around +0.7 to +0.9 is a correct projection, and +0.02 means something is wrong. It cannot see everything; [accuracy.md](accuracy.md) says what it misses.
- **Levelling** says which route was used, best first:
  - *Aligned to the camera's own levelled stitch*: the file carries a panorama the camera stitched and levelled itself (on the cameras tested, only the X5 does), and the render is turned to match it. It also faces the same way as the camera's panorama.
  - *From gravity*: the file, or another frame from the same shutter press, carried an inertial record, so pitch and roll are both corrected. On an X5 this is only used if aligning to the stitch fails: some X5 records cover several seconds of the camera being moved, and one of those rendered upside down from gravity alone.
  - *From the calibration* is the fallback: it corrects the sensor's mounting angle, which is 91° on a OneR, but not how the camera was held, so a tilted shot stays tilted.

`--level` forces the choice. `stitch`, `imu` and `calibration` fail rather than quietly falling back, which is what you want when comparing them.

Whichever route levels it, a photo's panorama faces the way Insta360 Studio opens it: the middle of the image is where Studio's view starts. Videos aren't turned this way yet.

The file does not say what angle the rim of each fisheye circle corresponds to, or how far the lens departs from the equidistant model the calibration describes. Both are measured per camera and applied automatically: 194° for a OneR, 192° for an X3 photo and 185.5° for an X3 video, 197.5° for an X5 photo and 195.3° for an X5 video, and a radial correction of up to 1.75° on the OneR and X3. `--field-of-view` overrides the angle. The [format notes](formats/insta360-agent-notes.md#the-equidistant-model-is-close-but-not-exact) say how they were measured.

Clip-on lens guards narrow that angle by about 2%, and the file does not record whether they were fitted. On an X5, `render` works it out from the picture: it tries both angles and keeps the one at which the two lenses agree clearly better where they overlap, and assumes no guards when neither wins. The output's `lens guards` line says what it decided. `--lens-guards on` or `off` overrides it.

### What the metadata does and does not claim

The geometry fields are written, including the cropped-area fields: a partial panorama without them gets stretched around the whole sphere, which looks plausible rather than broken.

The pose fields are deliberately left out. `PoseHeadingDegrees` would state which compass direction the centre faces, and nothing in the file fixes that. `PosePitchDegrees` and `PoseRollDegrees` would assert the panorama is level, which is only as true as the levelling. A viewer that finds no pose fields assumes an unknown heading and a level horizon, which is the honest claim; a written `0.0` would look exactly like a measured one.

## Look around in a photo

`open` shows a photo as a sphere in golblick's own viewer window: drag to look around, scroll or `+` and `-` to zoom, double-click or `F` for full screen, `Esc` to leave it. A bar of buttons along the bottom does the same by touch or click, and pinching zooms on a touchscreen. It needs the `desktop` extra.

```sh
golblick open IMG_20260314_090825_00_008.insp
```

Nothing is rendered first: the graphics card projects the two lenses as it draws, with the same lens model and corrections as `render`, so the photo is on screen in about a second. A few seconds later the view updates with what takes longer to work out: where the seam between the lenses goes, and on an X5 whether lens guards were fitted and how the camera's own stitch levels it.

**Open at this view next time**, in the bar's **⋮** menu, makes the current view the one the photo opens with, and **Open the default way** goes back to facing the way Insta360 Studio opens it. The bar and its menu are the same as in the Nextcloud app's sphere view. The views are kept in `~/.local/share/golblick/views.json`, by file name and size, never in the photo.

To open photos by double-clicking them, run this once:

```sh
golblick desktop install
```

It gives `.insp` files a type of their own, as a kind of JPEG so your other image viewers still offer to open them, and makes `golblick open` the default for it. Everything goes in your own `~/.local/share`, and `golblick desktop uninstall` removes it. Files are recognised by their `.insp` extension; `open` checks the content and refuses anything that isn't an Insta360 photo. Videos don't open this way yet.

## Stitch a video

`render` on a video stitches the whole clip into a 360 MP4 next to it, steadied from the camera's motion sensor, with the sound copied across and the file marked as 360° video so that players and Memories treat it as one. It needs ffmpeg on the PATH as well as the `render` extra. On a OneR or X3, give it the `_00_` file; the `_10_` file holding the other lens has to be in the same folder.

```sh
$ golblick render VID_20260126_115034_00_011.insv
VID_20260126_115034_00_011.360.mp4
  lens guards    detected: the lenses agree at 191.0 degrees, not 195.3
  field of view  191.0 degrees (the camera's measured value for video, less for lens guards)
  seam           aimed and routed
  levelling      from gravity at the opening (inertial record)
  steadying      follows the camera's turns, 337 frames from the motion record
  335 frames at 2880x1440, tables made by 8 processes
  done: 15.3 MiB in 3:31
```

The stitch is the one the [Nextcloud app](../nextcloud-app/README.md#videos) makes: the same lens model, one seam chosen for the whole clip, and the two lenses' brightness evened out along it. The steadying is applied in the same pass, so the picture is resampled only once. `--no-steady` gives the plain stitch, levelled at the start only, and `--lock` keeps the direction the clip opens in instead of following the camera's turns. The default size is 2880 × 1440; `-w` changes it.

It is slow, because every frame gets its own projection. On a desktop with 16 threads, at 2880, each second of video took 8 to 11 seconds on OneR and X3 clips and 19 on an X5 clip. The work is spread over half the machine's threads, fewer if memory is short, and `--jobs` sets the number.

## Steady a video

`stabilise` works out, from the camera's motion sensor, the rotation that steadies each frame of a 360 video, and writes it as JSON next to the clip:

```sh
$ golblick stabilise VID_20260126_115034_00_011.insv
VID_20260126_115034_00_011.stabilise.json  337 frames
```

Each frame gets a rotation (a quaternion, `w, x, y, z`) from the frame as rendered, levelled at the clip's opening, to the steadied view, along with the time it was captured. The steadied view keeps the horizon level and follows the camera's turns, smoothed over a couple of seconds. That differs from Insta360 Studio's FlowState, which follows turns much more slowly. With `--lock` it keeps the direction the clip opens in instead, like Studio's Direction Lock. It needs nothing installed beyond golblick, and takes about 13 seconds for a 30-minute clip. The Nextcloud app uses the same calculation when it plays a video; [accuracy.md](accuracy.md) has how it compares with Studio.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
