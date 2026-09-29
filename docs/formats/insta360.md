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

### Getting the full-resolution frame out

For a `.insp` this costs nothing: the JPEG is everything in front of the
trailer, so the frame comes out by slicing the file at the trailer offset. No
decoding, no re-encoding, no vendor software. `kugelblick render` projects from
this rather than from record `0x0200`, which is a twentieth of the pixels on a
OneR.

Worth checking that the slice ends on `FFD9`. The trailer is appended after the
JPEG's own end marker, so the two boundaries must coincide; if they do not, the
trailer was misparsed and everything downstream is built on it.

⚠️ **The frame header is a long way in.** These files carry a run of `APP2`
segments in front of the `SOF` marker — 10 or 11 on a OneR and X3, 76 on the X5
measured — so the dimensions sit about **0.6 MB** into a OneR file and **4.9 MB**
into an X5 one. A reader that scans only the first megabyte finds no frame
header, and must not conclude the file is malformed. This cost one wrong
census.

✅ **What the `APP2` run holds is the preview, again.** Concatenate every
`APP2` payload in front of the `SOF` marker and the result is **byte-identical
to the payload of trailer record `0x0200`** — the dual-fisheye JPEG on a OneR
and X3, the raw NV12 plane on an X5. Measured on **all 1,384 files that carry
record `0x0200`**; the other 31 are 25 OneR stills with no preview record and
the 6 with no trailer.

So the camera writes its preview twice: once through the standard JPEG segment
mechanism, once in the proprietary trailer. That is worth knowing because the
first copy is reachable **without parsing the trailer at all** — reassembling
`APP2` segments is ordinary JPEG parsing, which any imaging library already
does. On an X5 that yields the equirectangular stitch directly.

