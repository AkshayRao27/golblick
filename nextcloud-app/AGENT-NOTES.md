# Implementation notes for agents

Details behind the [README](README.md), for anyone (human or coding agent) changing the app. The container format itself is documented in [docs/formats/insta360-agent-notes.md](../docs/formats/insta360-agent-notes.md), which owns every measured fact about the files.

## No new server-side dependency

The whole reader is reimplemented here in PHP: the trailer walk, the protobuf field walk, the lens calibration parse and the equirectangular projection. Pixels go through **GD**, which Nextcloud already requires. Nothing shells out, and the Python library in the parent repository is not called.

```
lib/Insta360/     Trailer · Protobuf · Calibration · EmbeddedPreview · Imu · LensProfile   the reader
lib/Render/       Equirectangular · Seam · Orientation                                    the projection
lib/Preview/      Insta360                                                                the provider
```

The reader is a deliberate port of `src/golblick/vendors/insta360/` and is kept close enough to compare side by side. A change to the projection goes into both, and the two outputs are compared on the same file afterwards.

## Performance

Measured over 1,415 stills from three camera bodies, at 256 px wide:

| | |
|---|---|
| Rendered | **1,409** (1,359 projected from the embedded preview, 25 from the full-resolution frame, 25 already stitched) |
| Declined | 6 (no trailer), handed back to Nextcloud's own JPEG provider |
| Errors | **0** |
| Cost | 41 ms median, 58 ms at p95, 411 ms worst |

The full-resolution fallback is by far the expensive case (369 ms median, against 41 ms for the embedded preview), which is why it stays a fallback. The camera's own stitch is cheapest at 20 ms, being only a colour conversion.

A 1024 px preview through the full Nextcloud stack, including PNG encoding and storage, costs roughly half a second. It is generated once and cached.

Re-verified on Nextcloud 35 with the app installed, running under the container's own PHP at `memory_limit=128M`: 305 of 311 rendered, 6 declined for carrying no trailer, zero errors, 40 ms median.

## Memory

The full-resolution fallback is the only path that can be large. GD decodes to four bytes a pixel whatever the output size, and has no way to decode a JPEG at reduced scale, so an 18 MP frame needs about 70 MB and a 72 MP one about 290 MB. The renderer checks the frame's dimensions before decoding and refuses rather than exhausting the limit, because running out of memory inside `imagecreatefromstring` is a fatal error that takes the whole request down instead of raising something catchable.

Files the app declines fall through to Nextcloud's own JPEG provider, which then has to decode a full-resolution dual-fisheye frame itself. Depending on `preview_max_memory` (core's default is 256 MB, compared against `width * height * 4`), core may refuse them too, or run out of memory.

## Sharing `image/jpeg` with Nextcloud's own provider

Nextcloud orders preview providers by the **length of their mimetype regex**, descending. This app registers `/^image\/jpeg$/`, which is longer than core's `/image\/jpeg/` and so is tried first. It then looks for the Insta360 trailer magic and returns `null` for anything else, so ordinary JPEGs fall straight through to core.

That ordering is an implementation detail of Nextcloud, not published API. If it changes, the failure is mild: core renders the frame it finds, which is the unprojected lens pair.

## Why `image/jpeg`, and why the mapping has to be added by hand

A `.insp` is a JPEG: everything in front of the trailer is a complete one, and PHP's `finfo` already reports `image/jpeg` for these files. Nextcloud disagrees only because its extension table has never heard of the format, so the mapping makes the extension agree with content detection. It's also the only option that works: Memories decides what to index from a hard-coded list of image mimetypes, so a bespoke `image/x-…` type would never be indexed.

Nextcloud reads custom mimetype mappings only from `config/mimetypemapping.json`. An app *can* write that file itself: Nextcloud's Maps app does it in a repair step (`lib/Migration/RegisterMimeType.php`, merging into the file via `\OC::$configDir` and calling `IMimeTypeLoader::updateFilecache`), with a matching unregister step. golblick deliberately doesn't, so the admin sees the config change; it relies on private API (`\OC::$configDir`) and fails on a read-only config directory. The private `registerType()` on the mimetype detector looks like another route and is a trap: calling it before the defaults load makes the loader think mappings are already present, and it skips every built-in type.

The mapping also tells the rest of Nextcloud that the original file is an ordinary photo, so anything that serves originals directly (Memories' zoom, for one) serves the lens pair.

## Levelling routes

| Route | What it fixes | Stills in the test library |
|---|---|---|
| The camera's own stitch | everything; it was levelled on the device | 48 (X5 only) |
| Gravity, from the inertial record | roll and pitch | 1,384 (417 from their own record, 967 from another frame of the same shutter press) |
| The lens calibration | the sensor's mounting angle only | the fallback when neither of the above is available |

The provider looks for a sibling frame only in the same folder. Without any levelling a OneR renders 90° on its side, so the calibration route is the floor.

## Testing

Use a throwaway Nextcloud in Docker, never an instance holding real photos. Previews are cached on the server, and the browser caches them under a URL keyed on the file's etag, so after changing the renderer: redeploy the app, clear previews with `occ preview:cleanup` (not by deleting files, which leaves the database rows behind), and make sure the browser fetches fresh copies before judging the result.
