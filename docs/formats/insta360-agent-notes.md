# Insta360 container: research notes

These are the detailed working notes behind the reader: every measurement, the method behind it, and the conclusions that turned out to be wrong, kept so that nobody repeats them. Most of it was written by the coding agents that did the measuring, for whoever (human or agent) changes the reader next. **If you just want to know what is in an Insta360 file, read [insta360.md](insta360.md) instead.**

Counts below are from the library as it stood when each measurement was taken, mostly 1,415 stills; later sections say where a number has since been superseded.

Everything here was measured directly from files produced by **Insta360** cameras that I (or my friends) own. Where something is inferred rather than measured, it says so. That distinction is deliberate, and claims that have not earned their confidence are marked **unverified**.

The evidence base matters, because two of the findings below are differences *between* cameras that a single-camera sample cannot see:

| Model | Files | Firmware | Trailer |
|---|---|---|---|
| OneR | 1,344 | v1.0.83 … v1.3.8 | version 3 |
| X3 | 40 | v1.2.16, v1.2.64/66 | version 3 |
| X5 | 25 | v1.10.7_build2 | version 3 |

That is every `.insp` in one test library, 1,415 files in all, of which 1,409 parse. The six that do not parse carry no trailer at all: two are exported JPEGs with the trailer stripped, four are zero-filled files.

