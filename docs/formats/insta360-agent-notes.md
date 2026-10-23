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
| `.insv` | MP4 | One video stream per lens, plus AAC audio. The X5 puts both streams in one file; the OneR and X3 write one file per lens (see below) |
| `.lrv` | MP4 | Low-bitrate proxy with both lenses side by side in one stream |

Because both are valid standard containers, ordinary decoders open them and show something. An `.insp` opens in any image viewer and looks like two fisheye circles. Not all cameras store a stitched image. Still dimensions are per camera, and the X5 and X3 each have photos in my library taken in two modes:

| Model | Still size | Files |
|---|---|---|
| OneR | 6080×3040 | 1,344 |
| X3 | 5952×2976 | 39 |
| X3 | 11968×5984 | 1 |
| X5 | 5888×2944 | 7 |
| X5 | 11904×5952 | 18 |

Each is two square cells side by side. Measured on an X5, video is two 2880×2880 HEVC streams at 59.94 fps, around 154 Mbps combined.

⚠️ **Correction (2026-10-08): the table used to say every `.insv` holds two HEVC streams, which is only the X5.** Measured over every video in the test library (the stream layout with ffprobe, the records with the trailer reader):

| Camera | Master | Second file | Proxy |
|---|---|---|---|
| OneR | `VID_…_00_…insv`, one 2880×2880 stream (lens 0), H.264 (40) or HEVC (46); carries the trailer | `VID_…_10_…insv`, the same for lens 1, **no trailer** (88 files) | `LRV_…_11_…insv` (an `.insv` extension), 736×368, both lenses side by side in one stream (77) |
| X3 | as the OneR, H.264 (2) | as the OneR | `.lrv`, H.264 1024×512, both lenses side by side (3) |
| X5 | one file, two 2880×2880 HEVC streams (44) | none | `.lrv`, H.264 1664×832, both lenses side by side, not stitched (39) |

So on a OneR or X3 the two halves of a clip are two files, paired by name, and only the `_00_` one says anything about the camera.

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
| `0x0400` | 16 B per frame | Video, all three cameras: the frame log, one entry per frame (see [below](#stabilising-video-from-the-record)) |
| `0x0700`, `0x0a00`, `0x0c00`, `0x1600`, `0x1b00`, `0x1c00`, `0x1d00` | 35 B to 8.3 MB | X5 video only. **Unidentified** |

⚠️ Correction (2026-10-11): `0x0400` was listed in the last row as X5-only and unidentified. Every video from all three cameras carries it (22 clips checked), and it is the frame log.

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
| 27 | Video: the sensor crop, `{1: source width, 2: source height, 3: kept width, 4: kept height, 5: x, 6: y}` in the calibration's reference pixels, per lens. See "A video is a crop of the still sensor" |
| 53 | Calibration, polynomial model |
| 54 | Calibration, MEI model |
| 111 | Calibration, extended MEI model |
| 7 | Capture time, `YYYYMMDDhhmmss` as a varint (X5; absent from the OneR file checked) |
| 11 | Location: three doubles, latitude, longitude and a third value (zero or absent without a GPS fix) |
| 26 | On the X5, a submessage holding the file's path on the SD card, e.g. `./DCIM/Camera01/IMG_…insp` |

### What in a still identifies a person

Measured 2026-10-07 on stills from all three cameras, for `golblick share` (`vendors/insta360/share.py`), which clears all of it in place.

| Where | What | How it was found |
|---|---|---|
| EXIF GPS IFD | latitude, longitude, altitude | exiftool; 1,151 of 1,434 readable stills in one library carry a real fix (OneR 1,083/1,346, X3 36/40, X5 32/48) |
| Metadata field 11 | the same latitude and longitude, as doubles | searching every record for the EXIF coordinates as doubles, floats, degrees×10⁷ integers and text: found only here, on all three cameras |
| Metadata field 1 | serial number | its only occurrence in the file, on all three |
| EXIF `DateTime`, `DateTimeOriginal`, `DateTimeDigitized`; field 7 | date and time taken | |
| EXIF `ImageDescription`; field 26 | the file name or SD-card path, which carry the date | |
| Records `0x0900`, `0x0b00` | not decoded | ⚠️ neither the serial nor the coordinates were found in them; nothing more is known |

No XMP in any of them. The OneR and X3 also split a second JFIF image across their APP2 segments; JFIF carries no EXIF.

Insta360 Studio 6.0.6 opens, previews and exports the cleaned copies of a OneR, an X3 and two X5 stills (checked 2026-10-08). It shows the serial as zeros, and the exported JPEGs have blank EXIF dates. Each export still gets a GPS IFD, at latitude 0, longitude 0 and altitude 0, which Studio writes from the cleared field 11; a map would place those exports off the coast of West Africa. In Studio's media library the OneR and X3 copies showed a placeholder instead of a thumbnail and the X5 copies showed one. ⚠️ Whether the OneR and X3 originals get a thumbnail there was not checked; the only bytes that differ from the originals are in the EXIF and metadata fields listed above.

## Calibration

The most useful finding in the format, and the one that makes open tooling viable: **calibration is stored as underscore-delimited ASCII**, not packed binary, and the richer cameras store it **several times** at increasing fidelity.

**How many models you get depends on the camera**, so tooling must not require the richest one to be present:

| Model | Calibration fields | Count |
|---|---|---|
| OneR | 5 | one model only |
| X3 | 5, 53, 54 | three |
| X5 | 5, 53, 54, 111 | four |

Field 5, the equidistant model, is the only one present on every file measured, and the only one whose interior is confirmed in full. Two readings of the richer models have since been measured: field 53's lens offset (see "Field 53 says where the two lenses sit") and field 54's radial curve (see "The equidistant model is close, but not exact"). A renderer that works from field 5 therefore covers the whole library; one that requires field 111 covers 25 files out of 1,415.

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

⚠️ **The rim angle is not in the file.** The equidistant model gives the image circle's radius in pixels but not the angle that rim corresponds to, so it has to be fitted. Recovered by scoring: **194° on the X5 and the OneR, 192° on the X3.** ⚠️ Refitted on 2026-10-01 with the lenses in register, the OneR and X3 values hold; the X5's does not settle. Lens agreement prefers 198°, while the stitch the X5 embeds puts its rim at 194°. It stays at 194° until something decides between them. 🔴 **Corrected 2026-10-10: the X5's 194° was fitted on stills shot with lens guards fitted.** Without guards an X5 photo fits 197.5° and an X5 video 195.3°; guards divide either by 1.0225. (Corrected 2026-10-18: the video figure was the sensor crop showing through, and is 197.5° too once the crop is applied; see "A video is a crop of the still sensor".) See the next section. The OneR and X3 values were not affected: no guards were involved in their measurements, as far as is known.

### Lens guards narrow the field of view (X5)

Clip-on lens guards refract the edge of the view, so a lens with a guard fitted maps a smaller angle onto the same image circle. Nothing in the file records whether one was fitted: no metadata field changes between one camera's guarded and unguarded files (checked field by field over 92 X5 files).

| What | Measured |
|---|---|
| Insta360 Studio's "Standard lens guards" setting against its "off", same frames of four clips | a pure radial scale: +0.24° at 5° off the axis, +1.0° at 45°, +1.9° at 85°, i.e. **2.25% of the angle**, identical on the three clips with enough texture to measure |
| Field of view fitted per file by lens agreement, 48 X5 stills | two tight groups, **193.1–194.8°** (files shot with guards) and **196.5–198.1°** (without), 2.0% apart |
| The same, 44 X5 videos, three frames each | **about 191.2°** with guards and **about 195.3°** without, 2.1% apart |
| At the seam, against Studio exports | a guarded clip breaks at 194° and is continuous at 189.7°; an unguarded clip kinks at 194° and is continuous at 195.3°; an unguarded still lands where Studio puts it at 197.5° and not at 194° |

So the profile stores the unguarded angles (197.5° photo, 195.3° video) and a guard factor of 1.0225. Photo and video differ because a video's lens image is not an exact scaled copy of the still sensor's frame that the calibration describes; the difference is fitted, not explained.

🔴 **Corrected 2026-10-18: explained, and no longer fitted.** The video angles were measured with the still calibration scaled to the video frame, and a video is a crop of the sensor, not a scaled copy. Applying the crop turns 195.3° into 197.6° and 191.2° into 193.3°, the stills' two groups, so the profile now stores one angle per camera. See "A video is a crop of the still sensor".

⚠️ **Unverified: that the two groups are guards and not firmware.** In the files measured, the change from guarded to unguarded coincides with a firmware update (v1.9.6 to v1.10.7). Two things favour guards: the groups are the same 2% apart as Studio's guard setting, and one clip from between the two periods fits best with a guard on **one** lens only (disagreement 26.2 against 30.3 with neither and 32.1 with both), which a firmware change, applied to both lenses, cannot produce. That is one clip.

**Telling them apart per file.** `render.pick_field_of_view` scores the lenses' disagreement over a ring about the bisector at both angles and picks one only if it beats the other by 15%; otherwise it declines and the caller assumes no guards. Over the files above, as ratios of disagreement at the guarded angle to the bare one (guarded picked below 0.85): guarded stills 0.35–0.88, so 7 of 9 detected and two undecided; unguarded stills 0.99–2.67, none flagged; guarded videos 0.43–0.75, all 19 detected; unguarded videos 1.45–2.36, none of 24 flagged; the clip with one guard 1.06, undecided. Python and the Nextcloud app's port give the same scores to four decimals on the same frames.

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

⚠️ **Two X3 scenes is thin.** They agree to within 0.2° in every bin, but it is still two scenes. ⚠️ **The X5 is not corrected, and a fixed correction is measured not to help.** (🔴 Measured at 194° on every file, before lens guards were found; the guarded and unguarded files were mixed in this, so it should be repeated per group.) Measured 2026-10-02 on all 48 X5 stills against both the embedded stitch and Insta360 Studio exports. The curve has a repeatable shape (the reference puts content further from the axis, peaking around +1.2° at 40–50°) but its size varies from 0.1° to 2.9° by scene, and the two references agree with each other per scene to about 0.2–0.3°. On one frame exported in all four Studio stitching modes, the profiles are identical to 0.02°. Held out at 2048 wide: uncorrected 5.5 px against the stitch and 6.7 px against Studio; a table fitted on half the files gave 6.7–7.0 and 5.7–6.9, better on only 7–8 of 15. So both references appear to adapt the stitch to the scene, and neither can measure a fixed lens curve. ⚠️ Unverified: that the size follows scene depth (indoor scenes show 1.5–2.4°, open outdoor ones the least). Settling it needs a reference that does not adapt, such as a test chart or a distant-only scene. On the field of view, lens agreement prefers 198° on firmware v1.10.7 and v1.11.10 and 194° on v1.7.43 and v1.9.6, but the latter are all from one trip, so firmware and scene are confounded; the references' curve is a bump that returns towards zero at the rim, which neither value fits. ⚠️ The table depends on the field of view it was fitted at: a table fitted at 194° and used at 192° double-counts the difference.

✅ **Corrected 2026-10-23: the X5's curve is in the file, in field 54.** Read as the unified camera model (raw360-formats and GyroView read it that way first; see the README's prior art), each lens block of field 54 starts with xi, fx and fy, and its twelfth to fourteenth values are the radial terms k1, k2 and k3. Read as stored, its scale doesn't match the vendor's stitch (GyroView measured 2–5% off, varying between X5 units), so golblick keeps only its shape: the curve is anchored to the equidistant model at 90°, where the fitted field of view already holds the seam, `correction(θ) = 90·r(θ)/r(90°) − θ`, the two lenses averaged (they differ by at most 0.02°). Nothing is fitted to a reference. It peaks at −2.3° around 50° and returns to zero at the rim, the shape the paragraph above describes.

Scored per lens against the camera's own stitch, 10–80° off the axis, orientation refitted for each variant, at 2048 wide: median 11.1 px without it, **2.1 px** with it, better on 43 of 45 photos, and flat at about 2 px from 10° to 80° where the equidistant model ranges 7–12 px (`render` at each photo's own field of view, lens guards decided as shipped). The two exceptions, and the earlier finding that the size varies by scene, are lens guards: the guard decision is wrong on five photos (four judged guarded fit as bare, 1.7–2.4 px at 197.5° against 6–7 px at 193.15°; one judged bare fits as guarded, 2.6 against 6.0 px), and the 2026-10-02 measurement rendered every photo at 194°. With the right angle every X5 photo comes out at 1.4–3.0 px. Lens agreement makes the same wrong guard decisions with either curve; the camera's stitch separates them (alignment 0.965 against 0.908).

