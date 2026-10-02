# How good are the panoramas?

On the three cameras tested, close to what Insta360 Studio 6.0.6 on Windows 11 produces. Horizons are level to about a degree, the two lenses line up to within a few pixels, and the main visible flaw is where something close to the camera crosses the line between the lenses.

This page says how that was checked, and what the *lens agreement* number that `golblick render` prints does and doesn't tell you.

## Numbers

| Check | Result | Compared against |
|---|---|---|
| Horizon level | median error 1.0–1.2° on all three cameras | Insta360 Studio's levelled exports of the same photos |
| Photos levelled | 1,432 of 1,438 (the other 6 have no trailer to read) | |
| Where each lens's picture lands, OneR | median 3.0 px off at 2048 px wide (9.8 px before the lens correction) | Insta360 Studio's exports, on scenes not used to measure the correction |
| Same, X3 | about 1 px (about 3–4 px before) | the same, but only two scenes |
| Same, X5 | 5.5–6.7 px, with no correction; a fixed correction doesn't improve it (see below) | the panorama the X5 stores, and Studio's exports, all 48 photos |

Insta360 Studio exports were made with its stitching optimisation switched off, so they show where the camera's calibration puts things rather than Studio's extra per-photo warping. On X5 photos, Studio's horizon and the horizon of the panorama the camera stores agree to within 0.03°, so for levelling the two references are effectively the same thing.

## What's still visible

- **Near objects at the seam.** The two lenses don't sit at the same point, so they see something a metre away from slightly different angles, and no fixed projection can make both views line up. golblick moves the seam, per photo, to where the two lenses agree best, which can steer it around a nearby subject, but anything close that the seam can't avoid will still show a break. Insta360 Studio's *Optical Flow* stitching handles this somewhat better.
- **Brightness differences between the lenses.** Each lens exposes slightly differently. golblick blends across the seam but doesn't correct the exposure.

## The *lens agreement* line

`golblick render` prints a number like `lens agreement +0.858`. Each lens sees a little more than half the sphere, so there is a band both lenses see. The number is how closely the two lenses' pictures of that band match.

Around +0.7 to +0.9 means the projection is right. Around +0.02 means something is badly wrong, usually a camera golblick doesn't understand yet.

It is a quick sanity check and not a quality score. Because it only compares the lenses with each other, it can't tell you whether the panorama is upside down, mirrored, or tilted, and it can't see errors that move both lenses the same way. It also depends on the scene: a photo of a plain wall scores lower than a busy street even when both are stitched equally well. So don't use it to rank photos against each other. If you are checking a new camera, look at the picture too: text in the scene shows a mirror at a glance, and a horizon or a straight edge shows whether the lenses line up across the seam.

On the X5, both references move the lens picture by a different amount in every scene (from 0.1° to 2.9°), and they agree with each other scene by scene. They seem to adjust the stitch to each scene, so they can't pin down a fixed lens curve, and a correction fitted on half the photos made the other half no better. The X5 is left uncorrected.

For the method behind each measurement, see the [research notes](formats/insta360-agent-notes.md).