Other camera models and firmware revisions may still differ. The parser in this repository validates its own assumptions rather than trusting them (see [The self-check](#the-self-check)).

## The outer containers

| Extension | Container | Contents |
|---|---|---|
| `.insp` | JPEG | One dual-fisheye still: two circular images side by side |
| `.insv` | MP4 | Two separate HEVC video streams, one per lens, plus AAC audio |
| `.lrv` | MP4 | Low-bitrate H.264 proxy, also dual fisheye |

Because both are valid standard containers, ordinary decoders open them and show something. An `.insp` opens in any image viewer and looks like two fisheye circles. Not all cameras store a stitched image. Still dimensions are per camera, and the X5 and X3 each have photos in my library taken in two modes:

| Model | Still size | Files |
|---|---|---|
| OneR | 6080×3040 | 1,344 |
| X3 | 5952×2976 | 39 |
| X3 | 11968×5984 | 1 |
| X5 | 5888×2944 | 7 |
| X5 | 11904×5952 | 18 |

Each is two square cells side by side. Measured on an X5, video is two 2880×2880 HEVC streams at 59.94 fps, around 154 Mbps combined.

An `.lrv` is a dual fisheye *proxy*, so it is no more viewable than the master. Insta360's phone app and Studio both use it as a fast preview, and Studio expects the `.insv` and `.lrv` to be imported together ([Insta360's import guide](https://onlinemanual.insta360.com/studio/en-us/troubleshooting/file-import-issue/media-import-issue)).

### Getting the full-resolution frame out

For a `.insp`, the JPEG is everything in front of the trailer, so the frame comes out by slicing the file at the trailer offset. `golblick render` projects from this rather than from record `0x0200`, which is a tenth of the pixels on a OneR.

Worth checking that the slice ends on `FFD9`. The trailer is appended after the JPEG's own end marker, so the two boundaries must coincide; if they do not, the trailer was misparsed and everything downstream is built on it.

⚠️ **The frame header is a long way in.** These files carry a run of `APP2` segments in front of the `SOF` marker (10 or 11 on a OneR and X3, 76 on the X5 measured), so the dimensions sit about **0.6 MB** into a OneR file and **4.9 MB** into an X5 one. A reader that scans only the first megabyte finds no frame header, and must not conclude the file is malformed. This cost one wrong census.

✅ **What the `APP2` run holds is the preview, again.** Concatenate every `APP2` payload in front of the `SOF` marker and the result is **byte-identical to the payload of trailer record `0x0200`**, which is the dual-fisheye JPEG on a OneR and X3 and the raw NV12 plane on an X5. Measured on **all 1,384 files that carry record `0x0200`**; the other 31 are 25 OneR stills with no preview record and the 6 with no trailer.

So the camera writes its preview twice: once through the standard JPEG segment mechanism, once in the proprietary trailer. That is worth knowing because the first copy is reachable **without parsing the trailer at all**. Reassembling `APP2` segments is ordinary JPEG parsing, which any imaging library already does. On an X5 that yields the equirectangular stitch directly.

⚠️ One caveat if you take that route: the `APP2` copy is the payload **without** record `0x0200`'s 40-byte header, and on the X5 that header is where the NV12 dimensions are declared. A reader that skips the trailer gets X5 pixels with no stated geometry.

## The trailer

Appended after the container's own data, so standard decoders never see it. Read it **backwards from EOF**.

```
...record data...
[pad]                  32 zero bytes on every file measured (see below)
uint32   trailer_size  total trailer length, this footer and magic included
uint32   version       3
char[32] magic         "8db42d694ccc418790edff439fe026bf"
```

`trailer_size` is measured from the end of the file, so the trailer occupies `[filesize - trailer_size, filesize)`. This matters in practice: an `.insv` master can run to many gigabytes, and the trailer can be read without touching the rest of the file.

### Records

Records sit in front of the footer. Each is **followed** by its own six-byte footer rather than preceded by a header, so the sequence is walked backwards:

```
<record data>
uint16 record_id
uint32 record_size     length of the data immediately preceding this footer
```

Record ids observed:

| Id | Size (example) | Contents |
|---|---|---|
| `0x0101` | 2,956 B | protobuf: serial, model, firmware, dimensions, **calibration** |
| `0x0200` | varies | The camera's own full-size preview (see [below](#record-0x0200--the-cameras-own-preview)) |
| `0x0300` | 2,000 B | IMU samples (see [below](#record-0x0300--imu)) |
| `0x0900` | 7,008 B | **Unidentified**. Frequently zero-length |
| `0x0b00` | 38,982 B | **Unidentified**. Frequently zero-length |
| `0x0000` | 310 B | X5 video only: an index of where the other records sit (see [below](#the-self-check)) |
| `0x0400`, `0x0700`, `0x0a00`, `0x0c00`, `0x1600`, `0x1b00`, `0x1c00`, `0x1d00` | 35 B to 8.3 MB | X5 video only. **Unidentified** |

### Zero-length records

A record may declare a size of **0**: it is then nothing but its own six-byte footer. `0x0900` and `0x0b00` appear this way on most OneR and X3 files (898 of the 1,415 measured, which is 63% of the library).

This is worth stating plainly because reading a zero size as "no more records" is a natural mistake, and an expensive one: it ends the walk six or twelve bytes short of the trailer boundary, the self-check below then correctly refuses the file, and the reader rejects most of a real library while parsing the sample it was developed against perfectly. An empty record is data, not a terminator.

### The padding

Between the last record and the trailer footer sit 32 zero bytes on every file measured. **Nothing in the format announces this**, and it is not derivable from any field, so treating it as a constant would be a guess.

⚠️ The pad and an empty record are **not distinguishable byte for byte**, because six zero bytes read equally well as padding or as a record with id 0 and size 0. The reader breaks the tie by treating id `0x0000` as padding, since no record has ever been observed with that id. Without that rule a run of zero bytes whose length divides by six makes the discovered pad width ambiguous, and the self-check stops being decisive.

### The self-check

The record walk has a natural correctness proof: it must consume the records region **exactly**, ending on the trailer's first byte. The reader therefore tries the plausible padding widths and keeps whichever one makes the walk land on the boundary. A wrong pad width, or a changed layout in future firmware, leaves the walk ending somewhere else, and the reader raises instead of returning plausible-looking nonsense.

✅ **X5 video uses an indexed layout, and is read through the index.** Measured 2026-10-02 over every video in the test library: 163 OneR and 2 X3 `.insv` masters and 3 X3 `.lrv` proxies walk as above, and all 44 X5 `.insv` and 39 X5 `.lrv` failed to (the OneR's 88 `_10_` second-lens files and 6 `.lrv` proxies from 2026 whose last bytes are all zero carry no trailer at all). The X5 video trailer is still version 3 with the same magic and the same 32-byte pad, but its records are not contiguous: they are scattered through the trailer with gaps between them, and the gaps hold either zeros or high-entropy bytes that look like leftovers of earlier records, so no backward walk can close. The last record before the pad has id `0x0000` and is an index of 310 bytes, 31 entries of 10: a `uint16` record id with its bytes in the opposite order to the record footer's, a `uint32` record size, and a `uint32` offset of the record data from the start of the trailer. Unused entries are all zero. On all 83 files every entry points at a record whose own footer repeats the entry's id and size, no two records overlap, the last record ends exactly where the index begins, and entry *n* holds the record whose id has high byte *n*. Independent check: exiftool 13.50 reads id 0 as a "directory table" (its comment cites the Ace Pro) and reported the same offsets and sizes on an X5 `.lrv`. The reader tries the index only after every padding width has failed to close a walk, so no file that parsed before is reinterpreted, and it refuses the file unless the first three properties hold, the last one standing in for the boundary check. The slot-numbering property is observed, not enforced. **Unverified:** why the gaps exist (on the one file checked, the absolute file offsets of most records are multiples of 256 KiB, which suggests the camera reserves aligned space, but nothing was measured to confirm it), and what any of the eight video-only ids contain. Without the index, id `0x0000` would read as padding, which is why the walk still stops on it.

## Record `0x0101` — metadata

Standard protobuf wire format. No schema is published, so this project reads fields by number and does not attempt to model the message; a firmware revision that adds or renumbers fields then degrades to "that field is missing" rather than failing outright.

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

The most useful finding in the format, and the one that makes open tooling viable: **calibration is stored as underscore-delimited ASCII**, not packed binary, and the richer cameras store it **several times** at increasing fidelity.

**How many models you get depends on the camera**, so tooling must not require the richest one to be present:

| Model | Calibration fields | Count |
|---|---|---|
| OneR | 5 | one model only |
| X3 | 5, 53, 54 | three |
| X5 | 5, 53, 54, 111 | four |

Field 5, the equidistant model, is the only one present on every file measured, and the only one whose interior is confirmed. A renderer that works from field 5 therefore covers the whole library; one that requires field 111 covers 25 files out of 1,415.

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

**Parameters are quoted against a reference frame that is usually not the image size**, so they must be scaled by `actual_width / reference_width` before use. The reference frame is carried in the calibration string itself. Read it from there, because it is **per camera**, not a constant of the format:

| Model | Reference frame | Still size | Scale |
|---|---|---|---|
| OneR | 6080×3040 | 6080×3040 | 1.0 (the one camera where they coincide) |
| X3 | 11904×5952 | 5952×2976 | 0.5 |
| X5 | 10752×5376 | 5888×2944 | 0.547619 |
| X5 | 10752×5376 | 11904×5952 | 1.107143 (note this one is **above 1**) |

🔴 An earlier version of this document gave 10752×5376 as a property of the format. It is the X5's value. Hard-coding it would misplace every lens circle on a OneR, which is 1,344 of the 1,415 files measured. Scaling is also not always a reduction: the X5's high-resolution still mode is *wider* than its own reference frame.

The scaling rule is verifiable geometrically rather than by assertion. On the X5, the equidistant lens radius of 2650.989 scales to **1451.7 px**, against a half-cell of 1472 px: the image circle lands just inside its half of the frame, which is what a fisheye circle should do. The repository asserts this in a test.

### Lens orientation differs between cameras — do not assume 0/180

The equidistant model's sixth per-lens value (yaw) is **constant for a given camera** and differs sharply between them:

| Model | Lens 0 yaw | Lens 1 yaw | Files | Bodies |
|---|---|---|---|---|
| OneR | −178.89° | 0.22° | 1,344 | 1 |
| X3 | 88.99° | 89.86° | 40 | 1 |
| X5 | 90.05° | 89.71° | 25 | 1 |

✅ **Yaw is the sensor's rotation within its own image circle, not the direction the lens points.** That is why both X5 lenses read ~90°: the sensors are mounted a quarter turn round, and the two lenses face opposite ways by construction. Read in each lens's own frame, every camera states the back-to-back flip the same way: the two yaws **sum** to about ±180° (OneR −178.67°, X3 +178.85°, X5 +179.76°), and what is left over is the small relative rotation. The OneR only looks different because it puts the half turn in lens 0 and the X3 and X5 split it between the two.

So what a renderer needs is the **relative** rotation, taken modulo 180°. Each lens states its yaw **in its own frame**, and lens 1 faces the other way, so a rotation about the shared axis that lens 1 states as positive is negative in lens 0's frame. The relative rotation is therefore the **sum**, negated:

```
relative spin = −(yaw₀ + yaw₁)   mod 180°
```

| Model | Stored yaw 0 | Stored yaw 1 | −(sum) mod 180° | Against the vendor's stitch | Difference mod 180° (wrong) |
|---|---|---|---|---|---|
| OneR | −178.890° | +0.218° | **−1.328°** | −1.328° | −0.892° |
| X3 | +88.992° | +89.858° | **+1.150°** | +1.116° | +0.866° |
| X5 | +90.047° | +89.714° | **+0.239°** | +0.247° | −0.333° |

"Against the vendor's stitch" is the relative rotation recovered by matching each lens of a render, block by block, against an independent stitch of the same file: Insta360 Studio exports for the OneR (14 scenes, spread 0.03°) and the X3 (2 scenes), and the stitch the X5 embeds in its own file (12 scenes). Away from the seam each lens appears alone in the reference, so every block measures one lens's placement, and the global alignment cancels out of the difference between the two lenses.

🔴 **An earlier version of this document gave the relative rotation as the difference of the two yaws**, and supported it with a "Measured" column from maximising lens agreement in the overlap: −1.39°, +0.87° and +0.17°. That column favoured the sum on two cameras of three and was read as confirming the difference. On a OneR the error is 0.44°, about 5 px at 4096 wide along the whole seam. It broke every horizon that crossed the seam, and overlap agreement could not see it: the two lenses disagree 21% less in the overlap once it is corrected (40 of 40 frames improve).

### The fourth and fifth values are small rotations, in the same own-frame sense

The fourth and fifth per-lens values are rotations about the lens's own x and y axes, in degrees, stated in that lens's own frame, like the yaw. In lens 0's frame, lens 1's x reverses, so the relative rotation they predict is `(−(v₄⁰ + v₄¹), v₅¹ − v₅⁰)` about x and y.

| Model | Predicted about x | Measured about x | Predicted about y | Measured about y |
|---|---|---|---|---|
| OneR | −0.572° | −0.539° | −0.001° | −0.018° |
| X3 | −0.027° | −0.046° | +0.047° | **−0.330°** |
| X5 | −0.142° | −0.104° | −0.135° | **+0.212°** (spread 0.29°) |

✅ Confirmed on a OneR on both axes, which is 95% of the library measured.

⚠️ **Unverified about y on the X3 and X5.** Both show a residual of about 0.3° that the stored values do not predict, on the X5 against a reference that is itself noisy. The rotation is applied on every camera, because the rule is one reading of one format and on those two cameras the stored values about y are close to zero anyway, so applying them neither causes nor removes the residual.

🔴 An earlier version of this document said these two values "score worse than ignoring them, so the convention is wrong", and later work searched 48 axis, sign and order conventions against lens agreement. The search could only apply the same signs to both lenses, and the own-frame reading needs opposite signs about x. It also could not reach the spin error, which was larger.

⚠️ **The rim angle is not in the file.** The equidistant model gives the image circle's radius in pixels but not the angle that rim corresponds to, so it has to be fitted. Recovered by scoring: **194° on the X5 and the OneR, 192° on the X3.** ⚠️ Refitted on 2026-10-01 with the lenses in register, the OneR and X3 values hold; the X5's does not settle. Lens agreement prefers 198°, while the stitch the X5 embeds puts its rim at 194°. It stays at 194° until something decides between them.

### The equidistant model is close, but not exact

The equidistant model maps the angle off a lens's axis linearly to radius in its image circle. Matching single-lens blocks of a render against Insta360 Studio's export of the same file, as for the rotations above, shows that **no lens here is exactly equidistant**. The departure is a smooth curve that is the same for both lenses of a camera and the same in every scene measured. It is not in the file.

Correction to the equidistant model, in degrees: a direction at the angle shown is recorded where the equidistant model would put that angle **plus** this.

| Angle off the axis | 10° | 20° | 30° | 40° | 50° | 60° | 70° | 74° | 80° | 86° |
|---|---|---|---|---|---|---|---|---|---|---|
| OneR (194°) | −0.02 | −0.23 | −0.32 | −0.15 | +0.31 | +0.92 | +1.39 | **+1.45** | +1.29 | +0.72 |
| X3 (192°) | −0.74 | −1.27 | −1.64 | **−1.75** | −1.50 | −0.86 | −0.02 | +0.28 | +0.56 | +0.45 |

Held out means scored on scenes the curve was not fitted on: the other seven bursts for the OneR, and the other scene for the X3. Distances are median displacement against Studio at 2048 wide.

| | Measured on | Fit residual | Held out, uncorrected | Held out, corrected |
|---|---|---|---|---|
| OneR | 14 scenes | 0.017° RMS | 9.8 px | **3.0 px**, 7 of 7 scenes better |
| X3 | 2 scenes | 0.044° RMS | 3.95 px and 2.89 px | **1.02 px** and **1.10 px** |

Studio shows a blend near the seam, so it constrains the curve only out to about 86°. Beyond that the curve is continued in a straight line. That rule has no free parameter, and lens agreement across the seam, scored on bursts it was not chosen on, prefers it to any bend: 12% better than no correction on a OneR, and better on all 40 X3 frames tried.

⚠️ **Two X3 scenes is thin.** They agree to within 0.2° in every bin, but it is still two scenes. ⚠️ **The X5 is not corrected, and a fixed correction is measured not to help.** Measured 2026-10-02 on all 48 X5 stills against both the embedded stitch and Insta360 Studio exports. The curve has a repeatable shape (the reference puts content further from the axis, peaking around +1.2° at 40–50°) but its size varies from 0.1° to 2.9° by scene, and the two references agree with each other per scene to about 0.2–0.3°. On one frame exported in all four Studio stitching modes, the profiles are identical to 0.02°. Held out at 2048 wide: uncorrected 5.5 px against the stitch and 6.7 px against Studio; a table fitted on half the files gave 6.7–7.0 and 5.7–6.9, better on only 7–8 of 15. So both references appear to adapt the stitch to the scene, and neither can measure a fixed lens curve. ⚠️ Unverified: that the size follows scene depth (indoor scenes show 1.5–2.4°, open outdoor ones the least). Settling it needs a reference that does not adapt, such as a test chart or a distant-only scene. On the field of view, lens agreement prefers 198° on firmware v1.10.7 and v1.11.10 and 194° on v1.7.43 and v1.9.6, but the latter are all from one trip, so firmware and scene are confounded; the references' curve is a bump that returns towards zero at the rim, which neither value fits. ⚠️ The table depends on the field of view it was fitted at: a table fitted at 194° and used at 192° double-counts the difference.

### The absolute yaw is the mounting angle, and it levels the roll axis for free

The *relative* yaw is what a renderer needs to place the two hemispheres correctly. The **absolute** value turns out to be worth just as much, and was discarded for longer than it should have been.

Rendering with lens 0 as the reference produces a panorama in **lens 0's sensor frame**. That frame is not the camera body's, because the sensor is mounted at an angle, and the angle differs by 90° between a OneR and an X3/X5. So the same correct projection code yields an upright X3 and a OneR lying on its side.

The stored yaw is quoted against a reference 90° from the body's up, so:

```
body_roll = 90° − yaw₀     (about the lens axis, i.e. the render's roll)
```

| Model | Lens 0 yaw | `body_roll` | Files | Spread over the library |
|---|---|---|---|---|
| OneR | −178.89° | **−91.11°** | 1,344 | **0.00°** |
| X3 | +88.99° | **+1.01°** | 40 | **0.00°** |
| X5 | +90.05° | **−0.05°** | 25 | **0.00°** |

✅ **Verified.** The value has zero spread across all 1,409 files that carry a trailer, so it is a constant of the body rather than anything per-shot. Applying it turns a OneR render from 90° on its side into a level panorama, and moves the X3 and X5 by ~1° and ~0°, matching the fact that those two already rendered upright. Confirmed visually on eight OneR stills spread across the library and four years of capture.

This matters because it is the only levelling that costs nothing: it needs neither a reference stitch (which only the X5 embeds) nor an IMU record (which 965 of 1,344 OneR stills lack), so it applies to **every** file. See [Levelling](#levelling).

⚠️ **It corrects the mounting, not the attitude.** A camera genuinely tilted when the shutter fired is still tilted afterwards. This fixes one axis (roll about the lens axis) and leaves pitch to the other two routes.

⚠️ **The 90° in the formula is fitted to three bodies**, not derived from anything the file states. It holds across a 90° difference in mounting, which is what earns it any trust, but a fourth camera could disagree. The library carries one body per model, so these are three independent samples, not 1,409.

### The calibration is the same in every file from one camera body

For every (camera, field) pair there is **exactly one** distinct calibration string: one across all 1,344 OneR files, one across all 40 X3 files, one across all 25 X5 files, and likewise for fields 53, 54 and 111. It is written into each file rather than re-derived per shot, so it can be cached per camera.

⚠️ The library holds **one body of each model**, with one serial number per model across all 1,415 files. So this measures "constant per body", and cannot distinguish a per-unit factory calibration from a per-model constant. The parameters are lens-specific measurements, which makes per-unit the more likely reading, but that is reasoning, not evidence. Either way the practical consequence stands: 1,415 files provide only **three** independent calibration samples, so agreement across the library is not corroboration.

### What is *not* verified

Field 5's six per-lens values *are* identified: radius, centre x, centre y, roll, pitch, yaw. The convention for roll and pitch is still open, as noted above.

The **interior layout of fields 53, 54 and 111 is inferred from shape**, not confirmed. The names above describe how many numbers appear where; they are not claims about which coefficient means what, and which model Insta360 Studio actually uses is unknown. This library therefore exposes those parameters as a raw tuple rather than as named attributes. Identifying them is the first task of the rendering work.

## Record `0x0200` — the camera's own preview

Previously recorded here as unidentified. It is the camera's own full-size preview, and **what it contains depends on the camera**.

| Model | Encoding | Dimensions | Layout |
|---|---|---|---|
| OneR, X3 | JPEG | 1920×960 | **dual fisheye** |
| X5 | NV12 (YUV 4:2:0) | 2560×1280, declared in the header | **equirectangular stitch** |

The X5 variant is the valuable one: a 2560×1280 panorama, stitched and horizon-levelled on device, sitting in the file with no processing required. It is the same image as the EXIF thumbnail at 64× the pixel count.

### The NV12 header

Forty bytes, then the pixel data. Ten `uint32` fields, identical across all 25 X5 files measured:

```
offset  0  uint32  1          ⚠️ constant; meaning unverified
offset  4  uint32  4915240    the record size, this header included
offset  8  uint32  1          ⚠️ constant; meaning unverified
offset 12  uint32  0
offset 16  uint32  2560       width
offset 20  uint32  1280       height
offset 24  uint32[4]  0
```

Only width and height are identified, and they are enough. The payload is then exactly `width × height × 3 / 2` bytes, as NV12 requires for a full-resolution luma plane followed by one interleaved chroma plane at half resolution in both axes. **That identity is a self-check**, not an assumption: it held on all 25 files, and a reader that finds it broken should refuse rather than hand back a buffer that decodes to garbage.

Because every file measured came from one camera on one firmware, the constants above are **not** established as constants of the format, only as constants of this sample. Treat `1` at offsets 0 and 8 as unexplained, not as magic to match against.

### How the layout was established

The encoding predicts the layout on every file measured, but the format does not announce it, so it is an observation about two camera generations rather than a rule. Measured on all 1,409 files that parse, by the mean brightness of the frame corners, which a fisheye pair leaves outside the image circle and therefore black:

| Group | n | Corner brightness | Reading |
|---|---|---|---|
| OneR JPEG | 1,319 | 0.0–24.7, median 0.0 | fisheye pair |
| X3 JPEG | 40 | 1.0–19.9, median 3.8 | fisheye pair |
| X5 NV12 | 24 | 147.5–239.0, median 188.9 | stitched |
| X5 NV12 | 1 | 2.8 | an all-black frame; says nothing either way |

## Record `0x0300` — IMU

Each entry is a 64-bit millisecond timecode followed by six values: three accelerometer axes in **g**, then three angular velocities. Both are confirmed against exiftool, value for value, on files from all three cameras.

🔴 **Two encodings, and the entry stride is not a property of the camera model.**

| Stride | Payload | Value |
|---|---|---|
| 20 B | `int64` timecode + 6 × `uint16` | `(raw − 32768) / 1000` |
| 56 B | `int64` timecode + 6 × `float64` | as stored |

Of the 379 OneR stills in one library that carry this record, **285 use the 56-byte form and 94 use the 20-byte one**. Both groups are the same camera model, so the stride must be *searched*, not looked up. `imu.entries` keeps only a stride that divides the record exactly and whose timecodes rise monotonically, and refuses when none fits or more than one does.

⚠️ **Most files carry no IMU at all.** Over all 1,415 `.insp`:

| | Files |
|---|---|
| Decoded | 442 |
| No `0x0300` record | 965 (all OneR, 72% of that camera's stills) |
| No trailer at all | 6 |
| Zero-length record | 2 (X3) |

So an IMU-derived horizon serves **about a third** of this library. Levelling that has to work everywhere needs a second route.

### Why this was previously recorded as undecoded

An earlier pass reported that the payload "does not read as three floats, as doubles, or as plausibly-scaled int16". Two mistakes compounded: the 20-byte stride measured on an X5 was assumed to hold everywhere, so the 56-byte entries were being sliced at the wrong boundary; and the 16-bit form was tried as *signed* rather than as unsigned biased by `0x8000`. Both were settled in minutes once exiftool's decoded output was put beside the raw bytes, which is the cross-check that should have come first.

## The embedded thumbnail

Every `.insp` measured carries a 320×160 thumbnail in EXIF IFD1. **Whether it is a stitch depends on the camera**, and the difference decides what can be built on it:

| Model | n | Thumbnail contents |
|---|---|---|
| X5 | 25 | stitched, horizon-levelled equirectangular |
| X3 | 40 | the dual-fisheye pair, shrunk |
| OneR | 1,344 | the dual-fisheye pair, shrunk |

🔴 An earlier version of this document stated the stitch as a property of the format. It was generalised from two X5 stills, and it is wrong for 1,384 of the 1,415 files measured. The correction is recorded rather than quietly edited, because the mistake is instructive: the sample was not the population.

Two consequences, both now conditional on the camera:

1. **A displayable preview exists without stitching, but only on the X5.** Record `0x0200` gives 2560×1280 there. On a OneR or X3 neither the thumbnail nor `0x0200` is viewable as a panorama, so a photo grid that wants a round picture for those files has to stitch one.
2. **Ground truth exists, but only on the X5.** A stitch built from the calibration data can be scored against the camera's own output, with no reference renders from Insta360 Studio. ⚠️ For OneR and X3 files there is **no embedded stitch to score against at all**, so accuracy on those cameras cannot be measured this way. Since the X5 is also the only camera that carries all four calibration models, the accuracy harness and the richest calibration data happen to coincide on the same 25 files.

## Scoring without a reference

Only the X5 embeds a stitch, so for 98% of the library there is nothing to compare a render against. There is, however, evidence every file carries: the lenses see **past** 180°, so there is a band where both observe the same scene, and a correct projection makes those two views coincide.

Pearson correlation over that overlap band, on one still per camera:

| Model | Fitted rim angle | Overlap agreement |
|---|---|---|
| X5 | 194° | +0.75 |
| OneR | 194° | +0.71 |
| X3 | 192° | +0.90 |

A wrong rotation convention drops this to about **+0.02**, so it discriminates sharply. It is also what identified the yaw, and it needs no vendor software and no embedded stitch.

🔴 It compares the lenses to *each other*, not to the world, so it is **blind to the absolute orientation** of the result. Because lens 1 faces backwards, a rotation of the world about the lens axis appears as +a in one lens and −a in the other and leaves the score untouched. A render scored this way can still be upside down. Levelling has to come from the camera's own stitch (X5 only) or from the gravity vector in the IMU record (see [Levelling](#levelling)).

⚠️ It is also not a sharpness measure: it rewards the hemispheres agreeing, and says nothing about parallax at the seam, which no calibration fixes.

## Levelling

A projection built from the calibration is correct and **arbitrarily oriented**, because the calibration fixes the lenses relative to each other, not relative to the world. Three routes put the horizon where it belongs, and they answer different questions.

| Route | What it fixes | Needs | Files it reaches (of 1,415) |
|---|---|---|---|
| 0: the mounting angle | Roll about the lens axis | Nothing beyond the calibration | **1,409** |
| 1: solve against the stitch | All three axes | An embedded stitch (X5 only) | 25 |
| 2: gravity from the IMU | Pitch and roll | An IMU record *and* a measured axis mapping | **404** |

Route 0 is partial and reaches everything; route 2 is the accurate one and now reaches 404 files rather than 25, because the OneR's axis mapping has been measured. The two compose in practice: prefer gravity where it exists, fall back to the mounting angle where it does not.

⚠️ Superseded: that 404 predates both the X3's measured mapping and burst borrowing. Measured over 1,438 stills, **1,432** are levelled, 1,384 of them from gravity (417 from their own record, 967 from another frame of the same shutter press) and 48 from an on-device stitch. The 6 that are not carry no trailer.

🔴 **The 965 files with no inertial record cannot be levelled, and that is a property of the files rather than a gap in this reader.** Insta360's own Studio, given the same files, produces an export that agrees with route 0 alone to **0.8°** (p90 0.9°, n=7), so it is not levelling them either. Nothing further is recoverable from a still that carries no `0x0300`.

### Route 0 — the sensor mounting angle, from the calibration alone

The cheapest correction, and the one that was missed longest. The absolute yaw in the equidistant model is the sensor's mounting angle in the camera body, so rolling the render by `90° − yaw₀` about the lens axis lands it in the body frame. On a OneR that is a **91° correction**; without it every one of the 1,344 OneR stills renders on its side.

It needs no reference and no IMU, so it applies to every file that carries a trailer. It fixes one axis only: a camera that was genuinely tilted stays tilted. See [The absolute yaw is the mounting angle](#the-absolute-yaw-is-the-mounting-angle-and-it-levels-the-roll-axis-for-free) for the measurement and its limits. `render.body_orientation`.

### Route 1 — solve the rotation against the camera's own stitch

Record `0x0200` on an X5 is horizon-levelled, so the rotation between it and a raw render *is* the camera's levelling. `render.fit_orientation` searches for it: yaw is exactly a horizontal shift in equirectangular, so it comes out of one FFT cross-correlation per candidate tilt rather than a third axis of grid search, and three quartering passes take the grid from 10° to under 0.2°.

Over the 25 X5 stills in one library: **24 aligned, 1 refused**. The refusal is an all-black exposure, which carries 0.3–0.6 grey levels of deviation where a real frame carries 50–65, and which aligned to a confident-looking nonsense rotation before that check existed.

| | Correlation with the camera's stitch |
|---|---|
| No levelling | 0.18 median |
| Solved rotation | **0.88 median** (0.82–0.96) |

🔴 **Yaw is a constant, not a variable.** Across those 24 files it reads **180.3°, sd 1.8°**. Our render faces the opposite way to the camera's stitch, and always by the same amount. Pitch and roll are not constant at all (−49.8°…+21.4° and −40.8°…+14.1°): those are how the camera was held.

⚠️ This route is ground truth for **25 files in 1,415**. A OneR or X3 embeds the fisheye pair rather than a stitch, so there is nothing to solve against.

✅ **Since 2026-10-07 `golblick render` levels by this route whenever the file has a stitch** (`render.orientation_from_reference`, `--level auto` or `stitch`), and uses gravity only when it cannot. The reason is route 2's failure on long inertial records, below. The alignment runs on a 512×256 render (a global search at 256×128, then a refinement), takes about 8 seconds, composes the correction on the left of the starting orientation (measured: the other three products scored 0.27 or less), and declines below an agreement of 0.5. Over all 48 X5 stills in one library: 47 aligned (agreement 0.68–0.99, median 0.86), leaving a median 0.44° that a second alignment still wants to correct (p90 1.2°, worst 3.0°); the 48th is the all-black exposure, which is refused and falls back to gravity. The same 47 from gravity alone: median 1.9°, p90 3.1°, and three over 5°, the worst 104°. It also fixes the 180° yaw, so the render faces the way the camera's own panorama does.

🔴 **Gravity from a long X5 record can be badly wrong.** Most X5 records are 100 samples; five in one library run 7.7 to 13 seconds, during which the camera was moved, and the median of the whole record is not the attitude at the shutter. Leftover tilt against the stitch, for the four worst:

| Still | Whole record | First 100 samples | Last 100 samples |
|---|---|---|---|
| A, 8.1 s | 9.1° | 3.5° | 33.9° |
| B, 7.8 s | 10.0° | 3.0° | 22.3° |
| C, 7.7 s | 4.8° | 3.3° | 25.2° |
| D, 13.1 s | **103.7°** (rendered upside down) | 46.3° | 129.7° |

No window rescues them: the end of the record, where the camera settles, is the worst, and the start, the best of the three, is still 46° off on D. Where in the record the shutter fired is **not measured**. OneR and X3 records are not affected in practice (longest about 2.8 s, worst median stray 9.5°, and both of the two worst still render upright), and their whole-record median is what was validated against Studio, so it stays: an end-of-record window would move some OneR files by up to 20°.

### Route 2 — the gravity vector from the IMU

The accelerometer says which way is down, on any camera that records one. The axis mapping between the IMU and the render was measured by fitting the 24 solved rotations above; a least-squares fit over all of them landed within 3° of an exact signed permutation, and **the exact permutation scored better than the fit**, with 2.3° median error against the camera's own levelling versus 4.0°:

```
up_render = (−a_z, −a_x, −a_y)         # Insta360 X5
```

🔴 **That map is a reflection (its determinant is −1)**, and that is a measurement, not a slip. It says the stored triple, *as decoded here*, is not a right-handed (x, y, z) on this camera. Two components transposed, or one inverted in the camera's own convention, would both produce it and nothing measured distinguishes them, so the composite is recorded rather than a story about which axis is which. ⚠️ The OneR's map is **also** a reflection, so this is the vendor's convention rather than a quirk of one body, and a candidate map with determinant +1 should be treated as suspect. It was recorded here as a proper rotation until 2026-09-29, and that map was wrong; see below.

Scored end to end, against the camera's own stitch, on the same 24 files:

| | All | Upright (≤5°) | Tilted (>5°) |
|---|---|---|---|
| No levelling | 0.33 | 0.54 | 0.30 |
| From the IMU, before the sign fix | 0.83 | 0.88 | 0.67 |
| **From the IMU** | **0.86** | 0.87 | **0.83** |
| Solved against the stitch (ceiling) | 0.88 | | |

n = 25, of which 14 upright and 11 tilted.

🔴 **The mapping is per camera and is never borrowed.** Upright, an X5 reads gravity along −x and a OneR along +x. Those are opposite signs on the same axis, so applying one camera's mapping to the other hangs the panorama upside down. `imu.gravity_up` **refuses** a model it has not measured.

### Measuring the mapping without a levelled reference

Only the X5 embeds a stitch, so for every other camera there is nothing to score a candidate mapping against. What there is instead is *a lot of files*: over hundreds of handheld shots the camera is upright **on average**, so the signed permutation that carries the population's median reading to vertical is the mapping.

That is an assumption about photographers, not a measurement, so it was **validated on the X5 first**, the one camera where the answer is already known from its own stitch. The estimator picks `(+z, −x, −y)`: exactly the mapping measured directly, at 0.24° off vertical, with the next candidate class 89.7° away.

Applied to the OneR it gave:

```
up_render = (−a_x, a_y, −a_z)          # Insta360 OneR -- WRONG, see below
```

| Evidence | Result |
|---|---|
| Files, and separate days | 379 stills over **31 dates** (per-day medians agree within ~10°) |
| Separation from the runner-up | best 6.3° off vertical, next class **81.8°** |
| Independent cross-check | lands within **5.9°** of the body-up that `body_roll` derives from the *calibration string*, which knows nothing of the IMU |
| Visual, on the failure cases | shots the IMU calls tilted 90–152° go from upside-down to level; shots it calls upright render identically to route 0 |

That last row is the one that matters. Route 0 applies the same constant to every file, so it cannot straighten a tilted shot, and the near-upright control rules out the mapping simply rotating everything at random.

⚠️ The 6.3° residual means the population's average attitude is 6° off vertical under this mapping. Whether that is how people hold a OneR or a small mounting tilt is **not established**; on the X5 the exact permutation beat a least-squares fit when scored against the stitch, which is weak evidence that the idealised permutation is right and the residual is behaviour.

### 🔴 That mapping was wrong, and so was the method that produced it

Corrected **2026-09-29**, against Insta360 Studio's own horizon-levelled exports of the same files. They are the first reference for this camera not produced by this project.

```
up_render = (−a_x, −a_z, a_y)          # Insta360 OneR
```

Measured over 358 stills, rendered through this library and compared to the export by feature correspondence, reporting the angle between the two zenith directions:

| Inertial encoding | Old map | **This map** | p90 | Within 5° |
|---|---|---|---|---|
| 56-byte | 9.1° | **1.2°** | 3.8° | 91% |
| 20-byte | 61.5° | **1.0°** | 2.4° | 100% |

Both encodings pick the same map independently, over **every** OneR still in the library that carries an inertial record: 379 files, not a sample.

The **X5 is the control**, twice over. Its map was measured directly against its own stitch long before any of this, and running the same search against Studio returns that same map, with the runner-up 4.5° away: the search changes a map only where the map is wrong.

🔴 **Studio reproduces the device rather than giving a second opinion.** On X5 files, which carry an on-device levelled stitch, Studio's export and the camera's own stitch agree to **0.03°** (p90 0.39°, n=47). So the residual degrees in the table above are this renderer's, not a disagreement between stitchers, and they are worth chasing rather than accepting as a floor.

🔴 **The failure was the reference, not the search.** Every row of the evidence table above is scored against where `body_roll` puts the zenith. That is the camera body's idea of up, not the world's, and for this camera it is systematically off. So the estimator, the "independent cross-check" at 5.9°, and the 81.8° separation from the runner-up were all measuring agreement with the same wrong thing. A separation that large is not a guarantee of correctness; it only says the candidates disagree about the proxy.

⚠️ **Two things recorded here as findings were this defect.** The OneR's 10.8° "residual wobble" after levelling was the map, not the camera. So was the claim that the 20-byte entry encoding could not be reconciled by any signed permutation. The permutation search was correct, but it was scored against the same bad proxy. There was never a second encoding problem. Under the corrected map the two encodings agree to within a tenth of a degree.

⚠️ **The X3 refusal below is NOT resolved by this.** Its failure is inconsistency *between sessions*, which no fixed mapping of any kind can repair. It remains refused, and still has no export to score against.

### ⛔ Why the X3 *was* refused — and why that was wrong

The same estimator produces an answer for the X3. It is wrong, and the way it fails is worth recording.

No signed permutation fits at all: the best is **36.9°** off vertical, against 0.24° for the X5. Fitting a general rotation instead does reach vertical by construction, but it **visibly tips shots that render level without any tilt correction at all**.

The reason is visible in the per-session medians. The X3 sample is 38 files over 5 days, and two of those days supply 25 of them:

| Date | Files | Median reading | From the pooled median |
|---|---|---|---|
| Session 1 | 15 | (−0.613, −0.789, +0.043) | 1.2° |
| Session 3 | 10 | (−0.599, −0.800, −0.015) | 2.3° |
| Session 2 | 6 | (−0.690, −0.724, +0.023) | 5.7° |
| Session 4 | 6 | (−0.760, −0.553, −0.340) | **26.3°** |
| 2025-01-25 | 1 | (−0.941, −0.337, −0.022) | **32.5°** |

Files from 2024-05-13 and 2024-05-23 **both render level with no tilt correction**, yet their inertial medians are 26° apart. The conclusion drawn was that no fixed mapping can level both, so the camera was refused.

🔴 **That conclusion was wrong, and it was wrong for the same reason the OneR's map was wrong: it is measured against the calibration's zenith.** The readings really do differ between those sessions (that part was observed correctly), but that is how the camera was *held* on those days, not how it reports. Scored against a real horizon instead, one fixed mapping levels every session:

```
up_render = (−a_z, −a_x, −a_y)         # Insta360 X3 — the same map as the X5
```

| Session | Files | Gravity | Mounting angle alone |
|---|---|---|---|
| Session 1 | 15 | **0.96°** | 52.31° |
| Session 2 | 6 | **0.68°** | 46.01° |
| Session 3 | 10 | **0.78°** | 52.99° |
| Session 4 | 6 | **1.00°** | 48.72° |

38 files, 0.83° median, p90 1.67°, every one within 5°. The search that found it returns the X5's and the OneR's maps **unchanged**, which is what separates measuring from fitting.

⚠️ The reasoning "two sessions disagree, therefore the sensor is unreliable" assumed the sessions shared an attitude, and the only evidence for that was the same proxy under test.

### ✅ The azimuth disagreement, explained

This document previously recorded an unexplained anomaly: the tilt *magnitude* the IMU predicted matched the solved rotation within ±1.5°, the *azimuth* did not, the error grew with tilt, and **no single offset fitted**.

The reason no offset fitted is that it was never an offset. Comparing the two per file, the azimuths are **negatives of each other**. That is a reflection, which no rotation about the vertical can express:

| | Disagreement with the solved rotation, tilted frames |
|---|---|
| As it was | 13.97° median, 71.14° worst |
| Mirroring the x component | **1.69° median, 10.39° worst** |

So one sign in the X5's axis map was wrong, in the one component that leaves the tilt magnitude untouched while flipping its direction. That is why the magnitude always looked right. Corrected above; the end-to-end scores in the table are after the fix.

⚠️ What remains: the two worst frames are still ~10° out, and they are the two most tilted in the library (50° and 47°). Whether that is accelerometer error under motion, or something else, is not established.

## A measured baseline for naive stitching

Scored by SSIM against the embedded 320×160 thumbnail, for one X5 still. ⚠️ Record `0x0200` supersedes the thumbnail as the reference (it is the same image from the same camera at 2560×1280), so these numbers are a baseline measured against the coarser of the two references, and should be re-measured against `0x0200` before anything is compared to them:

| Approach | SSIM |
|---|---|
| `ffmpeg v360=dfisheye:e:ih_fov=193:iv_fov=193` | 0.448 |
| Same, with orientation corrected | 0.589 |

The orientation correction was found by grid search, not derived. The ceiling is explained: `v360`'s `dfisheye` input cannot express per-lens centre, radius, rotation or distortion, so it discards almost everything the calibration knows, and it applies no seam blending. Two further limits are worth knowing:

- The camera does **horizon levelling** on its output, using gravity. A raw stitch does not, so a handheld shot shows a visibly curved horizon.
- **Parallax at the seam** duplicates or tears objects close to the camera where the hemispheres meet. No amount of calibration fixes this; it needs optical-flow blending.

`v360` and `remap` are **CPU-only** in ffmpeg and do not compose with NVENC, so GPU acceleration applies to encoding, not to the projection.

## Reproducing this

```sh
golblick probe FILE -v        # records, metadata, every calibration model
golblick preview FILE -o p.png  # record 0x0200, the camera's full-size preview
golblick thumb FILE -o t.jpg    # the 320x160 EXIF thumbnail
exiftool -ee3 -G1 -s FILE       # independent cross-check
```

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
