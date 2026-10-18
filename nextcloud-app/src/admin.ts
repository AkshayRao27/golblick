/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * The admin settings page (lib/Settings/Admin.php renders its mount point).
 * Plain DOM, like the rest of the app's front end: four short sections do not
 * justify a framework. Every change is saved as soon as it is made.
 */
import { getRequestToken } from '@nextcloud/auth';
import { generateUrl } from '@nextcloud/router';

type Level = 'ok' | 'warn' | 'error' | 'info';
type Check = { id: string; level: Level; title: string; detail: string };
type SettingsState = {
  zoom_width: number;
  memories_zoom: boolean;
  sphere_files: boolean;
  sphere_viewer: boolean;
  sphere_memories: boolean;
  sphere_public: boolean;
  prerender: boolean;
  video_width: number;
  /** [from, to) in the server's time zone, or null for any time. */
  video_hours: [number, number] | null;
  video_render: boolean;
  video_beside: boolean;
  video_bake: boolean;
};
type Status = {
  settings: SettingsState;
  checks: Check[];
  cache: { files: number; bytes: number; current: number };
  insp: number;
  videos: {
    usable: boolean;
    clips: number;
    bytes: number;
    hours: { zone: string; now: string; open: boolean };
    cache: { files: number; bytes: number; current: number };
    rendering: {
      fileid: number; started: number | null; baking: boolean; gpu: boolean;
      clip: string | null; duration: number | null; done: number | null;
    } | null;
    queue: { clips: number; bytes: number };
    failed: number;
    worker: { alive: boolean; seen: number; device: string; encoder: string; stitch: boolean } | null;
    compose: { aio: boolean; yaml: string } | null;
    beside: number;
  };
};

const root = document.getElementById('golblick-admin');

