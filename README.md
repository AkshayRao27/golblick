# Golblick

**Read, inspect and render 360-camera files on Linux.**

360 cameras wrap their footage in vendor-specific containers, and vendors ship little or nothing for Linux. An Insta360 `.insp` opens in any image viewer as two fisheye circles side by side, because that is what it contains: the camera does not store a stitched photo. Everything needed to turn those circles into a panorama is in a trailer at the end of the file, in plain ASCII and protobuf, readable without any of the vendor's code.

Golblick reads that trailer. It finds clips you are about to lose, pulls out the camera's own previews, and renders a levelled panorama that any 360 viewer will open as a sphere. A companion Nextcloud app does the same for your photo timeline. The name is Hindi *gol* (round) and German *Blick* (view).

---

## 🚩 Please read this before you use it

**Essentially all of the code here was written by LLMs.** Claude Code (Opus 5, then Fable 5) did the work. I directed it and tested it, but I know just enough programming to know how much I don't know, and I could not have written or fully reviewed this myself.

What has been checked:

- The test suite: 100 tests without the optional extras, 130 with rendering enabled, all synthesised (no real photos in the repository).
- A test library of 1,438 stills from three cameras (Insta360 OneR, X3 and X5). 1,432 of them render and level; the other six carry no trailer and are refused.
- Renders scored against two references the project did not produce: the stitch the X5 embeds in its own files, and panoramas exported from Insta360 Studio. How that works, and what it can't see, is in [docs/accuracy.md](docs/accuracy.md).
- The Nextcloud app, on throwaway Nextcloud 33 and 35 instances in Docker. Not on anyone's production server.

The CLI only reads your files. `render`, `preview` and `thumb` write a new file and leave the original alone. The Nextcloud app only reads files and generates previews, but it needs a line in your Nextcloud config, and that line has side effects worth reading about in [the app's README](nextcloud-app/README.md) before you add it.

### ⚠️ YMMV

This is alpha software. It works on the three cameras it was tested with, and nothing else has been tried. There is no support, no warranty, and no promise that any of this will be maintained. Keep backups of anything you care about, which for photos you should be doing anyway.

---

## What it does

| | |
|---|---|
| 🧭 **Triage** | Pairs video masters with their low-resolution proxies and lists the clips whose master is gone, so you can see what exists only as a proxy before deleting anything |
| 🔍 **Probe** | Shows what a file contains: the trailer's records, the camera model and firmware, and the lens calibration |
| 🖼️ **Previews** | Extracts the camera's own preview, which on an X5 is already a stitched panorama |
| 🌐 **Render** | Projects the lens pair into an equirectangular panorama with GPano metadata, levelled from the camera's motion sensor where possible, with the seam routed around nearby subjects |
| ☁️ **Nextcloud** | A pure-PHP preview app, so `.insp` stills show up as panoramas in Files and Memories, with no extra server dependencies |

## Cameras

| Camera | Status |
|---|---|
| Insta360 OneR, X3, X5, stills (`.insp`) | ✅ Read, rendered and levelled. Lens corrections measured per camera (the X5 is not yet corrected) |
| Insta360 video (`.insv`, `.lrv`) | 🟨 Read and triaged; not rendered yet |
| Other Insta360 models | ❓ Untested. Other models may store things differently, and [I'd love to hear how yours does](CONTRIBUTING.md#testing-a-camera-i-dont-have) |
| Other vendors | ❌ None yet. The code is built around a vendor registry, so adding one is a new module rather than a rewrite |

## Quick start

```sh
uv tool install 'golblick[render]'      # or: pipx install 'golblick[render]'
golblick render IMG_20260314_090809_00_007.insp -o pano.jpg
golblick triage ~/Photos
```

Without `[render]` everything except rendering still works, with no dependencies at all.

## More

- [docs/usage.md](docs/usage.md): every command, with example output
- [nextcloud-app/README.md](nextcloud-app/README.md): installing the Nextcloud app, and what it changes
- [docs/formats/insta360.md](docs/formats/insta360.md): what is known about the Insta360 container, and how each fact was measured
- [docs/accuracy.md](docs/accuracy.md): how renders are checked, and the blind spot of each check
- [CONTRIBUTING.md](CONTRIBUTING.md): reporting issues, and testing a camera I don't have
- [docs/development.md](docs/development.md) and [AGENTS.md](AGENTS.md): working on the code, by hand or with a coding agent

## Prior art

[insv-stitch](https://github.com/BenjaminHenriksson/insv-stitch) (MIT) is a video-only Insta360 X5 stitching pipeline and was a useful reference for the projection maths. It is not vendored here.

## Licence

MIT, except `nextcloud-app/`, which is AGPL-3.0-or-later as the Nextcloud app ecosystem requires.

Not affiliated with, endorsed by, or connected to any camera manufacturer. Vendor names are used only to identify the file formats this software reads.
