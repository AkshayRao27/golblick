/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * Adds "View as sphere" to Files, to Nextcloud's Viewer (which Files and
 * Photos both use), and to Memories, without changing any of them. The server
 * loads this script on those apps' pages (lib/Listener/LoadSphereViewer.php).
 *
 * | Where              | How                                               |
 * |--------------------|---------------------------------------------------|
 * | Files list         | a file action, through @nextcloud/files: real API |
 * |                    | (also "Report to golblick", for GitHub issues)    |
 * | Viewer (Files, Photos) | a button added to the open viewer's header    |
 * | Memories           | a button added to its viewer's top bar            |
 *
 * ⚠️ The last two are provisional. Neither the Viewer nor Memories offers a way
 * for another app to add a button, so these find their place in the page by
 * class name and work out which file is open from what is on screen. If those
 * apps change their markup the button stops appearing; nothing else breaks.
 * Memories has a sphere view of its own after 9.1.0-alpha.2, and where it
 * offers one for the open photo this button stays out of the way
 * (memoriesHasOwnSphere). That view loads the original, which for a .insp is
 * the lens pair; lib/Middleware/MemoriesZoom.php hands it the panorama instead.
 *
 * In Memories, a 360 video or photo can also open straight into the sphere,
 * as each user chooses on their personal settings page (decideMemories).
 *
 * Either part can be switched off on the admin page; the server passes the
 * choice in as initial state, and loads nothing at all if both are off.
 *
 * On a public share link the page is Files and the Viewer again, and the same
 * buttons go through the share's token instead (config.share; see overlay.ts).
 */
import { mdiClipboardTextOutline, mdiPanoramaSphereOutline } from '@mdi/js';
import { DefaultType, registerFileAction } from '@nextcloud/files';
import { loadState } from '@nextcloud/initial-state';

import { config, info, openSphere, svgIcon } from './overlay';

const LABEL = 'View as sphere';
const BUTTON_CLASS = 'golblick-sphere-button';

const isInsp = (name: string | undefined) => !!name && name.toLowerCase().endsWith('.insp');
const isInsv = (name: string | undefined) => !!name && name.toLowerCase().endsWith('.insv');
// A clip's stitched copy saved next to it (VideoStore::BESIDE on the server).
const isSphereCopy = (name: string | undefined) => !!name && name.toLowerCase().endsWith('.360.mp4');

// ---- Files: a proper file action -------------------------------------------

if (config.files) registerFileAction({
  id: 'golblick-sphere',
  displayName: () => LABEL,
  iconSvgInline: () => svgIcon(mdiPanoramaSphereOutline),
  enabled: ({ nodes }) => nodes.length === 1 && isInsp(nodes[0].basename) && nodes[0].fileid !== undefined,
  exec: async ({ nodes }) => {
    const node = nodes[0];
    openSphere(Number(node.fileid), String(node.attributes?.etag ?? ''), node.basename);
    return null;
  },
  order: 50,
});

// Videos: the same sphere, playing. The default action for an .insv, so a
// click plays it; nothing else in Nextcloud can (see Preview/Insta360Video.php).
// Also for a stitched copy saved next to its clip, which the Viewer would
// otherwise play flat.
if (config.files) registerFileAction({
  id: 'golblick-video',
  displayName: () => 'Play as sphere',
  iconSvgInline: () => svgIcon(mdiPanoramaSphereOutline),
  enabled: ({ nodes }) => nodes.length === 1 && (isInsv(nodes[0].basename) || isSphereCopy(nodes[0].basename))
    && nodes[0].fileid !== undefined,
  exec: async ({ nodes }) => {
    const node = nodes[0];
    openSphere(Number(node.fileid), String(node.attributes?.etag ?? ''), node.basename, true);
    return null;
  },
  default: DefaultType.DEFAULT,
  // Files' own Download is a default action too, with no order; the first by
  // order wins, so this has to sort ahead of it.
  order: -1000,
});

// Under the same switch: it lives in the same menu, through the same API. Not
// on a public share link: a visitor isn't the one to report the owner's photo.
if (config.files && !config.share) registerFileAction({
  id: 'golblick-report',
  displayName: () => 'Report to golblick',
  iconSvgInline: () => svgIcon(mdiClipboardTextOutline),
  enabled: ({ nodes }) => nodes.length === 1 && isInsp(nodes[0].basename) && nodes[0].fileid !== undefined,
  exec: async ({ nodes }) => {
    const { openReport } = await import('./report');
    void openReport(Number(nodes[0].fileid));
    return null;
  },
  order: 51,
});

