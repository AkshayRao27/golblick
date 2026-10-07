/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * "Camera report" in a .insp file's actions menu: the summary the CLI prints
 * with `golblick report`, for a bug report. The server builds it
 * (lib/Service/CameraReport.php) and leaves out the file's name, folder and
 * the camera's serial number.
 *
 * The main button opens the camera issue form on GitHub already filled in,
 * so the person only has to say what went wrong. Issue forms take a query
 * parameter per field id (.github/ISSUE_TEMPLATE/camera.yml). The title has
 * one fixed shape, "Camera report: <model>, <firmware> (Nextcloud app)", so
 * reports can be sorted by camera at a glance.
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
  dialog.setAttribute('aria-label', 'Report camera');
  // margin:auto is what centres a modal dialog; Nextcloud's reset removes it.
  dialog.style.cssText = 'margin:auto;max-width:min(720px,calc(100vw - 32px));width:100%;padding:20px;border:0;'
    + 'border-radius:var(--border-radius-large,16px);background:var(--color-main-background,#fff);'
    + 'color:var(--color-main-text,#222);box-shadow:0 0 40px rgba(0,0,0,.3);';

  const title = document.createElement('h2');
  title.textContent = 'Report camera details to Golblick';
  title.style.cssText = 'margin:0 0 8px;font-size:20px;';

  const note = document.createElement('p');
  note.textContent = 'Something wrong with how this photo looks or loads? Open an issue on GitHub: the button below fills in '
    + 'the camera and this report for you, and you add what you saw. You need a GitHub account.';
  note.style.cssText = 'margin:0 0 12px;color:var(--color-text-maxcontrast,#6b6b6b);';

  const text = document.createElement('pre');
  text.textContent = 'Loading…';
  text.style.cssText = 'margin:0;padding:12px;max-height:50vh;overflow:auto;white-space:pre;font-size:13px;'
    + 'font-family:var(--font-face-monospace,ui-monospace,monospace);line-height:1.4;'
    + 'border-radius:var(--border-radius,8px);background:var(--color-background-dark,#f0f0f0);';

  const buttons = document.createElement('div');
  buttons.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;margin-top:16px;';
  const copy = button('Copy', false);
  const issue = button('Open an issue on GitHub', true);
  const close = button('Close', false);
  copy.disabled = issue.disabled = true;
  buttons.append(copy, issue, close);

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
    const data: { report: string; model: string | null; firmware: string | null } = await response.json();
    text.textContent = data.report;
    // Fenced, so it stays a block when pasted into a GitHub issue by hand.
    report = '```\n' + data.report + '\n```';
    copy.disabled = issue.disabled = false;
    issue.addEventListener('click', () => window.open(issueUrl(data), '_blank', 'noopener'));
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

/** The camera issue form, filled in. The report field renders as code, so it goes in unfenced. */
function issueUrl(data: { report: string; model: string | null; firmware: string | null }): string {
  const camera = [data.model ?? 'unrecognised file', data.firmware].filter(Boolean).join(', ');
  const query = new URLSearchParams({
    template: 'camera.yml',
    title: `Camera report: ${camera} (Nextcloud app)`,
    camera,
    report: data.report,
    where: 'Nextcloud app',
  });
  return `https://github.com/AkshayRao27/golblick/issues/new?${query}`;
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
