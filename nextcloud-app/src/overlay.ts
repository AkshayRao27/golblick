/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * The full-window sphere that every entry point opens: the Files action, the
 * button in Nextcloud's Viewer, and the button in Memories, for a signed-in
 * user or on a public share link.
 */
import { mdiClose } from '@mdi/js';
import { loadState } from '@nextcloud/initial-state';
import { generateUrl } from '@nextcloud/router';

import type { SphereView } from './sphere';

/** Which buttons to add, and the token when this page is a public share link. */
export const config = loadState<{ files: boolean; viewer: boolean; memories: boolean; share: string | null }>(
  'golblick', 'config', { files: true, viewer: true, memories: true, share: null });

/** The sphere endpoints: a signed-in user's files, or the share's (lib/Controller/PublicSphereController.php). */
const sphereUrl = (fileId: number) => generateUrl(config.share
  ? `/apps/golblick/s/${config.share}/sphere/${fileId}` : `/apps/golblick/sphere/${fileId}`);

/** On a share link, `path` is the file's place in the share, which its public preview is addressed by. */
export type Info = { sphere: boolean; etag: string | null; path?: string | null };
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
 */
export async function openSphere(fileId: number, etag: string, name = ''): Promise<void> {
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

  // Capture phase, so the viewer underneath never sees these keys: Escape
  // would close it as well, and the arrows would page to another photo.
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') shut();
    if (['Escape', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', ' '].includes(e.key)) {
      e.stopImmediatePropagation();
      e.preventDefault();
    }
  };

  const shut = () => {
    if (closed) return;
    closed = true;
    window.removeEventListener('keydown', onKey, true);
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
    status.textContent = 'This photo could not be shown as a sphere.';
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
