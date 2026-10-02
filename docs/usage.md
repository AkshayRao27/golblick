# Using the CLI

Everything here works on a plain Python install with no dependencies, except `render`, which needs numpy from the optional `render` extra.

```sh
uv tool install golblick              # or: pipx install golblick
uv tool install 'golblick[render]'    # adds panorama rendering
```

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

Two lines in that output are worth reading:

- **Lens agreement** scores the render against itself, by correlating the two lenses where they overlap. Around +0.7 to +0.9 is a correct projection, and +0.02 means something is wrong. It cannot see everything; [accuracy.md](accuracy.md) says what it misses.
- **Levelling** says which of two routes was used. *From gravity* means the file, or another frame from the same shutter press, carried an inertial record, so pitch and roll are both corrected. *From the calibration* is the fallback: it corrects the sensor's mounting angle, which is 91° on a OneR, but not how the camera was held, so a tilted shot stays tilted.

`--level` forces the choice. `imu` and `calibration` fail rather than quietly falling back, which is what you want when comparing the two.

The file does not say what angle the rim of each fisheye circle corresponds to, or how far the lens departs from the equidistant model the calibration describes. Both are measured per camera and applied automatically: 194° for a OneR and an X5, 192° for an X3, and a radial correction of up to 1.75° on the OneR and X3. `--field-of-view` overrides the first. The [format notes](formats/insta360-agent-notes.md#the-equidistant-model-is-close-but-not-exact) say how they were measured.

### What the metadata does and does not claim

The geometry fields are written, including the cropped-area fields: a partial panorama without them gets stretched around the whole sphere, which looks plausible rather than broken.

The pose fields are deliberately left out. `PoseHeadingDegrees` would state which compass direction the centre faces, and nothing in the file fixes that. `PosePitchDegrees` and `PoseRollDegrees` would assert the panorama is level, which is only as true as the levelling. A viewer that finds no pose fields assumes an unknown heading and a level horizon, which is the honest claim; a written `0.0` would look exactly like a measured one.