async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(generateUrl(`/apps/golblick${path}`), {
    method,
    credentials: 'same-origin',
    headers: { requesttoken: getRequestToken() ?? '', 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error((data as { error?: string }).error ?? `${response.status} ${response.statusText}`);
  return data as T;
}

/** document.createElement with properties and children; props are set as DOM properties. */
function el<K extends keyof HTMLElementTagNameMap>(tag: K, props: Record<string, unknown> = {}, ...children: (Node | string)[]): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  Object.assign(node, props);
  node.append(...children);
  return node;
}

const megabytes = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
const gigabytes = (bytes: number) => (bytes < 1024 ** 3 ? megabytes(bytes) : `${(bytes / 1024 ** 3).toFixed(1)} GB`);
/** 75 → "1:15", 3725 → "1:02:05". */
const clock = (seconds: number) => {
  const s = Math.floor(seconds);
  const parts = [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60];
  return (parts[0] > 0 ? parts : parts.slice(1)).map((n, i) => (i === 0 ? String(n) : String(n).padStart(2, '0'))).join(':');
};
/**
 * How many bytes of camera files make a second of video, to turn a library's
 * size into a duration: 12.5 to 12.7 MB/s measured on an X5 and a OneR clip,
 * 18 on an X3, so this errs long on X3 libraries.
 */
const CAMERA_BYTES_PER_SECOND = 12.5e6;

/** 60 → "1 minute", 400 → "7 minutes", 9000 → "2.5 hours". */
const span = (seconds: number) => {
  const minutes = Math.max(1, Math.round(seconds / 60));
  return minutes < 90 ? `${minutes} minute${minutes === 1 ? '' : 's'}` : `${(seconds / 3600).toFixed(1)} hours`;
};

/**
 * Where the clip being stitched has got to, from ffmpeg's own progress: how
 * much of it is written, how fast that is going, and what is left at that
 * pace. Each clip runs at its own pace, so there's no estimate for the queue.
 */
function renderingLine(r: NonNullable<Status['videos']['rendering']>): string {
  const name = r.clip ? `${r.clip}` : 'One video';
  if (r.baking) return ` ${name} is being steadied on the GPU now.`;
  const since = r.started ? new Date(r.started * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : null;
  let line = ` ${name} is being stitched${r.gpu ? ' on the GPU' : ''} now${since ? `, since ${since}` : ''}`;
  if (r.done !== null && r.duration && r.started) {
    const elapsed = Date.now() / 1000 - r.started;
    const pace = r.done / elapsed;
    line += `: ${clock(r.done)} of ${clock(r.duration)} (${Math.min(100, Math.floor(100 * r.done / r.duration))}%)`;
    if (pace > 0 && r.done > 0) {
      line += `, at ${pace.toFixed(2)}× real time, about ${span(Math.max(0, r.duration - r.done) / pace)} left`;
    }
  }
  return line + '.';
}
/** The Material Design icons the overview page's "Security & setup warnings" list uses, plus its check mark. */
const ICON: Record<Level, string> = {
  ok: 'M21,7L9,19L3.5,13.5L4.91,12.09L9,16.17L19.59,5.59L21,7Z',
  warn: 'M13 14H11V9H13M13 18H11V16H13M1 21H23L12 2L1 21Z',
  error: 'M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z',
  info: 'M13,9H11V7H13M13,17H11V11H13M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2Z',
};

function icon(level: Level) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', ICON[level]);
  svg.append(path);
  return el('span', { className: 'golblick-icon', ariaHidden: 'true' }, svg);
}

type Note = { text: string; level: 'ok' | 'error' | 'pending'; until?: number };

/**
 * Messages that must outlive a redraw: actions that change the numbers on the
 * page reload the status, which rebuilds every section.
 */
const carried = new Map<string, Note>();

/** How long "Saved." stays up. It only confirms the last change, so it must not outlive it. */
const SAVED_FOR_MS = 3000;

/**
 * A note under a control that says whether the last action worked. Results
 * that carry information (rows updated, panoramas removed) and errors stay
 * until the next action; a bare "Saved." fades, so a second change never sits
 * under the first one's confirmation.
 */
function feedback(key: string) {
  const node = el('p', { className: 'golblick-feedback', role: 'status' });
  let timer: number | undefined;
  const show = (note: Note | null) => {
    window.clearTimeout(timer);
    node.textContent = note?.text ?? '';
    if (!note) return;
    node.dataset.level = note.level;
    carried.set(key, note);
    if (note.until !== undefined) {
      timer = window.setTimeout(() => {
        show(null);
        // A redraw may have handed this key to a newer note; leave that one alone.
        if (carried.get(key) === note) carried.delete(key);
      }, note.until - Date.now());
    }
  };
  const kept = carried.get(key);
  carried.delete(key);
  if (kept && (kept.until === undefined || kept.until > Date.now())) {
    show(kept);
    if (kept.until === undefined) carried.delete(key);
  }
  return {
    node,
    pending: (text: string) => show({ text, level: 'pending' }),
    saved: () => show({ text: 'Saved.', level: 'ok', until: Date.now() + SAVED_FOR_MS }),
    ok: (text: string) => show({ text, level: 'ok' }),
    fail: (text: string) => show({ text, level: 'error' }),
  };
}

/** What a save sends: the settings as they're shown, except the hours go as "from-to", or "" for any time. */
type Change = Partial<Omit<SettingsState, 'video_hours'>> & { video_hours?: string };

async function save(change: Change, note: ReturnType<typeof feedback>) {
  note.pending('Saving…');
  try {
    await api('PUT', '/settings', change);
    note.saved();
  } catch (e) {
    note.fail(`Not saved: ${(e as Error).message}`);
  }
}

function toggle(label: string, hint: string, checked: boolean, onChange: (on: boolean) => void) {
  const input = el('input', { type: 'checkbox', checked });
  input.addEventListener('change', () => onChange(input.checked));
  return el('div', { className: 'golblick-toggle' },
    el('label', {}, input, ` ${label}`),
    el('p', { className: 'settings-hint' }, hint));
}

function render(status: Status) {
  if (!root) return;
  const s = status.settings;

  // ---- Setup
  const checks = el('ul', { className: 'golblick-checks' }, ...status.checks.map((c) =>
    el('li', { className: `level-${c.level}` },
      icon(c.level),
      el('div', { className: 'golblick-check' },
        el('div', { className: 'golblick-check-name' }, c.title),
        el('div', { className: 'golblick-check-detail' }, c.detail)))));
  const setupNote = feedback('setup');
  const recheck = el('button', { type: 'button', textContent: 'Check again' });
  recheck.addEventListener('click', () => void load());
  const actions = el('div', { className: 'golblick-actions' }, recheck);
  // One button per file type that still needs registering. Videos are opt-in.
  for (const [id, extension, after] of [
    ['video_mapping', 'insv', 'Their thumbnails are made the next time each one is shown in Files.'],
    ['mapping', 'insp', 'Memories adds them to the timeline at its next background run. You can also run "occ memories:index" to index them immediately.'],
  ] as const) {
    const check = status.checks.find((c) => c.id === id);
    if (!check || check.level === 'ok') continue;
    const register = el('button', { type: 'button', className: id === 'mapping' ? 'primary' : '', textContent: `Register .${extension} files` });
    register.addEventListener('click', async () => {
      register.disabled = true;
      try {
        const r = await api<{ written: boolean; rows: number }>('POST', '/settings/register', { extension });
        setupNote.ok(`${r.written ? 'Added the mapping to config/mimetypemapping.json. ' : ''}Updated ${r.rows} files. ${after}`);
        await load(false);
      } catch (e) {
        setupNote.fail((e as Error).message);
        register.disabled = false;
      }
    });
    actions.prepend(register);
  }

  // ---- Zoom and sphere view
  const widthNote = feedback('width');
  const width = el('select', {}, ...[1024, 2048, 3072, 4096].map((w) =>
    el('option', { value: String(w), selected: w === s.zoom_width }, `${w} pixels wide`)));
  width.addEventListener('change', () => void save({ zoom_width: Number(width.value) }, widthNote).then(() => load(false)));

  // ---- Cache
  const cacheNote = feedback('cache');
  const clear = el('button', { type: 'button', textContent: 'Clear cache', disabled: status.cache.files === 0 });
  clear.addEventListener('click', async () => {
    if (!window.confirm('Delete every cached full-size panorama? Each is rendered again the next time someone zooms or opens the sphere view.')) return;
    clear.disabled = true;
    try {
      const r = await api<{ removed: number }>('POST', '/settings/cache/clear');
      cacheNote.ok(`Removed ${r.removed} panoramas.`);
      await load(false);
    } catch (e) {
      cacheNote.fail((e as Error).message);
      clear.disabled = false;
    }
  });
  const stale = status.cache.files - status.cache.current;

  // ---- Pre-render
  const prerenderNote = feedback('prerender');

  // ---- Videos
  const v = status.videos;
  const videoNote = feedback('video_render');
  const besideNote = feedback('video_beside');
  const bakeNote = feedback('video_bake');
  const clock = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const workerLine = v.worker === null
    ? 'No GPU worker found.'
    : v.worker.alive
      ? `GPU worker running: ${v.worker.device}, encoding with ${v.worker.encoder}.` + (v.worker.stitch
        ? ' It stitches the videos as well.'
        : ' It can\'t stitch videos: that needs an NVIDIA card and read access to the data folder, which the compose file below adds.')
      : `The GPU worker was last seen at ${clock(v.worker.seen)} and isn't currently running.`;
  const workerSetup = v.compose === null || (v.worker?.alive && v.worker.stitch) ? null : workerSteps(v.compose);
  const videoWidthNote = feedback('video_width');
  const videoWidth = el('select', {}, ...[2880, 3840].map((w) =>
    el('option', { value: String(w), selected: w === s.video_width }, `${w} × ${w / 2}`)));
  videoWidth.addEventListener('change', () => {
    const width = Number(videoWidth.value);
    // Every clip is stitched again at the new size, which on a big library
    // runs for days on the CPU; say so before doing it.
    if (v.clips > 0 && !window.confirm(`Stitch all ${v.clips} videos again at ${width} wide? That's ${gigabytes(v.bytes)} of camera files, roughly ${span(v.bytes / CAMERA_BYTES_PER_SECOND)} of video. `
      + (v.worker?.alive && v.worker.stitch
        ? 'On the GPU worker that takes about as long again, or up to twice as long. '
        : 'On the server\'s CPU that takes several times as long, and slows the server while it runs. ')
      + 'Until a video has its new copy, its old one plays.')) {
      videoWidth.value = String(s.video_width);
      return;
    }
    void save({ video_width: width }, videoWidthNote).then(() => load(false));
  });
  const hoursNote = feedback('video_hours');
  const hourOptions = (selected: number | null) => Array.from({ length: 24 }, (_, h) =>
    el('option', { value: String(h), selected: h === selected }, `${String(h).padStart(2, '0')}:00`));
  const hoursFrom = el('select', {}, el('option', { value: '', selected: s.video_hours === null }, 'any time'),
    ...hourOptions(s.video_hours?.[0] ?? null));
  const hoursTo = el('select', { disabled: s.video_hours === null }, ...hourOptions(s.video_hours?.[1] ?? 7));
  const saveHours = () => {
    hoursTo.disabled = hoursFrom.value === '';
    if (hoursFrom.value !== '' && hoursFrom.value === hoursTo.value) {
      hoursNote.fail('The start and end have to be different hours.');
      return;
    }
    void save({ video_hours: hoursFrom.value === '' ? '' : `${hoursFrom.value}-${hoursTo.value}` }, hoursNote).then(() => load(false));
  };
  hoursFrom.addEventListener('change', saveHours);
  hoursTo.addEventListener('change', saveHours);
  const videoClearNote = feedback('video_clear');
  const videoClear = el('button', { type: 'button', textContent: 'Delete stitched videos', disabled: v.cache.files === 0 && v.failed === 0 });
  videoClear.addEventListener('click', async () => {
    if (!window.confirm('Delete every stitched video? With background rendering on, they are rendered again, which takes a long time.')) return;
    videoClear.disabled = true;
    try {
      const r = await api<{ removed: number }>('POST', '/settings/videos/clear');
      videoClearNote.ok(`Removed ${r.removed} videos, and cleared the list of videos that couldn't be stitched.`);
      await load(false);
    } catch (e) {
      videoClearNote.fail((e as Error).message);
      videoClear.disabled = false;
    }
  });
  const besideClearNote = feedback('video_clear_beside');
  const besideClear = el('button', { type: 'button', textContent: 'Delete copies saved next to clips', disabled: v.beside === 0 });
  besideClear.addEventListener('click', async () => {
    if (!window.confirm(`Delete the .360.mp4 copies saved next to their clips (${v.beside})? They go to the trash bin, so the space comes back once that is emptied. With stitching and saving on, they are made again.`)) return;
    besideClear.disabled = true;
    try {
      const r = await api<{ removed: number; bytes: number }>('POST', '/settings/videos/clear-beside');
      besideClearNote.ok(`Deleted ${r.removed} copies, ${gigabytes(r.bytes)}.`);
      await load(false);
    } catch (e) {
      besideClearNote.fail((e as Error).message);
      besideClear.disabled = false;
    }
  });
  const videoProgress = `${v.cache.current} of ${v.clips} registered videos are stitched at this size, ${megabytes(v.cache.bytes)} in all.`
    + (v.rendering ? renderingLine(v.rendering) : '')
    + (v.queue.clips > 0 ? ` ${v.queue.clips}${v.rendering ? ' more' : ''} ${v.queue.clips === 1 ? 'is' : 'are'} waiting, ${gigabytes(v.queue.bytes)} of camera files`
      + (!v.hours.open && s.video_hours ? `, until the stitching hours begin at ${String(s.video_hours[0]).padStart(2, '0')}:00.` : '.') : '')
    + (v.failed > 0 ? ` ${v.failed} couldn't be stitched; the server log says why.` : '');

  // ---- Integrations
  const zoomNote = feedback('memories_zoom');
  const filesNote = feedback('sphere_files');
  const memoriesButtonNote = feedback('sphere_memories');
  const viewerNote = feedback('sphere_viewer');
  const publicNote = feedback('sphere_public');

  root.replaceChildren(
    el('h2', {}, 'Golblick (360° Photos)'),

    el('h3', {}, 'Setup'),
    checks, actions, setupNote.node,

    el('h3', {}, 'Zooming and the sphere view'),
    el('p', { className: 'settings-hint' },
      'Zooming in Memories and the sphere view use a full-size panorama. It is rendered the first time someone needs it and then retained. A larger one is sharper but takes longer the first time: for example, about 6 seconds at 2048 and 19 seconds at 4096 for a OneR photo. X5 photos stop at 2560, the size of the panorama the camera stores.'),
    el('label', {}, 'Panorama size ', width), widthNote.node,

    el('h3', {}, 'Panorama cache'),
    el('p', {}, `${status.cache.files} panoramas, ${megabytes(status.cache.bytes)}.`
      + (stale === 1 ? ' One of them was made at a different size; it is replaced when that photo is viewed again, or removed now by clearing the cache.'
        : stale > 1 ? ` ${stale} of them were made at a different size; each is replaced when its photo is viewed again, or all are removed now by clearing the cache.` : '')),
    clear, cacheNote.node,

    el('h3', {}, 'Background rendering'),
    toggle('Render full-size panoramas in the background',
      'Pre-generates panoramas so that the first zoom or sphere view of a photo doesn\'t have waiting time. It runs in Nextcloud\'s background jobs, about two minutes at a time, newest photos first, and costs CPU time: at 4096 pixels, roughly 19 seconds per OneR photo.',
      s.prerender, (on) => void save({ prerender: on }, prerenderNote)),
    el('p', { className: 'golblick-progress' }, `${status.cache.current} of ${status.insp} .insp files have a panorama at the current size.`),
    prerenderNote.node,

    el('h3', {}, 'Videos'),
    el('p', { className: 'settings-hint' },
      'Insta360 videos play as a sphere from Files once the server has stitched them (done in the background, newest first). It is slow and needs memory: for every second of video, about 12 CPU-seconds at 2880 wide and 18 at 3840 (so a five-minute clip takes 15 minutes or more on four cores); a render needs about 1 GB of memory at 2880 and 1.5 GB at 3840, and the copies take about 5 GB per hour of video at 2880 and 9 GB at 3840. The horizon is levelled once per clip, at its start. It needs .insv registered (see Setup), ffmpeg, and the data directory on the local disk. With golblick\'s GPU worker running on an NVIDIA card, the worker stitches instead, at about 2 to 3 CPU-seconds per second of video.'),
    toggle('Stitch videos in the background',
      v.usable ? 'Runs ffmpeg at the lowest priority, one video at a time.' : 'Not available: the data directory isn\'t on local disk.',
      s.video_render, (on) => void save({ video_render: on }, videoNote)),
    videoNote.node,
    toggle('Save each stitched copy next to its clip',
      'Moves each finished copy into the clip\'s folder as an ordinary video file, named after the clip with .360.mp4 at the end, so it shows up in Memories and plays in any app that handles 360° video. It counts against that folder\'s storage and desktop clients sync it like any other file. Copies already stitched are moved over one at a time. Turning this off later leaves saved copies where they are.',
      s.video_beside, (on) => void save({ video_beside: on }, besideNote)),
    besideNote.node,
    toggle('Bake steadying into each copy',
      'Copies then play steadied in any app as well as when downloaded. It needs golblick\'s GPU worker running next to Nextcloud (see the app\'s README); without one, copies stay as stitched and are steadied as they play. Copies stitched before this was switched on aren\'t changed.',
      s.video_bake, (on) => void save({ video_bake: on }, bakeNote)),
    el('p', { className: 'golblick-progress' }, workerLine),
    ...(workerSetup ? [workerSetup] : []),
    bakeNote.node,
    el('label', {}, 'Stitch new videos from ', hoursFrom, ' to ', hoursTo),
    el('p', { className: 'golblick-progress' },
      `No new video is started outside these hours (a running task will be allowed to finish) and finished copies wait to be saved next to their clips (which is the biggest burst of disk writes). The hours are in the server's time zone, ${v.hours.zone}, where it's ${v.hours.now} now.`),
    hoursNote.node,
    el('label', {}, 'Video size ', videoWidth),
    el('p', { className: 'golblick-progress' }, '3840 is sharper, but a browser that decodes video on the CPU may not be able to keep up with it, resulting in choppy playback. Changing the size stitches every clip again.'),
    videoWidthNote.node,
    el('p', { className: 'golblick-progress' }, videoProgress),
    el('div', { className: 'golblick-actions' }, videoClear, besideClear), videoClearNote.node, besideClearNote.node,

    el('h3', {}, 'Integrations'),
    el('p', { className: 'settings-hint' },
      'These rely on details of other apps that can change in an update. If one stops working, it can be turned off here without affecting previews. Each switch is saved as soon as you change it; pages that are already open pick up the change when they are reloaded.'),

    el('h4', {}, 'Memories'),
    toggle('Show panorama when zooming',
      'Without this, zooming into a .insp in Memories shows two fisheye circles, and so does Memories\' own sphere view in releases that have one.',
      s.memories_zoom, (on) => void save({ memories_zoom: on }, zoomNote)),
    zoomNote.node,
    toggle('Add "View as sphere" button',
      'Memories has no way for other apps to add buttons, so golblick inserts this one into the viewer\'s top bar itself. Memories releases that have their own sphere view show their own button instead.',
      s.sphere_memories, (on) => void save({ sphere_memories: on }, memoriesButtonNote)),
    memoriesButtonNote.node,

    el('h4', {}, 'Files'),
    toggle('Add "View as sphere" and "Report to golblick"',
      'Adds both to a .insp file\'s actions menu, through the Files app\'s own interface for this. "Report to golblick" opens an issue on GitHub with a summary of the file filled in: a problem with a photo, or a camera golblick hasn\'t been tested with. The summary leaves out the file\'s name, its folder and the camera\'s serial number.',
      s.sphere_files, (on) => void save({ sphere_files: on }, filesNote)),
    filesNote.node,

    el('h4', {}, 'Photos'),
    toggle('Add "View as sphere" button',
      'In the image viewer that Files and Photos open. The viewer has no way for other apps to add buttons, so golblick inserts this one into its top bar itself.',
      s.sphere_viewer, (on) => void save({ sphere_viewer: on }, viewerNote)),
    viewerNote.node,

    el('h4', {}, 'Public share links'),
    toggle('Offer "View as sphere" on share links',
      'Visitors to a share link get the Files and image viewer buttons above, if those are on. Only for shares that let visitors see the files, and not for a password-protected share until its password is entered. Opening a photo\'s sphere renders its full-size panorama the first time, so a visitor can make the server do that for every .insp in a shared folder.',
      s.sphere_public, (on) => void save({ sphere_public: on }, publicNote)),
    publicNote.node,
  );
}

/** Whether the worker steps were open, so a redraw after saving a setting keeps them open. */
let workerStepsOpen = false;

/** How to start the GPU worker, with the compose file the server filled in for itself. */
function workerSteps(compose: { aio: boolean; yaml: string }) {
  const yaml = el('pre', { className: 'golblick-compose' }, compose.yaml);
  const copyNote = feedback('compose_copy');
  const copy = el('button', { type: 'button', textContent: 'Copy' });
  copy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(compose.yaml);
      copyNote.ok('Copied.');
    } catch {
      // No clipboard outside HTTPS: select the text so it can be copied by hand.
      window.getSelection()?.selectAllChildren(yaml);
      copyNote.fail('Couldn\'t copy; the text is selected, so copy it with Ctrl+C.');
    }
  });
  const toolkit = el('a', { href: 'https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html', target: '_blank', rel: 'noreferrer' }, 'NVIDIA\'s container toolkit');
  const steps = el('details', { className: 'golblick-worker-setup', open: workerStepsOpen },
    el('summary', {}, 'Set up the GPU worker'),
    el('ol', {},
      el('li', {}, 'On the Docker host, install ', toolkit, ' and run ', el('code', {}, 'nvidia-ctk runtime configure --runtime=docker'), '. It has been tried with NVIDIA cards only.'),
      el('li', {}, 'Save this as ', el('code', {}, 'compose.yaml'), ' in a folder of its own on that host. ',
        compose.aio
          ? 'If you gave the AIO mastercontainer NEXTCLOUD_DATADIR, put the same line, such as NEXTCLOUD_DATADIR=/mnt/ncdata, in a file named .env next to it. The paths assume Docker keeps its volumes in /var/lib/docker.'
          : 'The folder paths are as this server sees them. If Nextcloud runs in a container, change each to the same folder\'s path on the host.'),
      el('li', {}, 'Run ', el('code', {}, 'docker compose up -d'), ' in that folder, and reload this page a minute later.')),
    yaml, copy, copyNote.node);
  steps.addEventListener('toggle', () => { workerStepsOpen = steps.open; });
  return steps;
}

async function load(showLoading = true) {
  if (!root) return;
  if (showLoading) root.querySelector('.settings-hint')?.replaceChildren('Checking…');
  try {
    render(await api<Status>('GET', '/settings/status'));
  } catch (e) {
    root.replaceChildren(el('h2', {}, 'Golblick (360° Photos)'),
      el('p', { className: 'golblick-feedback', role: 'status' }, `Could not load the settings: ${(e as Error).message}`));
  }
}

void load();
