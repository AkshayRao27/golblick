# Implementation notes for agents

Details behind the [README](README.md), for anyone (human or coding agent) changing the app. The container format itself is documented in [docs/formats/insta360-agent-notes.md](../docs/formats/insta360-agent-notes.md), which owns every measured fact about the files.

## No new server-side dependency

The whole reader is reimplemented here in PHP: the trailer walk, the protobuf field walk, the lens calibration parse and the equirectangular projection. Pixels go through **GD**, which Nextcloud already requires. Nothing shells out except `Service/VideoDecoder`, for OneR and X3 video thumbnails only (see [Videos](#videos-libpreviewinsta360videophp)), and the Python library in the parent repository is not called.

```
lib/Insta360/     Trailer · Protobuf · Calibration · EmbeddedPreview · Imu · LensProfile · Keyframes   the reader
lib/Render/       Equirectangular · Seam · Orientation                                                the projection
lib/Preview/      Insta360 · Insta360Video                                                            the providers
lib/Service/      VideoDecoder                                                                        ffmpeg, for video keyframes
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

## Why `image/jpeg`, and why the mapping is only added when the admin asks

A `.insp` is a JPEG: everything in front of the trailer is a complete one, and PHP's `finfo` already reports `image/jpeg` for these files. Nextcloud disagrees only because its extension table has never heard of the format, so the mapping makes the extension agree with content detection. It's also the only option that works: Memories decides what to index from a hard-coded list of image mimetypes, so a bespoke `image/x-…` type would never be indexed.

Nextcloud reads custom mimetype mappings only from `config/mimetypemapping.json`. An app *can* write that file itself: Nextcloud's Maps app does it in a repair step (`lib/Migration/RegisterMimeType.php`, merging into the file via `\OC::$configDir` and calling `IMimeTypeLoader::updateFilecache`), with a matching unregister step. golblick deliberately doesn't do it on install, so the admin sees the config change. Since 0.2.0 the settings page does the same thing when the admin clicks **Register .insp files** (`SetupCheck::register()`): it merges into the existing file, refuses to touch a file that isn't valid JSON or that already maps `insp` to something else, writes through a temporary file and a rename, and then calls `IMimeTypeLoader::updateFilecache('insp', …)`, which is the per-extension half of `occ maintenance:mimetype:update-db --repair-filecache` and needs no `files:scan`. It still relies on private API (`\OC::$configDir`, the directory `OC\Files\Type\Detection` reads), and on a read-only config directory it says so and leaves the step to the admin. The private `registerType()` on the mimetype detector looks like another route and is a trap: calling it before the defaults load makes the loader think mappings are already present, and it skips every built-in type.

The mapping also tells the rest of Nextcloud that the original file is an ordinary photo, so anything that serves originals directly (Memories' zoom, for one) serves the lens pair.

## Memories zoom (`lib/Middleware/MemoriesZoom.php`)

Memories loads `/apps/memories/api/image/decodable/{id}` when the viewer zooms past the preview, controlled by its `high_res_cond` setting (`zoom` by default). For `image/jpeg` that endpoint returns the original bytes, so a `.insp` zoomed into the lens pair. The app registers a **global** middleware (`registerMiddleware(..., true)`, NC 26+) whose `afterController` matches `OCA\Memories\Controller\ImageController::decodable`, a 200 response and a `.insp` extension, and replaces the body with a panorama from the preview provider at `zoom_width` (app config, default 4096, clamped 1024–4096). Memories' controller still runs first and decides access, so nothing new is exposed. Renders are cached in app data as `zoom/{fileid}-{etag}-{width}.jpg`; a new etag replaces the old entry.

Memories' own sphere view (after 9.1.0-alpha.2, upstream `b139f975`) loads the same endpoint, so this middleware is also what puts the stitched panorama on its sphere. Without it the sphere shows the lens pair on its side. Memories classifies a 2:1 `.insp` as `pano = 1` ("wide"): a "View panorama" button, not the automatic sphere that `pano = 2` (GPano) gets.

| Measured on NC 35.0.0 / PHP 8.4.25 / Memories 9.0.1 | |
|---|---|
| OneR, cold, by width | 1920: 5.7 s · 2048: 6.2 s · 3072: 11.0 s · 4096: 19.0 s (about 2.2 µs per output pixel) |
| X5, cold | 1.8 s (its stored stitch, 2560 wide) |
| Cached | 0.45 s, mostly Memories reading the original before the swap |

What it doesn't cover, and why:

- **WebDAV downloads are left alone.** files_photospheres builds its sphere from the WebDAV download (`node.encodedSource`), and its button depends on a DAV property computed from the file's XMP. Rewriting either would change what downloads and sync clients receive.
- **The Viewer app** (Files, Photos) never loads the original for a JPEG that has a preview; it requests a screen-sized preview, capped by `preview_max_x`. Zoom there enlarges the preview.
- **Class and method names are not API.** If Memories renames them, the middleware stops matching and both zoom and Memories' sphere show the lens pair again.
- ⚠️ When testing a redeploy, the official image runs `opcache.revalidate_freq=60`, and Apache's workers keep the old bootstrap: a newly registered middleware did nothing until `apachectl graceful`.

## Sphere viewer (`src/`, built into `js/`)

`lib/Listener/LoadSphereViewer.php` adds `js/golblick-main.mjs` to every logged-in page rendered for `files`, `photos` and `memories` (`BeforeTemplateRenderedEvent`). Nothing in those apps is configured or patched. The script adds a **View as sphere** entry in three places; all three open the same full-window overlay (`src/overlay.ts`), which starts on `/core/preview?…&x=2048` and swaps in `/apps/golblick/sphere/{id}` (the `PanoramaStore` render shared with `MemoriesZoom`). three.js loads as a separate chunk only when a sphere opens.

| Where | Hook | Finds the file by | Stability |
|---|---|---|---|
| Files list | `registerFileAction` from `@nextcloud/files` ~4.0 (shared registry `window._nc_files_scope.v4_0`) | the node | public API; pin the major to what the server ships |
| Viewer (Files, Photos) | button inserted into `#viewer .modal-header .header-actions` | `fileId=` or `/preview/{id}` in the active image's `src` | DOM, provisional |
| Memories | button inserted into `.memories-viewer .top-bar .action-items`; skipped when `_m.viewer.currentPhoto.pano > 0` for the open file, i.e. when Memories offers its own sphere (after 9.1.0-alpha.2; the label is translated and on phones sits in the "…" menu, so the page is not checked) | `#v/{day}/{id}` in the URL hash | DOM, provisional |

- **Buttons are clones of a neighbouring button**, with the icon and label replaced. Copying class names alone showed the browser's default border: Nextcloud's buttons get their look from scoped styles keyed on `data-v-*` attributes, which a clone carries. Computed styles of the clone and its neighbour were compared in Chromium and matched in both places.
- `GET /apps/golblick/sphere/{id}/info` (name check only, cheap) and `GET /apps/golblick/sphere/{id}` (the JPEG) are `NoCSRFRequired` read-only GETs, resolved inside the signed-in user's folder.
- **Public share links** (`lib/Controller/PublicSphereController.php`, `GET /apps/golblick/s/{token}/sphere/{id}[/info]`, switch `sphere_public`, default on). A share link's page is Files plus the Viewer, so the same two buttons work once the script is loaded: `LoadSphereViewer` also listens for `OCA\Files_Sharing\Event\BeforeTemplateRenderedEvent`, skips it when it has a scope (the password prompt), and passes the token as `config.share`. The controller extends `PublicShareController`, so core's middleware checks the token, throttles guessing and 404s a password share not unlocked in this session. The file is the shared file itself or `Folder::getFirstNodeById` inside the shared folder, so an id from elsewhere in the owner's files is a 404. It follows core's public previews: read permission and `IShare::canSeeContent()`. ⚠️ That method checks the share's `permissions.download` attribute and the admin's `shareapi_allow_view_without_download`, not the `hide_download` column; a share with `hide_download=1` still shows content, as core's previews do. Tested on the official Debian image and on Nextcloud AIO: file share, folder share, group folder share, an id outside the share, a bad token, a password share not unlocked, an upload-only share and the switch off are all refused; a share with the download attribute off answered 200 with view-without-download on and refused with it off, the same as core's `publicpreview`. The sphere starts on core's `publicpreview` (by path, which `info` returns) and "Report to golblick" isn't offered.
- The sphere code is a cut-down port of `PsPanorama.ts` from the Memories branch: full spheres only, same mirror fix and drag scaling.
- Build: `npm ci && npm run build` in `nextcloud-app/`, then commit `js/`. The app installs by copying the folder, so the built files have to be in the repository. `npm run typecheck` runs `tsc`. Vite doesn't strip whitespace in library ES builds, so `vite.config.ts` sets `minify: 'terser'`: the three.js chunk went from 849 KB (180 KB gzipped) to 531 KB (129 KB). There is no downstream bundler to tree-shake for.
- Test with a headless browser on a running server: the Files action is inside the row's "Actions" menu, not the sharing button next to it.
- **Report to golblick** (`src/report.ts`, `lib/Service/CameraReport.php`, `GET /apps/golblick/report/{id}`, CSRF-checked, same user-folder resolution as the sphere endpoints). The app's counterpart of the CLI's `golblick report`, in the same layout, with records sorted by id in both so they line up. Two issue forms, picked by the `tested` line (a measured lens profile, `LensProfile::isMeasured()` / `lens_profile()`, in both): tested → `photo-problem.yml`, title `Photo problem: <model>, <firmware> (Nextcloud app|command line)`; untested → `untested-camera.yml`, title `Untested camera: …`. An unreadable `.insp` is a photo problem; in the CLI an unrecognised file with a foreign extension goes to untested camera. It says what *this app* does, which differs from the CLI: an X5 is shown from the camera's stitch, so it has no levelling line. The levelling line comes from `Preview\Insta360::levelling()`, the provider's own decision, not a copy of it. It leaves out the name (Insta360 names carry the date and time), the folder and the serial; PHP's `FormatError` messages carry no path, so nothing needs scrubbing here, unlike the CLI. A native `<dialog>`, not `@nextcloud/dialogs`: Files cancels the default on Escape, so the dialog closes itself on keydown, and Nextcloud's reset removes the `margin:auto` that centres it. ⚠️ A burst split across folders reports "no inertial record here or in the rest of the burst" for the frames away from the donor: `burstImu()` searches the file's own folder only, by design.

## Admin settings (`lib/Settings/`, `lib/Service/Settings.php`, `src/admin.ts`)

One page under Administration settings, own section. `src/admin.ts` renders it in plain DOM from `GET /apps/golblick/settings/status`; changes save immediately. `SettingsController` is admin-only and CSRF-checked because no method opts out.

| App config key | Default | What reads it |
|---|---|---|
| `zoom_width` | 4096 | `PanoramaStore`. The page offers 1024/2048/3072/4096; any value set with `occ` is clamped to 1024–4096 |
| `memories_zoom` | yes | `MemoriesZoom::afterController`. Off = Memories gets the original (the lens pair) |
| `sphere_files` | yes | `LoadSphereViewer` → initial state `config.files` → both Files actions, "View as sphere" and "Report to golblick" |
| `sphere_viewer` | yes | same, `config.viewer` → the button in the Viewer (Files and Photos) |
| `sphere_memories` | yes | same, `config.memories` → the button in Memories' viewer. With all three `sphere_*` off the script isn't loaded at all |
| `sphere_public` | yes | on public share links, the Files and Viewer buttons (under their own switches) through `PublicSphereController`; off, the script isn't loaded there and the endpoints answer `sphere: false` / 404 |
| `prerender` | no | `BackgroundJob\Prerender` |

- Each line of the setup check (`SetupCheck::run()`) covers a failure that has actually happened. The `.insp` counts query `filecache` by `name ILIKE '%.insp'` with `path LIKE 'files/%'` (user files, not trash or app data). That filter also matters for group folders: a folder's files live on its own storage under `files/`, but the data directory's root storage can carry a second, stale index of the same files under `__groupfolders/<id>/files/`, which no user mounts. One instance had 1,137 such rows beside 1,438 real ones, none updated in over a year; dropping the filter would count both. That is a sequential scan, measured at 157 ms cold and 72 ms warm on a 308k-row PostgreSQL filecache, so the page fetches it after it renders rather than blocking on it.
- ImageMagick isn't this app's dependency. Its line is there because on Nextcloud AIO a missing `imagemagick-raw` makes ImageMagick recurse on any DNG until php-fpm segfaults, and an Insta360 camera shooting RAW puts a DNG beside every `.insp`. `Imagick::queryFormats('DNG')` is safe to call without the coder (returns `[]`, measured on AIO's ImageMagick 7.1.2-30); reading the file is what crashes.
- Pre-rendering is a `TimedJob` every 15 minutes that stops after 120 s. It keeps no state: it walks `.insp` files newest first by `mtime` (sync clients keep the camera's time; on one real library 1,437 of 1,438 matched the date in the file name) and skips any already cached at the current width, so each run continues where the last left off and a newly added photo goes first. Cached files are skipped by comparing `<fileid>-<etag>-<width>.jpg` against one listing of the cache folder before any file is opened. A file the renderer refuses (no camera data) is tried again every run; the refusal happens while reading the trailer, so it costs little. A group folder file has no owner home to open it through, so it is opened via `IUserMountCache::getMountsForFileId()` and the folder of the first user who has it mounted; the cached panorama is the same whoever renders it and is only served through endpoints that check the viewer's own access. Measured on a 4-core AIO copy: one run took 129 s and rendered 6 OneR panoramas at 4096.
- The cache figures count entries by name: `<fileid>-<etag>-<width>.jpg`. Entries at another width are left by a size change and replaced only when their file is rendered again, hence the clear button.
- In current themes `--color-success` and its siblings are pale tints; the icons use the solid `--color-element-success` and so on.

## Videos (`lib/Preview/Insta360Video.php`)

Opt-in: `.insv` is mapped to `application/x-insta360-insv` only when the admin presses **Register .insv files** (`SetupCheck::register('insv')`). A type nothing else claims, on purpose: `video/mp4` would put the files in Memories and the Viewer, which would play the raw fisheye (one lens on a OneR, the first of two streams on an X5). Measured on a test instance: after registering and `occ memories:index`, no `.insv` row in `oc_memories` or `oc_memories_failures`; clicking one in Files downloads it. Step 3 of the video plan (playback in Memories) is when the type changes.

- **Trailer reads by seeking.** A video trailer runs to 83 MB on an X5, so `Trailer::read($handle, $only)` locates every record by walking footers (or the X5 video index) through seeks and reads only the payloads asked for; `fetch()` reads one more later, while the handle is open. A walk longer than 64 records counts as not closing, which can only make it refuse. `get()` on a record that exists but wasn't read throws rather than returning null. Checked against the Python reader on all 1,783 `.insp`/`.insv`/`.lrv` files in one library: identical record ids, sizes and metadata, including the 83 X5 videos read through the index.
- **X5:** record `0x0200` is NV12, stitched and levelled by the camera, so it goes through `Equirectangular::fromNv12` as an X5 still does.
- **OneR, X3:** records `0x0200` and `0x0500` are the opening frame's keyframes (`Keyframes`, a port of `keyframe.py`). `VideoDecoder` finds ffmpeg as core's Movie provider does (`preview_ffmpeg_path`, then `IBinaryFinder`), writes each stream to a temporary file, and has ffmpeg scale each lens and `hstack` them into the lens pair at the width needed, so PHP only holds the finished pair, which goes through `refuseIfTooBigToDecode` before GD decodes it. Files, not pipes, because a 1.5 MB keyframe in and a 10 MB PNG out can deadlock on pipe buffers. 60-second timeout. Then `Equirectangular::fromLensPair` as for a still.
- **Levelling** uses the first `Imu::OPENING_SAMPLES` (1,500) of the record, the same rule as `imu.py`, which says why: memory (a 23-minute clip holds about 700,000 samples, and PHP holds each as an array) and the opening frame being at the start. Past that, `Imu::decode` still checks every timecode, so a stride is accepted or refused on the whole record exactly as the Python does.
- **`_10_` files** have no trailer; the provider reads the `_00_` file of the same name in the same folder, so both show the same picture.
- **Measured** on the official Debian image with ffmpeg added on two OneR clips, one X3 clip with their `_10_` partners, an X5 clip and a OneR proxy: every preview 200, 1.0 s (X5) to 3.8 s (OneR) at 1024. Against `golblick render` at 1024 on the same files, the fitted rotation between the two is 0.00–0.16° and the mean difference 3–15 grey levels, the same size as the PHP-to-Python difference on two `.insp` photos measured the same way (9–12), so nothing video-specific.

## Levelling routes

| Route | What it fixes | Stills in the test library |
|---|---|---|
| The camera's own stitch | everything; it was levelled on the device | 48 (X5 only) |
| Gravity, from the inertial record | roll and pitch | 1,384 (417 from their own record, 967 from another frame of the same shutter press) |
| The lens calibration | the sensor's mounting angle only | the fallback when neither of the above is available |

The provider looks for a sibling frame only in the same folder. Without any levelling a OneR renders 90° on its side, so the calibration route is the floor.

## Testing

Use a throwaway Nextcloud in Docker, never an instance holding real photos. Previews are cached on the server, and the browser caches them under a URL keyed on the file's etag, so after changing the renderer: redeploy the app, clear previews with `occ preview:cleanup` (not by deleting files, which leaves the database rows behind), and make sure the browser fetches fresh copies before judging the result.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