The X3 keeps its measured table. Against Insta360 Studio's export of each of its 40 photos, field 54's curve does far better than none (2.6 px against 7.1, 40 of 40) but worse than the table fitted on two of them (1.5 px, better on 39 of 40). The OneR carries no field 54.

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

### Field 53 says where the two lenses sit

The seventh to ninth values of each lens block in field 53 are a position. Lens 0 reads zero on every camera; lens 1 reads:

| Model | Lens 1 relative to lens 0 |
|---|---|
| X5 | (−0.000868, 0.000085, −0.032509) |
| X3 | (−0.000972, 0.000006, −0.027296) |
| OneR | no field 53 |

Read as metres, that is the two lenses' separation through the body, almost entirely along the lens axis, which is the shape a back-to-back camera has.

What is verified is the **direction and its sign**. Near the seam a subject at distance r is seen by the two lenses about b/r radians apart, across the seam. Aiming both lenses at a common point along this direction lines such subjects up (a goggle strap that broke at the seam on an X5 clip becomes continuous, 19% less disagreement in the overlap on held-out frames), and flipping the sign cannot: the search then finds no parallax at all. ⚠️ **The unit is not verified**, and the renderer does not need it: it searches in parallax angle, so only the direction enters.

Two limits follow from the geometry, not from the method:

- **A blind zone.** The lenses overlap by about 15°, so anything closer than roughly b / 15° (about 12 cm on an X5) is never seen by both lenses at the same point. A hand or a glove that close cannot be stitched by anything, Insta360 Studio included.
- **A OneR carries no field 53.** Assuming an axial baseline found nothing on the one OneR clip tried, where the cost was dominated by the lenses' exposure difference in video; not measured further.

⚠️ **Correction (2026-10-10): a wrong field of view looks like a near subject to that search.** A first version also claimed a skier's leg on an X3 clip and 46% less disagreement there. That was mostly the X3's video field of view being 6.5° off (next section): an across-the-seam shift is what both an angle error and parallax produce, so the search "lined up" about 6° of parallax in every direction in every frame, and the warp that did it bent straight lines across the seam. With the angle corrected, both X3 clips have nothing left to line up. Check the angle before trusting a parallax that is the same everywhere.

### Video sees less than the still says (X3, X5)

> 🔴 **Superseded 2026-10-18** by "A video is a crop of the still sensor", below. The angles in this section were real measurements of the wrong thing: a still calibration scaled to the video frame makes every lens too small, and a narrower field of view makes up for it. The OneR row was wrong outright: one clip of a wall right next to the camera, where parallax hides a 10° error. The section is kept as it was, because the method's blind spot is the lesson.

The calibration is quoted against the still sensor's frame, and a video's lens image is not an exact scaled copy of it, so the field of view that makes the lenses meet at the seam differs between photo and video. Measured at the seam on far straight things (a pole, a mountain ridge), which have no parallax and only line up at the right angle:

| Model | Photo | Video | How |
|---|---|---|---|
| X5 | 197.5 | 195.3 | Studio exports and lens agreement (see the lens guards section) |
| X3 | 192 | 185.5 | two clips: steps at 192, 188 and 187; straight at 185 and 186 |
| OneR | 194 | 194 | one clip: straight at 190 and 194, a gap opens at 186 |

Lens agreement on a ring about the seam can NOT settle this: on every camera, OneR included, it keeps falling as the angle shrinks, because the samples move towards the rims, where both lenses are darker and softer. The X3 case was found by the seam planner instead, which kept finding the same parallax everywhere; at 185 and 185.5 it finds none on either clip.

### A video is a crop of the still sensor

The calibration describes the still sensor. A video keeps the centre of each lens's sensor and drops a margin all round, and metadata field 27 records how much: the source side, the kept side, and an x and y offset, in the calibration's reference pixels. Every video trailer in the library carries it (251 files, the rest have no trailer), always as a centred square crop of a square lens:

| Model | Lens side | Kept | Margin | Files |
|---|---|---|---|---|
| OneR | 3040 | 2880 | 80 | 86 masters, 77 proxies |
| X3 | 5952 | 5760 | 96 | 2 masters, 3 proxies |
| X5 | 5376 | 5312 | 32 | 44 masters, 39 proxies |

So a video's lens centres move in by the margin (lens 1 also by lens 0's two margins, since it sits in the right half) and the lens radius stays the same number of sensor pixels. Scaling the still calibration to the video frame, as golblick did until 2026-10-18, puts the centres within half a pixel of the same place and makes the radius too small by kept / side: 5.3% on a OneR, 3.2% on an X3, 1.2% on an X5.

Measured against Insta360 Studio's exports with stitching optimisation and stabilisation off: features matched between one raw lens and the same frame of Studio's panorama, a rotation fitted between the two, and a single multiplier on golblick's lens radius fitted alongside it. A multiplier of 1 means the scaled calibration is right; side / kept means the crop is.

| Clip | Firmware | Best multiplier | RMS | Crop predicts |
|---|---|---|---|---|
| X3 | 1.0.83 | 1.0325–1.035 | 0.088° | 1.0333 |
| OneR | 2.0.8 | 1.0550 | 0.048° | 1.0556 |
| OneR | 1.1.43 | 1.0550 | 0.069° | 1.0556 |
| OneR | 1.2.66 | 1.0550 | 0.061° | 1.0556 |
| OneR | 1.1.43 | 1.0550 | 0.047° | 1.0556 |

The X3 is the control: the fit lands on the crop and on the 185.5° fitted independently at the seam (192 / 185.5 = 1.035). With the crop applied, the same fit gives exactly 1.000 on two OneR clips and the X3. The X5 can't be measured this way: it has no radial correction, so a single multiplier can't fit its lens shape (RMS 0.23°). Its seam-fitted 195.3° agrees with the crop to 0.15°.

What it changed: on a OneR video the seam fell about 4.7° short of the true halfway line on each lens, so about 9° of the scene across the seam was never shown. Anything near the camera could vanish into that band. On the X3 the seam planner had been absorbing the same error as parallax (the correction above).

⚠️ Blind spots: the fit compares against Studio's stitch, so it shares any error Studio makes in the one lens measured. And a radius error and a field-of-view error are the same thing to it. Only centred square crops are understood; anything else is refused.

### What is *not* verified

Field 5's six per-lens values *are* identified: radius, centre x, centre y, roll, pitch, yaw. The convention for roll and pitch is still open, as noted above.

The **interior layout of fields 53, 54 and 111 is inferred from shape**, not confirmed, apart from field 53's lens offset (above). The names above describe how many numbers appear where; they are not claims about which coefficient means what, and which model Insta360 Studio actually uses is unknown. This library therefore exposes those parameters as a raw tuple rather than as named attributes. Identifying them is the first task of the rendering work.

## Record `0x0200` — the camera's own preview

Previously recorded here as unidentified. It is the camera's own full-size preview, and **what it contains depends on the camera**.

| Model | Encoding | Dimensions | Layout |
|---|---|---|---|
| OneR, X3 | JPEG | 1920×960 | **dual fisheye** |
| X5 | NV12 (YUV 4:2:0) | 2560×1280, declared in the header | **equirectangular stitch** |

The X5 variant is the valuable one: a 2560×1280 panorama, stitched and horizon-levelled on device, sitting in the file with no processing required. It is the same image as the EXIF thumbnail at 64× the pixel count.

**In videos it is different again**, measured 2026-10-08 on all 345 `.insv` and `.lrv` files in the test library:

| File | `0x0200` | `0x0500` |
|---|---|---|
| OneR, X3 master (88) | one keyframe of lens 0 at full size (2880×2880), in the clip's own codec | the matching keyframe of lens 1 |
| OneR, X3 proxy (80) | one proxy keyframe, both lenses side by side (736×368 OneR, 1024×512 X3) | byte-identical to `0x0200` on all 80 |
| X5 master and `.lrv` (83) | NV12, 1280×640, equirectangular stitch, the same 40-byte header as stills | absent |
| OneR `_10_` (88), zero-filled `.lrv` (6) | no trailer | |

The keyframe records are a 22-byte header followed by an Annex B stream (an HEVC VPS or an H.264 SPS first) that ffmpeg decodes to one frame. ⚠️ The header is undecoded: bytes 0–3 are `00 00 01 34` or `00 00 00 01`, bytes 16–21 `00 02 00 01 xx 10` with `xx` one of `0c`, `0f`, `10`, `12`. Which frame of the clip the keyframes are is not established; they look like the opening frame, unchecked. So a OneR or X3 clip carries a whole dual-fisheye frame, both lenses, in the `_00_` file's trailer, but as compressed video, which nothing in this project decodes without ffmpeg. The X5's is ready to use as it stands.

**The keyframes are frame 0.** Decoded and compared with the first 40 frames of the `_00_` stream on three clips (OneR HEVC, OneR H.264, X3), the lens-0 keyframe matches frame 0 to within one grey level (mean absolute difference 0.8–1.0) and the next four frames by 1.6 or more. `golblick render` on a OneR or X3 `.insv` decodes both with ffmpeg (`keyframe.py`, `cli._decode_keyframes`), puts lens 0 on the left as in a still, and projects that. Scored against Insta360 Studio's exports of frame 0 of the same five clips (four OneR, one X3; `render.fit_orientation`, tilt of the fitted rotation):

| Ours | Studio export | Tilt left over |
|---|---|---|
| calibration roll only | stitching optimisation off, stabilisation off | 0.9–2.3°, median 1.3° |
| no rotation at all | the same | 91° on the OneR (the sensor mounting), 2.4° on the X3 |
| gravity, median of the whole record | stitching optimisation off, FlowState on | 1.0–3.4°, median 2.7° |
| gravity, first 50 samples (about 0.1 s) | the same | 1.1–2.6°, median 1.9° |

So Studio's export with stabilisation off is the camera's frame with only the mounting corrected, which is what golblick's calibration route produces; the 1.3° between them is the floor this comparison can measure. Its yaw is 180° from ours on all five (179.3–182.1), as with stills. Gravity levels frame 0 to within about 1.5° of that floor. The start of the record did better on 2 clips and the same on 3; that is too few and too small a difference to tune on, so the whole-record median stays. ⚠️ Five clips from two cameras.

On the X5, record `0x0200` matches Studio's FlowState frame 0 with a correlation of 0.99 and 0.6–3.8° of tilt on three clips, so the camera's own stitch is a levelled picture of the opening frame. Whether it is exactly frame 0 was not checked.

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

