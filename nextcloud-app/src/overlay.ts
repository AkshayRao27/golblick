/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * The full-window sphere that every entry point opens: the Files action, the
 * button in Nextcloud's Viewer, and the button in Memories, for a signed-in
 * user or on a public share link.
 */
import {
  mdiBackupRestore, mdiChevronDown, mdiChevronLeft, mdiChevronRight, mdiChevronUp, mdiClose, mdiCompassOutline,
  mdiDotsVertical, mdiFullscreen, mdiFullscreenExit, mdiImageFilterCenterFocus, mdiMagnifyMinusOutline,
  mdiMagnifyPlusOutline, mdiPause, mdiPlay, mdiVideoStabilization, mdiVolumeHigh, mdiVolumeOff,
} from '@mdi/js';
import { getRequestToken } from '@nextcloud/auth';
import { loadState } from '@nextcloud/initial-state';
import { generateUrl } from '@nextcloud/router';

import type { Motion, SphereView } from './sphere';

/** Which buttons to add, and the token when this page is a public share link. */
export const config = loadState<{ files: boolean; viewer: boolean; memories: boolean; share: string | null }>(
  'golblick', 'config', { files: true, viewer: true, memories: true, share: null });

/** The sphere endpoints: a signed-in user's files, or the share's (lib/Controller/PublicSphereController.php). */
const sphereUrl = (fileId: number) => generateUrl(config.share
  ? `/apps/golblick/s/${config.share}/sphere/${fileId}` : `/apps/golblick/sphere/${fileId}`);

/**
 * On a share link, `path` is the file's place in the share, which its public
 * preview is addressed by. For a video, `video` says whether its stitched copy
 * is ready, and `videoEtag` versions that copy (it changes whenever the copy is made again).
 */
export type Info = {
  sphere: boolean; etag: string | null; path?: string | null; video?: boolean; videoEtag?: string | null;
  /** Where it opens (lib/Service/ViewStore.php), and whether this user may change that. */
  view?: OpeningView; canSetView?: boolean;
};
type OpeningView = { longitude: number; latitude: number; fov: number | null; chosen: boolean };
const infoCache = new Map<number, Promise<Info>>();

/**
 * Whether a file is one of ours. Cheap on the server, and cached per page.
 *
 * Only an answer is cached, never a failure: a cached failure (during an app
 * upgrade, say) would hide the button and the player for that file until the
 * tab is reloaded.
 */
export function info(fileId: number): Promise<Info> {
  let pending = infoCache.get(fileId);
  if (!pending) {
    const failed = (): Info => {
      infoCache.delete(fileId);
      return { sphere: false, etag: null };
    };
    pending = fetch(`${sphereUrl(fileId)}/info`, { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() as Promise<Info> : failed()))
      .catch(failed);
    infoCache.set(fileId, pending);
  }
  return pending;
}

/** The screen-sized preview the sphere starts on, from the same place the page's own previews come from. */
async function previewUrl(fileId: number, etag: string): Promise<string | null> {
  const size = `x=2048&y=1024&a=1&etag=${encodeURIComponent(etag)}`;
  if (!config.share) return generateUrl('/core/preview') + `?fileId=${fileId}&${size}`;
  const answer = await info(fileId);
  if (!answer.sphere || answer.path == null) return null;
  return generateUrl(`/apps/files_sharing/publicpreview/${config.share}`) + `?file=${encodeURIComponent(answer.path)}&${size}`;
}

const videoUrl = (fileId: number, etag: string) => generateUrl(config.share
  ? `/apps/golblick/s/${config.share}/video/${fileId}` : `/apps/golblick/video/${fileId}`) + `?etag=${encodeURIComponent(etag)}`;

// v is MotionStore::VERSION: the browser keeps a track for a day, and a new one has a new address.
const motionUrl = (fileId: number, etag: string) => generateUrl(config.share
  ? `/apps/golblick/s/${config.share}/motion/${fileId}` : `/apps/golblick/motion/${fileId}`) + `?etag=${encodeURIComponent(etag)}&v=5`;

