/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * The personal settings page: what a 360 photo or video does when it opens in
 * Memories, for the user and on links they share from it. Each choice saves as soon as it is made (lib/Controller/PreferencesController.php),
 * and main.ts reads them from the page's initial state.
 */
import { getRequestToken } from '@nextcloud/auth';
import { loadState } from '@nextcloud/initial-state';
import { generateUrl } from '@nextcloud/router';

type Preferences = { open_video: string; open_photo: string; share_video: string; share_photo: string };

type Question = { name: keyof Preferences; title: string; hint?: string; choices: [string, string][] };

const VIDEO_CHOICES: [string, string][] = [
  ['sphere', 'Open as a sphere'],
  ['paused', 'Show flat, without playing; the sphere button plays it as a sphere'],
  ['play', 'Play flat (Memories default)'],
];
const PHOTO_CHOICES: [string, string][] = [
  ['flat', 'Show flat, with a sphere-viewer button'],
  ['sphere', 'Open as a sphere'],
];

const GROUPS: { title: string; hint?: string; questions: Question[] }[] = [
  {
    title: 'Opening in Memories',
    questions: [
      {
        name: 'open_video',
        title: '360° videos',
        hint: 'Memories plays a 360° video as a flat, stretched rectangle. This applies to stitched copies and to any MP4 marked as 360° video, in a browser. Memories\' Android app always plays them flat.',
        choices: VIDEO_CHOICES,
      },
      {
        name: 'open_photo',
        title: '360° photos',
        hint: 'Memories 10 also has its own "View panorama" button, which shows the same panorama. In Memories\' Android app, photos always open flat and that button is the way to the sphere.',
        choices: PHOTO_CHOICES,
      },
    ],
  },
  {
    title: 'On links you share from Memories',
    hint: 'What someone who opens a link you made in Memories sees, signed in or not. A link shared from Files opens a 360° video as a sphere when it\'s clicked.',
    questions: [
      { name: 'share_video', title: '360° videos', choices: VIDEO_CHOICES },
      { name: 'share_photo', title: '360° photos', choices: PHOTO_CHOICES },
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
  const current = loadState<Preferences>('golblick', 'preferences', { open_video: 'sphere', open_photo: 'flat', share_video: 'sphere', share_photo: 'flat' });
  for (const group of GROUPS) {
    root.append(el('h3', {}, group.title));
    if (group.hint) root.append(el('p', { className: 'settings-hint' }, group.hint));
    for (const question of group.questions) {
      const note = el('p', { className: 'golblick-feedback', role: 'status' });
      const options = question.choices.map(([value, label]) => {
        const input = el('input', { type: 'radio', name: `golblick-${question.name}`, value, checked: current[question.name] === value });
        input.addEventListener('change', () => { if (input.checked) void save({ [question.name]: value }, note); });
        return el('div', { className: 'golblick-toggle' }, el('label', {}, input, ` ${label}`));
      });
      root.append(el('h4', {}, question.title));
      if (question.hint) root.append(el('p', { className: 'settings-hint' }, question.hint));
      root.append(...options, note);
    }
  }
}
