/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * The full-window sphere that every entry point opens: the Files action, the
 * button in Nextcloud's Viewer, and the button in Memories, for a signed-in
 * user or on a public share link.
 */
import { mdiClose, mdiPause, mdiPlay, mdiVolumeHigh, mdiVolumeOff } from '@mdi/js';
import { loadState } from '@nextcloud/initial-state';
import { generateUrl } from '@nextcloud/router';

import type { SphereView } from './sphere';

/** Which buttons to add, and the token when this page is a public share link. */
export const config = loadState<{ files: boolean; viewer: boolean; memories: boolean; share: string | null }>(
  'golblick', 'config', { files: true, viewer: true, memories: true, share: null });

/** The sphere endpoints: a signed-in user's files, or the share's (lib/Controller/PublicSphereController.php). */
const sphereUrl = (fileId: number) => generateUrl(config.share
  ? `/apps/golblick/s/${config.share}/sphere/${fileId}` : `/apps/golblick/sphere/${fileId}`);

/**
 * On a share link, `path` is the file's place in the share, which its public
 * preview is addressed by. For a video, `video` says whether its stitched copy
 * is ready, and `videoEtag` versions it (it belongs to the clip's first file).
 */
export type Info = { sphere: boolean; etag: string | null; path?: string | null; video?: boolean; videoEtag?: string | null };
const infoCache = new Map<number, Promise<Info>>();

/** Whether a file is one of ours. Cheap on the server, and cached per page. */
export function info(fileId: number): Promise<Info> {
  let pending = infoCache.get(fileId);
  if (!pending) {
    pending = fetch(`${sphereUrl(fileId)}/info`, { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : { sphere: false, etag: null }))
      .catch(() => ({ sphere: false, etag: null }));
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
 */
export async function openSphere(fileId: number, etag: string, name = '', isVideo = false): Promise<void> {
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

  // Capture phase, so the viewer underneath never sees these keys: Escape
  // would close it as well, and the arrows would page to another photo.
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') shut();
    if (e.key === ' ' && player) {
      if (player.paused) void player.play();
      else player.pause();
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
      status.textContent = 'This is the first frame. The video hasn\'t been stitched yet; the server does that in the background.';
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
      // The click that opened this counts as permission to play with sound in
      // most browsers; where it doesn't, start muted and let the button unmute.
      player.play().catch(() => {
        if (!player) return;
        player.muted = true;
        return player.play();
      }).catch(() => {});
    }, { once: true });
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

/** Play and pause, a seek bar with the time, and sound on and off, along the bottom. */
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

  const clock = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
  const update = () => {
    const playing = !video.paused && !video.ended;
    play.innerHTML = svgIcon(playing ? mdiPause : mdiPlay, 22);
    play.title = playing ? 'Pause' : 'Play';
    play.setAttribute('aria-label', play.title);
    mute.innerHTML = svgIcon(video.muted ? mdiVolumeOff : mdiVolumeHigh, 20);
    mute.title = video.muted ? 'Unmute' : 'Mute';
    mute.setAttribute('aria-label', mute.title);
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

  bar.append(play, time, seek, mute);
  return bar;
}