/** The steadying track for a video, or null where the server has none (lib/Service/MotionStore). */
async function loadMotion(fileId: number, etag: string): Promise<Motion | null> {
  try {
    const response = await fetch(motionUrl(fileId, etag), { credentials: 'same-origin' });
    if (!response.ok) return null;
    const data = await response.json() as { period: number; frames: number; q: string; turn: string };
    const q = int16(data.q);
    const turn = int16(data.turn ?? '');
    return q.length >= 4 * data.frames && turn.length >= data.frames && data.period > 0
      ? { period: data.period, frames: data.frames, q, turn } : null;
  } catch {
    return null;
  }
}

/** Little-endian int16s from base64. */
function int16(base64: string): Int16Array {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  const view = new DataView(bytes.buffer);
  const out = new Int16Array(bytes.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = view.getInt16(2 * i, true);
  return out;
}

/** The viewer's last choice for a player toggle. A convenience only, so storage may fail. */
function preference(key: string, fallback: boolean): boolean {
  try {
    const stored = localStorage.getItem(key);
    return stored === null ? fallback : stored === '1';
  } catch {
    return fallback;
  }
}

/** The last volume chosen, 0 to 1; full where none was. */
function storedVolume(): number {
  try {
    const stored = Number(localStorage.getItem('golblick-volume') ?? '1');
    return Number.isFinite(stored) ? Math.max(0, Math.min(1, stored)) : 1;
  } catch {
    return 1;
  }
}

function rememberVolume(volume: number) {
  try {
    localStorage.setItem('golblick-volume', String(volume));
  } catch {
    // Private window or blocked storage: it just won't be remembered.
  }
}

function remember(key: string, on: boolean) {
  try {
    localStorage.setItem(key, on ? '1' : '0');
  } catch {
    // Private window or blocked storage: it just won't be remembered.
  }
}

/** A round on/off button for the video controls. */
function toggleButton(icon: string, title: (on: boolean) => string, on: boolean, change: (on: boolean) => void) {
  const button = document.createElement('button');
  button.type = 'button';
  button.style.cssText = 'flex:none;width:36px;height:36px;border:0;border-radius:50%;color:#fff;'
    + 'cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;';
  button.innerHTML = svgIcon(icon, 20);
  const show = (state: boolean) => {
    button.title = title(state);
    button.setAttribute('aria-label', button.title);
    button.setAttribute('aria-pressed', String(state));
    button.style.background = state ? 'rgba(255,255,255,.25)' : 'transparent';
  };
  show(on);
  button.addEventListener('click', () => {
    const next = button.getAttribute('aria-pressed') !== 'true';
    show(next);
    change(next);
  });
  return { button, show };
}

let open: (() => void) | null = null;

export function svgIcon(path: string, size = 20): string {
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true"><path fill="currentColor" d="${path}"/></svg>`;
}

/**
 * Open the sphere for one file.
 *
 * It starts on the screen-sized preview, which is ready at once, and swaps in
 * the full-size render when the server has it. The first render of a OneR
 * photo can take around 20 seconds, so the sphere is usable before then and
 * a line at the bottom says the sharper one is on its way.
 *
 * A video opens on its thumbnail, the clip's first frame, and plays its
 * stitched copy on the same sphere once that can play. A clip the server
 * hasn't stitched yet stays on the first frame and says so.
 *
 * With `pageThrough`, the left and right arrows close the sphere and go on to
 * the viewer underneath, so it moves to the next photo; main.ts uses that
 * when Memories opens straight into the sphere.
 */
export async function openSphere(fileId: number, etag: string, name = '', isVideo = false, pageThrough = false): Promise<void> {
  open?.();

  const overlay = document.createElement('div');
  overlay.className = 'golblick-sphere';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-label', name ? `${name}, as a sphere` : 'Sphere view');
  // Above Nextcloud's modals (9998) and Memories' viewer.
  overlay.style.cssText = 'position:fixed;inset:0;z-index:100000;background:#000;';

  const close = document.createElement('button');
  close.type = 'button';
  close.title = 'Close sphere view';
  close.setAttribute('aria-label', 'Close sphere view');
  close.innerHTML = svgIcon(mdiClose, 24);
  close.style.cssText = 'position:absolute;top:12px;right:12px;z-index:1;width:44px;height:44px;border:0;border-radius:50%;'
    + 'background:rgba(0,0,0,.5);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;';

  const status = document.createElement('div');
  status.style.cssText = 'position:absolute;left:50%;bottom:16px;transform:translateX(-50%);z-index:1;padding:6px 12px;'
    + 'border-radius:16px;background:rgba(0,0,0,.5);color:#fff;font-size:13px;pointer-events:none;';
  status.textContent = 'Loading…';

  overlay.append(close, status);
  document.body.appendChild(overlay);

  let view: SphereView | null = null;
  let closed = false;
  let player: HTMLVideoElement | null = null;
  let navigation: HTMLElement | null = null;
  let wake = () => {};

  // Capture phase, so the viewer underneath never sees these keys: Escape
  // would close it as well, and the arrows would page to another photo.
  const onKey = (e: KeyboardEvent) => {
    if (pageThrough && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
      shut();
      return;
    }
    if (e.key === 'Escape') shut();
    if (e.key === ' ' && player) {
      if (player.paused) void player.play();
      else player.pause();
      wake();
    }
    if (['Escape', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', ' '].includes(e.key)) {
      e.stopImmediatePropagation();
      e.preventDefault();
    }
  };

  const shut = () => {
    if (closed) return;
    closed = true;
    window.removeEventListener('keydown', onKey, true);
    if (player) {
      // Stop the download as well as the sound.
      player.pause();
      player.removeAttribute('src');
      player.load();
    }
    view?.destroy();
    overlay.remove();
    if (open === shut) open = null;
  };
  open = shut;
  close.addEventListener('click', shut);
  window.addEventListener('keydown', onKey, true);

  const full = `${sphereUrl(fileId)}?etag=${encodeURIComponent(etag)}`;

  try {
    const preview = await previewUrl(fileId, etag);
    if (closed) return;
    if (preview === null) throw new Error('not a sphere');
    const { SphereView } = await import('./sphere');
    if (closed) return;
    view = await SphereView.create(overlay, preview);
    if (closed) {
      view.destroy();
      return;
    }
    // Where this opens: the direction someone chose, or the default (the
    // middle of Insta360 Studio's export). Asked here and not before the
    // sphere appears, so a slow answer doesn't hold it up.
    const answer = await info(fileId).catch(() => null);
    if (closed) return;
    if (answer?.view) view.look(answer.view.longitude, answer.view.latitude, answer.view.fov);
    navigation = navigationBar(fileId, answer, view, () => player, status, overlay, isVideo);
    overlay.append(navigation);
    // Keep the controls above the canvas.
    overlay.append(close, status);
  } catch {
    status.textContent = isVideo ? 'This video could not be shown as a sphere.' : 'This photo could not be shown as a sphere.';
    return;
  }

  if (isVideo) {
    const answer = await info(fileId);
    if (closed) return;
    if (!answer.video || !answer.videoEtag) {
      status.textContent = 'This is the first frame. The video hasn\'t been stitched yet; the server will stitch it in the background.';
      return;
    }
    player = document.createElement('video');
    player.playsInline = true;
    player.preload = 'auto';
    player.src = videoUrl(fileId, answer.videoEtag);
    const controls = videoControls(player, () => view?.redraw());
    status.textContent = 'Loading video…';
    player.addEventListener('loadeddata', () => {
      if (closed || !player) return;
      view?.attachVideo(player);
      status.remove();
      overlay.append(controls);
      wake = autoHide(overlay, player, [navigation, controls, close].filter((part): part is HTMLElement => part !== null));
      // The click that opened this counts as permission to play with sound in
      // most browsers; where it doesn't, start muted and let the button unmute.
      player.play().catch(() => {
        if (!player) return;
        player.muted = true;
        return player.play();
      }).catch(() => {});
    }, { once: true });
    // Steadying arrives separately and switches on when it does; the video
    // doesn't wait for it, since a long clip takes the server a few seconds
    // the first time.
    void loadMotion(fileId, answer.videoEtag).then((motion) => {
      if (closed || !motion || !view) return;
      const steadyOn = preference('golblick-steady', true);
      const lockOn = preference('golblick-lock', true);
      view.setMotion(motion);
      view.setSteady(steadyOn);
      view.setLocked(lockOn);
      // Direction Lock, as Insta360 Studio calls it, only means something
      // while the video is steadied, so it is greyed out otherwise.
      const lock = toggleButton(mdiCompassOutline,
        (on) => on ? 'Direction locked: click to follow the camera\'s turns' : 'Following the camera\'s turns: click to lock the direction',
        lockOn, (on) => {
          view?.setLocked(on);
          remember('golblick-lock', on);
        });
      const steady = toggleButton(mdiVideoStabilization,
        (on) => on ? 'Steadied: click for the camera\'s own movement' : 'Not steadied: click to steady',
        steadyOn, (on) => {
          view?.setSteady(on);
          remember('golblick-steady', on);
          lock.button.disabled = !on;
          lock.button.style.opacity = on ? '1' : '.4';
        });
      lock.button.disabled = !steadyOn;
      lock.button.style.opacity = steadyOn ? '1' : '.4';
      controls.insertBefore(steady.button, controls.lastChild);
      controls.insertBefore(lock.button, controls.lastChild);
    });
    player.addEventListener('error', () => {
      if (!closed) status.textContent = 'The stitched video could not be played; showing the first frame.';
    }, { once: true });
    return;
  }

  status.textContent = 'Loading full resolution…';
  const sharper = await view.upgrade(full);
  if (closed) return;
  if (sharper) {
    status.remove();
  } else {
    status.textContent = 'Full resolution is not available; showing the preview.';
  }
}

/**
 * Turning, zooming and full screen along the bottom, for a touchscreen or
 * anyone without a wheel, and a "⋮" menu with where it opens, for someone who
 * may change the file. The same buttons, icons and order as the desktop
 * viewer (src/golblick/viewer.py in the library), so the two work alike.
 *
 * A video's opening view is kept for its opening frame, so it can only be set
 * there: later, the steadying has turned the sphere and the same direction
 * would point somewhere else at the start.
 */
function navigationBar(fileId: number, answer: Info | null, view: SphereView,
  player: () => HTMLVideoElement | null, status: HTMLElement, overlay: HTMLElement, isVideo: boolean): HTMLElement {
  const bar = document.createElement('div');
  // Above the video controls, which take the bottom edge.
  bar.style.cssText = `position:absolute;left:50%;bottom:${isVideo ? 72 : 16}px;transform:translateX(-50%);z-index:1;`
    + 'display:flex;gap:2px;padding:2px 8px;border-radius:24px;background:rgba(0,0,0,.55);';
  // The sphere listens for drags on the canvas; keep the bar's own presses to itself.
  for (const type of ['pointerdown', 'pointermove', 'wheel', 'touchstart', 'touchmove']) {
    bar.addEventListener(type, (e) => e.stopPropagation(), { passive: true });
  }
  const button = (icon: string, title: string) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.title = title;
    b.setAttribute('aria-label', title);
    b.innerHTML = svgIcon(icon, 24);
    b.style.cssText = 'width:44px;height:44px;border:0;border-radius:50%;background:transparent;color:#fff;'
      + 'cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;';
    hover(b);
    return b;
  };
  // Held down, a turn or zoom keeps going, like a key.
  const held = (icon: string, title: string, act: () => void) => {
    const b = button(icon, title);
    let timer: number | null = null;
    const stop = () => { if (timer !== null) window.clearInterval(timer); timer = null; };
    b.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      act();
      stop();
      timer = window.setInterval(act, 40);
    });
    for (const type of ['pointerup', 'pointerleave', 'pointercancel']) b.addEventListener(type, stop);
    b.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') act(); });
    return b;
  };
  const turn = (longitude: number, latitude: number, zoom = 1) => {
    const now = view.direction;
    view.look(now.longitude + longitude, now.latitude + latitude, now.fov * zoom);
  };
  const step = () => view.direction.fov / 30;

  const full = button(mdiFullscreen, 'Full screen');
  const showFull = () => {
    if (!overlay.isConnected) {
      document.removeEventListener('fullscreenchange', showFull);
      return;
    }
    const on = document.fullscreenElement === overlay;
    full.innerHTML = svgIcon(on ? mdiFullscreenExit : mdiFullscreen, 24);
    full.title = on ? 'Leave full screen' : 'Full screen';
    full.setAttribute('aria-label', full.title);
  };
  full.addEventListener('click', () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void overlay.requestFullscreen().catch(() => {});
  });
  document.addEventListener('fullscreenchange', showFull);

  bar.append(
    held(mdiChevronLeft, 'Turn left', () => turn(-step(), 0)),
    held(mdiChevronUp, 'Look up', () => turn(0, step())),
    held(mdiChevronDown, 'Look down', () => turn(0, -step())),
    held(mdiChevronRight, 'Turn right', () => turn(step(), 0)),
    held(mdiMagnifyMinusOutline, 'Zoom out', () => turn(0, 0, 1.03)),
    held(mdiMagnifyPlusOutline, 'Zoom in', () => turn(0, 0, 1 / 1.03)),
    full,
  );
  if (answer?.canSetView && answer.view) bar.append(openingMenu(fileId, answer.view, view, player, status, overlay));
  return bar;
}

