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
  sphere_buttons: boolean;
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
const ICON: Record<Level, string> = { ok: '✓', warn: '!', error: '✕', info: 'i' };

/**
 * Messages that must outlive a redraw: actions that change the numbers on the
 * page reload the status, which rebuilds every section.
 */
const carried = new Map<string, { text: string; level: 'ok' | 'error' }>();

/** A note under a control that says whether the last action worked. */
function feedback(key: string) {
  const node = el('p', { className: 'golblick-feedback', role: 'status' });
  const set = (text: string, level: 'ok' | 'error') => {
    node.textContent = text;
    node.dataset.level = level;
    carried.set(key, { text, level });
  };
  const kept = carried.get(key);
  if (kept) {
    node.textContent = kept.text;
    node.dataset.level = kept.level;
    carried.delete(key);
  }
  return { node, ok: (text: string) => set(text, 'ok'), fail: (text: string) => set(text, 'error') };
}

async function save(change: Partial<SettingsState>, note: ReturnType<typeof feedback>) {
  try {
    await api('PUT', '/settings', change);
    note.ok('Saved.');
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
      el('span', { className: 'golblick-icon', ariaHidden: 'true' }, ICON[c.level]),
      el('div', {}, el('strong', {}, c.title), el('p', {}, c.detail)))));
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
          + 'Memories adds them to the timeline at its next background run, or straight away with occ memories:index.');
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
  const switchesNote = feedback('switches');

  root.replaceChildren(
    el('h2', {}, '360 photos (golblick)'),

    el('h3', {}, 'Setup'),
    checks, actions, setupNote.node,

    el('h3', {}, 'Zooming and the sphere view'),
    el('p', { className: 'settings-hint' },
      'Zooming in Memories and the sphere view use a full-size panorama, rendered the first time someone needs it and then kept. '
      + 'A larger one is sharper and takes longer the first time: on a OneR photo, about 6 seconds at 2048 and 19 at 4096. '
      + 'X5 photos stop at 2560, the size of the panorama the camera stores.'),
    el('label', {}, 'Panorama size ', width), widthNote.node,

    el('h3', {}, 'Panorama cache'),
    el('p', {}, `${status.cache.files} panoramas, ${megabytes(status.cache.bytes)}.`
      + (stale === 1 ? ' One of them was made at a different size; it is replaced when that photo is viewed again, or removed now by clearing the cache.'
        : stale > 1 ? ` ${stale} of them were made at a different size; each is replaced when its photo is viewed again, or all are removed now by clearing the cache.` : '')),
    clear, cacheNote.node,

    el('h3', {}, 'Rendering ahead of time'),
    toggle('Render full-size panoramas in the background',
      'So the first zoom or sphere view of a photo doesn\'t wait. It runs in Nextcloud\'s background jobs, about two minutes at a time, '
      + 'and costs real CPU time: at 4096 pixels, roughly 19 seconds per OneR photo.',
      s.prerender, (on) => void save({ prerender: on }, prerenderNote)),
    el('p', { className: 'golblick-progress' }, `${status.cache.current} of ${status.insp} .insp files have a panorama at the current size.`),
    prerenderNote.node,

    el('h3', {}, 'Integrations'),
    el('p', { className: 'settings-hint' },
      'These rely on details of other apps that can change in an update. If one stops working, it can be turned off here without affecting the previews. '
      + 'Changes apply when a page is next loaded.'),
    toggle('Show the panorama when zooming in Memories',
      'Without this, zooming into a .insp in Memories shows the two fisheye circles, and so does Memories\' own sphere view in releases that have one.',
      s.memories_zoom, (on) => void save({ memories_zoom: on }, switchesNote)),
    toggle('"View as sphere" in the Files actions menu',
      'Uses the Files app\'s own interface for this.',
      s.sphere_files, (on) => void save({ sphere_files: on }, switchesNote)),
    toggle('"View as sphere" buttons in the image viewer and in Memories',
      'Added to those apps\' pages from outside, because neither lets another app add a button. If a later version of either moves things around, the button may not appear.',
      s.sphere_buttons, (on) => void save({ sphere_buttons: on }, switchesNote)),
    switchesNote.node,
  );
}

async function load(showLoading = true) {
  if (!root) return;
  if (showLoading) root.querySelector('.settings-hint')?.replaceChildren('Checking…');
  try {
    render(await api<Status>('GET', '/settings/status'));
  } catch (e) {
    root.replaceChildren(el('h2', {}, '360 photos (golblick)'),
      el('p', { className: 'golblick-feedback', role: 'status' }, `Could not load the settings: ${(e as Error).message}`));
  }
}

void load();
