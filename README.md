# kugelblick

Read, inspect and triage 360 camera files on Linux.

*Kugelblick* — German, roughly "sphere view". The name is deliberately
vendor-neutral and says nothing about lens count or output projection, so it
does not go stale as formats are added.

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

Status: **early.** Reading, inspection and triage work. Rendering does not exist
yet — see [Roadmap](#roadmap).

## Supported formats

| Vendor | Formats |
|---|---|
| Insta360 | `.insp`, `.insv`, `.lrv` — [format notes](docs/formats/insta360.md) |

One vendor so far, but the architecture is built around a
[registry](src/kugelblick/vendors/__init__.py) rather than assuming it. Adding a
second is a new module, not a refactor — see [Adding a vendor](#adding-a-vendor).

## Install

```sh
uv tool install kugelblick     # or: pipx install kugelblick
```

The library and CLI have **no dependencies**. Rendering, when it lands, will
need numpy and Pillow as an optional extra.

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

Insta360 stills embed a **stitched, horizon-levelled equirectangular preview**
in EXIF, produced on the camera:

```sh
kugelblick thumb IMG_20260314_090809_00_007.insp -o preview.jpg
```

It is only 320×160 on the X5, so it is a preview, not a substitute for a real
stitch. It is also this project's ground truth: a stitch built from the
calibration data can be scored against the camera's own output, so accuracy is
measurable without reference renders from the vendor's desktop software.

## Adding a vendor

A vendor is a module exposing `NAME`, `DESCRIPTION`, `EXTENSIONS`, and the
functions `matches`, `classify`, `describe` and `extract_thumbnail`. Listing it
in `VENDORS` is the only change needed elsewhere. Two conventions matter:

- **Detect by content, not extension.** `matches()` should sniff the file, so a
  renamed file is still recognised and an impostor is not claimed.
- **Refuse rather than guess.** A reader that cannot prove it understood a
  layout should raise `FormatError` instead of returning a plausible-looking
  result. See the padding discovery in
  [the Insta360 notes](docs/formats/insta360.md#the-self-check) for why.

## Roadmap

- [x] Container parsing, metadata, calibration, embedded previews, triage
- [ ] Equirectangular rendering, scored against the camera's own stitch
- [ ] GPano XMP output, so standard 360 viewers work
- [ ] Nextcloud app: preview provider
- [ ] 360 viewing in Nextcloud Memories (upstream)
- [ ] Video

## Prior art

[insv-stitch](https://github.com/BenjaminHenriksson/insv-stitch) (MIT) is a
video-only Insta360 X5 stitching pipeline and a useful reference for the
projection maths. It is not vendored here.

## Licence

MIT. The Nextcloud app, when added, will be AGPLv3 under `nextcloud-app/` as
that ecosystem requires.

Not affiliated with, endorsed by, or connected to any camera manufacturer.
Vendor names are used only to identify the file formats this software reads.
