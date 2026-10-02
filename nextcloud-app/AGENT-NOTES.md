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

## Memories zoom (`lib/Middleware/MemoriesZoom.php`)

Memories (9.0.1 and earlier) loads `/apps/memories/api/image/decodable/{id}` when the viewer zooms past the preview, controlled by its `high_res_cond` setting (`zoom` by default). For `image/jpeg` that endpoint returns the original bytes, so a `.insp` zoomed into the lens pair. The app registers a **global** middleware (`registerMiddleware(..., true)`, NC 26+) whose `afterController` matches `OCA\Memories\Controller\ImageController::decodable`, a 200 response and a `.insp` extension, and replaces the body with a panorama from the preview provider at `zoom_width` (app config, default 4096, clamped 1024–4096). Memories' controller still runs first and decides access, so nothing new is exposed. Renders are cached in app data as `zoom/{fileid}-{etag}-{width}.jpg`; a new etag replaces the old entry.

| Measured on NC 35.0.0 / PHP 8.4.25 / Memories 9.0.1 | |
|---|---|
| OneR, cold, by width | 1920: 5.7 s · 2048: 6.2 s · 3072: 11.0 s · 4096: 19.0 s (about 2.2 µs per output pixel) |
| X5, cold | 1.8 s (its stored stitch, 2560 wide) |
| Cached | 0.45 s, mostly Memories reading the original before the swap |

What it doesn't cover, and why:

- **WebDAV downloads are left alone.** files_photospheres builds its sphere from the WebDAV download (`node.encodedSource`), and its button depends on a DAV property computed from the file's XMP. Rewriting either would change what downloads and sync clients receive.
- **The Viewer app** (Files, Photos) never loads the original for a JPEG that has a preview; it requests a screen-sized preview, capped by `preview_max_x`. Zoom there enlarges the preview.
- **Class and method names are not API.** If Memories renames them, the middleware stops matching and zoom shows the lens pair again.
- ⚠️ When testing a redeploy, the official image runs `opcache.revalidate_freq=60`, and Apache's workers keep the old bootstrap: a newly registered middleware did nothing until `apachectl graceful`.

## Sphere viewer (`src/`, built into `js/`)

`lib/Listener/LoadSphereViewer.php` adds `js/golblick-main.mjs` to every logged-in page rendered for `files`, `photos` and `memories` (`BeforeTemplateRenderedEvent`). Nothing in those apps is configured or patched. The script adds a **View as sphere** entry in three places; all three open the same full-window overlay (`src/overlay.ts`), which starts on `/core/preview?…&x=2048` and swaps in `/apps/golblick/sphere/{id}` (the `PanoramaStore` render shared with `MemoriesZoom`). three.js loads as a separate chunk only when a sphere opens.

| Where | Hook | Finds the file by | Stability |
|---|---|---|---|
| Files list | `registerFileAction` from `@nextcloud/files` ~4.0 (shared registry `window._nc_files_scope.v4_0`) | the node | public API; pin the major to what the server ships |
| Viewer (Files, Photos) | button inserted into `#viewer .modal-header .header-actions` | `fileId=` or `/preview/{id}` in the active image's `src` | DOM, provisional |
| Memories | button inserted into `.memories-viewer .top-bar .action-items`; skipped if a button labelled "View as panorama" exists | `#v/{day}/{id}` in the URL hash | DOM, provisional |

- **Buttons are clones of a neighbouring button**, with the icon and label replaced. Copying class names alone showed the browser's default border: Nextcloud's buttons get their look from scoped styles keyed on `data-v-*` attributes, which a clone carries. Computed styles of the clone and its neighbour were compared in Chromium and matched in both places.
- `GET /apps/golblick/sphere/{id}/info` (name check only, cheap) and `GET /apps/golblick/sphere/{id}` (the JPEG) are `NoCSRFRequired` read-only GETs, resolved inside the signed-in user's folder. Public shares get no button.
- The sphere code is a cut-down port of `PsPanorama.ts` from the Memories branch: full spheres only, same mirror fix and drag scaling.
- Build: `npm ci && npm run build` in `nextcloud-app/`, then commit `js/`. The app installs by copying the folder, so the built files have to be in the repository. `npm run typecheck` runs `tsc`. Vite doesn't strip whitespace in library ES builds, so the three.js chunk is about 850 KB (180 KB gzipped).
- Test with a headless browser on a running server: the Files action is inside the row's "Actions" menu, not the sharing button next to it.

## Levelling routes

| Route | What it fixes | Stills in the test library |
|---|---|---|
| The camera's own stitch | everything; it was levelled on the device | 48 (X5 only) |
| Gravity, from the inertial record | roll and pitch | 1,384 (417 from their own record, 967 from another frame of the same shutter press) |
| The lens calibration | the sensor's mounting angle only | the fallback when neither of the above is available |

The provider looks for a sibling frame only in the same folder. Without any levelling a OneR renders 90° on its side, so the calibration route is the floor.

## Testing

Use a throwaway Nextcloud in Docker, never an instance holding real photos. Previews are cached on the server, and the browser caches them under a URL keyed on the file's etag, so after changing the renderer: redeploy the app, clear previews with `occ preview:cleanup` (not by deleting files, which leaves the database rows behind), and make sure the browser fetches fresh copies before judging the result.