/**
 * Fades a playing video's controls and the pointer out when nobody is reaching
 * for them, and returns what brings them back.
 *
 * Moving the pointer into the bottom of the picture, where the controls are,
 * brings them back. Moving it anywhere else doesn't: that is usually a hand on
 * its way to drag the view around, and it would bring them back before every
 * drag. A click or tap without a drag shows or hides them, which is all a
 * touchscreen has. They stay while the video is paused, the pointer is on
 * them, or their menu or a slider is in use. The desktop viewer does the same
 * (_AutoHide in src/golblick/viewer.py in the library).
 */
function autoHide(overlay: HTMLElement, video: HTMLVideoElement, parts: HTMLElement[]): () => void {
  const IDLE = 3000; // ms without reaching for them before they fade
  const CLICK = 6; // pixels a press may move and still be a click
  const REACH = 160; // pixels from the bottom edge, at least, where moving brings them back
  if (!document.getElementById('golblick-idle')) {
    // Over the canvas's own grab cursor, which is set on the element.
    const style = document.createElement('style');
    style.id = 'golblick-idle';
    style.textContent = '.golblick-idle, .golblick-idle * { cursor: none !important; }';
    document.head.append(style);
  }
  let shown = true;
  let timer: number | undefined;
  let press: { x: number; y: number } | null = null;
  let pointer: { x: number; y: number } | null = null;
  let holding = false; // a press on the controls: a slider being dragged, say
  const over = new Set<HTMLElement>();
  for (const part of parts) {
    part.style.transition = 'opacity .2s';
    part.addEventListener('pointerenter', () => over.add(part));
    part.addEventListener('pointerleave', () => over.delete(part));
    part.addEventListener('pointerdown', () => { holding = true; });
  }
  const busy = () => holding || over.size > 0 || overlay.querySelector('[role="menu"]:not([hidden])') !== null;
  const idle = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(expire, IDLE);
  };
  const show = () => {
    if (!shown) {
      shown = true;
      for (const part of parts) {
        part.style.opacity = '';
        part.style.pointerEvents = '';
      }
    }
    overlay.classList.remove('golblick-idle');
    idle();
  };
  const hide = () => {
    if (shown) {
      shown = false;
      for (const part of parts) {
        part.style.opacity = '0';
        // Faded, they don't catch clicks meant for the picture.
        part.style.pointerEvents = 'none';
        over.delete(part);
      }
    }
    // Not mid-drag: the pointer is what's being dragged.
    if (press === null) overlay.classList.add('golblick-idle');
    window.clearTimeout(timer);
  };
  function expire() {
    if (!overlay.isConnected || video.paused || video.ended) return;
    if (busy()) idle();
    else hide();
  }

  // Captured: the sphere keeps its presses from bubbling. A press on the controls is theirs.
  overlay.addEventListener('pointerdown', (e) => {
    if (!parts.some((part) => part.contains(e.target as Node))) press = { x: e.clientX, y: e.clientY };
  }, true);
  overlay.addEventListener('pointerup', (e) => {
    holding = false;
    if (press === null) return;
    const moved = Math.abs(e.clientX - press.x) + Math.abs(e.clientY - press.y);
    press = null;
    if (moved <= CLICK) {
      if (shown) hide();
      else show();
    } else if (!video.paused) {
      idle(); // the pointer, back after the drag, fades again
    }
  });
  overlay.addEventListener('pointermove', (e) => {
    if (e.pointerType !== 'mouse' || e.buttons !== 0) return;
    // A browser may also send moves when what's under a still pointer changes.
    const still = pointer !== null && Math.abs(e.clientX - pointer.x) + Math.abs(e.clientY - pointer.y) < 2;
    pointer = { x: e.clientX, y: e.clientY };
    if (still) return;
    if (e.clientY > overlay.clientHeight - Math.max(REACH, overlay.clientHeight / 4)) show();
  });
  overlay.addEventListener('pointerleave', expire);
  video.addEventListener('play', idle);
  video.addEventListener('pause', show);
  video.addEventListener('ended', show);
  if (!video.paused) idle();
  return show;
}

