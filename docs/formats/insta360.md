# The Insta360 `.insp` / `.insv` container

Everything here was measured directly from files produced by **Insta360**
cameras. Nothing is taken from leaked or decompiled sources. Where something is
inferred rather than measured, it says so — that distinction is deliberate, and
claims that have not earned their confidence are marked **unverified** rather
than quietly stated.

**The evidence base**, and it matters, because two of the findings below are
differences *between* cameras that a single-camera sample cannot see:

| Model | Files | Firmware | Trailer |
|---|---|---|---|
| OneR | 1,344 | v1.0.83 … v1.3.8 | version 3 |
| X3 | 40 | v1.2.16, v1.2.64/66 | version 3 |
| X5 | 25 | v1.10.7_build2 | version 3 |

That is every `.insp` in one personal library — 1,415 files, of which 1,409
parse. The six that do not carry no trailer at all: two are exported JPEGs with
the trailer stripped, four are zero-filled sync placeholders.

Other camera models and firmware revisions will still differ. The parser in this
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

Still dimensions are per camera, and the X5 and X3 each have two modes:

| Model | Still size | Files |
|---|---|---|
| OneR | 6080×3040 | 1,344 |
| X3 | 5952×2976 | 39 |
| X3 | 11968×5984 | 1 |
| X5 | 5888×2944 | 7 |
| X5 | 11904×5952 | 18 |

Each is two square cells side by side. Measured on an X5, video is two 2880×2880
HEVC streams at 59.94 fps, around 154 Mbps combined.

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
| `0x0200` | varies | The camera's own full-size preview — see [below](#record-0x0200--the-cameras-own-preview) |
| `0x0300` | 2,000 B | IMU samples |
| `0x0900` | 7,008 B | **Unidentified**. Frequently zero-length |
| `0x0b00` | 38,982 B | **Unidentified**. Frequently zero-length |

### Zero-length records

A record may declare a size of **0**: it is then nothing but its own six-byte
footer. `0x0900` and `0x0b00` appear this way on most OneR and X3 files — 898
of the 1,415 measured, which is 63% of the library.

This is worth stating plainly because reading a zero size as "no more records"
is a natural mistake, and an expensive one: it ends the walk six or twelve bytes
short of the trailer boundary, the self-check below then correctly refuses the
file, and the reader rejects most of a real library while parsing the sample it
was developed against perfectly. An empty record is data, not a terminator.

### The padding

Between the last record and the trailer footer sit 32 zero bytes on every file
measured. **Nothing in the format announces this**, and it is not derivable from
any field, so treating it as a constant would be a guess.

⚠️ The pad and an empty record are **not distinguishable byte for byte**: six
zero bytes read equally well as padding or as a record with id 0 and size 0. The
reader breaks the tie by treating id `0x0000` as padding, since no record has
ever been observed with that id. Without that rule a run of zero bytes whose
length divides by six makes the discovered pad width ambiguous, and the
self-check stops being decisive.

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
binary, and the richer cameras store it **several times** at increasing fidelity.

**How many models you get depends on the camera**, so tooling must not require
the richest one to be present:

| Model | Calibration fields | Count |
|---|---|---|
| OneR | 5 | one model only |
| X3 | 5, 53, 54 | three |
| X5 | 5, 53, 54, 111 | four |

Field 5, the equidistant model, is the only one present on every file measured —
and it is the only one whose interior is confirmed. A renderer that works from
field 5 therefore covers the whole library; one that requires field 111 covers
25 files out of 1,415.

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

**Parameters are quoted against a reference frame that is usually not the image
size**, so they must be scaled by `actual_width / reference_width` before use.
The reference frame is carried in the calibration string itself — read it from
there, because it is **per camera**, not a constant of the format:

| Model | Reference frame | Still size | Scale |
|---|---|---|---|
| OneR | 6080×3040 | 6080×3040 | 1.0 — the one camera where they coincide |
| X3 | 11904×5952 | 5952×2976 | 0.5 |
| X5 | 10752×5376 | 5888×2944 | 0.547619 |
| X5 | 10752×5376 | 11904×5952 | 1.107143 — note this one is **above 1** |

🔴 An earlier version of this document gave 10752×5376 as a property of the
format. It is the X5's value. Hard-coding it would misplace every lens circle on
a OneR, which is 1,344 of the 1,415 files measured. Scaling is also not always a
reduction: the X5's high-resolution still mode is *wider* than its own reference
frame.

The scaling rule is verifiable geometrically rather than by assertion. On the
X5, the equidistant lens radius of 2650.989 scales to **1451.7 px**, against a
half-cell of 1472 px: the image circle lands just inside its half of the frame,
which is what a fisheye circle should do. The repository asserts this in a test.

### Lens orientation differs between cameras — do not assume 0/180

The equidistant model's sixth per-lens value (yaw) is **constant for a given
camera** and differs sharply between them:

| Model | Lens 0 yaw | Lens 1 yaw | Files | Bodies |
|---|---|---|---|---|
| OneR | −178.89° | 0.22° | 1,344 | 1 |
| X3 | 88.99° | 89.86° | 40 | 1 |
| X5 | 90.05° | 89.71° | 25 | 1 |

So a OneR uses the conventional front/back arrangement, and an X3 or X5 does
not. Any stitch that hard-codes either one comes out rotated on the other
camera, and this is the single most common reason a naive
`ffmpeg v360=dfisheye` conversion looks wrong.

🔴 An earlier version of this document stated "both lens axes sit near 90° and
270°" as a fact about the format. It is X3/X5 behaviour, it is wrong for the
OneR, and the "270°" was wrong in any case — on an X5 *both* lenses read ~90°.
⚠️ How two lenses pointing in opposite directions both come to be quoted near
90° is **not established**; the 180° separation must be carried somewhere other
than this field. Until that is measured, treat the three angles as a per-lens
reference frame of unknown convention rather than as a compass bearing.

