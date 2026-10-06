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
  prerender: boolean;
};
type Status = {
  settings: SettingsState;
  checks: Check[];
  cache: { files: number; bytes: number; current: number };
  insp: number;
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

async function save(change: Partial<SettingsState>, note: ReturnType<typeof feedback>) {
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
  const mapping = status.checks.find((c) => c.id === 'mapping');
  if (mapping && mapping.level !== 'ok') {
    const register = el('button', { type: 'button', className: 'primary', textContent: 'Register .insp files' });
    register.addEventListener('click', async () => {
      register.disabled = true;
      try {
        const r = await api<{ written: boolean; rows: number }>('POST', '/settings/register');
        setupNote.ok(`${r.written ? 'Added the mapping to config/mimetypemapping.json. ' : ''}Updated ${r.rows} files. `
          + 'Memories adds them to the timeline at its next background run. You can also run "occ memories:index" to index them immediately.');
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

  // ---- Integrations
  const zoomNote = feedback('memories_zoom');
  const filesNote = feedback('sphere_files');
  const memoriesButtonNote = feedback('sphere_memories');
  const viewerNote = feedback('sphere_viewer');

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

    el('h3', {}, 'Integrations'),
    el('p', { className: 'settings-hint' },
      'These rely on details of other apps that can change in an update. If one stops working, it can be turned off here without affecting previews. '
      + 'Each switch is saved as soon as you change it; pages that are already open pick up the change when they are reloaded.'),

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
    toggle('Add "View as sphere" button',
      'Adds it to a .insp file\'s actions menu, through the Files app\'s own interface for this.',
      s.sphere_files, (on) => void save({ sphere_files: on }, filesNote)),
    filesNote.node,

    el('h4', {}, 'Photos'),
    toggle('Add "View as sphere" button',
      'In the image viewer that Files and Photos open. The viewer has no way for other apps to add buttons, so golblick inserts this one into its top bar itself.',
      s.sphere_viewer, (on) => void save({ sphere_viewer: on }, viewerNote)),
    viewerNote.node,
  );
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
