# What's in an Insta360 file

This page is the short version. The measurements behind it, and the method for each, are in the [research notes](insta360-agent-notes.md).

## The three file types

| Extension | What it is |
|---|---|
| `.insp` | A photo. A normal JPEG holding both lenses' images side by side, as two fisheye circles |
| `.insv` | A video. A normal MP4 with one video stream per lens |
| `.lrv` | A low-resolution copy of a video, also two fisheye circles. Insta360's apps use it for fast previews |

Any image viewer or video player can open these files, and you get the two circles, because that is what the file holds. Turning them into a panorama is a separate step, and doing it right needs information the camera writes at the end of the file.

## What the camera adds at the end

After the image or video, the camera appends a block of its own (golblick calls it the trailer). Standard software ignores it. It holds:

- the camera model, firmware version and serial number
- the lens calibration: where each fisheye circle sits in the frame, how big it is, and how the two lenses are rotated relative to each other, written as plain text
- a preview image
- readings from the camera's motion sensor, which say which way was down when the photo was taken

golblick reads that block without any of Insta360's code. The calibration places the two circles on the sphere, and the motion sensor reading levels the horizon.

## How the cameras differ

The three cameras tested don't store the same things, which is why a file from a fourth model might not work:

| | OneR | X3 | X5 |
|---|---|---|---|
| Photos tested | 1,344 | 40 | 48 |
| Photo sizes | 6080×3040 | 5952×2976, 11968×5984 | 5888×2944, 11904×5952 |
| Preview in the file | the two circles, 1920×960 | the two circles, 1920×960 | a finished, levelled panorama, 2560×1280 |
| Lens calibrations stored | 1 | 3 | 4 |
| Motion sensor reading | in about 3 in 10 photos | in all but 2 | in all |

Some differences that matter in practice:

- **Only the X5 stores a finished panorama.** `golblick preview` gets it out, and it is also what X5 renders are checked against. The OneR and X3 store the two circles, so their panoramas have to be built from scratch.
- **Most OneR photos have no motion sensor reading of their own.** In bursts and brackets the camera writes the reading to one frame, and golblick borrows it from another photo taken in the same shutter press.
- **The calibration doesn't say everything.** It doesn't say how wide each lens sees, or how far the lens departs from an ideal fisheye. Both were measured per camera and are built into golblick. The X5 is left uncorrected: a fixed correction didn't bring its renders closer to Insta360's.
- **The sensors are mounted at different angles.** A OneR's sensor sits 90° round from an X3's or X5's. The calibration records this, and without it every OneR panorama would come out on its side.

## What isn't known yet

- Video. `probe` reads videos from all three cameras, but none is rendered yet. X5 videos lay out their trailer differently, with an index of where each block sits, and several of those blocks aren't identified.
- Two record types in photos, `0x0900` and `0x0b00`, appear in most files and aren't identified.
- Three of the four calibration types. Only the simplest one is understood, and it's the one every camera stores. The others have a known number of values but not a known meaning, so golblick gives them to you as raw numbers.

## Try it on your own files

```sh
golblick probe FILE -v          # what the trailer holds, including the calibration
golblick preview FILE -o p.png  # the camera's own preview
exiftool -ee3 -G1 -s FILE       # an independent second opinion
```

`probe` prints the camera's serial number, so remove that line before sharing the output.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