/** A light highlight under the pointer, as the desktop viewer's buttons have. */
function hover(b: HTMLElement, colour = 'rgba(255,255,255,.12)') {
  b.addEventListener('pointerenter', () => { b.style.background = colour; });
  b.addEventListener('pointerleave', () => { b.style.background = 'transparent'; });
}

/** The "⋮" button and its menu: open at this view next time, or the default way. */
function openingMenu(fileId: number, current: OpeningView, view: SphereView,
  player: () => HTMLVideoElement | null, status: HTMLElement, overlay: HTMLElement): HTMLElement {
  const wrap = document.createElement('div');
  wrap.style.cssText = 'position:relative;display:flex;';
  const more = document.createElement('button');
  more.type = 'button';
  more.title = 'More';
  more.setAttribute('aria-label', 'More');
  more.setAttribute('aria-haspopup', 'menu');
  more.innerHTML = svgIcon(mdiDotsVertical, 24);
  more.style.cssText = 'width:44px;height:44px;border:0;border-radius:50%;background:transparent;color:#fff;'
    + 'cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;';
  hover(more);
  // Upwards: the bar sits along the bottom.
  const menu = document.createElement('div');
  menu.setAttribute('role', 'menu');
  menu.hidden = true;
  // The bar's own look, as the desktop viewer's menu has: translucent black, round corners.
  menu.style.cssText = 'position:absolute;right:0;bottom:52px;min-width:260px;padding:6px;border-radius:16px;'
    + 'background:rgba(0,0,0,.55);color:#fff;font-size:14px;';
  const item = (icon: string, label: string) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.setAttribute('role', 'menuitem');
    b.innerHTML = `${svgIcon(icon, 20)}<span>${label}</span>`;
    b.style.cssText = 'display:flex;align-items:center;gap:10px;width:100%;padding:9px 12px;border:0;border-radius:10px;'
      + 'background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;';
    hover(b);
    return b;
  };
  const here = item(mdiImageFilterCenterFocus, 'Open facing this way');
  const reset = item(mdiBackupRestore, 'Reset point of view');
  const allowReset = (on: boolean) => {
    reset.disabled = !on;
    reset.style.opacity = on ? '1' : '.4';
    reset.style.cursor = on ? 'pointer' : 'default';
  };
  allowReset(current.chosen);
  menu.append(here, reset);
  wrap.append(menu, more);

  const close = () => { menu.hidden = true; };
  more.addEventListener('click', (e) => {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
  });
  overlay.addEventListener('pointerdown', (e) => { if (!wrap.contains(e.target as Node)) close(); });

  const say = (text: string) => {
    status.textContent = text;
    overlay.append(status);
    window.setTimeout(() => { if (status.textContent === text) status.remove(); }, 3000);
  };
  const send = async (method: 'PUT' | 'DELETE', body?: object): Promise<OpeningView | null> => {
    const response = await fetch(`${sphereUrl(fileId)}/view`, {
      method,
      credentials: 'same-origin',
      headers: { requesttoken: getRequestToken() ?? '', 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
    const answer = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(answer.error ?? `${response.status} ${response.statusText}`);
    // Every file of a clip shares the view, so forget them all.
    infoCache.clear();
    return answer.view ?? null;
  };

  here.addEventListener('click', () => {
    close();
    const video = player();
    if (video && video.currentTime > 0.2) {
      say('Go back to the start of the video to set where it opens.');
      return;
    }
    const { longitude, latitude, fov } = view.direction;
    send('PUT', { longitude, latitude, fov })
      .then(() => { allowReset(true); say('It opens at this view now.'); })
      .catch((e: Error) => say(`Not saved: ${e.message}`));
  });
  reset.addEventListener('click', () => {
    if (reset.disabled) return;
    close();
    send('DELETE')
      .then((fallback) => {
        allowReset(false);
        if (fallback) view.look(fallback.longitude, fallback.latitude, fallback.fov);
        say('It opens the default way again.');
      })
      .catch((e: Error) => say(`Not saved: ${e.message}`));
  });
  return wrap;
}

/** Play and pause, a seek bar with the time, and the sound's mute and volume, along the bottom. */
function videoControls(video: HTMLVideoElement, redraw: () => void): HTMLElement {
  const bar = document.createElement('div');
  bar.style.cssText = 'position:absolute;left:12px;right:12px;bottom:12px;z-index:1;display:flex;align-items:center;gap:10px;'
    + 'padding:6px 10px;border-radius:22px;background:rgba(0,0,0,.55);color:#fff;font-size:13px;';
  // The sphere listens for drags on the canvas; keep the bar's own clicks and drags to itself.
  for (const type of ['pointerdown', 'pointermove', 'wheel', 'touchstart', 'touchmove']) {
    bar.addEventListener(type, (e) => e.stopPropagation(), { passive: true });
  }

  const button = (label: string): HTMLButtonElement => {
    const b = document.createElement('button');
    b.type = 'button';
    b.title = label;
    b.setAttribute('aria-label', label);
    b.style.cssText = 'flex:none;width:36px;height:36px;border:0;border-radius:50%;background:transparent;color:#fff;'
      + 'cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;';
    return b;
  };
  const play = button('Play');
  const mute = button('Mute');
  const time = document.createElement('span');
  time.style.cssText = 'flex:none;font-variant-numeric:tabular-nums;';
  const seek = document.createElement('input');
  seek.type = 'range';
  seek.min = '0';
  seek.step = 'any';
  seek.value = '0';
  seek.setAttribute('aria-label', 'Position');
  seek.style.cssText = 'flex:1;min-width:60px;accent-color:#fff;';
  const volume = document.createElement('input');
  volume.type = 'range';
  volume.min = '0';
  volume.max = '1';
  volume.step = 'any';
  volume.setAttribute('aria-label', 'Volume');
  volume.style.cssText = 'flex:none;width:72px;accent-color:#fff;';
  video.volume = storedVolume();
  // Mute and volume stay together at the end, after the steadying toggles.
  const sound = document.createElement('div');
  sound.style.cssText = 'flex:none;display:flex;align-items:center;gap:4px;';

  const clock = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
  const update = () => {
    const playing = !video.paused && !video.ended;
    play.innerHTML = svgIcon(playing ? mdiPause : mdiPlay, 22);
    play.title = playing ? 'Pause' : 'Play';
    play.setAttribute('aria-label', play.title);
    mute.innerHTML = svgIcon(video.muted ? mdiVolumeOff : mdiVolumeHigh, 20);
    mute.title = video.muted ? 'Unmute' : 'Mute';
    mute.setAttribute('aria-label', mute.title);
    if (document.activeElement !== volume) volume.value = String(video.muted ? 0 : video.volume);
    const duration = Number.isFinite(video.duration) ? video.duration : 0;
    seek.max = String(duration);
    if (document.activeElement !== seek) seek.value = String(video.currentTime);
    time.textContent = `${clock(video.currentTime)} / ${clock(duration)}`;
  };

  play.addEventListener('click', () => {
    if (video.paused || video.ended) void video.play();
    else video.pause();
  });
  mute.addEventListener('click', () => {
    video.muted = !video.muted;
    if (!video.muted && video.volume === 0) video.volume = 1;
  });
  volume.addEventListener('input', () => {
    video.volume = Number(volume.value);
    video.muted = video.volume === 0;
    rememberVolume(video.volume);
  });
  seek.addEventListener('input', () => {
    video.currentTime = Number(seek.value);
  });
  // A paused video only shows the new frame once it has decoded it; redraw then.
  video.addEventListener('seeked', () => {
    if ('requestVideoFrameCallback' in video) video.requestVideoFrameCallback(() => redraw());
    else redraw();
  });
  for (const type of ['play', 'pause', 'ended', 'timeupdate', 'volumechange', 'durationchange']) {
    video.addEventListener(type, update);
  }
  update();

  sound.append(mute, volume);
  bar.append(play, time, seek, sound);
  return bar;
}
