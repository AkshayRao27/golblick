/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * "Report to golblick" in a .insp file's actions menu: the summary the CLI
 * prints with `golblick report`. The server builds it
 * (lib/Service/CameraReport.php) and leaves out the file's name, folder and
 * the camera's serial number.
 *
 * Two kinds of issue use it, and the server's `tested` flag picks one:
 *
 * | tested | heading                          | form                | title prefix    |
 * |--------|----------------------------------|---------------------|-----------------|
 * | yes    | Report a problem with this photo | photo-problem.yml   | Photo problem   |
 * | no     | Report an untested camera        | untested-camera.yml | Untested camera |
 *
 * An unreadable .insp (tested is null) is a problem with a photo. The main
 * button opens the form on GitHub already filled in; issue forms take a query
 * parameter per field id (.github/ISSUE_TEMPLATE/). Titles have one fixed
 * shape, "<prefix>: <model>, <firmware> (Nextcloud app)", shared with the CLI.
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
  dialog.setAttribute('aria-label', 'Report to golblick');
  // margin:auto is what centres a modal dialog; Nextcloud's reset removes it.
  dialog.style.cssText = 'margin:auto;max-width:min(720px,calc(100vw - 32px));width:100%;padding:20px;border:0;'
    + 'border-radius:var(--border-radius-large,16px);background:var(--color-main-background,#fff);'
    + 'color:var(--color-main-text,#222);box-shadow:0 0 40px rgba(0,0,0,.3);';

  const title = document.createElement('h2');
  title.textContent = 'Report to golblick';
  title.style.cssText = 'margin:0 0 8px;font-size:20px;';

  const note = document.createElement('p');
  note.textContent = '';
  note.style.cssText = 'margin:0 0 12px;color:var(--color-text-maxcontrast,#6b6b6b);';

  const text = document.createElement('pre');
  text.textContent = 'Loading…';
  text.style.cssText = 'margin:0;padding:12px;max-height:50vh;overflow:auto;white-space:pre;font-size:13px;'
    + 'font-family:var(--font-face-monospace,ui-monospace,monospace);line-height:1.4;'
    + 'border-radius:var(--border-radius,8px);background:var(--color-background-dark,#f0f0f0);';

  const buttons = document.createElement('div');
  buttons.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;margin-top:16px;';
  const copy = button('Copy', false);
  const issue = button('Report on GitHub', true);
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
    const data: Report = await response.json();
    text.textContent = data.report;
    const untested = data.tested === false;
    if (untested) {
      title.textContent = 'Report an untested camera';
      note.textContent = `golblick hasn't been tested with the ${data.model} yet. A report helps whether this photo looks `
        + 'right or not: the button below opens an issue on GitHub with this report filled in, and you add how it looks.';
      issue.textContent = 'Report the camera on GitHub';
    } else {
      title.textContent = 'Report a problem with this photo';
      note.textContent = 'If this photo looks wrong or won\'t open, the button below opens an issue on GitHub with this '
        + 'report filled in, and you add what\'s wrong.';
      issue.textContent = 'Report the problem on GitHub';
    }
    note.textContent += ' You need a GitHub account. If you can send a few original photos, say so in the issue and you\'ll '
      + 'get a private upload link; don\'t attach them to the issue, which is public.';
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

type Report = { report: string; model: string | null; firmware: string | null; tested: boolean | null };

/** The right issue form, filled in. The report field renders as code, so it goes in unfenced. */
function issueUrl(data: Report): string {
  const camera = [data.model ?? 'unrecognised file', data.firmware].filter(Boolean).join(', ');
  const [template, prefix] = data.tested === false
    ? ['untested-camera.yml', 'Untested camera']
    : ['photo-problem.yml', 'Photo problem'];
  const query = new URLSearchParams({
    template,
    title: `${prefix}: ${camera} (Nextcloud app)`,
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