/**
 * A button that looks like its neighbours, made by cloning one of them.
 *
 * Copying class names is not enough: Nextcloud's buttons get most of their
 * look from component-scoped styles keyed on data-v-* attributes, so a bare
 * button with the same classes shows the browser's default border and
 * padding. A clone carries those attributes, and with them the size, shape,
 * hover state and theme colours of the button beside it. Event listeners are
 * not cloned, so it does nothing until given its own.
 */
function makeButton(reference: Element | null): HTMLButtonElement {
  let button: HTMLButtonElement;
  if (reference instanceof HTMLButtonElement) {
    button = reference.cloneNode(true) as HTMLButtonElement;
    for (const el of [button, ...button.querySelectorAll('[id]')]) el.removeAttribute('id');
    button.removeAttribute('aria-pressed');
    button.classList.remove('action-item__menutoggle');
    button.removeAttribute('aria-haspopup');
    button.removeAttribute('aria-expanded');
  } else {
    // No neighbour to copy from: a plain, borderless icon button.
    button = document.createElement('button');
    button.style.cssText = 'border:0;background:transparent;color:inherit;width:44px;height:44px;display:flex;'
      + 'align-items:center;justify-content:center;cursor:pointer;border-radius:8px;padding:0;';
    button.innerHTML = '<span class="button-vue__icon"></span>';
  }
  button.type = 'button';
  button.classList.add(BUTTON_CLASS);
  button.title = LABEL;
  button.setAttribute('aria-label', LABEL);

  // Same icon size as the neighbour's: Memories uses 24 px, the Viewer 20.
  const size = Number(reference?.querySelector('svg')?.getAttribute('width')) || 20;
  const slot = button.querySelector('.button-vue__icon') ?? button;
  slot.innerHTML = `<span class="material-design-icon" role="img">${svgIcon(mdiPanoramaSphereOutline, size)}</span>`;
  button.querySelector('.button-vue__text')?.replaceChildren();

  return button;
}

/**
 * Keep exactly one button in `container` while `fileId` is a sphere, and none
 * otherwise. Checks are asynchronous, so a slide that has moved on by the
 * time the answer arrives is ignored.
 */
function sync(container: Element | null, fileId: number | null, current: () => number | null, build: () => HTMLButtonElement) {
  const existing = container?.querySelector(`.${BUTTON_CLASS}`) as HTMLButtonElement | null;
  if (!container || fileId === null) {
    existing?.remove();
    return;
  }
  if (existing && existing.dataset.fileId === String(fileId)) return;
  existing?.remove();

  info(fileId).then((answer) => {
    if (!answer.sphere || current() !== fileId || !container.isConnected) return;
    if (container.querySelector(`.${BUTTON_CLASS}`)) return;
    const button = build();
    button.dataset.fileId = String(fileId);
    button.addEventListener('click', (e) => {
      e.stopPropagation();
      // A video under the sphere would carry on playing, sound and all.
      for (const video of document.querySelectorAll('.memories-viewer video, #viewer video')) (video as HTMLVideoElement).pause();
      if (memoriesFileId() === fileId) holding = fileId;
      openSphere(fileId, answer.etag ?? '', '', answer.video === true);
    });
    container.insertBefore(button, container.firstChild);
  });
}

// ---- Nextcloud's Viewer, as used by Files and Photos -----------------------

/** The open file's id, read from the active image's preview URL. */
function viewerFileId(): number | null {
  const img = document.querySelector('#viewer .viewer__file--active img') as HTMLImageElement | null;
  const src = img?.getAttribute('src') ?? '';
  const match = src.match(/[?&]fileId=(\d+)/) ?? src.match(/\/preview\/(\d+)/);
  return match ? Number(match[1]) : null;
}

function syncViewer() {
  // Next to the Viewer's own Edit and "…" buttons, and cloned from one of them.
  const group = document.querySelector('#viewer .modal-header .header-actions');
  sync(group, viewerFileId(), viewerFileId, () =>
    makeButton(group?.querySelector(`button:not(.${BUTTON_CLASS})`) ?? null));
}

// ---- Memories ----------------------------------------------------------------