⚠️ Correction (2026-10-11): the timecode is milliseconds only in the 56-byte form. In the 20-byte form it counts **microseconds**. Measured on 21 videos from all three cameras: with those units, every record spans its video's length plus 0.1 to 3.5 s, starting a little before the first frame and ending a little after the last. The angular velocities are radians per second; see [Stabilising video from the record](#stabilising-video-from-the-record).

⚠️ Two OneR clips repeat a timecode 2 and 5 times in some 100,000 samples, each time next to a step of 3 ms instead of 2. The decoder used to refuse both clips outright. It now accepts a repeat up to 0.1% of the entries and still refuses a timecode that goes backwards, which is what a wrong stride produces.

🔴 **Two encodings, and the entry stride is not a property of the camera model.**

| Stride | Payload | Value |
|---|---|---|
| 20 B | `int64` timecode + 6 × `uint16` | `(raw − 32768) × full scale / 32768`, the full scale from metadata field 65 |
| 56 B | `int64` timecode + 6 × `float64` | as stored |

⚠️ Correction (2026-10-20): the 20-byte form was read as thousandths, `(raw − 32768) / 1000`, which is how exiftool reads it too, and that is close to the unit but not it. Each value counts 1/32768ths of the sensor's full scale. Metadata field 65 gives the two ranges as `{1: g, 2: degrees per second}`, and it reads 32 g and 2000 °/s on all 86 twenty-byte clips in the library (X5, X3, and the OneR from 2023 on); none of the 46 float-form clips carries it. So the accelerometer is `raw / 1024` g and the gyroscope `raw × 2000 / 32768` °/s, and thousandths read them 2.4% high and 6.1% low. The accelerometer shows it. Over the quietest tenth of each record, thousandths put gravity at a median 1.025 g on the X5 and X3 and 1.02 g on the OneR's 20-byte form, against 1.005 g in the float form, and field 65 brings them to 1.00. The direction of gravity is the same either way, so levelling was never affected. Steadying was: every turn of a 20-byte clip came back 6.1% short. `imu.motion` applies field 65 and refuses a 20-byte record without it.

A check from the picture doesn't settle the gain on its own. With field 65 applied, the band's yaw shift per frame against the gyroscope's turn reads 0.93 to 0.99 on four 20-byte clips, and 1.01 on a float-form control, so the scatter is as large as the 6.5% in question. Content fixed to the camera pulls the band down: on the ski clip that read 0.93, the two sectors behind the camera, where the skier is, read 0.05 and 0.07, and the four in front 0.99 to 1.15.

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

## Stabilising video from the record

A video's `0x0300` record covers the whole clip, at 1 kHz on an X3 or X5 and 500 Hz on a OneR, so it can steady every frame. Three things had to be established: the gyroscope's axes and units, when each frame was captured on the record's clock, and a way to score the result.

### The reference: Insta360 Studio, against itself