### The calibration is the same in every file from one camera body

For every (camera, field) pair there is **exactly one** distinct calibration
string: one across all 1,344 OneR files, one across all 40 X3 files, one across
all 25 X5 files, and likewise for fields 53, 54 and 111. It is written into each
file rather than re-derived per shot, so it can be cached per camera.

⚠️ The library holds **one body of each model** — one serial number per model
across all 1,415 files. So this measures "constant per body", and cannot
distinguish a per-unit factory calibration from a per-model constant. The
parameters are lens-specific measurements, which makes per-unit the more likely
reading, but that is reasoning, not evidence. Either way the practical
consequence stands: 1,415 files provide only **three** independent calibration
samples, so agreement across the library is not corroboration.

### What is *not* verified

The **interior layout of fields 53, 54 and 111 is inferred from shape**, not
confirmed. The names above describe how many numbers appear where; they are not
claims about which coefficient means what, and which model Insta360 Studio
actually uses is unknown. This library therefore exposes those parameters as a
raw tuple rather than as named attributes. Identifying them is the first task of
the rendering work.

## Record `0x0200` — the camera's own preview

Previously recorded here as unidentified. It is the camera's own full-size
preview, and **what it contains depends on the camera**:

| Model | Encoding | Dimensions | Layout |
|---|---|---|---|
| OneR, X3 | JPEG | 1920×960 | **dual fisheye** |
| X5 | NV12 (YUV 4:2:0) | 2560×1280, declared in the header | **equirectangular stitch** |

The X5 variant is the valuable one: a 2560×1280 panorama, stitched and
horizon-levelled on device, sitting in the file with no processing required. It
is the same image as the EXIF thumbnail at 64× the pixel count.

### The NV12 header

Forty bytes, then the pixel data. Ten `uint32` fields, identical across all 25
X5 files measured:

```
offset  0  uint32  1          ⚠️ constant; meaning unverified
offset  4  uint32  4915240    the record size, this header included
offset  8  uint32  1          ⚠️ constant; meaning unverified
offset 12  uint32  0
offset 16  uint32  2560       width
offset 20  uint32  1280       height
offset 24  uint32[4]  0
```

Only width and height are identified, and they are enough. The payload is then
exactly `width × height × 3 / 2` bytes, as NV12 requires — a full-resolution
luma plane followed by one interleaved chroma plane at half resolution in both
axes. **That identity is a self-check**, not an assumption: it held on all 25
files, and a reader that finds it broken should refuse rather than hand back a
buffer that decodes to garbage.

Because every file measured came from one camera on one firmware, the constants
above are **not** established as constants of the format — only as constants of
this sample. Treat `1` at offsets 0 and 8 as unexplained, not as magic to match
against.

### How the layout was established

The encoding predicts the layout on every file measured, but the format does not
announce it, so it is an observation about two camera generations rather than a
rule. Measured on all 1,409 files that parse, by the mean brightness of the
frame corners — a fisheye pair leaves them outside the image circle and therefore
black:

| Group | n | Corner brightness | Reading |
|---|---|---|---|
| OneR JPEG | 1,319 | 0.0 – 24.7, median 0.0 | fisheye pair |
| X3 JPEG | 40 | 1.0 – 19.9, median 3.8 | fisheye pair |
| X5 NV12 | 24 | 147.5 – 239.0, median 188.9 | stitched |
| X5 NV12 | 1 | 2.8 | an all-black frame; says nothing either way |

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

Every `.insp` measured carries a 320×160 thumbnail in EXIF IFD1. **Whether it is
a stitch depends on the camera**, and the difference decides what can be built
on it:

| Model | n | Thumbnail contents |
|---|---|---|
| X5 | 25 | stitched, horizon-levelled equirectangular |
| X3 | 40 | the dual-fisheye pair, shrunk |
| OneR | 1,344 | the dual-fisheye pair, shrunk |

🔴 An earlier version of this document stated the stitch as a property of the
format. It was generalised from two X5 stills, and it is wrong for 1,384 of the
1,415 files measured. The correction is recorded rather than quietly edited,
because the mistake is instructive: the sample was not the population.

Two consequences, both now conditional on the camera:

1. **A displayable preview exists without stitching — on the X5 only.** Record
   `0x0200` gives 2560×1280 there. On a OneR or X3 neither the thumbnail nor
   `0x0200` is viewable as a panorama, so a photo grid that wants a round
   picture for those files has to stitch one.
2. **Ground truth exists — on the X5 only.** A stitch built from the calibration
   data can be scored against the camera's own output, with no reference renders
   from Insta360 Studio. ⚠️ For OneR and X3 files there is **no embedded stitch
   to score against at all**, so accuracy on those cameras cannot be measured
   this way. Since the X5 is also the only camera that carries all four
   calibration models, the accuracy harness and the richest calibration data
   happen to coincide on the same 25 files.

## A measured baseline for naive stitching

Scored by SSIM against the embedded 320×160 thumbnail, for one X5 still.
⚠️ Record `0x0200` supersedes the thumbnail as the reference — it is the same
image from the same camera at 2560×1280 — so these numbers are a baseline
measured against the coarser of the two references, and should be re-measured
against `0x0200` before anything is compared to them:

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
kugelblick probe FILE -v        # records, metadata, every calibration model
kugelblick preview FILE -o p.png  # record 0x0200, the camera's full-size preview
kugelblick thumb FILE -o t.jpg    # the 320x160 EXIF thumbnail
exiftool -ee3 -G1 -s FILE       # independent cross-check
```
