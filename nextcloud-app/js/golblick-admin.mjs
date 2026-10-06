import { g as $, a as _ } from "./index-CVEG_reJ.chunk.mjs";
const m = document.getElementById("golblick-admin");
async function f(t, s, a) {
  const n = await fetch($(`/apps/golblick${s}`), {
    method: t,
    credentials: "same-origin",
    headers: { requesttoken: _() ?? "", "Content-Type": "application/json" },
    body: a === void 0 ? void 0 : JSON.stringify(a)
  }), r = await n.json().catch(() => ({}));
  if (!n.ok) throw new Error(r.error ?? `${n.status} ${n.statusText}`);
  return r;
}
function e(t, s = {}, ...a) {
  const n = document.createElement(t);
  return Object.assign(n, s), n.append(...a), n;
}
const C = (t) => `${(t / 1024 / 1024).toFixed(t < 10 * 1024 * 1024 ? 1 : 0)} MB`, E = {
  ok: "M21,7L9,19L3.5,13.5L4.91,12.09L9,16.17L19.59,5.59L21,7Z",
  warn: "M13 14H11V9H13M13 18H11V16H13M1 21H23L12 2L1 21Z",
  error: "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  info: "M13,9H11V7H13M13,17H11V11H13M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2Z"
};
function A(t) {
  const s = "http://www.w3.org/2000/svg", a = document.createElementNS(s, "svg");
  a.setAttribute("viewBox", "0 0 24 24");
  const n = document.createElementNS(s, "path");
  return n.setAttribute("d", E[t]), a.append(n), e("span", { className: "golblick-icon", ariaHidden: "true" }, a);
}
const l = /* @__PURE__ */ new Map(), S = 3e3;
function c(t) {
  const s = e("p", { className: "golblick-feedback", role: "status" });
  let a;
  const n = (i) => {
    window.clearTimeout(a), s.textContent = i?.text ?? "", i && (s.dataset.level = i.level, l.set(t, i), i.until !== void 0 && (a = window.setTimeout(() => {
      n(null), l.get(t) === i && l.delete(t);
    }, i.until - Date.now())));
  }, r = l.get(t);
  return l.delete(t), r && (r.until === void 0 || r.until > Date.now()) && (n(r), r.until === void 0 && l.delete(t)), {
    node: s,
    pending: (i) => n({ text: i, level: "pending" }),
    saved: () => n({ text: "Saved.", level: "ok", until: Date.now() + S }),
    ok: (i) => n({ text: i, level: "ok" }),
    fail: (i) => n({ text: i, level: "error" })
  };
}
async function d(t, s) {
  s.pending("Saving…");
  try {
    await f("PUT", "/settings", t), s.saved();
  } catch (a) {
    s.fail(`Not saved: ${a.message}`);
  }
}
function h(t, s, a, n) {
  const r = e("input", { type: "checkbox", checked: a });
  return r.addEventListener("change", () => n(r.checked)), e(
    "div",
    { className: "golblick-toggle" },
    e("label", {}, r, ` ${t}`),
    e("p", { className: "settings-hint" }, s)
  );
}
function P(t) {
  if (!m) return;
  const s = t.settings, a = e("ul", { className: "golblick-checks" }, ...t.checks.map((o) => e(
    "li",
    { className: `level-${o.level}` },
    A(o.level),
    e(
      "div",
      { className: "golblick-check" },
      e("div", { className: "golblick-check-name" }, o.title),
      e("div", { className: "golblick-check-detail" }, o.detail)
    )
  ))), n = c("setup"), r = e("button", { type: "button", textContent: "Check again" });
  r.addEventListener("click", () => {
    p();
  });
  const i = e("div", { className: "golblick-actions" }, r), k = t.checks.find((o) => o.id === "mapping");
  if (k && k.level !== "ok") {
    const o = e("button", { type: "button", className: "primary", textContent: "Register .insp files" });
    o.addEventListener("click", async () => {
      o.disabled = !0;
      try {
        const u = await f("POST", "/settings/register");
        n.ok(`${u.written ? "Added the mapping to config/mimetypemapping.json. " : ""}Updated ${u.rows} files. Memories adds them to the timeline at its next background run. You can also run "occ memories:index" to index them immediately.`), await p(!1);
      } catch (u) {
        n.fail(u.message), o.disabled = !1;
      }
    }), i.prepend(o);
  }
  const N = c("width"), w = e("select", {}, ...[1024, 2048, 3072, 4096].map((o) => e("option", { value: String(o), selected: o === s.zoom_width }, `${o} pixels wide`)));
  w.addEventListener("change", () => {
    d({ zoom_width: Number(w.value) }, N).then(() => p(!1));
  });
  const v = c("cache"), g = e("button", { type: "button", textContent: "Clear cache", disabled: t.cache.files === 0 });
  g.addEventListener("click", async () => {
    if (window.confirm("Delete every cached full-size panorama? Each is rendered again the next time someone zooms or opens the sphere view.")) {
      g.disabled = !0;
      try {
        const o = await f("POST", "/settings/cache/clear");
        v.ok(`Removed ${o.removed} panoramas.`), await p(!1);
      } catch (o) {
        v.fail(o.message), g.disabled = !1;
      }
    }
  });
  const b = t.cache.files - t.cache.current, y = c("prerender"), L = c("memories_zoom"), x = c("sphere_files"), z = c("sphere_memories"), M = c("sphere_viewer");
  m.replaceChildren(
    e("h2", {}, "Golblick (360° Photos)"),
    e("h3", {}, "Setup"),
    a,
    i,
    n.node,
    e("h3", {}, "Zooming and the sphere view"),
    e(
      "p",
      { className: "settings-hint" },
      "Zooming in Memories and the sphere view use a full-size panorama. It is rendered the first time someone needs it and then retained. A larger one is sharper but takes longer the first time: for example, about 6 seconds at 2048 and 19 seconds at 4096 for a OneR photo. X5 photos stop at 2560, the size of the panorama the camera stores."
    ),
    e("label", {}, "Panorama size ", w),
    N.node,
    e("h3", {}, "Panorama cache"),
    e("p", {}, `${t.cache.files} panoramas, ${C(t.cache.bytes)}.` + (b === 1 ? " One of them was made at a different size; it is replaced when that photo is viewed again, or removed now by clearing the cache." : b > 1 ? ` ${b} of them were made at a different size; each is replaced when its photo is viewed again, or all are removed now by clearing the cache.` : "")),
    g,
    v.node,
    e("h3", {}, "Background rendering"),
    h(
      "Render full-size panoramas in the background",
      "Pre-generates panoramas so that the first zoom or sphere view of a photo doesn't have waiting time. It runs in Nextcloud's background jobs, about two minutes at a time, newest photos first, and costs CPU time: at 4096 pixels, roughly 19 seconds per OneR photo.",
      s.prerender,
      (o) => {
        d({ prerender: o }, y);
      }
    ),
    e("p", { className: "golblick-progress" }, `${t.cache.current} of ${t.insp} .insp files have a panorama at the current size.`),
    y.node,
    e("h3", {}, "Integrations"),
    e(
      "p",
      { className: "settings-hint" },
      "These rely on details of other apps that can change in an update. If one stops working, it can be turned off here without affecting previews. Each switch is saved as soon as you change it; pages that are already open pick up the change when they are reloaded."
    ),
    e("h4", {}, "Memories"),
    h(
      "Show panorama when zooming",
      "Without this, zooming into a .insp in Memories shows two fisheye circles, and so does Memories' own sphere view in releases that have one.",
      s.memories_zoom,
      (o) => {
        d({ memories_zoom: o }, L);
      }
    ),
    L.node,
    h(
      'Add "View as sphere" button',
      "Memories has no way for other apps to add buttons, so golblick inserts this one into the viewer's top bar itself. Memories releases that have their own sphere view show their own button instead.",
      s.sphere_memories,
      (o) => {
        d({ sphere_memories: o }, z);
      }
    ),
    z.node,
    e("h4", {}, "Files"),
    h(
      'Add "View as sphere" button',
      "Adds it to a .insp file's actions menu, through the Files app's own interface for this.",
      s.sphere_files,
      (o) => {
        d({ sphere_files: o }, x);
      }
    ),
    x.node,
    e("h4", {}, "Photos"),
    h(
      'Add "View as sphere" button',
      "In the image viewer that Files and Photos open. The viewer has no way for other apps to add buttons, so golblick inserts this one into its top bar itself.",
      s.sphere_viewer,
      (o) => {
        d({ sphere_viewer: o }, M);
      }
    ),
    M.node
  );
}
async function p(t = !0) {
  if (m) {
    t && m.querySelector(".settings-hint")?.replaceChildren("Checking…");
    try {
      P(await f("GET", "/settings/status"));
    } catch (s) {
      m.replaceChildren(
        e("h2", {}, "Golblick (360° Photos)"),
        e("p", { className: "golblick-feedback", role: "status" }, `Could not load the settings: ${s.message}`)
      );
    }
  }
}
p();