⚠️ One caveat if you take that route: the `APP2` copy is the payload **without**
record `0x0200`'s 40-byte header, and on the X5 that header is where the NV12
dimensions are declared. A reader that skips the trailer gets X5 pixels with no
stated geometry.

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
| `0x0300` | 2,000 B | IMU samples — see [below](#record-0x0300--imu) |
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

✅ **Yaw is the sensor's rotation within its own image circle — not the
direction the lens points.** That is why both X5 lenses read ~90°: the sensors
are mounted a quarter turn round, and the two lenses face opposite ways by
construction. The OneR's 179° difference is the same thing plus the
back-to-back flip stated explicitly, which the X3 and X5 leave implicit.

So what a renderer needs is the **relative** rotation, taken modulo 180°:

| Model | Stored yaw 0 | Stored yaw 1 | Difference | mod 180° | Measured |
|---|---|---|---|---|---|
| OneR | −178.890° | +0.218° | +179.108° | **−0.892°** | −1.39° |
| X3 | +88.992° | +89.858° | +0.866° | **+0.866°** | +0.87° |
| X5 | +90.047° | +89.714° | −0.333° | **−0.333°** | +0.17° |

"Measured" is the relative rotation recovered independently, by maximising the
agreement between the two lenses where they overlap (see
[Scoring without a reference](#scoring-without-a-reference)). It matches the
stored value within ±0.5° on all three cameras and exactly on the X3, which is
what earns the identification.

🔴 An earlier version of this document stated "both lens axes sit near 90° and
270°" as a fact about the format. It was wrong twice over: 270° was never
measured at all, and the angles are not bearings.

⚠️ **`roll` and `pitch` remain unidentified.** They are under 1° on every camera
measured, and applying them as tilts about the X and Y axes scores *worse* than
ignoring them, so the convention is wrong rather than the values meaningless.
They are not applied.

⚠️ **The rim angle is not in the file.** The equidistant model gives the image
circle's radius in pixels but not the angle that rim corresponds to, so it has
to be fitted. Recovered by scoring: **194° on the X5 and the OneR, 192° on the
X3.**

### The absolute yaw is the mounting angle, and it levels the roll axis for free

The *relative* yaw is what a renderer needs to place the two hemispheres
correctly. The **absolute** value turns out to be worth just as much, and was
discarded for longer than it should have been.

Rendering with lens 0 as the reference produces a panorama in **lens 0's sensor
frame**. That frame is not the camera body's, because the sensor is mounted at
an angle — and the angle differs by 90° between a OneR and an X3/X5. So the
same correct projection code yields an upright X3 and a OneR lying on its side.

The stored yaw is quoted against a reference 90° from the body's up, so:

```
body_roll = 90° − yaw₀     (about the lens axis, i.e. the render's roll)
```

| Model | Lens 0 yaw | `body_roll` | Files | Spread over the library |
|---|---|---|---|---|
| OneR | −178.89° | **−91.11°** | 1,344 | **0.00°** |
| X3 | +88.99° | **+1.01°** | 40 | **0.00°** |
| X5 | +90.05° | **−0.05°** | 25 | **0.00°** |

✅ **Verified**: the value has zero spread across all 1,409 files that carry a
trailer, so it is a constant of the body rather than anything per-shot.
Applying it turns a OneR render from 90° on its side into a level panorama, and
moves the X3 and X5 by ~1° and ~0°, matching the fact that those two already
rendered upright. Confirmed visually on eight OneR stills spread across the
library and four years of capture.

This matters because it is the only levelling that costs nothing: it needs
neither a reference stitch (which only the X5 embeds) nor an IMU record (which
965 of 1,344 OneR stills lack), so it applies to **every** file. See
[Levelling](#levelling).

⚠️ **It corrects the mounting, not the attitude.** A camera genuinely tilted
when the shutter fired is still tilted afterwards. This fixes one axis — roll
about the lens axis — and leaves pitch to the other two routes.

⚠️ **The 90° in the formula is fitted to three bodies**, not derived from
anything the file states. It holds across a 90° difference in mounting, which
is what earns it any trust, but a fourth camera could disagree. The library
carries one body per model, so these are three independent samples, not 1,409.

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

Field 5's six per-lens values *are* identified: radius, centre x, centre y,
roll, pitch, yaw — with roll and pitch's convention still open, as noted above.

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

Each entry is a 64-bit millisecond timecode followed by six values: three
accelerometer axes in **g**, then three angular velocities. Both are confirmed
against exiftool, value for value, on files from all three cameras.

🔴 **Two encodings, and the entry stride is not a property of the camera
model.**

| Stride | Payload | Value |
|---|---|---|
| 20 B | `int64` timecode + 6 × `uint16` | `(raw − 32768) / 1000` |
| 56 B | `int64` timecode + 6 × `float64` | as stored |

Of the 379 OneR stills in one library that carry this record, **285 use the
56-byte form and 94 use the 20-byte one** — the same camera model on both
sides, so the stride must be *searched*, not looked up. `imu.entries` keeps
only a stride that divides the record exactly and whose timecodes rise
monotonically, and refuses when none fits or more than one does.

⚠️ **Most files carry no IMU at all.** Over all 1,415 `.insp`:

| | Files |
|---|---|
| Decoded | 442 |
| No `0x0300` record | 965 — all OneR, 72% of that camera's stills |
| No trailer at all | 6 |
| Zero-length record | 2 (X3) |

So an IMU-derived horizon serves **about a third** of this library. Levelling
that has to work everywhere needs a second route.

### Why this was previously recorded as undecoded

An earlier pass reported that the payload "does not read as three floats, as
doubles, or as plausibly-scaled int16". Two mistakes compounded: the 20-byte
stride measured on an X5 was assumed to hold everywhere, so the 56-byte entries
were being sliced at the wrong boundary; and the 16-bit form was tried as
*signed* rather than as unsigned biased by `0x8000`. Both were settled in
minutes once exiftool's decoded output was put beside the raw bytes, which is
the cross-check that should have come first.

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

## Scoring without a reference

Only the X5 embeds a stitch, so for 98% of the library there is nothing to
compare a render against. There is, however, evidence every file carries: the
lenses see **past** 180°, so there is a band where both observe the same scene,
and a correct projection makes those two views coincide.

Pearson correlation over that overlap band, on one still per camera:

| Model | Fitted rim angle | Overlap agreement |
|---|---|---|
| X5 | 194° | +0.75 |
| OneR | 194° | +0.71 |
| X3 | 192° | +0.90 |

A wrong rotation convention drops this to about **+0.02**, so it discriminates
sharply. It is also what identified the yaw, and it needs no vendor software and
no embedded stitch.

🔴 **What it cannot do.** It compares the lenses to *each other*, not to the
world, so it is blind to the absolute orientation of the result. Because lens 1
faces backwards, a rotation of the world about the lens axis appears as +a in
one lens and −a in the other and leaves the score untouched. A render scored
this way can still be upside down. Levelling has to come from the camera's own
stitch (X5 only) or from the gravity vector in the IMU record — see
[Levelling](#levelling).

⚠️ It is also not a sharpness measure: it rewards the hemispheres agreeing, and
says nothing about parallax at the seam, which no calibration fixes.

## Levelling

A projection built from the calibration is correct and **arbitrarily
oriented**: the calibration fixes the lenses relative to each other, not
relative to the world. Three routes put the horizon where it belongs, and they
answer different questions.

| Route | What it fixes | Needs | Files it reaches (of 1,415) |
|---|---|---|---|
| 0 — the mounting angle | Roll about the lens axis | Nothing beyond the calibration | **1,409** |
| 1 — solve against the stitch | All three axes | An embedded stitch (X5 only) | 25 |
| 2 — gravity from the IMU | Pitch and roll | An IMU record *and* a measured axis mapping | **404** |

Route 0 is partial and reaches everything; route 2 is the accurate one and now
reaches 404 files rather than 25, because the OneR's axis mapping has been
measured. The two compose in practice: prefer gravity where it exists, fall
back to the mounting angle where it does not.

⚠️ Superseded: that 404 predates both the X3's measured mapping and burst
borrowing. Measured over 1,438 stills, **1,432** are levelled — 1,384 from
gravity (417 from their own record, 967 from another frame of the same shutter
press) and 48 from an on-device stitch. The 6 that are not carry no trailer.

🔴 **The 965 files with no inertial record cannot be levelled, and that is a
property of the files rather than a gap in this reader.** Insta360's own Studio,
given the same files, produces an export that agrees with route 0 alone to
**0.8°** (p90 0.9°, n=7) — so it is not levelling them either. Nothing further
is recoverable from a still that carries no `0x0300`.

### Route 0 — the sensor mounting angle, from the calibration alone

The cheapest correction, and the one that was missed longest. The absolute yaw
in the equidistant model is the sensor's mounting angle in the camera body, so
rolling the render by `90° − yaw₀` about the lens axis lands it in the body
frame. On a OneR that is a **91° correction**; without it every one of the
1,344 OneR stills renders on its side.

It needs no reference and no IMU, so it applies to every file that carries a
trailer. It fixes one axis only — a camera that was genuinely tilted stays
tilted. See
[The absolute yaw is the mounting angle](#the-absolute-yaw-is-the-mounting-angle-and-it-levels-the-roll-axis-for-free)
for the measurement and its limits. `render.body_orientation`.

### Route 1 — solve the rotation against the camera's own stitch

Record `0x0200` on an X5 is horizon-levelled, so the rotation between it and a
raw render *is* the camera's levelling. `render.fit_orientation` searches for
it: yaw is exactly a horizontal shift in equirectangular, so it comes out of one
FFT cross-correlation per candidate tilt rather than a third axis of grid
search, and three quartering passes take the grid from 10° to under 0.2°.

Over the 25 X5 stills in one library: **24 aligned, 1 refused** — the refusal
is an all-black exposure, which carries 0.3–0.6 grey levels of deviation where a
real frame carries 50–65, and which aligned to a confident-looking nonsense
rotation before that check existed.

| | Correlation with the camera's stitch |
|---|---|
| No levelling | 0.18 median |
| Solved rotation | **0.88 median** (0.82–0.96) |

🔴 **Yaw is a constant, not a variable.** Across those 24 files it reads
**180.3°, sd 1.8°** — our render faces the opposite way to the camera's stitch,
and always by the same amount. Pitch and roll are not constant at all
(−49.8°…+21.4° and −40.8°…+14.1°): those are how the camera was held.

⚠️ This route is ground truth for **25 files in 1,415**. A OneR or X3 embeds the
fisheye pair rather than a stitch, so there is nothing to solve against.

### Route 2 — the gravity vector from the IMU

The accelerometer says which way is down, on any camera that records one. The
axis mapping between the IMU and the render was measured by fitting the 24
solved rotations above; a least-squares fit over all of them landed within 3° of
an exact signed permutation, and **the exact permutation scored better than the
fit** — 2.3° median error against the camera's own levelling, versus 4.0°:

```
up_render = (−a_z, −a_x, −a_y)         # Insta360 X5
```

🔴 **That map is a reflection — its determinant is −1**, and that is a
measurement, not a slip. It says the stored triple, *as decoded here*, is not
a right-handed (x, y, z) on this camera. Two components transposed, or one
inverted in the camera's own convention, would both produce it and nothing
measured distinguishes them, so the composite is recorded rather than a story
about which axis is which. ⚠️ The OneR's map is **also** a reflection, so this
is the vendor's convention rather than a quirk of one body — a candidate map
with determinant +1 should be treated as suspect. It was recorded here as a
proper rotation until 2026-09-29, and that map was wrong; see below.

Scored end to end, against the camera's own stitch, on the same 24 files:

| | All | Upright (≤5°) | Tilted (>5°) |
|---|---|---|---|
| No levelling | 0.33 | 0.54 | 0.30 |
| From the IMU, before the sign fix | 0.83 | 0.88 | 0.67 |
| **From the IMU** | **0.86** | 0.87 | **0.83** |
| Solved against the stitch (ceiling) | 0.88 | | |

n = 25, of which 14 upright and 11 tilted.

🔴 **The mapping is per camera and is never borrowed.** Upright, an X5 reads
gravity along −x and a OneR along +x — opposite signs on the same axis, so
applying one camera's mapping to the other hangs the panorama upside down.
`imu.gravity_up` **refuses** a model it has not measured.

### Measuring the mapping without a levelled reference

Only the X5 embeds a stitch, so for every other camera there is nothing to
score a candidate mapping against. What there is instead is *a lot of files*:
over hundreds of handheld shots the camera is upright **on average**, so the
signed permutation that carries the population's median reading to vertical is
the mapping.

That is an assumption about photographers, not a measurement, so it was
**validated on the X5 first** — the one camera where the answer is already
known from its own stitch. The estimator picks `(+z, −x, −y)`: exactly the
mapping measured directly, at 0.24° off vertical, with the next candidate class
89.7° away.

Applied to the OneR it gave:

```
up_render = (−a_x, a_y, −a_z)          # Insta360 OneR -- WRONG, see below
```

| Evidence | Result |
|---|---|
| Files, and separate days | 379 stills over **31 dates** — per-day medians agree within ~10° |
| Separation from the runner-up | best 6.3° off vertical, next class **81.8°** |
| Independent cross-check | lands within **5.9°** of the body-up that `body_roll` derives from the *calibration string*, which knows nothing of the IMU |
| Visual, on the failure cases | shots the IMU calls tilted 90–152° go from upside-down to level; shots it calls upright render identically to route 0 |

That last row is the one that matters. Route 0 applies the same constant to
every file, so it cannot straighten a tilted shot — and the near-upright
control rules out the mapping simply rotating everything at random.

⚠️ The 6.3° residual means the population's average attitude is 6° off
vertical under this mapping. Whether that is how people hold a OneR or a small
mounting tilt is **not established**; on the X5 the exact permutation beat a
least-squares fit when scored against the stitch, which is weak evidence that
the idealised permutation is right and the residual is behaviour.

### 🔴 That mapping was wrong, and so was the method that produced it

Corrected **2026-09-29**, against Insta360 Studio's own horizon-levelled
exports of the same files — the first reference for this camera not produced by
this project.

```
up_render = (−a_x, −a_z, a_y)          # Insta360 OneR
```

Measured over 358 stills, rendered through this library and compared to the
export by feature correspondence, reporting the angle between the two zenith
directions:

| Inertial encoding | Old map | **This map** | p90 | Within 5° |
|---|---|---|---|---|
| 56-byte | 9.1° | **1.2°** | 3.8° | 91% |
| 20-byte | 61.5° | **1.0°** | 2.4° | 100% |

Both encodings pick the same map independently, over **every** OneR still in
the library that carries an inertial record — 379 files, not a sample.

The **X5 is the control**, twice over. Its map was measured directly against
its own stitch long before any of this, and running the same search against
Studio returns that same map, with the runner-up 4.5° away: the search changes
a map only where the map is wrong.

🔴 **Studio is not a second opinion — it reproduces the device.** On X5 files,
which carry an on-device levelled stitch, Studio's export and the camera's own
stitch agree to **0.03°** (p90 0.39°, n=47). So the residual degrees in the
table above are this renderer's, not a disagreement between stitchers, and
they are worth chasing rather than accepting as a floor.

🔴 **The failure was the reference, not the search.** Every row of the evidence
table above is scored against where `body_roll` puts the zenith. That is the
camera body's idea of up, not the world's, and for this camera it is
systematically off — so the estimator, the "independent cross-check" at 5.9°,
and the 81.8° separation from the runner-up were all measuring agreement with
the same wrong thing. A separation that large is not a guarantee of
correctness; it only says the candidates disagree about the proxy.

⚠️ **Two things recorded here as findings were this defect.** The OneR's 10.8°
"residual wobble" after levelling was the map, not the camera. So was the claim
that the 20-byte entry encoding could not be reconciled by any signed
permutation — the permutation search was correct, and was scored against the
same bad proxy. There was never a second encoding problem. Under the corrected
map the two encodings agree to within a tenth of a degree.

⚠️ **The X3 refusal below is NOT resolved by this.** Its failure is
inconsistency *between sessions*, which no fixed mapping of any kind can repair.
It remains refused, and still has no export to score against.

### ⛔ Why the X3 *was* refused — and why that was wrong

The same estimator produces an answer for the X3. It is wrong, and the way it
fails is worth recording.

No signed permutation fits at all: the best is **36.9°** off vertical, against
0.24° for the X5. Fitting a general rotation instead does reach vertical by
construction — and **visibly tips shots that render level without any tilt
correction at all**.

The reason is visible in the per-session medians. The X3 sample is 38 files
over 5 days, and two of those days supply 25 of them:

| Date | Files | Median reading | From the pooled median |
|---|---|---|---|
| 2024-05-13 | 15 | (−0.613, −0.789, +0.043) | 1.2° |
| 2024-05-16 | 10 | (−0.599, −0.800, −0.015) | 2.3° |
| 2024-05-14 | 6 | (−0.690, −0.724, +0.023) | 5.7° |
| 2024-05-23 | 6 | (−0.760, −0.553, −0.340) | **26.3°** |
| 2025-01-25 | 1 | (−0.941, −0.337, −0.022) | **32.5°** |

Files from 2024-05-13 and 2024-05-23 **both render level with no tilt
correction**, yet their inertial medians are 26° apart. The conclusion drawn
was that no fixed mapping can level both, so the camera was refused.

🔴 **That conclusion was wrong, and it was wrong for the same reason the OneR's
map was wrong: it is measured against the calibration's zenith.** The readings
really do differ between those sessions — that part was observed correctly —
but that is how the camera was *held* on those days, not how it reports. Scored
against a real horizon instead, one fixed mapping levels every session:

```
up_render = (−a_z, −a_x, −a_y)         # Insta360 X3 — the same map as the X5
```

| Session | Files | Gravity | Mounting angle alone |
|---|---|---|---|
| 2024-05-13 | 15 | **0.96°** | 52.31° |
| 2024-05-14 | 6 | **0.68°** | 46.01° |
| 2024-05-16 | 10 | **0.78°** | 52.99° |
| 2024-05-23 | 6 | **1.00°** | 48.72° |

38 files, 0.83° median, p90 1.67°, every one within 5°. The search that found
it returns the X5's and the OneR's maps **unchanged**, which is what separates
measuring from fitting.

⚠️ The lesson is about the yardstick, not the arithmetic. "Two sessions
disagree, therefore the sensor is unreliable" assumed the sessions shared an
attitude, and the only evidence for that was the same proxy under test.

### ✅ The azimuth disagreement, explained

This document previously recorded an unexplained anomaly: the tilt *magnitude*
the IMU predicted matched the solved rotation within ±1.5°, the *azimuth* did
not, the error grew with tilt, and **no single offset fitted**.

The reason no offset fitted is that it was never an offset. Comparing the two
per file, the azimuths are **negatives of each other** — a reflection, which no
rotation about the vertical can express:

| | Disagreement with the solved rotation, tilted frames |
|---|---|
| As it was | 13.97° median, 71.14° worst |
| Mirroring the x component | **1.69° median, 10.39° worst** |

So one sign in the X5's axis map was wrong, in the one component that leaves
the tilt magnitude untouched while flipping its direction. That is why the
magnitude always looked right. Corrected above; the end-to-end scores in the
table are after the fix.

⚠️ What remains: the two worst frames are still ~10° out, and they are the two
most tilted in the library (50° and 47°). Whether that is accelerometer error
under motion, or something else, is not established.

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