/** Memories puts the open photo's file id at the end of the hash: #v/<day>/<id>. */
function memoriesFileId(): number | null {
  if (!document.querySelector('.memories-viewer .pswp--open')) return null;
  const match = window.location.hash.match(/^#v\/[^/]+\/(\d+)/);
  return match ? Number(match[1]) : null;
}

type MemoriesGlobal = { viewer?: { currentPhoto?: { fileid?: number; pano?: number; flag?: number } | null } };

/** Memories' FLAG_IS_VIDEO (src/services/utils/const.ts). */
const MEMORIES_IS_VIDEO = 1 << 2;

/**
 * Whether Memories shows its own sphere for this photo. Releases after
 * 9.1.0-alpha.2 classify photos into `pano` at index time, and anything above
 * 0 gets a "View panorama" action. Read from Memories' global rather than the
 * page: the label is translated, and on a phone the action sits in the "…"
 * menu where the top bar can't see it. Older releases have no `pano`, and a
 * .insp indexed before the upgrade has 0 until it is re-indexed, so both keep
 * this button.
 */
function memoriesHasOwnSphere(fileId: number | null): boolean {
  const photo = (globalThis as { _m?: MemoriesGlobal })._m?.viewer?.currentPhoto;
  // Its sphere is for photos only: it skips a video even when it has marked
  // it as a panorama, so a video keeps this button.
  if (((photo?.flag ?? 0) & MEMORIES_IS_VIDEO) !== 0) return false;
  return fileId !== null && photo?.fileid === fileId && (photo.pano ?? 0) > 0;
}

/**
 * What the user wants a 360 photo or video to do when it opens in Memories,
 * from their personal settings (lib/Service/Preferences.php). Memories plays
 * a video flat and at once, its own `video_autoplay` setting permitting, so
 * keeping it still means pausing its player as it starts: the player is
 * Memories' own and changes between releases, but it always ends in a <video>.
 */
const preferences = loadState<{ open_video: string; open_photo: string }>(
  'golblick', 'preferences', { open_video: 'play', open_photo: 'flat' });
const asIs = preferences.open_video === 'play' && preferences.open_photo === 'flat';

/** The Memories slide whose video may not start by itself, until the user acts on the viewer. */
let holding: number | null = null;
/** A video held back before it was known whether it is a sphere, to start again if it isn't. */
let held: HTMLVideoElement | null = null;
/** The slide last decided on, so each is decided once per visit. */
let decided: number | null = null;

if (config.memories && !asIs) {
  // Capture, because media events don't bubble.
  document.addEventListener('play', (e) => {
    const video = e.target;
    if (holding === null || holding !== memoriesFileId() || !(video instanceof HTMLVideoElement)
      || !video.closest('.memories-viewer')) return;
    video.pause();
    held = video;
  }, true);
  // A click or key on the viewer is the user's own, and may play the video
  // flat; not while the sphere is open over it.
  const release = (e: Event) => {
    if (holding === null || document.querySelector('.golblick-sphere')) return;
    if (e.type === 'keydown' || (e.target instanceof Element && e.target.closest('.memories-viewer'))) {
      holding = null;
      held = null;
    }
  };
  document.addEventListener('pointerdown', release, true);
  document.addEventListener('keydown', release, true);
}

/** Open the slide as a sphere, or hold its video still, as the user chose. */
function decideMemories(fileId: number | null) {
  if (asIs || fileId === decided) return;
  decided = fileId;
  holding = fileId;
  held = null;
  if (fileId === null) return;
  info(fileId).then((answer) => {
    if (decided !== fileId) return;
    const isVideo = 'video' in answer;
    const choice = isVideo ? preferences.open_video : preferences.open_photo;
    if (!answer.sphere || choice === 'play' || choice === 'flat' || (!isVideo && memoriesHasOwnSphere(fileId))) {
      if (holding === fileId) {
        holding = null;
        if (held?.isConnected) void held.play().catch(() => {});
        held = null;
      }
      return;
    }
    if (choice !== 'sphere' || document.querySelector('.golblick-sphere')) return;
    for (const video of document.querySelectorAll('.memories-viewer video')) (video as HTMLVideoElement).pause();
    openSphere(fileId, answer.etag ?? '', '', answer.video === true, true);
  });
}

function syncMemories() {
  decideMemories(memoriesFileId());
  const bar = document.querySelector('.memories-viewer .top-bar .action-items');
  if (memoriesHasOwnSphere(memoriesFileId())) {
    bar?.querySelector(`.${BUTTON_CLASS}`)?.remove();
    return;
  }
  sync(bar, memoriesFileId(), memoriesFileId, () =>
    makeButton(bar?.querySelector(`button.action-item--single:not(.${BUTTON_CLASS})`) ?? null));
}

// ---- Watch the page ------------------------------------------------------------

let scheduled = false;
function schedule() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => {
    scheduled = false;
    if (config.viewer) syncViewer();
    if (config.memories) syncMemories();
  });
}

if (config.viewer || config.memories) {
  new MutationObserver(schedule).observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['src', 'class'],
  });
  window.addEventListener('hashchange', schedule);
}