Eleven clips were exported from Insta360 Studio twice, with stabilisation off and with FlowState, everything else equal. Within a clip the two exports show the same picture turned, so the rotation that lines up frame *k* of one with frame *k* of the other is exactly how Studio steadied that frame. It was solved per frame at 512×256 with the same alignment as [Route 1](#route-1--solve-the-rotation-against-the-cameras-own-stitch), seeded from the frame before; alignment scores were 0.97 to 0.997. Frame 0 of each export is frame 0 of the source clip (cross-correlating frame-to-frame change), and Studio drops the last two frames.

Seven clips were tracked: three X5, three OneR and one X3. One of the OneR clips carries no usable signal, because Studio's FlowState holds it static. An eighth, a OneR clip from 2021 whose gyroscope reads about 0.002 rad/s throughout, was left out.

### The gyroscope shares the accelerometer's axes

Fitting angular velocity from the Studio track against the gyroscope over all 48 signed permutations, then asking which rotation takes the prediction "the accelerometer's map, applied to the gyroscope" into Studio's frame:

| Camera | Residual with the predicted map | Without the reflection sign | Studio's frame from ours |
|---|---|---|---|
| X5 | 0.16 | 1.92 | identity, within 1.4° |
| OneR | 0.58 | 1.75 | yaw 180°, roll −90° (the mounting angle) |

So no new constants: the measured gravity maps carry over. The one twist is that all three cameras' maps are reflections (determinant −1), and an angular velocity is an axial vector, so it changes sign under one. The units are radians per second: the fitted scale was 0.98 to 1.07. ⚠️ Correction (2026-10-20): not in the 20-byte form, which reads 6.1% short until it is scaled by field 65 ([Record `0x0300` — IMU](#record-0x0300--imu)). A fit with that much scatter could not tell 1.00 from 1.065. The OneR residual is higher because its clip moves little and FlowState's own smoothing shows up in the track. The X3's frame (yaw 180°) was confirmed by the horizon: the opening level matches Studio's FlowState frame 0 to 0.76° with it.

⚠️ Measuring this from the record alone failed. Gravity seen from a turning body moves at the gyroscope's rate, but on a steady clip the accelerometer's noise (about 1°) swamps the motion, and on a carried one its direction swings about 9° in every window with walking. Neither fit explained the data (residual 0.64 to 0.97).

### When each frame was captured

- Metadata field 24 is frame 0's timecode on the record's clock. Against Studio, frame 0 fitted within 4 ms of it on an X5 clip and 7 ms on a OneR clip, by cross-correlating the size of the rotation per frame (which needs no axis map).
- Record `0x0400` is the frame log: 16-byte entries, an `int64` timecode on the same clock and a `float64` that reads as the exposure time in seconds (1/1,144 s on a bright X3 clip). It holds 7 to 35 more entries than the video has frames; one clip that continues a split 30-minute recording holds about 600 more, starting 16.7 s before its record.
- On every X3 and X5 clip, field 24 equals one of the log's entries exactly, and the entries from there on are the frames. On a OneR it sits 6 to 11 ms after an entry. golblick takes frame *k*'s time as field 24 plus the log's spacing from that entry on, and refuses when field 24 is outside the record or more than half a frame from any entry. ⚠️ That holds for the 20-byte form only; the 56-byte form's stamps come late, [below](#frame-stamps-in-the-56-byte-form-come-late).
- A shift from field 24 was tried on the cleanest clip: 0 ms scored best, with ±10 ms within 0.1° and ±20 ms clearly worse.

### The method

[`golblick.stabilise`](../../src/golblick/stabilise.py) has the details. In outline: integrate the gyroscope; express each accelerometer reading that is within 0.1 g of 1 g in that frame; average it over a centred window (σ = 2 s); turn the attitude so the average is up. The view keeps the horizon level, and its heading follows the camera's twist about the vertical, smoothed with σ = 2 s.

A filter that only looks back (the usual complementary filter) started 3.4° off on a clip that opens while moving, then lagged behind it. The centred window needs no opening estimate. Both windows were chosen on one X5 clip and checked on the rest.

### Against Studio's FlowState

Per frame: the tilt between the two steadied horizons, and the yaw shake left (yaw difference minus its own 0.5 s smoothing). "Unstabilised" is the clip levelled once at its opening, as the Nextcloud app rendered it before.

| Clip | Camera | Horizon vs Studio, median (p95) | Yaw shake left, rms |
|---|---|---|---|
| 1 (tuning) | X5 | 9.5° (26.6°) → 0.6° (2.3°) | 3.5° → 0.3° |
| 2 | X5 | 6.9° (16.5°) → 2.3° (3.4°) | 2.6° → 0.6° |
| 3 | X5 | 11.8° (27.2°) → 1.4° (2.8°) | 3.8° → 0.7° |
| 4 | OneR | 3.2° (21.5°) → 1.4° (2.7°) | 6.6° → 0.9° |
| 5 | OneR | 0.7° (3.7°) → 0.4° (1.0°) | 0.5° → 0.15° |
| 6 | X3 | 1.1° (2.1°) → 1.0° (1.1°) | 0.14° → 0.08° |

⚠️ On clip 2 the remaining horizon difference is a steady 1.3° about the lens axis, which fits a small fixed rotation between Studio's frame and ours (the X5 frame fit above left about that much). Studio is the reference here, not ground truth, so which of the two is level is not established.

⚠️ The heading is not scored. The yaw shake is the difference left after removing its own 0.5 s smoothing, so it says nothing about where the view points over seconds, and there the two differ by design: FlowState follows turns much more slowly. Over three clips the slow heading difference spanned 134°, 137° and 229°, while the camera turned through 202°, 130° and 305°. So FlowState follows partly, somewhere between golblick's 2-second follow and a fixed direction. Which is better depends on the clip. golblick follows by default, so a walk keeps looking ahead, and offers a lock (`stabilise.track(lock=True)`, a toggle in the Nextcloud player) that keeps the opening direction, like Studio's Direction Lock. The lock was not scored against Studio, whose Direction Lock exports were not kept; it is the same attitude with the heading held, and `test_stabilise` checks it holds through a pan.

⚠️ Correction (2026-10-19): every steadied copy `golblick render` made until then turned each frame from the fourth on by the next frame's turn. The stitch times every stream by its frame number with `setpts=N*den/num/TB`, which ffmpeg works out in floating point and truncates: at 30000/1001, frame 3 came out as 3002 on a lens stream (time base 1/30000) and as 2 on the tables (1001/30000), and the filters that pair their inputs by time stayed one frame apart from there on. It showed as the opposite of steadying: on a walking OneR clip, frames with more than 0.5° of jerk went from 16.7% unsteadied to 24.1% steadied, and to 7.6% once fixed (`round()` in the expression). The Nextcloud worker's copies were not affected: they keep the files' own timestamps, and a frame-brightness comparison against the source lined them up at offset 0.

How it was found, which is also how to check the timing: the yaw the unsteadied picture shows from frame to frame, correlated with the gyroscope's at a range of offsets, peaks where the record and the picture agree. Through the shipped stitch the peak sat 32 to 55 ms early on every clip with motion, all three cameras, which looked like a timing rule and was a frame of the stitch. Through the player's decoder, whose labels match a plain decode frame for frame, it sits within 3.4 ms of 0 on X3, X5 and 2023 OneR clips and 3 to 15 ms early on 2020 OneR clips (6 clips; correlation at 0 already 0.91 to 0.97). That last residual is under half a frame and varies by clip, so it is recorded, not corrected. ⚠️ Correction (2026-10-19, later the same day): on fast turns it was the visible jerk on those clips, and it follows the record's form and the exposure, so it is now corrected; [next section](#frame-stamps-in-the-56-byte-form-come-late).

### Frame stamps in the 56-byte form come late

The 56-byte form (here, OneR clips from 2020 and 2021) stamps each frame later than the picture shows it, by more the longer the exposure. Measured as in the section above, through the player's decoder, over the first 10 to 12 s of 60 clips, keeping those whose correlation peaks at 0.94 or more:

| Form | Clips | Where the picture matches the gyroscope |
|---|---|---|
| 20-byte (OneR from 2023, X3, X5) | 23 | within ±5 ms of the frame's time, whatever the exposure (a 1/50 s exposure: −0.5 ms) |
| 56-byte, exposure 1/1,000 s or shorter | 10 | +0.3 to −13.3 ms, median −8.2 ms |
| 56-byte, 1/195 s | 1 | −3.8 ms |
| 56-byte, 1/120 s | 2 | −10.2, −12.3 ms |
| 56-byte, 1/60 s | 2 | −15.9, −18.4 ms |
| 56-byte, 1/30 s | 2 | −21.8, −35.6 ms |

It holds within a clip: the three thirds of each stretch agree to a few milliseconds, and on two clips of 3.5 minutes, stretches a minute apart stay within 6 ms of each other with no trend, so it isn't one clock running slow against the other.

Candidate rules, each with one constant, scored leaving one clip out at a time (error against the clip's own peak; 17 clips, one of them measured earlier):

| Frame seen at | Median error | Worst |
|---|---|---|
| field 24 and the log's spacing (before) | 10.2 ms | 35.6 ms |
| the same, less a constant | 4.1 ms | 25.6 ms |
| the same, less half the exposure and 7.8 ms | 2.0 ms | 11.2 ms |
| **the log entry's own time, less half its exposure and 18.6 ms** | **1.7 ms** | **8.2 ms** |
| either, less the whole exposure and a constant | 4.0 ms | 17.2 ms |

golblick uses the fourth: field 24 still picks frame 0, but each frame's time comes from its own log entry and exposure (`imu._STAMPED_LATE`, `Imu::STAMPED_LATE` in the app). Half the exposure is what a stamp at the end of the exposure would need. The 18.6 ms is not explained. The difference between the third and fourth rows rests on the three 25 fps clips, because field 24 sits 7 ms before its entry at 25 fps and 11 ms before it at 29.97 fps.

⚠️ Correction (2026-10-19, later): the 18.6 ms is now replaced by a number the file carries. Metadata field 28 reads −12 on every 2020–21 clip recorded at 25 fps and −6 on every one at 29.97 fps (46 clips), and taking frame *k* at field 24 plus *k* periods of the log's own spacing plus field 28 (ms), less half its exposure, fits the picture better with no fitted constant at all. Measured as above on all 46 clips of the 56-byte form, keeping the 30 whose correlation peaks at 0.94 or more, as the error against each clip's own peak:

| Frame seen at | 25 fps (5 clips), median / worst | 29.97 fps (25 clips) | All 30 |
|---|---|---|---|
| the log entry's time, less half its exposure and 18.6 ms | 1.2 / 7.4 ms | 2.2 / 8.0 ms | 2.15 / 8.0 ms |
| **field 24, the log's spacing and field 28, less half the exposure** | 1.6 / 8.0 ms | **1.8 / 6.4 ms** | **1.69 / 8.0 ms** |

The 18.6 ms was the two modes averaged: under it the 29.97 fps clips matched the picture 1.9 ms later than their frame times (median), and field 28 moves them by 1.8. Every one of the 46 logs is evenly spaced to within its millisecond rounding (at most 0.56 ms off a straight line, over up to 20,452 entries), at exactly 40 or 1001/30 ms, so counting frames off from field 24 is safe; golblick refuses a log with a frame missing rather than miscount, and a 56-byte clip without field 28. All 132 videos in the library still read. The rule is `imu._LATE_STAMPS` (`Imu::LATE_STAMPS` in the app).

What it does to the player, scored as the turn left from frame to frame in the locked view (rms change of the yaw / vertical step, degrees; the clip's own peak offset for comparison):

| Clip, exposure | Before | With the rule | At the clip's own peak |
|---|---|---|---|
| walking, 1/2,000 s, 3 s with turns up to 363°/s | 0.67 / 0.28 | 0.30 / 0.18 | 0.48 / 0.13 |
| walking, 1/3,000 s, 2.5 s | 1.24 / 0.12 | 0.59 / 0.04 | 0.16 / 0.08 |
| 1/60 s, 8 s | 0.18 / 0.17 | 0.03 / 0.03 | 0.04 / 0.03 |
| 1/30 s, 8 s | 1.21 / 0.65 | 0.13 / 0.12 | 0.10 / 0.07 |
| the clip it fits worst (peak +0.3 ms), 8 s | 0.26 / 0.21 | 0.32 / 0.07 | as before |

⚠️ The scatter of a few milliseconds between clips, and within one, is not explained, and on a fast turn that is still visible: the second clip would be nearly four times steadier at its own peak. Measuring each clip's offset from its picture would get that, at the cost of decoding a stretch of it before steadying; it isn't done.

⚠️ What this doesn't do: correct rolling shutter. The sensor reads a frame line by line, so fast motion leaves a wobble within the frame that a rotation per frame cannot remove. Whether Studio corrects it was not checked.

⚠️ Correction (2026-10-19): on fast turns the rolling shutter was most of the shake left over. Studio's export of a 25 fps clip corrects it, and golblick now does too, on the OneR and X3. [Next section](#rolling-shutter).

### Rolling shutter

A OneR reads each frame a row at a time, so a pixel near the bottom of a lens image was seen later than one near the top. Its sensor sits on its side in the body, so a pan runs along the readout: one side of the sphere is stretched and the opposite side squeezed, and one rotation per frame can't undo that. A score over a band all the way round hides it, because opposite sides move opposite ways; it shows when the turn is measured separately in each 45° of longitude.

Metadata field 25 holds the readout time in milliseconds, per file. It follows the recording mode: 35.2 ms on the 2020–21 clips at 25 fps, 23.5 ms at 29.97 fps, 31.2 and 22.3 ms on 2023 clips. Two checks tie it to the picture:

| Check | Result |
|---|---|
| The readout that steadies the player's locked view best, fitted per clip on 15 OneR clips with fast turns, scored per sector | follows field 25 per mode: 18–24 ms on the 23.5 ms clips, 24–30 on 35.2, 30–36 on 31.2, 24 on 22.3. The fit spanned the image circle, which is a little shorter than the image, so it is expected slightly under. Typical gain 1.5 to 3.5 times |
| Insta360 Studio's stabilisation-off export of a 25 fps clip against golblick's unsteadied render, per sector, frames 100–125 (turns up to 16° a frame) | the sectors disagree by 1.60° on average and 3.81° at worst uncorrected; by 0.12° and 0.24° with the model below, the comparison's noise floor |

The model: in a lens image *h* rows high, row *y* was seen at the frame's time plus (*y*/*h* − ½) × field 25, with *y* running down the rows as golblick decodes them, the same way in both lenses. The other three combinations of axis and direction made the match worse than no correction at all (2.2° to 4.1° on frames 104–119, against 2.25° uncorrected and 0.44° for this one, with an earlier and cruder form of the correction). For each pixel, golblick takes the camera's turn between the frame's time and that row's time from the gyroscope, turns the ray by it and projects it again (`stabilise.shutter`, `render._project_read`). It keeps five turns per frame and interpolates between them; nine scored the same. The video stitch and the desktop player's shader both apply it, and the player's picture matches the renderer's to 0.01 px median on a fast-turn frame.

In the player's locked view, as the mean over the 8 sectors of the change in the frame-to-frame turn (degrees):

| Clip | Before | Corrected |
|---|---|---|
| 25 fps, walking, frames 60–125 | 0.93 | 0.29 |
| 29.97 fps, walking, frames 100–150 | 0.62 | 0.13 |
| 29.97 fps, short jolts, frames 125–160 | 0.52 | 0.13 |

Those figures include a second fix. Each frame used to take the attitude of the next gyroscope sample, up to 2 ms after its own time at 500 Hz; it now takes the attitude at its own time, as the timing census did. On its own that changed little (0.98, 0.61, 0.49), but the frame and its rows must be turned from the same moment: on the third clip the shutter correction alone reached 0.23.

The X3 and X5 carry field 25 too: 31.5 or 15.7 ms on the X3 clips here, 21.2 or 9.2 ms on the X5. Which way each reads in golblick's lens images was measured the same way, all eight combinations of axis and per-lens direction against no correction (mean per-sector jerk in the locked view, or disagreement with a Studio stabilisation-off export, degrees):

| Clip | None | Down the rows, both lenses | Best other |
|---|---|---|---|
| X3, 15.7 ms, the one X3 clip with fast turns, locked view | 0.45 | **0.30** | 0.47 |
| X5, 21.2 ms, Studio export, fast frames, stable sectors | 1.35 | **1.08** | 1.25 (rows, first lens reversed) |
| X5, 21.2 ms, a second Studio export | 1.02 | 1.12 | **0.91** (rows, second lens reversed) |
| X5, two other fast clips, locked view | 3.79 / 1.21 | 3.37 / 1.06 | 3.50 / 1.05 |

So the X3 reads like the OneR, and is corrected (one clip: the only combination that helped, every other one worse than none). ⚠️ The X5 isn't: the two exports favour different directions, nothing reaches the second export's noise floor (0.1°), and the other two clips are mostly featureless, with something close to the lens moving with the camera, which the measure can't separate from the scene. The X5 keeps its lenses as separate streams, and which stream golblick pairs with which lens is itself an open question ([Which way a levelled panorama faces](#which-way-a-levelled-panorama-faces)), so the direction may differ per lens in a way these clips don't settle.

⚠️ Correction (2026-10-20): the X5 reads down its rows like the other two, and is now corrected. Three things were wrong with the X5 rows above. The gyroscope read 6.1% low on the X5 then ([Record `0x0300` — IMU](#record-0x0300--imu)). The first export was made with lens guards on, which scales Studio's lens by 2.25% of the angle ([Lens guards narrow the field of view](#lens-guards-narrow-the-field-of-view-x5)), far more than the warp being looked for. And a shift per sector is a poor way to see this warp on an X5: its sensor isn't on its side, so a pan shears the picture instead of stretching it along the longitude, and the band's mean shift barely moves.

A test that needs no export settles it. In golblick's locked view, the dense optical flow between two consecutive uncorrected frames is regressed on the flow the correction would take out of them (the flow from each frame to its corrected render, frame k's less frame k+1's), over textured pixels, on pairs of frames that both turn 1.5° or more within the readout (2° for the control). A slope of 1 means the model is right, −1 the opposite direction, 0 no such warp:

| Clip | Pairs | Slope | Bootstrap over pairs, 5–95% |
|---|---|---|---|
| OneR, 25 fps, known to read down (control) | 40 | +1.09 | +0.76 to +1.56 |
| X5, 21.2 ms, walking | 54 | +1.43 | +0.50 to +2.32 |
| X5, 21.2 ms, skiing | 59 | +1.23 | +0.06 to +2.44 |

Reading up is ruled out on both X5 clips, and no correction on the walking one. A single pair scatters widely, because the camera's movement also shifts near content between frames, so this says which way the rows are read, not how long it takes; the time is field 25's, as on the other cameras. With the same correction applied to both lenses the slope can't come out near 1 if one of them read the other way, so the open question of which stream is which lens doesn't change the direction. The desktop player's shader matches the renderer to 0.01 px median on a fast X5 frame, where the correction moves the picture by 2.3 px median and 8 px at most.

⚠️ A second OneR clip's Studio export (29.97 fps, stabilisation off) shows no correction, although the same model steadies that clip in golblick's player as well as the others. Not explained.

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

🔴 **It can't rank files by stitch quality.** A correlation over the band is dominated by large-scale brightness. Over a 1,432-file corpus the highest score, 0.985, is a visibly misregistered frame of sky against trees, the lowest, 0.096, is a blank white room that stitches cleanly, and a file verified against the vendor's own export sits below the median. It separates a correct projection from a wrong convention (0.75–0.90 against 0.02, one file at a time) and nothing finer.

## Stitching the seam

What the hand-over in `render.equirectangular`, `render.plan_seam` and `render.remap_tables` is based on. "Disagreement" is the mean grey difference between the two lenses near the seam; the Nextcloud app runs the same algorithms.

### Blend weights

🔴 **Cross-fade on how far each lens is from the best-placed lens, not on how far it is from its own rim.** With a 194° lens a rim taper only starts at 92°, so both lenses carry full weight across the middle of the 14° overlap. The first weighting did that, and 17.9% of every sphere came out a 50/50 average of two views separated by parallax: you could see the scene through a person standing near the seam, and the mix stayed visible for about 12° whatever the feather was set to. Narrowing the feather makes it worse, because it widens the plateau where both weights saturate. Weighted against the closest lens, objects near the seam are cut rather than made transparent, which is the trade the vendor's own stitcher makes. Overlap agreement can't see the difference, because it is blindest exactly where the lenses are averaged; `test_render` catches it by painting one lens red and the other blue. The rim taper stays as well, and only matters where a lens has no partner.

### Cross-fade width

`min(3°, max(1.5°, 4 output rows))`. It has to be a few pixels wide so the hand-over doesn't alias into a stair-step at small sizes (1° is 1.4 rows of a 256-row preview), and a wide blend drags back the content a routed seam went round. It also needs a minimum angle, because hiding the brightness step between the lenses is a question of angle, not pixels: a width in pixels alone came to 0.35° at 4096 wide and the seam showed as a hard line. Gradient at the seam over the gradient just outside it, nine frames: 1.16 at 0.35°, 1.11 at 0.70°, 1.01 at 1.5°, which still keeps 17% of the routing gain. Above 2° routing stops paying at all.

The desktop player hands a video over in two bands. Detail keeps the 1.5° cross-fade, so a subject near the seam is cut rather than doubled. What the lenses show blurred (a mipmap level about 3° across) hands over across 6°, so a brightness difference between the lenses fades out instead of drawing a line. A single 6° cross-fade hid the step too, and doubled a glove and a zip close to the camera on an X5 clip; the two bands left those as the 1.5° fade had them. Stitched copies hand over the same way (`render.remap_tables(coarse=...)` adds the wide band's table; a copy is the narrow blend plus `(share − wide)` times the difference of the lenses blurred over 3°).

With two bands the player no longer evens out the lenses. It used to, in the same way as the stitched copies: lens 1 less lens 0, averaged across a strip along the seam. Content close to the camera sits in a different place in each lens, so that average counts it as a brightness difference; with an arm lying along the seam it moved the table and the arm by 10 to 13 levels in opposite directions. Scored against the vendor's own player on four clips (its correction per point along the seam, read off screenshots against this player with the balance off), the typical error was 4.0 levels with the balance, about 2.5 with a version that ignores stretches where the lenses see different things, and 2.4 with none; by eye, none looked at least as good. The stitched copies dropped the balance too, for two bands: simulated on the same four clips, their typical error against the vendor's player was 4.9 levels with one band and the balance, 2.0 with two bands and none. On an X3 clip whose lenses differ by about 20 levels along the seam, the copy's step across the narrow band is no sharper than across bands 2° to either side (median −0.5 levels; +1.5 with the balance, +19 with neither): the difference becomes a ramp about 6° wide instead of a line.

### Routing the seam

With two lenses the hand-over can follow a path instead of the bisector: parametrise it by `d = θ₀ − θ₁` against the azimuth about the lens axis, and put it where the lenses already agree, so a near subject is walked round instead of cut through. Median 25% less disagreement across nine frames, 10% to 57%.

| Choice | Measured |
|---|---|
| Route only at 2048 wide or more | a grid built at 2048 helps all nine frames and is never worse than +7%; at 1024 one frame loses 25%, at 512 two lose up to 30%. The cost has many near-equal paths, and a thin grid picks one by noise |
| A 256 × 48 grid | 512 × 64 scores 28% and 192 × 32 25%. The PHP port decides from a small probe render, and at 512 × 64 it saw about 0.5 samples per bin and declined |
| Cost averaged over the cross-fade's width, not one row | otherwise the path dodges a near object and the blend drags it back; on the first frame tried that made routing look worthless (16.86 → 17.51) |
| A closed, connected path | the azimuth wraps, and a seam that jumps is a tear. Per-column minima jump up to 62 of 64 rows between neighbours, which is what limits the gain |
| Two passes (free start, then pinned to where it landed) | against the exact cyclic answer on five frames: 0.0% median, 3.9% worst. The exact version needs a back-pointer table per start, which the PHP port can't afford |

🔴 **The decline needs a margin and a floor.** The first guard asked only whether the routed path was cheaper than the straight one, which can never fail: the search minimises over connected paths and the bisector is one of them. A featureless scene then got a seam that wandered after noise. Now the straight seam stays unless the lenses disagree by at least 2 grey levels along it and the route cuts that by 10%; `test_render` checks the decline fires.

### Aiming the lenses at a parallax (video)

A video gets one plan per clip, because its tables are written once. `plan_seam` first picks a parallax per azimuth, aiming both lenses along the field 53 baseline (see "Field 53 says where the two lenses sit"), then routes the cut round what still disagrees, which also moves it off a flare only one lens has. Each guard came from an artefact the disagreement score couldn't see:

- Any jump between parallax levels is allowed, because distance is discontinuous at the edge of a near subject. A path limited to one level per column leaked near parallax 17° either side of one and bent the far scene there.
- Only a minimum inside the searched range counts. A column still improving at the largest parallax has its subject in the blind zone, and the warp there bent a glove into a swirl.
- Runs narrower than 8 columns (about 11°) are removed. Sliding one lens 9° laid its sun flare over the other lens's sun, halved the disagreement and sheared the sky into a swirl.
- Chosen on every other frame, checked on the rest, and declined unless it clears the routing margin there. Checked on the frames it was chosen on, a plan always looks good: a clip filmed from a stand, with people walking past, passed that check and did worse than the bisector on a third of the frames it hadn't seen. On held-out frames of a clip with the holder near the seam: 19% less disagreement than the bisector, never worse on any frame.

### Sampling

Bilinear, because the projection lands between source pixels everywhere. Scored against a 3× render box-downsampled to the target size, the RMSE at 2048 wide falls from 5.28 (nearest-neighbour) to 3.26, 62% of what quadrupling the pixel count buys. ⚠️ Don't score this with high-frequency energy: nearest-neighbour adds high frequencies, because its jaggies are aliasing, so that metric rewards the worse sampler.

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

⚠️ Superseded: those files can be levelled from another frame of the same shutter press. See [Borrowing the record from the same shutter press](#borrowing-the-record-from-the-same-shutter-press).

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

🔴 **It is also per kind of file: an X5 video uses a different map from an X5 still** (measured 2026-10-08). The first stitched X5 video came out 127° off level with the still map. Fitting frame 0 of every X5 video in the library (44, both lens streams decoded, unlevelled render) to the camera's own stitch of it (record `0x0200`), and comparing the up direction that implies with the accelerometer's median over the first 1,500 samples:

```
up_render = (+a_z, −a_x, +a_y)          # Insta360 X5, video
```

| Map, samples | Median | p90 | Within 5° |
|---|---|---|---|
| **video map, first 1,500** | **3.7°** | 9.8° | 73% |
| video map, whole record | 21° | 82° | 5% |
| still map, first 1,500 | 87° | 139° | 0% |

It is the still map turned 180° about the vertical, and the yaw that fits each video to its stitch is 0° (within 4°) on all 44, where X5 stills need 180°: the same half turn, seen in the heading. Which of the two (the inertial frame, or which stream holds which calibrated lens) the half turn belongs to is not established; lens agreement cannot tell, because swapping the lenses is a rotation and it is blind to rotations. The window was then varied: the first 1,000 to 3,000 samples score 3.4–3.7° median, 25 to 300 score 4.3–6.8°, so a window of that size is also the best of those tried for a video's opening frame. OneR and X3 videos keep their still maps, which level frame 0 to within 1.0–3.4° of Insta360 Studio's export on five clips. `imu.is_video` decides by content (`ftyp` at byte 4).

### Borrowing the record from the same shutter press

965 of 1,438 stills in one library carry no inertial record, all OneR. Every one of them sits in a burst or HDR bracket where another frame carries one, and the record is identical between those frames, not merely similar: on the 13 capture instants that carry three records each, the gravity vectors agree to 0.00° (max 0.00°) over 36 frames. The camera takes one reading per shutter press and writes it to some frames and not others.

So `imu.gravity_up_nearby` borrows the bytes from a sibling with the same timestamp in the same directory, sorted so two runs pick the same donor. Scored against Studio's exports on 291 frames that carry no record: 1.09° median, p90 1.94°, 98% within 5°, against 10.43° and 52.99° for the mounting angle alone.

⚠️ This contradicts the 🔴 paragraph under [Levelling](#levelling), which found Studio's exports of files with no record agreeing with the mounting angle alone (n=7). The 291-frame comparison is the later and larger one; the two were not reconciled.

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

The code's comment on this map recorded a second set of figures for the same comparison (old map, this map, p90, within 5°): 56-byte 9.6°, 1.16°, 3.4°, 92% (285 files); 20-byte 42.9°, 1.06°, 2.4°, 100% (94 files). Which run each table came from is not recorded; they agree on the map.

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

### Which way a levelled panorama faces

Gravity fixes pitch and roll and says nothing about the heading, so a levelled render opens wherever the levelling rotation leaves the sensor frame. Insta360 Studio's exports are centred on a fixed direction relative to the camera, and golblick's renders were turned away from it on every camera. Each photo was rendered levelled from gravity, and the turn about the vertical that lines it up with Studio's export was solved (`render.fit_orientation`):

| | Photos | Turn to Studio, levelled from gravity | Predicted by the render frame's −z on the horizon |
|---|---|---|---|
| OneR | 15 | 110° to 180° | median 1.3°, worst 8.3° off |
| X3 | 12 | 163° to 179° | median 3.4°, worst 18.3° off |
| X5 | 12 | 179° to 180° | median 0.5°, worst 1.3° off |

Studio's exports are centred on the horizontal projection of the render frame's −z, one lens axis, on all three cameras (`PHOTO_FORWARD`, applied by `render.face`). A constant half turn fits the X3 and X5 nearly as well and misses tilted OneR photos by up to 70°: the 110° cases are the camera tipped with gravity mostly along that axis, where the smallest levelling rotation and "keep the lens axis forward" part ways. ⚠️ The X3 photos were all held at much the same tilt, so they fit +y almost as well (median 2.4°); the OneR and X5 separate the two. An X5 levelled against its own stitch already faced Studio's way, since Studio and the stitch agree. After the change, renders of tilted OneR, X3 and X5 photos sit 0° to 6° from Studio (one X3 at 18°), and the Nextcloud app's panoramas 0.7° to 2.1°.

⚠️ **Corrected 2026-10-18.** This section and the 0.6 docs first said golblick now opens a photo "the way Studio opens it". What was measured is the centre of Studio's **exports**. Studio's own viewer was checked by eye on one photo only, where it opened facing a wall, as golblick 0.6 does; whether it always opens on its export's centre is not established. Neither is a choice of the scene's content: a photo that opened facing a wall still does, in both. What fixes a photo that opens at an uninteresting point is the opening view a user sets.

Video opening frames, levelled the same way, were also about half a turn off on three clips with full-length Studio exports (two OneR, one X5), and the −z rule predicts them to within 1° to 7°. ⚠️ Those exports had stabilisation off, so they aren't levelled, and the comparison is rougher than for photos.

🔴 **Corrected 2026-10-18: the X5 is the other way round in video.** Frame 0 of a stitched clip, levelled from gravity and scored against frame 0 of Studio's FlowState export, which is levelled (`render.fit_orientation`, yaw of the fitted rotation):

| | Clips | Turned to −z | Left as levelled |
|---|---|---|---|
| OneR | 4 | −6.7° to 0.0° | 145° to 178° off |
| X3 | 1 | 2.5° | 179° off |
| X5 | 3 | 147° to 180° off | −31.6° to 2.8° |

Against the unstabilised exports of the same X5 clips the levelled render is −12°, 0° and −2.5° off. So an X5 video opens on +z (`VIDEO_FORWARD`), a half turn from an X5 photo. Which X5 clip the earlier paragraph used isn't recorded, and it can't be checked again. ⚠️ Not settled: whether this is how the camera and Studio centre an X5 video, or golblick pairing the X5's two video streams with the wrong lenses, which would look the same, since swapping the lenses is a half turn. Seam agreement slightly favours the current pairing on all three clips (3% to 5%), but the OneR, whose pairing can't be wrong, separates by the same small margin, so that isn't evidence either way.

## Lens brightness in video

In a still, the camera has already matched its two lenses; in a video it has not. Measured 2026-10-09 as lens 1 over lens 0 on the band both lenses see, a degree inside each rim, pixels near black or white left out:

| Source | Lens 1 / lens 0 |
|---|---|
| 8 OneR stills, spread through the library | 0.99–1.02 (luma) |
| X3 clip, four frames through it | 1.18 every frame (luma); per channel R 1.19, G 1.10, B 0.81 |
| X5 clip | 0.93–0.95 |
| OneR clips | 0.90–1.05 and 1.05–1.13, drifting within each clip |

⚠️ **It is not one factor per clip.** Broken into 30° sectors round the seam, the X3 frame reads 1.2–1.4 along the sky and 0.85–1.03 along the ground: glare from the sun on one lens, added on top of the picture, more than an exposure difference. A gain per channel would have lowered the step in the sky and made one along the ground. Nothing evens it out now: the player and the stitched copies hand over in two bands, which spread the step into a ramp about 6° wide ("Cross-fade width"). Until 0.8 the Nextcloud app evened it out frame by frame along the seam (`nextcloud-app/AGENT-NOTES.md`, "Lens balance"), which shifted content near the camera. ⚠️ Where glare has washed one lens out entirely, there is no picture left to match, and the seam stays.

⚠️ **Weight by area when measuring this.** The same X3 frame read R 1.28, G 1.18, B 0.68 when sampled on an equirectangular grid with the lens axis on its equator, against 1.19, 1.10, 0.81 on an even grid round the seam: the equirectangular grid puts the seam through its poles, where pixels crowd, so it counts mostly the sky and the ground. Both are right about their own sample; only the even grid describes the seam as a whole. The X3 and X5 are one clip each.

## A measured baseline for naive stitching

Scored by SSIM against the embedded 320×160 thumbnail, for one X5 still. ⚠️ Record `0x0200` supersedes the thumbnail as the reference (it is the same image from the same camera at 2560×1280), so these numbers are a baseline measured against the coarser of the two references, and should be re-measured against `0x0200` before anything is compared to them:

| Approach | SSIM |
|---|---|
| `ffmpeg v360=dfisheye:e:ih_fov=193:iv_fov=193` | 0.448 |
| Same, with orientation corrected | 0.589 |

The orientation correction was found by grid search, not derived. The ceiling is explained: `v360`'s `dfisheye` input cannot express per-lens centre, radius, rotation or distortion, so it discards almost everything the calibration knows, and it applies no seam blending. Two further limits are worth knowing:

- The camera does **horizon levelling** on its output, using gravity. A raw stitch does not, so a handheld shot shows a visibly curved horizon.
- **Parallax at the seam** duplicates or tears objects close to the camera where the hemispheres meet. No amount of calibration fixes this; it needs optical-flow blending.
  - ⚠️ Correction: the calibration does carry what parallax depends on. Field 53 states the lens baseline (see "Field 53 says where the two lenses sit"), and aiming both lenses at a chosen distance per azimuth lines up subjects beyond the blind zone. Choosing that distance is a search, not a calibration value.

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
