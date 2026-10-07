/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * "Camera report" in a .insp file's actions menu: the summary the CLI prints
 * with `golblick report`, for pasting into a bug report. The server builds it
 * (lib/Service/CameraReport.php) and leaves out the file's name, folder and
 * the camera's serial number.
 *
 * A native <dialog> rather than Nextcloud's Vue dialogs: it brings focus
 * handling, Escape and the top layer with it, and costs no dependency.
 */
import { getRequestToken } from '@nextcloud/auth';
import { generateUrl } from '@nextcloud/router';

export async function openReport(fileId: number): Promise<void> {
  addStyle();
  const dialog = document.createElement('dialog');
  dialog.className = 'golblick-report';
  dialog.setAttribute('aria-label', 'Camera report');
  // margin:auto is what centres a modal dialog; Nextcloud's reset removes it.
  dialog.style.cssText = 'margin:auto;max-width:min(720px,calc(100vw - 32px));width:100%;padding:20px;border:0;'
    + 'border-radius:var(--border-radius-large,16px);background:var(--color-main-background,#fff);'
    + 'color:var(--color-main-text,#222);box-shadow:0 0 40px rgba(0,0,0,.3);';

  const title = document.createElement('h2');
  title.textContent = 'Camera report';
  title.style.cssText = 'margin:0 0 8px;font-size:20px;';

  const note = document.createElement('p');
  note.textContent = 'For a bug report on GitHub. It leaves out the file\'s name, its folder and the camera\'s serial number.';
  note.style.cssText = 'margin:0 0 12px;color:var(--color-text-maxcontrast,#6b6b6b);';

  const text = document.createElement('pre');
  text.textContent = 'Loading…';
  text.style.cssText = 'margin:0;padding:12px;max-height:50vh;overflow:auto;white-space:pre;font-size:13px;'
    + 'font-family:var(--font-face-monospace,ui-monospace,monospace);line-height:1.4;'
    + 'border-radius:var(--border-radius,8px);background:var(--color-background-dark,#f0f0f0);';

  const buttons = document.createElement('div');
  buttons.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;margin-top:16px;';
  const copy = button('Copy', true);
  const close = button('Close', false);
  copy.disabled = true;
  buttons.append(copy, close);

  dialog.append(title, note, text, buttons);
  document.body.appendChild(dialog);
  dialog.addEventListener('close', () => dialog.remove());
  close.addEventListener('click', () => dialog.close());
  // Files handles Escape itself and cancels the default, which is what would
  // close a modal dialog, so close it here first.
  dialog.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    event.stopPropagation();
    dialog.close();
  });
  dialog.showModal();

  let report = '';
  try {
    const response = await fetch(generateUrl(`/apps/golblick/report/${fileId}`), {
      headers: { requesttoken: getRequestToken() ?? '', Accept: 'application/json' },
    });
    if (!response.ok) throw new Error(String(response.status));
    const body: string = (await response.json()).report;
    text.textContent = body;
    // Fenced, so it stays a block when pasted into a GitHub issue.
    report = '```\n' + body + '\n```';
    copy.disabled = false;
  } catch {
    text.textContent = 'The report could not be made for this file.';
    return;
  }

  copy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(report);
      copy.textContent = 'Copied';
    } catch {
      // No clipboard access (an insecure origin, or a refused permission):
      // select the text so a manual copy is one keystroke.
      const range = document.createRange();
      range.selectNodeContents(text);
      getSelection()?.removeAllRanges();
      getSelection()?.addRange(range);
      copy.textContent = 'Press Ctrl+C to copy';
    }
  });
}

/** ::backdrop can't be set inline, so one rule goes in the page, once. */
function addStyle(): void {
  if (document.getElementById('golblick-report-style')) return;
  const style = document.createElement('style');
  style.id = 'golblick-report-style';
  style.textContent = 'dialog.golblick-report::backdrop{background:rgba(0,0,0,.5);}';
  document.head.appendChild(style);
}

function button(label: string, primary: boolean): HTMLButtonElement {
  const element = document.createElement('button');
  element.type = 'button';
  element.textContent = label;
  if (primary) element.className = 'primary';
  return element;
}
