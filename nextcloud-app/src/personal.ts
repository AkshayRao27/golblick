/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * The personal settings page: what a 360 photo or video does when it opens in
 * Memories. Each choice saves as soon as it is made (lib/Controller/PreferencesController.php),
 * and main.ts reads them from the page's initial state.
 */
import { getRequestToken } from '@nextcloud/auth';
import { loadState } from '@nextcloud/initial-state';
import { generateUrl } from '@nextcloud/router';

type Preferences = { open_video: string; open_photo: string };

const QUESTIONS: { name: keyof Preferences; title: string; hint: string; choices: [string, string][] }[] = [
  {
    name: 'open_video',
    title: '360° videos in Memories',
    hint: 'Memories plays a 360° video as a flat, stretched rectangle. This applies to stitched copies and to any MP4 marked as 360° video.',
    choices: [
      ['sphere', 'Open as a sphere'],
      ['paused', 'Show flat, without playing; the sphere button plays it as a sphere'],
      ['play', 'Play flat, as Memories does'],
    ],
  },
  {
    name: 'open_photo',
    title: '360° photos in Memories',
    hint: 'Where Memories has its own panorama view for a photo, it decides instead.',
    choices: [
      ['flat', 'Show flat, with the sphere button'],
      ['sphere', 'Open as a sphere'],
    ],
  },
];

function el<K extends keyof HTMLElementTagNameMap>(tag: K, props: Record<string, unknown> = {}, ...children: (Node | string)[]): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  Object.assign(node, props);
  node.append(...children);
  return node;
}

async function save(change: Partial<Preferences>, note: HTMLElement) {
  note.dataset.level = 'pending';
  note.textContent = 'Saving…';
  try {
    const response = await fetch(generateUrl('/apps/golblick/preferences'), {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { requesttoken: getRequestToken() ?? '', 'Content-Type': 'application/json' },
      body: JSON.stringify(change),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error((data as { error?: string }).error ?? `${response.status} ${response.statusText}`);
    note.dataset.level = 'ok';
    note.textContent = 'Saved.';
    window.setTimeout(() => { if (note.textContent === 'Saved.') note.textContent = ''; }, 3000);
  } catch (e) {
    note.dataset.level = 'error';
    note.textContent = `Not saved: ${(e as Error).message}`;
  }
}

const root = document.getElementById('golblick-admin');
if (root) {
  const current = loadState<Preferences>('golblick', 'preferences', { open_video: 'sphere', open_photo: 'flat' });
  for (const question of QUESTIONS) {
    const note = el('p', { className: 'golblick-feedback', role: 'status' });
    const options = question.choices.map(([value, label]) => {
      const input = el('input', { type: 'radio', name: `golblick-${question.name}`, value, checked: current[question.name] === value });
      input.addEventListener('change', () => { if (input.checked) void save({ [question.name]: value }, note); });
      return el('div', { className: 'golblick-toggle' }, el('label', {}, input, ` ${label}`));
    });
    root.append(el('h3', {}, question.title), el('p', { className: 'settings-hint' }, question.hint), ...options, note);
  }
}
