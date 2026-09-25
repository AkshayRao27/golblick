# kugelblick

Read, inspect and triage 360 camera files on Linux.

> ⚠️ **The name is provisional and will change before release.**
> [kugelblick.de](http://kugelblick.de) is an existing site about interactive 360°
> panoramas — the same subject matter — so shipping under this name would be
> confusing. A replacement needs to be free on PyPI, npm and GitHub, absent from
> the web, and must bake in no assumption: not a vendor, and not a lens geometry.

360 cameras wrap their footage in vendor-specific containers. Standard tools
open them and show *something* — which is exactly why they are confusing. An
Insta360 `.insp` opens in any image viewer as two fisheye circles side by side,
because that is what it contains: the camera does not store a stitched image.
Everything describing how to turn those circles into a viewable panorama lives
in a proprietary trailer the decoder skipped over.

Vendors ship little or nothing for Linux, which leaves people unable to do basic
things with their own footage — including working out which clips they still
have. It turns out the necessary information is already in the files, in plain
ASCII, readable without any proprietary code.

Status: **early, but it renders now.** Reading, inspection and triage work, and
`kugelblick render` turns a still into an equirectangular panorama with the
GPano metadata that makes standard 360 viewers open it as a sphere. The horizon
is levelled: fully, from the camera's inertial record, where the file carries
one and that camera's axes have been measured; otherwise for roll only. See
[Roadmap](#roadmap).

## Supported formats

| Vendor | Formats |
|---|---|
| Insta360 | `.insp`, `.insv`, `.lrv` — [format notes](docs/formats/insta360.md) |

Verified against OneR, X3 and X5 files.

One vendor so far, but the architecture is built around a
[registry](src/kugelblick/vendors/__init__.py) rather than assuming it. Adding a
second is a new module, not a refactor — see [Adding a vendor](#adding-a-vendor).

## Install

```sh
uv tool install kugelblick     # or: pipx install kugelblick
```

The library and CLI have **no dependencies**, and the test suite is run both
with and without the extra to keep it that way. Rendering needs numpy under the
optional `render` extra:

```sh
uv tool install 'kugelblick[render]'
```

## Usage

### Find clips whose master has gone missing

Cameras commonly write a full-quality master and a low-resolution proxy for
every clip:

```
VID_20260227_142557_00_005.insv    master, two HEVC fisheye streams
LRV_20260227_142557_01_005.lrv     proxy, one low-bitrate H.264 stream
```

The proxy is *not* a stitched preview — it is dual fisheye too, so it is no more
viewable than the master, and pure duplication while the master is present. Once
the master is deleted the proxy becomes the only surviving copy of that clip, at
a fraction of the quality. That is easy to do by accident and invisible
afterwards:

```sh
$ kugelblick triage ~/Photos/Trips
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

`--json` gives the same thing machine-readably. Nothing records whether a
deletion was deliberate, so the tool reports and does not judge.

### Inspect a file

```sh
$ kugelblick probe IMG_20260314_090809_00_007.insp
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

Add `-v` to print the calibration parameters themselves.

### Get a viewable image today

Insta360 stills carry the camera's own preview, larger and more useful than the
320×160 EXIF thumbnail:

```sh
kugelblick preview IMG_20260314_090809_00_007.insp -o preview.png
  2560x1280  nv12  equirectangular
```

**What you get depends on the camera**, and the command says which you got:

| Camera | Preview | Viewable as a panorama? |
|---|---|---|
| X5 | 2560×1280, stitched and horizon-levelled on device | yes |
| X3, OneR | 1920×960, the dual-fisheye pair | no — it still needs stitching |

On an X5 that is also this project's ground truth: a stitch built from the
calibration data can be scored against the camera's own output, so accuracy is
measurable without reference renders from the vendor's desktop software. On the
other cameras there is no embedded stitch to score against, which is a real
constraint on the rendering work rather than a gap in the reader.

`kugelblick thumb` still extracts the small EXIF thumbnail, with the same
caveat: it is a stitch on an X5 and the fisheye pair everywhere else.

### Render a panorama

`render` projects the lens pair into an equirectangular image and writes the
GPano XMP that tells a viewer it is a sphere rather than a wide photograph.
It needs the `render` extra.

```sh
$ kugelblick render IMG_20260314_090809_00_007.insp -o pano.jpg -w 4096
  pano.jpg  (1.9 MiB)
    4096x2048  equirectangular  from 6080x3040
    field of view  194 degrees (fit it with --field-of-view)
    levelling      roll -91.11 degrees, from the calibration
                   this corrects the sensor mounting, not how the camera was held
    lens agreement +0.858  (a wrong convention scores about +0.02)
```

It projects from the **full-resolution frame**, not the embedded preview — on a
OneR that is 6080×3040 rather than 1920×960. Output is JPEG unless the filename
ends in `.png`.

Two numbers in that output are worth reading rather than ignoring:

- **Lens agreement** scores the render against itself, by correlating the two
  lenses where they overlap. Around +0.7 to +0.9 is a correct projection; +0.02
  means something is wrong. See [How accuracy is measured](#how-accuracy-is-measured).
- **Levelling** reports which of two routes it used. *From gravity* means the
  file carried an inertial record and that camera's axes are known, so pitch
  and roll are both corrected — a shot taken with the camera upside down comes
  out the right way up. *From the calibration* is the fallback: it corrects the
  sensor's *mounting angle* — 91° on a OneR, so without it those renders come
  out on their side — but ⚠️ **not** how the camera was held, so a tilted shot
  stays tilted.

`--level` forces the choice. `imu` and `calibration` fail rather than quietly
falling back, which is what you want when comparing the two.

`--field-of-view` is worth knowing about: the angle the rim of each fisheye
circle corresponds to is **not stored in the file**. The default of 194° is
right for a OneR and an X5; an X3 wants 192.

#### What the metadata does and does not claim

The geometry fields are written, including the cropped-area fields — a partial
panorama without them gets stretched around the whole sphere, which looks
plausible rather than broken.

The **pose** fields are deliberately omitted. `PoseHeadingDegrees` would state
which compass direction the centre faces, and nothing in the file fixes that;
`PosePitchDegrees` and `PoseRollDegrees` would assert the panorama is level,
which is only as true as the levelling. A viewer that finds no pose fields
assumes an unknown heading and a level horizon, which is the honest claim.
Writing a fabricated `0.0` would be indistinguishable from a measured one.

## Adding a vendor

A vendor is a module exposing `NAME`, `DESCRIPTION`, `EXTENSIONS`, and the
functions `matches`, `classify`, `describe` and `extract_thumbnail`, plus the
optional `extract_preview` and `extract_source`. Listing it in `VENDORS` is the only change needed
elsewhere. Three conventions matter:

- **Detect by content, not extension.** `matches()` should sniff the file, so a
  renamed file is still recognised and an impostor is not claimed.
- **Refuse rather than guess.** A reader that cannot prove it understood a
  layout should raise `FormatError` instead of returning a plausible-looking
  result. See the padding discovery in
  [the Insta360 notes](docs/formats/insta360.md#the-self-check) for why.
- **Test against more than one camera.** Much of what looks like a property of a
  format turns out to be a property of the camera that wrote the file — which
  model carries a stitch, what reference frame calibration is quoted against,
  how the lenses are oriented. The Insta360 notes mark each of those explicitly.

## Roadmap

- [x] Container parsing, metadata, calibration, embedded previews, triage
- [x] Equirectangular rendering, with GPano XMP so standard 360 viewers open it
- [~] Levelling — pitch and roll from the inertial record where there is one;
      roll everywhere else. One camera's inertial axes are still unmeasured
- [x] Nextcloud app: preview provider — `nextcloud-app/`, pure PHP, GD only
- [ ] 360 viewing in Nextcloud Memories (upstream)
- [ ] Video

## How accuracy is measured

A stitch has to be checked against something. The obvious reference is the
camera's own stitched preview — but only some cameras embed one (on this
project's sample, the X5 does and the OneR and X3 do not), so it cannot be the
basis for the whole library.

Every file carries a better-distributed reference: the lenses see **past** 180°,
so there is a band where both observe the same scene, and a correct projection
makes those two views coincide. Correlating them over that band scores a render
with no vendor software, no reference image, and no embedded stitch — on any
dual-fisheye camera.

On correctly-projected stills this sits around +0.7 to +0.9; a wrong rotation
convention drops it to +0.02, so it discriminates sharply. It is what identified
the meaning of the stored lens angles.

🔴 It compares the lenses to each other, not to the world, so it is blind to the
absolute orientation of the result — a render that scores well can still be
upside down. Orientation has to come from somewhere else: the sensor mounting
angle in the calibration (every file), the camera's own stitch (one camera
only), or the gravity vector in the inertial record (about a third of files).

Where a camera embeds its own levelled stitch, levelling can be scored against
it properly. Correlation with that reference: **0.33** unlevelled, **0.86**
from the inertial record, **0.88** for the best rotation solvable against the
reference itself. So the inertial route gets most of the way to the ceiling
without using the reference at all — which matters, because most cameras do
not provide one.

⚠️ Treating that blind spot as a property of the *format* rather than of the
*metric* is what left every OneR render lying on its side for a while. The
absolute lens angle was in the calibration string the whole time.

## Prior art

[insv-stitch](https://github.com/BenjaminHenriksson/insv-stitch) (MIT) is a
video-only Insta360 X5 stitching pipeline and a useful reference for the
projection maths. It is not vendored here.

## Licence

MIT. The Nextcloud app, when added, will be AGPLv3 under `nextcloud-app/` as
that ecosystem requires.

Not affiliated with, endorsed by, or connected to any camera manufacturer.
Vendor names are used only to identify the file formats this software reads.
