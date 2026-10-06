import { g as z, a as C } from "./index-CVEG_reJ.chunk.mjs";
const h = document.getElementById("golblick-admin");
async function u(t, n, i) {
  const o = await fetch(z(`/apps/golblick${n}`), {
    method: t,
    credentials: "same-origin",
    headers: { requesttoken: C() ?? "", "Content-Type": "application/json" },
    body: i === void 0 ? void 0 : JSON.stringify(i)
  }), s = await o.json().catch(() => ({}));
  if (!o.ok) throw new Error(s.error ?? `${o.status} ${o.statusText}`);
  return s;
}
function e(t, n = {}, ...i) {
  const o = document.createElement(t);
  return Object.assign(o, n), o.append(...i), o;
}
const x = (t) => `${(t / 1024 / 1024).toFixed(t < 10 * 1024 * 1024 ? 1 : 0)} MB`, E = { ok: "✓", warn: "!", error: "✕", info: "i" }, k = /* @__PURE__ */ new Map();
function c(t) {
  const n = e("p", { className: "golblick-feedback", role: "status" }), i = (s, r) => {
    n.textContent = s, n.dataset.level = r, k.set(t, { text: s, level: r });
  }, o = k.get(t);
  return o && (n.textContent = o.text, n.dataset.level = o.level, k.delete(t)), { node: n, ok: (s) => i(s, "ok"), fail: (s) => i(s, "error") };
}
async function d(t, n) {
  try {
    await u("PUT", "/settings", t), n.ok("Saved.");
  } catch (i) {
    n.fail(`Not saved: ${i.message}`);
  }
}
function f(t, n, i, o) {
  const s = e("input", { type: "checkbox", checked: i });
  return s.addEventListener("change", () => o(s.checked)), e(
    "div",
    { className: "golblick-toggle" },
    e("label", {}, s, ` ${t}`),
    e("p", { className: "settings-hint" }, n)
  );
}
function S(t) {
  if (!h) return;
  const n = t.settings, i = e("ul", { className: "golblick-checks" }, ...t.checks.map((a) => e(
    "li",
    { className: `level-${a.level}` },
    e("span", { className: "golblick-icon", ariaHidden: "true" }, E[a.level]),
    e("div", {}, e("strong", {}, a.title), e("p", {}, a.detail))
  ))), o = c("setup"), s = e("button", { type: "button", textContent: "Check again" });
  s.addEventListener("click", () => {
    l();
  });
  const r = e("div", { className: "golblick-actions" }, s), y = t.checks.find((a) => a.id === "mapping");
  if (y && y.level !== "ok") {
    const a = e("button", { type: "button", className: "primary", textContent: "Register .insp files" });
    a.addEventListener("click", async () => {
      a.disabled = !0;
      try {
        const g = await u("POST", "/settings/register");
        o.ok(`${g.written ? "Added the mapping to config/mimetypemapping.json. " : ""}Updated ${g.rows} files. Memories adds them to the timeline at its next background run, or straight away with occ memories:index.`), await l(!1);
      } catch (g) {
        o.fail(g.message), a.disabled = !1;
      }
    }), r.prepend(a);
  }
  const N = c("width"), w = e("select", {}, ...[1024, 2048, 3072, 4096].map((a) => e("option", { value: String(a), selected: a === n.zoom_width }, `${a} pixels wide`)));
  w.addEventListener("change", () => {
    d({ zoom_width: Number(w.value) }, N).then(() => l(!1));
  });
  const b = c("cache"), p = e("button", { type: "button", textContent: "Clear cache", disabled: t.cache.files === 0 });
  p.addEventListener("click", async () => {
    if (window.confirm("Delete every cached full-size panorama? Each is rendered again the next time someone zooms or opens the sphere view.")) {
      p.disabled = !0;
      try {
        const a = await u("POST", "/settings/cache/clear");
        b.ok(`Removed ${a.removed} panoramas.`), await l(!1);
      } catch (a) {
        b.fail(a.message), p.disabled = !1;
      }
    }
  });
  const v = t.cache.files - t.cache.current, $ = c("prerender"), m = c("switches");
  h.replaceChildren(
    e("h2", {}, "360 photos (golblick)"),
    e("h3", {}, "Setup"),
    i,
    r,
    o.node,
    e("h3", {}, "Zooming and the sphere view"),
    e(
      "p",
      { className: "settings-hint" },
      "Zooming in Memories and the sphere view use a full-size panorama, rendered the first time someone needs it and then kept. A larger one is sharper and takes longer the first time: on a OneR photo, about 6 seconds at 2048 and 19 at 4096. X5 photos stop at 2560, the size of the panorama the camera stores."
    ),
    e("label", {}, "Panorama size ", w),
    N.node,
    e("h3", {}, "Panorama cache"),
    e("p", {}, `${t.cache.files} panoramas, ${x(t.cache.bytes)}.` + (v === 1 ? " One of them was made at a different size; it is replaced when that photo is viewed again, or removed now by clearing the cache." : v > 1 ? ` ${v} of them were made at a different size; each is replaced when its photo is viewed again, or all are removed now by clearing the cache.` : "")),
    p,
    b.node,
    e("h3", {}, "Rendering ahead of time"),
    f(
      "Render full-size panoramas in the background",
      "So the first zoom or sphere view of a photo doesn't wait. It runs in Nextcloud's background jobs, about two minutes at a time, and costs real CPU time: at 4096 pixels, roughly 19 seconds per OneR photo.",
      n.prerender,
      (a) => {
        d({ prerender: a }, $);
      }
    ),
    e("p", { className: "golblick-progress" }, `${t.cache.current} of ${t.insp} .insp files have a panorama at the current size.`),
    $.node,
    e("h3", {}, "Integrations"),
    e(
      "p",
      { className: "settings-hint" },
      "These rely on details of other apps that can change in an update. If one stops working, it can be turned off here without affecting the previews. Changes apply when a page is next loaded."
    ),
    f(
      "Show the panorama when zooming in Memories",
      "Without this, zooming into a .insp in Memories shows the two fisheye circles, and so does Memories' own sphere view in releases that have one.",
      n.memories_zoom,
      (a) => {
        d({ memories_zoom: a }, m);
      }
    ),
    f(
      '"View as sphere" in the Files actions menu',
      "Uses the Files app's own interface for this.",
      n.sphere_files,
      (a) => {
        d({ sphere_files: a }, m);
      }
    ),
    f(
      '"View as sphere" buttons in the image viewer and in Memories',
      "Added to those apps' pages from outside, because neither lets another app add a button. If a later version of either moves things around, the button may not appear.",
      n.sphere_buttons,
      (a) => {
        d({ sphere_buttons: a }, m);
      }
    ),
    m.node
  );
}
async function l(t = !0) {
  if (h) {
    t && h.querySelector(".settings-hint")?.replaceChildren("Checking…");
    try {
      S(await u("GET", "/settings/status"));
    } catch (n) {
      h.replaceChildren(
        e("h2", {}, "360 photos (golblick)"),
        e("p", { className: "golblick-feedback", role: "status" }, `Could not load the settings: ${n.message}`)
      );
    }
  }
}
l();
