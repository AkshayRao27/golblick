# The Insta360 `.insp` / `.insv` container

Everything here was measured directly from files produced by an **Insta360 X5**
on firmware **v1.10.7_build2**, trailer **version 3**. Nothing is taken from
leaked or decompiled sources. Where something is inferred rather than measured,
it says so — that distinction is deliberate, and claims that have not earned
their confidence are marked **unverified** rather than quietly stated.

Other camera models and firmware revisions will differ. The parser in this
repository validates its own assumptions rather than trusting them (see
[The self-check](#the-self-check)).

## The outer containers

| Extension | Container | Contents |
|---|---|---|
| `.insp` | JPEG | One dual-fisheye still — two circular images side by side |
| `.insv` | MP4 | **Two separate HEVC video streams**, one per lens, plus AAC audio |
| `.lrv` | MP4 | Low-bitrate H.264 proxy, also dual fisheye |

Because both are valid standard containers, ordinary decoders open them and show
something — which is precisely why the format is confusing in practice. An
`.insp` opens in any image viewer and looks like two fisheye circles, because
that is exactly what it is. **The camera does not store a stitched image.**

Measured on an X5: stills are 5888×2944 (two 2944×2944 cells); video is two
2880×2880 HEVC streams at 59.94 fps, around 154 Mbps combined.

An `.lrv` is a *proxy*, not a preview: it is dual fisheye too, so it is no more
viewable than the master. It exists for scrubbing in the phone app.

## The trailer

Appended after the container's own data, so standard decoders never see it.
Read it **backwards from EOF**:

```
...record data...
[pad]                  32 zero bytes on every file measured (see below)
uint32   trailer_size  total trailer length, this footer and magic included
uint32   version       3
char[32] magic         "8db42d694ccc418790edff439fe026bf"
```

`trailer_size` is measured from the end of the file, so the trailer occupies
`[filesize - trailer_size, filesize)`. This matters in practice: an `.insv`
master can run to many gigabytes, and the trailer can be read without touching
the rest of the file.

### Records

Records sit in front of the footer. Each is **followed** by its own six-byte
footer rather than preceded by a header, so the sequence is walked backwards:

```
<record data>
uint16 record_id
uint32 record_size     length of the data immediately preceding this footer
```

Record ids observed:

| Id | Size (example) | Contents |
|---|---|---|
| `0x0101` | 2,956 B | protobuf: serial, model, firmware, dimensions, **calibration** |
| `0x0200` | 4,915,240 B | 40-byte header + 4,915,200 bytes. Not a JPEG. **Unidentified** |
| `0x0300` | 2,000 B | IMU samples |
| `0x0900` | 7,008 B | **Unidentified** |
| `0x0b00` | 38,982 B | **Unidentified** |

### The padding

Between the last record and the trailer footer sit 32 zero bytes on every file
measured. **Nothing in the format announces this**, and it is not derivable from
any field, so treating it as a constant would be a guess.

### The self-check

The record walk has a natural correctness proof: it must consume the records
region **exactly**, ending on the trailer's first byte. The reader therefore
tries the plausible padding widths and keeps whichever one makes the walk land
on the boundary. A wrong pad width — or a changed layout in future firmware —
leaves the walk ending somewhere else, and the reader raises instead of
returning plausible-looking nonsense.

## Record `0x0101` — metadata

Standard protobuf wire format. No schema is published, so this project reads
fields by number and does not attempt to model the message; a firmware revision
that adds or renumbers fields then degrades to "that field is missing" rather
than failing outright.

| Field | Contents |
|---|---|
| 1 | Camera serial number |
| 2 | Model, e.g. `Insta360 X5` |
| 3 | Firmware, e.g. `v1.10.7_build2` |
| 5 | Calibration, equidistant model |
| 19 | `{1: width, 2: height}` of the source image |
| 53 | Calibration, polynomial model |
| 54 | Calibration, MEI model |
| 111 | Calibration, extended MEI model |

## Calibration

The most useful finding in the format, and the one that makes open tooling
viable: **calibration is stored as underscore-delimited ASCII**, not packed
binary, and it is stored **four times** at increasing fidelity.

Every string has the shape:

```
<lens_count> _ <lens 0 block> _ <lens 1 block> _ <globals>
```

| Field | Per lens | Trailing globals | Shape |
|---|---|---|---|
| 5 | 6 | 3 | radius, centre x, centre y, roll, pitch, yaw |
| 53 | 16 | 1 | + translation + 4-term polynomial + per-lens reference frame |
| 54 | 19 | 1 | fx, fy, cx, cy + extrinsics + 5 coefficients + reference frame |
| 111 | 27 | 1 | as 54, with 13 coefficients |

Example, field 5:

```
2_2650.989_2691.500_2693.820_-0.873_0.140_90.047
 _2644.985_8069.050_2693.770_1.015_0.005_89.714_10752_5376_1137
```

### The reference frame, and why it matters

**All four models are quoted against a 10752×5376 frame regardless of the actual
image size.** Parameters must be scaled by `actual_width / 10752` before use —
0.547619 for a 5888-wide still.

This is verifiable geometrically rather than by assertion. The equidistant lens
radius of 2650.989 scales to **1451.7 px**, against a half-cell of 1472 px: the
image circle lands just inside its half of the frame, which is what a fisheye
circle should do. The repository asserts this in a test.

### Lens yaw is ~90°, not 0/180

Both lens axes sit near 90° and 270°, not 0° and 180°. Any stitch that assumes
the conventional front/back arrangement comes out rotated. This is the single
most common reason a naive `ffmpeg v360=dfisheye` conversion looks wrong.

### What is *not* verified

The **interior layout of fields 53, 54 and 111 is inferred from shape**, not
confirmed. The names above describe how many numbers appear where; they are not
claims about which coefficient means what, and which model Insta360 Studio
actually uses is unknown. This library therefore exposes those parameters as a
raw tuple rather than as named attributes. Identifying them is the first task of
the rendering work.

## Record `0x0300` — IMU

Fixed **20-byte entries** (100 of them in a 2,000-byte record):

```
int64  timecode      increments by 1000 units between samples
byte[12] payload     encoding undetermined
```

The timecode is confirmed: the decoded values match exiftool's output exactly
and increase monotonically. The 12-byte payload is **not** yet decoded — it does
not read as three floats, as doubles, or as plausibly-scaled int16, and on a
still photograph every entry is identical, which limits what can be inferred.

exiftool does decode accelerometer and angular-velocity values from this record,
so the information is recoverable; this library simply has not confirmed the
layout yet. It matters for horizon levelling, which needs the gravity vector.

## The embedded thumbnail

Every `.insp` carries a **stitched, horizon-levelled equirectangular thumbnail**
in EXIF IFD1 — 320×160 on the X5. The camera does the stitch on device.

Two consequences:

1. A usable preview is available instantly, with no stitching and no
   dependencies. Good enough for a photo grid.
2. **It is ground truth.** A stitch built from the calibration data can be scored
   against the camera's own output, so accuracy is measurable without reference
   renders from Insta360 Studio.

## A measured baseline for naive stitching

Scored by SSIM against the embedded thumbnail, for one X5 still:

| Approach | SSIM |
|---|---|
| `ffmpeg v360=dfisheye:e:ih_fov=193:iv_fov=193` | 0.448 |
| Same, with orientation corrected | 0.589 |

The orientation correction was found by grid search, not derived. The ceiling is
explained: `v360`'s `dfisheye` input cannot express per-lens centre, radius,
rotation or distortion, so it discards almost everything the calibration knows,
and it applies no seam blending. Two further limits are worth knowing:

- **Horizon levelling.** The camera levels its output using gravity. A raw
  stitch does not, so a handheld shot shows a visibly curved horizon.
- **Parallax at the seam.** Objects close to the camera are duplicated or torn
  where the hemispheres meet. No amount of calibration fixes this; it needs
  optical-flow blending.

`v360` and `remap` are **CPU-only** in ffmpeg and do not compose with NVENC, so
GPU acceleration applies to encoding, not to the projection.

## Reproducing this

```sh
spherekit probe FILE -v      # records, metadata, all four calibration models
spherekit thumb FILE -o t.jpg
exiftool -ee3 -G1 -s FILE   # independent cross-check
```
