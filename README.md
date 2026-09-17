# insta360-tools

Read, inspect and triage Insta360 `.insp` and `.insv` files on Linux.

Insta360 ships no Linux software. That leaves anyone on Linux unable to do even
basic things with their own footage — including working out which clips they
still have. This project starts from the observation that **everything needed is
already inside the files**, in plain ASCII, and none of it requires proprietary
code to read.

Status: **early.** Reading, inspection and triage work. Rendering does not exist
yet — see [Roadmap](#roadmap).

## Install

```sh
uv tool install insta360-tools     # or: pipx install insta360-tools
```

The library and CLI have **no dependencies**. Rendering, when it lands, will
need numpy and Pillow as an optional extra.

## Usage

### Find clips whose master has gone missing

The camera writes a full-quality master and a low-resolution proxy for every
video clip:

```
VID_20260227_142557_00_005.insv    master, two HEVC fisheye streams
LRV_20260227_142557_01_005.lrv     proxy, one low-bitrate H.264 stream
```

Both are dual-fisheye — the proxy is *not* a stitched preview, so it is pure
duplication while its master is present, and the only surviving copy once the
master is gone. Deleting masters and forgetting the proxies is easy, and the
result is indistinguishable from data loss unless you go looking:

```sh
$ insta360 triage ~/Photos/Trips
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

`--json` gives the same thing machine-readably.

### Inspect a file

```sh
$ insta360 probe IMG_20260314_090809_00_007.insp
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

An `.insp` is a dual-fisheye JPEG — two circles side by side — so viewing it
directly is useless. But the camera embeds a **stitched, horizon-levelled
equirectangular thumbnail** in EXIF, and that is immediately usable:

```sh
insta360 thumb IMG_20260314_090809_00_007.insp -o preview.jpg
```

It is only 320×160 on the X5, so it is a preview, not a substitute for a real
stitch. It is also this project's ground truth: a stitch built from the
calibration data can be scored against the camera's own, which means accuracy
can be measured without reference renders from Insta360 Studio.

## What is actually in these files

Full detail in [docs/FORMAT.md](docs/FORMAT.md). In short:

| | |
|---|---|
| `.insp` | JPEG, dual fisheye, unstitched, plus a trailer |
| `.insv` | MP4 with **two separate HEVC streams**, one per lens, plus a trailer |
| `.lrv` | low-bitrate proxy, also dual fisheye |
| Trailer | length-prefixed records walked backwards from a 32-byte magic at EOF |

The lens calibration lives in a protobuf record as underscore-delimited ASCII,
stored **four times** at increasing fidelity. It is not obfuscated or encrypted.

## Roadmap

- [x] Trailer parsing, metadata, calibration, embedded thumbnails, triage
- [ ] Equirectangular rendering from the calibration models, scored against the
      camera's own stitch
- [ ] GPano XMP output, so standard 360 viewers work
- [ ] Nextcloud app: preview provider for `.insp`
- [ ] 360 viewing in Nextcloud Memories (upstream)
- [ ] Video

## Prior art

[insv-stitch](https://github.com/BenjaminHenriksson/insv-stitch) (MIT) is a
video-only X5 stitching pipeline and a useful reference for the projection
maths. It is not vendored here.

## Licence

MIT. The Nextcloud app, when added, will be AGPLv3 under `nextcloud-app/` as
that ecosystem requires.
