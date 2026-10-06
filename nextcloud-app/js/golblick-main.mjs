import { b as oo, g as gt } from "./index-CVEG_reJ.chunk.mjs";
var ro = "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z", bn = "M22 8.1C21.7 8 21.3 7.8 21 7.7C19.4 4.3 16 2 12 2S4.6 4.3 3 7.7C2.7 7.8 2.3 8 2.1 8.1C1.4 8.5 1 9.2 1 9.9V14.1C1 14.8 1.4 15.5 2 15.9C2.3 16 2.7 16.2 3 16.3C4.6 19.7 8 22 12 22S19.4 19.7 21 16.3C21.3 16.2 21.6 16 21.9 15.8C22.5 15.4 23 14.8 23 14V9.9C23 9.2 22.6 8.5 22 8.1M21 9.9V14.1C18.8 15.3 15.5 16 12 16S5.2 15.3 3 14.1V9.9C5.2 8.7 8.5 8 12 8S18.8 8.7 21 9.9M12 4C14.4 4 16.5 5 18 6.7C16.2 6.2 14.1 6 12 6S7.8 6.2 6.1 6.7C7.5 5 9.6 4 12 4M12 20C9.6 20 7.5 19 6.1 17.3C7.8 17.8 9.9 18 12 18S16.2 17.8 18 17.3C16.5 19 14.4 20 12 20Z", y = /* @__PURE__ */ ((t) => (t[t.Debug = 0] = "Debug", t[t.Info = 1] = "Info", t[t.Warn = 2] = "Warn", t[t.Error = 3] = "Error", t[t.Fatal = 4] = "Fatal", t))(y || {});
class io {
  context;
  constructor(n) {
    this.context = n || {};
  }
  formatMessage(n, r, l) {
    let c = "[" + y[r].toUpperCase() + "] ";
    return l && l.app && (c += l.app + ": "), typeof n == "string" ? c + n : (c += `Unexpected ${n.name}`, n.message && (c += ` "${n.message}"`), r === y.Debug && n.stack && (c += `

Stack trace:
${n.stack}`), c);
  }
  log(n, r, l) {
    if (!(typeof this.context?.level == "number" && n < this.context?.level))
      switch (typeof r == "object" && l?.error === void 0 && (l.error = r), n) {
        case y.Debug:
          console.debug(this.formatMessage(r, y.Debug, l), l);
          break;
        case y.Info:
          console.info(this.formatMessage(r, y.Info, l), l);
          break;
        case y.Warn:
          console.warn(this.formatMessage(r, y.Warn, l), l);
          break;
        case y.Error:
          console.error(this.formatMessage(r, y.Error, l), l);
          break;
        case y.Fatal:
        default:
          console.error(this.formatMessage(r, y.Fatal, l), l);
          break;
      }
  }
  debug(n, r) {
    this.log(y.Debug, n, Object.assign({}, this.context, r));
  }
  info(n, r) {
    this.log(y.Info, n, Object.assign({}, this.context, r));
  }
  warn(n, r) {
    this.log(y.Warn, n, Object.assign({}, this.context, r));
  }
  error(n, r) {
    this.log(y.Error, n, Object.assign({}, this.context, r));
  }
  fatal(n, r) {
    this.log(y.Fatal, n, Object.assign({}, this.context, r));
  }
}
function so(t) {
  return new io(t);
}
class ao {
  context;
  factory;
  constructor(n) {
    this.context = {}, this.factory = n;
  }
  /**
   * Set the app name within the logging context
   *
   * @param appId App name
   */
  setApp(n) {
    return this.context.app = n, this;
  }
  /**
   * Set the logging level within the logging context
   *
   * @param level Logging level
   */
  setLogLevel(n) {
    return this.context.level = n, this;
  }
  /* eslint-disable jsdoc/no-undefined-types */
  /**
   * Set the user id within the logging context
   * @param uid User ID
   * @see {@link detectUser}
   */
  /* eslint-enable jsdoc/no-undefined-types */
  setUid(n) {
    return this.context.uid = n, this;
  }
  /**
   * Detect the currently logged in user and set the user id within the logging context
   */
  detectUser() {
    const n = oo();
    return n !== null && (this.context.uid = n.uid), this;
  }
  /**
   * Detect and use logging level configured in nextcloud config
   */
  detectLogLevel() {
    const n = this, r = () => {
      document.readyState === "complete" || document.readyState === "interactive" ? (n.context.level = window._oc_config?.loglevel ?? y.Warn, window._oc_debug && (n.context.level = y.Debug), document.removeEventListener("readystatechange", r)) : document.addEventListener("readystatechange", r);
    };
    return r(), this;
  }
  /** Build a logger using the logging context and factory */
  build() {
    return this.context.level === void 0 && this.detectLogLevel(), this.factory(this.context);
  }
}
function lo() {
  return new ao(so);
}
window._nc_files_scope ??= {};
window._nc_files_scope.v4_0 ??= {};
const ve = window._nc_files_scope.v4_0, co = lo().setApp("@nextcloud/files").detectUser().build();
var uo = class extends EventTarget {
  dispatchTypedEvent(t, n) {
    return super.dispatchEvent(n);
  }
};
function fo(t, n, r) {
  const l = `#initial-state-${t}-${n}`;
  if (window._nc_initial_state?.has(l))
    return window._nc_initial_state.get(l);
  window._nc_initial_state || (window._nc_initial_state = /* @__PURE__ */ new Map());
  const c = document.querySelector(l);
  if (c === null) {
    if (r !== void 0)
      return r;
    throw new Error(`Could not find initial state ${n} of ${t}`);
  }
  try {
    const f = JSON.parse(atob(c.value));
    return window._nc_initial_state.set(l, f), f;
  } catch (f) {
    if (console.error("[@nextcloud/initial-state] Could not parse initial state", { key: n, app: t, error: f }), r !== void 0)
      return r;
    throw new Error(`Could not parse initial state ${n} of ${t}`, { cause: f });
  }
}
function en(t, n) {
  (n == null || n > t.length) && (n = t.length);
  for (var r = 0, l = Array(n); r < n; r++) l[r] = t[r];
  return l;
}
function po(t) {
  if (Array.isArray(t)) return t;
}
function mo(t, n) {
  var r = t == null ? null : typeof Symbol < "u" && t[Symbol.iterator] || t["@@iterator"];
  if (r != null) {
    var l, c, f, h, D = [], v = !0, H = !1;
    try {
      if (f = (r = r.call(t)).next, n !== 0) for (; !(v = (l = f.call(r)).done) && (D.push(l.value), D.length !== n); v = !0) ;
    } catch (B) {
      H = !0, c = B;
    } finally {
      try {
        if (!v && r.return != null && (h = r.return(), Object(h) !== h)) return;
      } finally {
        if (H) throw c;
      }
    }
    return D;
  }
}
function ho() {
  throw new TypeError(`Invalid attempt to destructure non-iterable instance.
In order to be iterable, non-array objects must have a [Symbol.iterator]() method.`);
}
function go(t, n) {
  return po(t) || mo(t, n) || _o(t, n) || ho();
}
function _o(t, n) {
  if (t) {
    if (typeof t == "string") return en(t, n);
    var r = {}.toString.call(t).slice(8, -1);
    return r === "Object" && t.constructor && (r = t.constructor.name), r === "Map" || r === "Set" ? Array.from(t) : r === "Arguments" || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(r) ? en(t, n) : void 0;
  }
}
const En = Object.entries, tn = Object.setPrototypeOf, To = Object.isFrozen, bo = Object.getPrototypeOf, Eo = Object.getOwnPropertyDescriptor;
let S = Object.freeze, w = Object.seal, pe = Object.create, yn = typeof Reflect < "u" && Reflect, _t = yn.apply, Tt = yn.construct;
S || (S = function(n) {
  return n;
});
w || (w = function(n) {
  return n;
});
_t || (_t = function(n, r) {
  for (var l = arguments.length, c = new Array(l > 2 ? l - 2 : 0), f = 2; f < l; f++) c[f - 2] = arguments[f];
  return n.apply(r, c);
});
Tt || (Tt = function(n) {
  for (var r = arguments.length, l = new Array(r > 1 ? r - 1 : 0), c = 1; c < r; c++) l[c - 1] = arguments[c];
  return new n(...l);
});
const Q = A(Array.prototype.forEach), yo = A(Array.prototype.lastIndexOf), nn = A(Array.prototype.pop), ye = A(Array.prototype.push), Ao = A(Array.prototype.splice), de = Array.isArray, we = A(String.prototype.toLowerCase), lt = A(String.prototype.toString), on = A(String.prototype.match), Ae = A(String.prototype.replace), rn = A(String.prototype.indexOf), So = A(String.prototype.trim), wo = A(Number.prototype.toString), vo = A(Boolean.prototype.toString), sn = typeof BigInt > "u" ? null : A(BigInt.prototype.toString), an = typeof Symbol > "u" ? null : A(Symbol.prototype.toString), I = A(Object.prototype.hasOwnProperty), Se = A(Object.prototype.toString), O = A(RegExp.prototype.test), Y = Oo(TypeError);
function A(t) {
  return function(n) {
    n instanceof RegExp && (n.lastIndex = 0);
    for (var r = arguments.length, l = new Array(r > 1 ? r - 1 : 0), c = 1; c < r; c++) l[c - 1] = arguments[c];
    return _t(t, n, l);
  };
}
function Oo(t) {
  return function() {
    for (var n = arguments.length, r = new Array(n), l = 0; l < n; l++) r[l] = arguments[l];
    return Tt(t, r);
  };
}
function m(t, n) {
  let r = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : we;
  if (tn && tn(t, null), !de(n)) return t;
  let l = n.length;
  for (; l--; ) {
    let c = n[l];
    if (typeof c == "string") {
      const f = r(c);
      f !== c && (To(n) || (n[l] = f), c = f);
    }
    t[c] = !0;
  }
  return t;
}
function Lo(t) {
  for (let n = 0; n < t.length; n++) I(t, n) || (t[n] = null);
  return t;
}
function N(t) {
  const n = pe(null);
  for (const l of En(t)) {
    var r = go(l, 2);
    const c = r[0], f = r[1];
    I(t, c) && (de(f) ? n[c] = Lo(f) : f && typeof f == "object" && f.constructor === Object ? n[c] = N(f) : n[c] = f);
  }
  return n;
}
function Ro(t) {
  switch (typeof t) {
    case "string":
      return t;
    case "number":
      return wo(t);
    case "boolean":
      return vo(t);
    case "bigint":
      return sn ? sn(t) : "0";
    case "symbol":
      return an ? an(t) : "Symbol()";
    case "undefined":
      return Se(t);
    case "function":
    case "object": {
      if (t === null) return Se(t);
      const n = t, r = P(n, "toString");
      if (typeof r == "function") {
        const l = r(n);
        return typeof l == "string" ? l : Se(l);
      }
      return Se(t);
    }
    default:
      return Se(t);
  }
}
function P(t, n) {
  for (; t !== null; ) {
    const l = Eo(t, n);
    if (l) {
      if (l.get) return A(l.get);
      if (typeof l.value == "function") return A(l.value);
    }
    t = bo(t);
  }
  function r() {
    return null;
  }
  return r;
}
function Io(t) {
  try {
    return O(t, ""), !0;
  } catch {
    return !1;
  }
}
const ln = S([
  "a",
  "abbr",
  "acronym",
  "address",
  "area",
  "article",
  "aside",
  "audio",
  "b",
  "bdi",
  "bdo",
  "big",
  "blink",
  "blockquote",
  "body",
  "br",
  "button",
  "canvas",
  "caption",
  "center",
  "cite",
  "code",
  "col",
  "colgroup",
  "content",
  "data",
  "datalist",
  "dd",
  "decorator",
  "del",
  "details",
  "dfn",
  "dialog",
  "dir",
  "div",
  "dl",
  "dt",
  "element",
  "em",
  "fieldset",
  "figcaption",
  "figure",
  "font",
  "footer",
  "form",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "head",
  "header",
  "hgroup",
  "hr",
  "html",
  "i",
  "img",
  "input",
  "ins",
  "kbd",
  "label",
  "legend",
  "li",
  "main",
  "map",
  "mark",
  "marquee",
  "menu",
  "menuitem",
  "meter",
  "nav",
  "nobr",
  "ol",
  "optgroup",
  "option",
  "output",
  "p",
  "picture",
  "pre",
  "progress",
  "q",
  "rp",
  "rt",
  "ruby",
  "s",
  "samp",
  "search",
  "section",
  "select",
  "shadow",
  "slot",
  "small",
  "source",
  "spacer",
  "span",
  "strike",
  "strong",
  "style",
  "sub",
  "summary",
  "sup",
  "table",
  "tbody",
  "td",
  "template",
  "textarea",
  "tfoot",
  "th",
  "thead",
  "time",
  "tr",
  "track",
  "tt",
  "u",
  "ul",
  "var",
  "video",
  "wbr"
]), ct = S([
  "svg",
  "a",
  "altglyph",
  "altglyphdef",
  "altglyphitem",
  "animatecolor",
  "animatemotion",
  "animatetransform",
  "circle",
  "clippath",
  "defs",
  "desc",
  "ellipse",
  "enterkeyhint",
  "exportparts",
  "filter",
  "font",
  "g",
  "glyph",
  "glyphref",
  "hkern",
  "image",
  "inputmode",
  "line",
  "lineargradient",
  "marker",
  "mask",
  "metadata",
  "mpath",
  "part",
  "path",
  "pattern",
  "polygon",
  "polyline",
  "radialgradient",
  "rect",
  "stop",
  "style",
  "switch",
  "symbol",
  "text",
  "textpath",
  "title",
  "tref",
  "tspan",
  "view",
  "vkern"
]), ut = S([
  "feBlend",
  "feColorMatrix",
  "feComponentTransfer",
  "feComposite",
  "feConvolveMatrix",
  "feDiffuseLighting",
  "feDisplacementMap",
  "feDistantLight",
  "feDropShadow",
  "feFlood",
  "feFuncA",
  "feFuncB",
  "feFuncG",
  "feFuncR",
  "feGaussianBlur",
  "feImage",
  "feMerge",
  "feMergeNode",
  "feMorphology",
  "feOffset",
  "fePointLight",
  "feSpecularLighting",
  "feSpotLight",
  "feTile",
  "feTurbulence"
]), Do = S([
  "animate",
  "color-profile",
  "cursor",
  "discard",
  "font-face",
  "font-face-format",
  "font-face-name",
  "font-face-src",
  "font-face-uri",
  "foreignobject",
  "hatch",
  "hatchpath",
  "mesh",
  "meshgradient",
  "meshpatch",
  "meshrow",
  "missing-glyph",
  "script",
  "set",
  "solidcolor",
  "unknown",
  "use"
]), ft = S([
  "math",
  "menclose",
  "merror",
  "mfenced",
  "mfrac",
  "mglyph",
  "mi",
  "mlabeledtr",
  "mmultiscripts",
  "mn",
  "mo",
  "mover",
  "mpadded",
  "mphantom",
  "mroot",
  "mrow",
  "ms",
  "mspace",
  "msqrt",
  "mstyle",
  "msub",
  "msup",
  "msubsup",
  "mtable",
  "mtd",
  "mtext",
  "mtr",
  "munder",
  "munderover",
  "mprescripts"
]), Co = S([
  "maction",
  "maligngroup",
  "malignmark",
  "mlongdiv",
  "mscarries",
  "mscarry",
  "msgroup",
  "mstack",
  "msline",
  "msrow",
  "semantics",
  "annotation",
  "annotation-xml",
  "mprescripts",
  "none"
]), cn = S(["#text"]), un = S([
  "accept",
  "action",
  "align",
  "alt",
  "autocapitalize",
  "autocomplete",
  "autopictureinpicture",
  "autoplay",
  "background",
  "bgcolor",
  "border",
  "capture",
  "cellpadding",
  "cellspacing",
  "checked",
  "cite",
  "class",
  "clear",
  "color",
  "cols",
  "colspan",
  "command",
  "commandfor",
  "controls",
  "controlslist",
  "coords",
  "crossorigin",
  "datetime",
  "decoding",
  "default",
  "dir",
  "disabled",
  "disablepictureinpicture",
  "disableremoteplayback",
  "download",
  "draggable",
  "enctype",
  "enterkeyhint",
  "exportparts",
  "face",
  "for",
  "headers",
  "height",
  "hidden",
  "high",
  "href",
  "hreflang",
  "id",
  "inert",
  "inputmode",
  "integrity",
  "ismap",
  "kind",
  "label",
  "lang",
  "list",
  "loading",
  "loop",
  "low",
  "max",
  "maxlength",
  "media",
  "method",
  "min",
  "minlength",
  "multiple",
  "muted",
  "name",
  "nonce",
  "noshade",
  "novalidate",
  "nowrap",
  "open",
  "optimum",
  "part",
  "pattern",
  "placeholder",
  "playsinline",
  "popover",
  "popovertarget",
  "popovertargetaction",
  "poster",
  "preload",
  "pubdate",
  "radiogroup",
  "readonly",
  "rel",
  "required",
  "rev",
  "reversed",
  "role",
  "rows",
  "rowspan",
  "spellcheck",
  "scope",
  "selected",
  "shape",
  "size",
  "sizes",
  "slot",
  "span",
  "srclang",
  "start",
  "src",
  "srcset",
  "step",
  "style",
  "summary",
  "tabindex",
  "title",
  "translate",
  "type",
  "usemap",
  "valign",
  "value",
  "width",
  "wrap",
  "xmlns"
]), pt = S([
  "accent-height",
  "accumulate",
  "additive",
  "alignment-baseline",
  "amplitude",
  "ascent",
  "attributename",
  "attributetype",
  "azimuth",
  "basefrequency",
  "baseline-shift",
  "begin",
  "bias",
  "by",
  "class",
  "clip",
  "clippathunits",
  "clip-path",
  "clip-rule",
  "color",
  "color-interpolation",
  "color-interpolation-filters",
  "color-profile",
  "color-rendering",
  "cx",
  "cy",
  "d",
  "dx",
  "dy",
  "diffuseconstant",
  "direction",
  "display",
  "divisor",
  "dominant-baseline",
  "dur",
  "edgemode",
  "elevation",
  "end",
  "exponent",
  "fill",
  "fill-opacity",
  "fill-rule",
  "filter",
  "filterunits",
  "flood-color",
  "flood-opacity",
  "font-family",
  "font-size",
  "font-size-adjust",
  "font-stretch",
  "font-style",
  "font-variant",
  "font-weight",
  "fx",
  "fy",
  "g1",
  "g2",
  "glyph-name",
  "glyphref",
  "gradientunits",
  "gradienttransform",
  "height",
  "href",
  "id",
  "image-rendering",
  "in",
  "in2",
  "intercept",
  "k",
  "k1",
  "k2",
  "k3",
  "k4",
  "kerning",
  "keypoints",
  "keysplines",
  "keytimes",
  "lang",
  "lengthadjust",
  "letter-spacing",
  "kernelmatrix",
  "kernelunitlength",
  "lighting-color",
  "local",
  "marker-end",
  "marker-mid",
  "marker-start",
  "markerheight",
  "markerunits",
  "markerwidth",
  "maskcontentunits",
  "maskunits",
  "max",
  "mask",
  "mask-type",
  "media",
  "method",
  "mode",
  "min",
  "name",
  "numoctaves",
  "offset",
  "operator",
  "opacity",
  "order",
  "orient",
  "orientation",
  "origin",
  "overflow",
  "paint-order",
  "path",
  "pathlength",
  "patterncontentunits",
  "patterntransform",
  "patternunits",
  "pointer-events",
  "points",
  "preservealpha",
  "preserveaspectratio",
  "primitiveunits",
  "r",
  "rx",
  "ry",
  "radius",
  "refx",
  "refy",
  "repeatcount",
  "repeatdur",
  "restart",
  "result",
  "rotate",
  "scale",
  "seed",
  "shape-rendering",
  "slope",
  "specularconstant",
  "specularexponent",
  "spreadmethod",
  "startoffset",
  "stddeviation",
  "stitchtiles",
  "stop-color",
  "stop-opacity",
  "stroke-dasharray",
  "stroke-dashoffset",
  "stroke-linecap",
  "stroke-linejoin",
  "stroke-miterlimit",
  "stroke-opacity",
  "stroke",
  "stroke-width",
  "style",
  "surfacescale",
  "systemlanguage",
  "tabindex",
  "tablevalues",
  "targetx",
  "targety",
  "transform",
  "transform-origin",
  "text-anchor",
  "text-decoration",
  "text-orientation",
  "text-rendering",
  "textlength",
  "type",
  "u1",
  "u2",
  "unicode",
  "values",
  "vector-effect",
  "viewbox",
  "visibility",
  "version",
  "vert-adv-y",
  "vert-origin-x",
  "vert-origin-y",
  "width",
  "word-spacing",
  "wrap",
  "writing-mode",
  "xchannelselector",
  "ychannelselector",
  "x",
  "x1",
  "x2",
  "xmlns",
  "y",
  "y1",
  "y2",
  "z",
  "zoomandpan"
]), fn = S([
  "accent",
  "accentunder",
  "align",
  "bevelled",
  "close",
  "columnalign",
  "columnlines",
  "columnspacing",
  "columnspan",
  "denomalign",
  "depth",
  "dir",
  "display",
  "displaystyle",
  "encoding",
  "fence",
  "frame",
  "height",
  "href",
  "id",
  "largeop",
  "length",
  "linethickness",
  "lquote",
  "lspace",
  "mathbackground",
  "mathcolor",
  "mathsize",
  "mathvariant",
  "maxsize",
  "minsize",
  "movablelimits",
  "notation",
  "numalign",
  "open",
  "rowalign",
  "rowlines",
  "rowspacing",
  "rowspan",
  "rspace",
  "rquote",
  "scriptlevel",
  "scriptminsize",
  "scriptsizemultiplier",
  "selection",
  "separator",
  "separators",
  "stretchy",
  "subscriptshift",
  "supscriptshift",
  "symmetric",
  "voffset",
  "width",
  "xmlns"
]), He = S([
  "xlink:href",
  "xml:id",
  "xlink:title",
  "xml:space",
  "xmlns:xlink"
]), xo = w(/{{[\w\W]*|^[\w\W]*}}/g), No = w(/<%[\w\W]*|^[\w\W]*%>/g), Mo = w(/\${[\w\W]*/g), Po = w(/^data-[\-\w.\u00B7-\uFFFF]+$/), ko = w(/^aria-[\-\w]+$/), pn = w(/^(?:(?:(?:f|ht)tps?|mailto|tel|callto|sms|cid|xmpp|matrix):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i), Uo = w(/^(?:\w+script|data):/i), Fo = w(/[\u0000-\u0020\u00A0\u1680\u180E\u2000-\u2029\u205F\u3000]/g), zo = w(/^html$/i), Ho = w(/^[a-z][.\w]*(-[.\w]+)+$/i), dn = w(/<[/\w!]/g), mn = w(/<[/\w]/g), Bo = w(/<\/no(script|embed|frames)/i), Wo = w(/\/>/i), x = {
  element: 1,
  attribute: 2,
  text: 3,
  cdataSection: 4,
  entityReference: 5,
  entityNode: 6,
  processingInstruction: 7,
  comment: 8,
  document: 9,
  documentType: 10,
  documentFragment: 11,
  notation: 12
}, An = [
  "style",
  "script",
  "xmp",
  "iframe",
  "noembed",
  "noframes",
  "plaintext",
  "noscript"
], Go = S(m({}, An)), $o = (function() {
  const t = {};
  return Q(An, (n) => {
    t[n] = w(new RegExp("</" + n + "(?=[\\t\\n\\f\\r />])", "i"));
  }), S(t);
})(), jo = function() {
  return typeof window > "u" ? null : window;
}, Yo = function(n, r) {
  if (typeof n != "object" || typeof n.createPolicy != "function") return null;
  let l = null;
  const c = "data-tt-policy-suffix";
  r && r.hasAttribute(c) && (l = r.getAttribute(c));
  const f = "dompurify" + (l ? "#" + l : "");
  try {
    return n.createPolicy(f, {
      createHTML(h) {
        return h;
      },
      createScriptURL(h) {
        return h;
      }
    });
  } catch {
    return console.warn("TrustedTypes policy " + f + " could not be created."), null;
  }
}, hn = function() {
  return {
    afterSanitizeAttributes: [],
    afterSanitizeElements: [],
    afterSanitizeShadowDOM: [],
    beforeSanitizeAttributes: [],
    beforeSanitizeElements: [],
    beforeSanitizeShadowDOM: [],
    uponSanitizeAttribute: [],
    uponSanitizeElement: [],
    uponSanitizeShadowNode: []
  };
}, q = function(n, r, l, c) {
  return I(n, r) && de(n[r]) ? m(c.base ? N(c.base) : {}, n[r], c.transform) : l;
}, dt = function(n, r, l) {
  const c = I(n, r) ? n[r] : void 0;
  return c && typeof c == "object" ? N(c) : l();
};
function Sn() {
  let t = arguments.length > 0 && arguments[0] !== void 0 ? arguments[0] : jo();
  const n = (s) => Sn(s);
  if (n.version = "3.4.16", n.removed = [], !t || !t.document || t.document.nodeType !== x.document || !t.Element)
    return n.isSupported = !1, n;
  let r = t.document;
  const l = r, c = l.currentScript;
  t.DocumentFragment;
  const f = t.HTMLTemplateElement, h = t.Node, D = t.Element, v = t.NodeFilter;
  t.NamedNodeMap === void 0 && (t.NamedNodeMap || t.MozNamedAttrMap), t.HTMLFormElement;
  const H = t.DOMParser, B = t.trustedTypes, k = D.prototype, We = P(k, "cloneNode"), he = P(k, "remove"), W = P(k, "removeAttributeNode"), Rn = P(k, "nextSibling"), ee = P(k, "childNodes"), te = P(k, "parentNode"), yt = P(k, "shadowRoot"), Ge = P(k, "attributes"), V = h && h.prototype ? P(h.prototype, "nodeType") : null, ne = h && h.prototype ? P(h.prototype, "nodeName") : null, Oe = h && h.prototype ? P(h.prototype, "ownerDocument") : null, ge = function(e) {
    return V ? V(e) : e.nodeType;
  }, $e = function(e) {
    return ne ? ne(e) : e.nodeName;
  };
  if (typeof f == "function") {
    const s = r.createElement("template");
    s.content && s.content.ownerDocument && (r = s.content.ownerDocument);
  }
  let R, X = "", je, At = !1, _e = 0;
  const St = function() {
    if (_e > 0) throw Y('A configured TRUSTED_TYPES_POLICY callback (createHTML or createScriptURL) must not call DOMPurify.sanitize, as that causes infinite recursion. Do not pass a policy whose callbacks wrap DOMPurify as TRUSTED_TYPES_POLICY; see the "DOMPurify and Trusted Types" section of the README.');
  }, oe = function(e) {
    St(), _e++;
    try {
      return R.createHTML(e);
    } finally {
      _e--;
    }
  }, In = function(e) {
    St(), _e++;
    try {
      return R.createScriptURL(e);
    } finally {
      _e--;
    }
  }, Dn = function() {
    return At || (je = Yo(B, c), At = !0), je;
  }, Le = r, Ye = Le.implementation, wt = Le.createNodeIterator, Cn = Le.createDocumentFragment, xn = Le.getElementsByTagName, Nn = l.importNode;
  let g = hn();
  n.isSupported = typeof En == "function" && typeof te == "function" && Ye && Ye.createHTMLDocument !== void 0;
  const Mn = xo, Pn = No, kn = Mo, Un = Po, Fn = ko, zn = Uo, vt = Fo, Hn = Ho;
  let Ot = pn, _ = null;
  const qe = m({}, [
    ...ln,
    ...ct,
    ...ut,
    ...ft,
    ...cn
  ]);
  let T = null;
  const Ve = m({}, [
    ...un,
    ...pt,
    ...fn,
    ...He
  ]);
  let U = Object.seal(pe(null, {
    tagNameCheck: {
      writable: !0,
      configurable: !1,
      enumerable: !0,
      value: null
    },
    attributeNameCheck: {
      writable: !0,
      configurable: !1,
      enumerable: !0,
      value: null
    },
    allowCustomizedBuiltInElements: {
      writable: !0,
      configurable: !1,
      enumerable: !0,
      value: !1
    }
  })), Te = null, Lt = null;
  const G = Object.seal(pe(null, {
    tagCheck: {
      writable: !0,
      configurable: !1,
      enumerable: !0,
      value: null
    },
    attributeCheck: {
      writable: !0,
      configurable: !1,
      enumerable: !0,
      value: null
    }
  }));
  let Rt = !0, Xe = !0, It = !1, Dt = !0, $ = !1, K = !0, Z = !1, Ke = !1, Re = null, Ie = null, Ze = !1, re = !1, De = !1, Ce = !1, Ct = !0, xt = !1;
  const Nt = "user-content-";
  let Je = !0, Qe = !1, ie = {}, se = null;
  const Mt = m({}, [
    "annotation-xml",
    "audio",
    "colgroup",
    "desc",
    "foreignobject",
    "head",
    "iframe",
    "math",
    "mi",
    "mn",
    "mo",
    "ms",
    "mtext",
    "noembed",
    "noframes",
    "noscript",
    "plaintext",
    "script",
    "selectedcontent",
    "style",
    "svg",
    "template",
    "thead",
    "title",
    "video",
    "xmp"
  ]);
  let Pt = null;
  const kt = m({}, [
    "audio",
    "video",
    "img",
    "source",
    "image",
    "track"
  ]);
  let Ut = null;
  const Ft = m({}, [
    "alt",
    "class",
    "for",
    "id",
    "label",
    "name",
    "pattern",
    "placeholder",
    "role",
    "summary",
    "title",
    "value",
    "style",
    "xmlns"
  ]), xe = "http://www.w3.org/1998/Math/MathML", Ne = "http://www.w3.org/2000/svg", F = "http://www.w3.org/1999/xhtml";
  let ae = F, et = !1, tt = null;
  const Bn = m({}, [
    xe,
    Ne,
    F
  ], lt), zt = S([
    "mi",
    "mo",
    "mn",
    "ms",
    "mtext"
  ]);
  let nt = m({}, zt);
  const Ht = S(["annotation-xml"]);
  let ot = m({}, Ht);
  const Wn = m({}, [
    "title",
    "style",
    "font",
    "a",
    "script"
  ]);
  let be = null;
  const Gn = ["application/xhtml+xml", "text/html"], $n = "text/html";
  let E = null, le = null;
  const jn = r.createElement("form"), Bt = function(e) {
    return e instanceof RegExp || e instanceof Function;
  }, rt = function() {
    let e = arguments.length > 0 && arguments[0] !== void 0 ? arguments[0] : {};
    if (le && le === e) return;
    (!e || typeof e != "object") && (e = {}), e = N(e), be = Gn.indexOf(e.PARSER_MEDIA_TYPE) === -1 ? $n : e.PARSER_MEDIA_TYPE, E = be === "application/xhtml+xml" ? lt : we, _ = q(e, "ALLOWED_TAGS", qe, { transform: E }), T = q(e, "ALLOWED_ATTR", Ve, { transform: E }), tt = q(e, "ALLOWED_NAMESPACES", Bn, { transform: lt }), Ut = q(e, "ADD_URI_SAFE_ATTR", Ft, {
      transform: E,
      base: Ft
    }), Pt = q(e, "ADD_DATA_URI_TAGS", kt, {
      transform: E,
      base: kt
    }), se = q(e, "FORBID_CONTENTS", Mt, { transform: E }), Te = q(e, "FORBID_TAGS", N({}), { transform: E }), Lt = q(e, "FORBID_ATTR", N({}), { transform: E }), ie = I(e, "USE_PROFILES") ? e.USE_PROFILES && typeof e.USE_PROFILES == "object" ? N(e.USE_PROFILES) : e.USE_PROFILES : !1, Rt = e.ALLOW_ARIA_ATTR !== !1, Xe = e.ALLOW_DATA_ATTR !== !1, It = e.ALLOW_UNKNOWN_PROTOCOLS || !1, Dt = e.ALLOW_SELF_CLOSE_IN_ATTR !== !1, $ = e.SAFE_FOR_TEMPLATES || !1, K = e.SAFE_FOR_XML !== !1, Z = e.WHOLE_DOCUMENT || !1, re = e.RETURN_DOM || !1, De = e.RETURN_DOM_FRAGMENT || !1, Ce = e.RETURN_TRUSTED_TYPE || !1, Ze = e.FORCE_BODY || !1, Ct = e.SANITIZE_DOM !== !1, xt = e.SANITIZE_NAMED_PROPS || !1, Je = e.KEEP_CONTENT !== !1, Qe = e.IN_PLACE || !1, Ot = Io(e.ALLOWED_URI_REGEXP) ? e.ALLOWED_URI_REGEXP : pn, ae = typeof e.NAMESPACE == "string" ? e.NAMESPACE : F, nt = dt(e, "MATHML_TEXT_INTEGRATION_POINTS", () => m({}, zt)), ot = dt(e, "HTML_INTEGRATION_POINTS", () => m({}, Ht));
    const o = dt(e, "CUSTOM_ELEMENT_HANDLING", () => pe(null));
    if (U = pe(null), I(o, "tagNameCheck") && Bt(o.tagNameCheck) && (U.tagNameCheck = o.tagNameCheck), I(o, "attributeNameCheck") && Bt(o.attributeNameCheck) && (U.attributeNameCheck = o.attributeNameCheck), I(o, "allowCustomizedBuiltInElements") && typeof o.allowCustomizedBuiltInElements == "boolean" && (U.allowCustomizedBuiltInElements = o.allowCustomizedBuiltInElements), w(U), $ && (Xe = !1), De && (re = !0), ie && (_ = m({}, cn), T = pe(null), ie.html === !0 && (m(_, ln), m(T, un)), ie.svg === !0 && (m(_, ct), m(T, pt), m(T, He)), ie.svgFilters === !0 && (m(_, ut), m(T, pt), m(T, He)), ie.mathMl === !0 && (m(_, ft), m(T, fn), m(T, He))), G.tagCheck = null, G.attributeCheck = null, I(e, "ADD_TAGS") && (typeof e.ADD_TAGS == "function" ? G.tagCheck = e.ADD_TAGS : de(e.ADD_TAGS) && (_ === qe && (_ = N(_)), m(_, e.ADD_TAGS, E))), I(e, "ADD_ATTR") && (typeof e.ADD_ATTR == "function" ? G.attributeCheck = e.ADD_ATTR : de(e.ADD_ATTR) && (T === Ve && (T = N(T)), m(T, e.ADD_ATTR, E))), I(e, "ADD_FORBID_CONTENTS") && de(e.ADD_FORBID_CONTENTS) && (se === Mt && (se = N(se)), m(se, e.ADD_FORBID_CONTENTS, E)), Je && (_["#text"] = !0), Z && m(_, [
      "html",
      "head",
      "body"
    ]), _.table && (m(_, ["tbody"]), delete Te.tbody), e.TRUSTED_TYPES_POLICY) {
      if (typeof e.TRUSTED_TYPES_POLICY.createHTML != "function") throw Y('TRUSTED_TYPES_POLICY configuration option must provide a "createHTML" hook.');
      if (typeof e.TRUSTED_TYPES_POLICY.createScriptURL != "function") throw Y('TRUSTED_TYPES_POLICY configuration option must provide a "createScriptURL" hook.');
      const i = R;
      R = e.TRUSTED_TYPES_POLICY;
      try {
        X = oe("");
      } catch (a) {
        throw R = i, a;
      }
    } else e.TRUSTED_TYPES_POLICY === null ? (R = void 0, X = "") : (R === void 0 && (R = Dn()), R && typeof X == "string" && (X = oe("")));
    S && S(e), le = e;
  }, Wt = m({}, [
    ...ct,
    ...ut,
    ...Do
  ]), Gt = m({}, [...ft, ...Co]), Yn = function(e, o, i) {
    return o.namespaceURI === F ? e === "svg" : o.namespaceURI === xe ? e === "svg" && (i === "annotation-xml" || nt[i]) : !!Wt[e];
  }, qn = function(e, o, i) {
    return o.namespaceURI === F ? e === "math" : o.namespaceURI === Ne ? e === "math" && ot[i] : !!Gt[e];
  }, Vn = function(e, o, i) {
    return o.namespaceURI === Ne && !ot[i] || o.namespaceURI === xe && !nt[i] ? !1 : !Gt[e] && (Wn[e] || !Wt[e]);
  }, Xn = function(e) {
    let o = te(e);
    (!o || !o.tagName) && (o = {
      namespaceURI: ae,
      tagName: "template"
    });
    const i = we(e.tagName), a = we(o.tagName);
    return tt[e.namespaceURI] ? e.namespaceURI === Ne ? Yn(i, o, a) : e.namespaceURI === xe ? qn(i, o, a) : e.namespaceURI === F ? Vn(i, o, a) : !!(be === "application/xhtml+xml" && tt[e.namespaceURI]) : !1;
  }, j = function(e) {
    ye(n.removed, { element: e });
    try {
      te(e).removeChild(e);
    } catch {
      if (he(e), !te(e)) throw Y("a node selected for removal could not be detached from its tree and cannot be safely returned; refusing to sanitize in place");
    }
  }, $t = function(e, o, i) {
    try {
      W(e, o);
    } catch {
      try {
        e.removeAttribute(i);
      } catch {
      }
    }
  }, Me = function(e) {
    Pe(e);
    const o = ee(e);
    if (o) {
      const a = [];
      Q(o, (u) => {
        ye(a, u);
      }), Q(a, (u) => {
        try {
          he(u);
        } catch {
        }
      });
    }
    const i = Ge(e);
    if (i) for (let a = i.length - 1; a >= 0; --a) {
      const u = i[a], p = u && u.name;
      typeof p == "string" && $t(e, u, p);
    }
  }, J = function(e, o, i) {
    if (!i) try {
      i = o.getAttributeNode(e);
    } catch {
      i = null;
    }
    ye(n.removed, {
      attribute: i || null,
      from: o
    });
    try {
      i ? W(o, i) : o.removeAttribute(e);
    } catch {
      try {
        o.removeAttribute(e);
      } catch {
      }
    }
    if (e === "is")
      if (re || De) try {
        j(o);
      } catch {
      }
      else try {
        o.setAttribute(e, "");
      } catch {
      }
  }, Kn = function(e) {
    const o = Ge(e);
    if (o)
      for (let i = o.length - 1; i >= 0; --i) {
        const a = o[i], u = a && a.name;
        typeof u != "string" || T[E(u)] || $t(e, a, u);
      }
  }, Pe = function(e) {
    const o = [e];
    for (; o.length > 0; ) {
      const i = o.pop();
      ge(i) === x.element && Kn(i);
      const a = ee(i);
      if (a) for (let u = a.length - 1; u >= 0; --u) o.push(a[u]);
    }
  }, jt = function(e, o) {
    return K ? e === "patchsrc" ? !0 : e === "for" && o !== "label" && o !== "output" : !1;
  }, Zn = function(e) {
    if (!K) return;
    const o = [e];
    for (; o.length > 0; ) {
      const i = o.pop(), a = ge(i);
      if (a === x.processingInstruction || a === x.comment && O(mn, i.data)) {
        try {
          he(i);
        } catch {
        }
        continue;
      }
      if (a === x.element) {
        const p = i, d = E($e(i));
        try {
          p.hasAttribute && p.hasAttribute("patchsrc") && p.removeAttribute("patchsrc"), p.hasAttribute && p.hasAttribute("for") && jt("for", d) && p.removeAttribute("for");
        } catch {
        }
      }
      const u = ee(i);
      if (u) for (let p = u.length - 1; p >= 0; --p) o.push(u[p]);
    }
  }, Yt = function(e) {
    let o = null, i = null;
    if (Ze) e = "<remove></remove>" + e;
    else {
      const p = on(e, /^[\r\n\t ]+/);
      i = p && p[0];
    }
    be === "application/xhtml+xml" && ae === F && (e = '<html xmlns="http://www.w3.org/1999/xhtml"><head></head><body>' + e + "</body></html>");
    const a = R ? oe(e) : e;
    if (ae === F) try {
      o = new H().parseFromString(a, be);
    } catch {
    }
    if (!o || !o.documentElement) {
      o = Ye.createDocument(ae, "template", null);
      try {
        o.documentElement.innerHTML = et ? X : a;
      } catch {
      }
    }
    const u = o.body || o.documentElement;
    return e && i && u.insertBefore(r.createTextNode(i), u.childNodes[0] || null), ae === F ? xn.call(o, Z ? "html" : "body")[0] : Z ? o.documentElement : u;
  }, qt = function(e) {
    const o = Oe ? Oe(e) : e.ownerDocument;
    return wt.call(o || e, e, v.SHOW_ELEMENT | v.SHOW_COMMENT | v.SHOW_TEXT | v.SHOW_PROCESSING_INSTRUCTION | v.SHOW_CDATA_SECTION, null);
  }, ke = function(e) {
    return e = Ae(e, Mn, " "), e = Ae(e, Pn, " "), e = Ae(e, kn, " "), e;
  }, it = function(e) {
    var o;
    e.normalize();
    const i = Oe ? Oe(e) : e.ownerDocument, a = wt.call(i || e, e, v.SHOW_TEXT | v.SHOW_COMMENT | v.SHOW_CDATA_SECTION | v.SHOW_PROCESSING_INSTRUCTION, null);
    let u = a.nextNode();
    for (; u; )
      u.data = ke(u.data), u = a.nextNode();
    const p = (o = e.querySelectorAll) === null || o === void 0 ? void 0 : o.call(e, "template");
    p && Q(p, (d) => {
      ce(d.content) && it(d.content);
    });
  }, Ue = function(e) {
    const o = ne ? ne(e) : null;
    return typeof o != "string" || E(o) !== "form" ? !1 : typeof e.nodeName != "string" || typeof e.textContent != "string" || typeof e.removeChild != "function" || e.attributes !== Ge(e) || typeof e.removeAttribute != "function" || typeof e.removeAttributeNode != "function" || typeof e.getAttributeNode != "function" || typeof e.setAttribute != "function" || typeof e.namespaceURI != "string" || typeof e.insertBefore != "function" || typeof e.hasChildNodes != "function" || e.nodeType !== V(e) || e.childNodes !== ee(e);
  }, ce = function(e) {
    if (!V || typeof e != "object" || e === null) return !1;
    try {
      return V(e) === x.documentFragment;
    } catch {
      return !1;
    }
  }, Ee = function(e) {
    if (!V || typeof e != "object" || e === null) return !1;
    try {
      return typeof V(e) == "number";
    } catch {
      return !1;
    }
  };
  function z(s, e, o) {
    s.length !== 0 && Q(s, (i) => {
      i.call(n, e, o, le);
    });
  }
  const Jn = function(e, o) {
    return !!(K && e.hasChildNodes() && !Ee(e.firstElementChild) && O(dn, e.textContent) && O(dn, e.innerHTML) || K && e.namespaceURI === F && Go[o] && (Ee(e.firstElementChild) || typeof e.textContent == "string" && O($o[o], e.textContent)) || e.nodeType === x.processingInstruction || K && e.nodeType === x.comment && O(mn, e.data));
  }, Fe = function(e, o) {
    if (e instanceof RegExp) return O(e, o);
    if (e instanceof Function) {
      for (var i = arguments.length, a = new Array(i > 2 ? i - 2 : 0), u = 2; u < i; u++) a[u - 2] = arguments[u];
      return !!e(o, ...a);
    }
    return !1;
  }, Qn = function(e, o, i) {
    if (!Te[o] && Zt(o) && Fe(U.tagNameCheck, o)) return !1;
    if (Je && !se[o]) {
      const a = te(e), u = ee(e);
      if (u && a) {
        const p = u.length;
        for (let d = p - 1; d >= 0; --d) {
          const b = e === i ? We(u[d], !0) : u[d];
          a.insertBefore(b, Rn(e));
        }
      }
    }
    return j(e), !0;
  }, Vt = function(e, o, i, a) {
    return e.length === 0 ? o : o === i || o === a ? N(o) : o;
  }, ue = function(e, o) {
    return e === o || te(e) !== null ? !1 : (Qe && Pe(e), !0);
  }, Xt = function(e, o) {
    if (z(g.beforeSanitizeElements, e, null), ue(e, o)) return !0;
    if (Ue(e))
      return j(e), !0;
    const i = E($e(e));
    if (_ = Vt(g.uponSanitizeElement, _, qe, Re), z(g.uponSanitizeElement, e, {
      tagName: i,
      allowedTags: _
    }), ue(e, o)) return !0;
    if (Jn(e, i))
      return j(e), !0;
    if (Te[i] || !(G.tagCheck instanceof Function && G.tagCheck(i)) && !_[i]) {
      const a = Qn(e, i, o);
      return a === !1 && (z(g.afterSanitizeElements, e, null), ue(e, o)) ? !0 : a;
    }
    if (ge(e) === x.element && !Xn(e) || (i === "noscript" || i === "noembed" || i === "noframes") && O(Bo, e.innerHTML))
      return j(e), !0;
    if ($ && e.nodeType === x.text) {
      const a = ke(e.textContent);
      e.textContent !== a && (ye(n.removed, { element: e.cloneNode() }), e.textContent = a);
    }
    return z(g.afterSanitizeElements, e, null), ue(e, o);
  }, Kt = function(e, o, i) {
    if (Lt[o] || jt(o, e) || Ct && (o === "id" || o === "name") && (i in r || i in jn)) return !1;
    const a = T[o] || G.attributeCheck instanceof Function && G.attributeCheck(o, e);
    return Xe && O(Un, o) || Rt && O(Fn, o) ? !0 : a ? Ut[o] || O(Ot, Ae(i, vt, "")) || (o === "src" || o === "xlink:href" || o === "href") && e !== "script" && rn(i, "data:") === 0 && Pt[e] || It && !O(zn, Ae(i, vt, "")) ? !0 : !i : Zt(e) && Fe(U.tagNameCheck, e) && Fe(U.attributeNameCheck, o, e) || o === "is" && U.allowCustomizedBuiltInElements && Fe(U.tagNameCheck, i);
  }, eo = m({}, [
    "annotation-xml",
    "color-profile",
    "font-face",
    "font-face-format",
    "font-face-name",
    "font-face-src",
    "font-face-uri",
    "missing-glyph"
  ]), Zt = function(e) {
    return !eo[we(e)] && O(Hn, e);
  }, to = function(e, o, i, a) {
    if (R && typeof B == "object" && typeof B.getAttributeType == "function" && !i) switch (B.getAttributeType(e, o)) {
      case "TrustedHTML":
        return oe(a);
      case "TrustedScriptURL":
        return In(a);
    }
    return a;
  }, no = function(e, o, i, a) {
    try {
      return i ? e.setAttributeNS(i, o, a) : e.setAttribute(o, a), Ue(e) ? (j(e), !1) : !0;
    } catch {
      return J(o, e), !1;
    }
  }, Jt = function(e, o) {
    if (z(g.beforeSanitizeAttributes, e, null), ue(e, o)) return;
    const i = e.attributes;
    if (!i || Ue(e)) return;
    T = Vt(g.uponSanitizeAttribute, T, Ve, Ie);
    const a = {
      attrName: "",
      attrValue: "",
      keepAttr: !0,
      allowedAttributes: T,
      forceKeepAttr: void 0
    };
    let u = i.length;
    const p = E(e.nodeName);
    for (; u--; ) {
      const d = i[u], b = d.name, M = d.namespaceURI, C = d.value, fe = E(b), at = C;
      let L = b === "value" ? at : So(at), Qt = !1;
      if (a.attrName = fe, a.attrValue = L, a.keepAttr = !0, a.forceKeepAttr = void 0, z(g.uponSanitizeAttribute, e, a), L = a.attrValue, xt && (fe === "id" || fe === "name") && rn(L, Nt) !== 0 && (J(b, e, d), L = Nt + L, Qt = !0), K && O(/((--!?|])>)|<\/(style|script|title|xmp|textarea|noscript|iframe|noembed|noframes)/i, L)) {
        J(b, e, d);
        continue;
      }
      if (fe === "attributename" && on(L, "href")) {
        J(b, e, d);
        continue;
      }
      if (!a.forceKeepAttr) {
        if (!a.keepAttr) {
          J(b, e, d);
          continue;
        }
        if (!Dt && O(Wo, L)) {
          J(b, e, d);
          continue;
        }
        if ($ && (L = ke(L)), !Kt(p, fe, L)) {
          J(b, e, d);
          continue;
        }
        L = to(p, fe, M, L), L !== at && no(e, b, M, L) && Qt && nn(n.removed);
      }
    }
    z(g.afterSanitizeAttributes, e, null), ue(e, o);
  }, ze = function(e) {
    let o = null;
    const i = qt(e);
    for (z(g.beforeSanitizeShadowDOM, e, null); o = i.nextNode(); )
      if (z(g.uponSanitizeShadowNode, o, null), Xt(o, e), Jt(o, e), ce(o.content) && ze(o.content), ge(o) === x.element) {
        const a = yt(o);
        ce(a) && (st(a), ze(a));
      }
    z(g.afterSanitizeShadowDOM, e, null);
  }, st = function(e) {
    const o = [{
      node: e,
      shadow: null
    }];
    for (; o.length > 0; ) {
      const i = o.pop();
      if (i.shadow) {
        ze(i.shadow);
        continue;
      }
      const a = i.node, u = ge(a) === x.element, p = ee(a);
      if (p) for (let d = p.length - 1; d >= 0; --d) o.push({
        node: p[d],
        shadow: null
      });
      if (u) {
        const d = ne ? ne(a) : null;
        if (typeof d == "string" && E(d) === "template") {
          const b = a.content;
          ce(b) && o.push({
            node: b,
            shadow: null
          });
        }
      }
      if (u) {
        const d = yt(a);
        ce(d) && o.push({
          node: null,
          shadow: d
        }, {
          node: d,
          shadow: null
        });
      }
    }
  };
  return n.sanitize = function(s) {
    let e = arguments.length > 1 && arguments[1] !== void 0 ? arguments[1] : {}, o = null, i = null, a = null, u = null;
    if (et = !s, et && (s = "<!-->"), typeof s != "string" && !Ee(s) && (s = Ro(s), typeof s != "string"))
      throw Y("dirty is not a string, aborting");
    if (!n.isSupported) return s;
    Ke ? (_ = Re, T = Ie) : rt(e), (g.uponSanitizeElement.length > 0 || g.uponSanitizeAttribute.length > 0) && (_ = N(_)), g.uponSanitizeAttribute.length > 0 && (T = N(T)), n.removed = [];
    const p = Qe && typeof s != "string" && Ee(s);
    if (p) {
      Zn(s);
      const M = $e(s);
      if (typeof M == "string") {
        const C = E(M);
        if (!_[C] || Te[C])
          throw Me(s), Y("root node is forbidden and cannot be sanitized in-place");
      }
      if (Ue(s))
        throw Me(s), Y("root node is clobbered and cannot be sanitized in-place");
      try {
        st(s);
      } catch (C) {
        throw Me(s), C;
      }
    } else if (Ee(s))
      o = Yt("<!---->"), i = o.ownerDocument.importNode(s, !0), i.nodeType === x.element && i.nodeName === "BODY" || i.nodeName === "HTML" ? o = i : o.appendChild(i), st(o);
    else {
      if (!re && !$ && !Z && s.indexOf("<") === -1) return R && Ce ? oe(s) : s;
      if (o = Yt(s), !o) return re ? null : Ce ? X : "";
    }
    o && Ze && j(o.firstChild);
    const d = p ? s : o;
    try {
      const M = qt(d);
      for (; a = M.nextNode(); )
        Xt(a, d), Jt(a, d), ce(a.content) && ze(a.content);
    } catch (M) {
      throw p && (Me(s), Q(n.removed, (C) => {
        C.element && Pe(C.element);
      })), M;
    }
    if (p) {
      let M = !1;
      if (Q(n.removed, (C) => {
        C.element && (C.element === s && (M = !0), Pe(C.element));
      }), M) throw Y("a node selected for removal could not be safely returned; refusing to sanitize in place");
      return $ && it(s), s;
    }
    if (re) {
      if ($ && it(o), De)
        for (u = Cn.call(o.ownerDocument); o.firstChild; ) u.appendChild(o.firstChild);
      else u = o;
      return (T.shadowroot || T.shadowrootmode) && (u = Nn.call(l, u, !0)), u;
    }
    let b = Z ? o.outerHTML : o.innerHTML;
    return Z && _["!doctype"] && o.ownerDocument && o.ownerDocument.doctype && o.ownerDocument.doctype.name && O(zo, o.ownerDocument.doctype.name) && (b = "<!DOCTYPE " + o.ownerDocument.doctype.name + `>
` + b), $ && (b = ke(b)), R && Ce ? oe(b) : b;
  }, n.setConfig = function() {
    let s = arguments.length > 0 && arguments[0] !== void 0 ? arguments[0] : {};
    rt(s), Ke = !0, Re = _, Ie = T;
  }, n.clearConfig = function() {
    le = null, Ke = !1, Re = null, Ie = null, R = je, X = "";
  }, n.isValidAttribute = function(s, e, o) {
    le || rt({});
    const i = E(s), a = E(e);
    return Kt(i, a, o);
  }, n.addHook = function(s, e) {
    typeof e == "function" && I(g, s) && ye(g[s], e);
  }, n.removeHook = function(s, e) {
    if (I(g, s)) {
      if (e !== void 0) {
        const o = yo(g[s], e);
        return o === -1 ? void 0 : Ao(g[s], o, 1)[0];
      }
      return nn(g[s]);
    }
  }, n.removeHooks = function(s) {
    I(g, s) && (g[s] = []);
  }, n.removeAllHooks = function() {
    g = hn();
  }, n;
}
Sn();
globalThis._nc_l10n_locale ??= typeof document < "u" && document.documentElement.dataset.locale || Intl.DateTimeFormat().resolvedOptions().locale.replaceAll(/-/g, "_");
globalThis._nc_l10n_language ??= typeof document < "u" && document.documentElement.lang || (globalThis.navigator?.language ?? "en");
globalThis._oc_l10n_registry_translations ??= {};
globalThis._oc_l10n_registry_plural_functions ??= {};
class qo extends uo {
}
function Vo() {
  return ve.registry ??= new qo(), ve.registry;
}
const Xo = Object.freeze({
  DEFAULT: "default",
  HIDDEN: "hidden"
});
function Ko(t) {
  if (Zo(t), ve.fileActions ??= /* @__PURE__ */ new Map(), ve.fileActions.has(t.id)) {
    co.error(`FileAction ${t.id} already registered`, { action: t });
    return;
  }
  ve.fileActions.set(t.id, t), Vo().dispatchTypedEvent("register:action", new CustomEvent("register:action", { detail: t }));
}
function Zo(t) {
  if (!t.id || typeof t.id != "string")
    throw new Error("Invalid id");
  if (!t.displayName || typeof t.displayName != "function")
    throw new Error("Invalid displayName function");
  if ("title" in t && typeof t.title != "function")
    throw new Error("Invalid title function");
  if (!t.iconSvgInline || typeof t.iconSvgInline != "function")
    throw new Error("Invalid iconSvgInline function");
  if (!t.exec || typeof t.exec != "function")
    throw new Error("Invalid exec function");
  if ("enabled" in t && typeof t.enabled != "function")
    throw new Error("Invalid enabled function");
  if ("execBatch" in t && typeof t.execBatch != "function")
    throw new Error("Invalid execBatch function");
  if ("order" in t && typeof t.order != "number")
    throw new Error("Invalid order");
  if (t.destructive !== void 0 && typeof t.destructive != "boolean")
    throw new Error("Invalid destructive flag");
  if ("parent" in t && typeof t.parent != "string")
    throw new Error("Invalid parent");
  if (t.default && !Object.values(Xo).includes(t.default))
    throw new Error("Invalid default");
  if ("inline" in t && typeof t.inline != "function")
    throw new Error("Invalid inline function");
  if ("renderInline" in t && typeof t.renderInline != "function")
    throw new Error("Invalid renderInline function");
  if ("hotkey" in t && t.hotkey !== void 0) {
    if (typeof t.hotkey != "object")
      throw new Error("Invalid hotkey configuration");
    if (typeof t.hotkey.key != "string" || !t.hotkey.key)
      throw new Error("Missing or invalid hotkey key");
    if (typeof t.hotkey.description != "string" || !t.hotkey.description)
      throw new Error("Missing or invalid hotkey description");
  }
}
let Be = null;
function Et(t, n = 20) {
  return `<svg viewBox="0 0 24 24" width="${n}" height="${n}" aria-hidden="true"><path fill="currentColor" d="${t}"/></svg>`;
}
async function wn(t, n, r = "") {
  Be?.();
  const l = document.createElement("div");
  l.className = "golblick-sphere", l.setAttribute("role", "dialog"), l.setAttribute("aria-label", r ? `${r}, as a sphere` : "Sphere view"), l.style.cssText = "position:fixed;inset:0;z-index:100000;background:#000;";
  const c = document.createElement("button");
  c.type = "button", c.title = "Close sphere view", c.setAttribute("aria-label", "Close sphere view"), c.innerHTML = Et(ro, 24), c.style.cssText = "position:absolute;top:12px;right:12px;z-index:1;width:44px;height:44px;border:0;border-radius:50%;background:rgba(0,0,0,.5);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;";
  const f = document.createElement("div");
  f.style.cssText = "position:absolute;left:50%;bottom:16px;transform:translateX(-50%);z-index:1;padding:6px 12px;border-radius:16px;background:rgba(0,0,0,.5);color:#fff;font-size:13px;pointer-events:none;", f.textContent = "Loading…", l.append(c, f), document.body.appendChild(l);
  let h = null, D = !1;
  const v = (W) => {
    W.key === "Escape" && H(), ["Escape", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", " "].includes(W.key) && (W.stopImmediatePropagation(), W.preventDefault());
  }, H = () => {
    D || (D = !0, window.removeEventListener("keydown", v, !0), h?.destroy(), l.remove(), Be === H && (Be = null));
  };
  Be = H, c.addEventListener("click", H), window.addEventListener("keydown", v, !0);
  const B = `etag=${encodeURIComponent(n)}`, k = gt("/core/preview") + `?fileId=${t}&x=2048&y=1024&a=1&${B}`, We = gt(`/apps/golblick/sphere/${t}`) + `?${B}`;
  try {
    const { SphereView: W } = await import("./sphere-44dHSg5o.chunk.mjs");
    if (D) return;
    if (h = await W.create(l, k), D) {
      h.destroy();
      return;
    }
    l.append(c, f);
  } catch {
    f.textContent = "This photo could not be shown as a sphere.";
    return;
  }
  f.textContent = "Loading full resolution…";
  const he = await h.upgrade(We);
  D || (he ? f.remove() : f.textContent = "Full resolution is not available; showing the preview.");
}
const bt = "View as sphere", me = "golblick-sphere-button", Jo = (t) => !!t && t.toLowerCase().endsWith(".insp"), vn = fo("golblick", "config", { files: !0, buttons: !0 });
vn.files && Ko({
  id: "golblick-sphere",
  displayName: () => bt,
  iconSvgInline: () => Et(bn),
  enabled: ({ nodes: t }) => t.length === 1 && Jo(t[0].basename) && t[0].fileid !== void 0,
  exec: async ({ nodes: t }) => {
    const n = t[0];
    return wn(Number(n.fileid), String(n.attributes?.etag ?? ""), n.basename), null;
  },
  order: 50
});
const gn = /* @__PURE__ */ new Map();
function Qo(t) {
  let n = gn.get(t);
  return n || (n = fetch(gt(`/apps/golblick/sphere/${t}/info`), { credentials: "same-origin" }).then((r) => r.ok ? r.json() : { sphere: !1, etag: null }).catch(() => ({ sphere: !1, etag: null })), gn.set(t, n)), n;
}
function On(t) {
  let n;
  if (t instanceof HTMLButtonElement) {
    n = t.cloneNode(!0);
    for (const c of [n, ...n.querySelectorAll("[id]")]) c.removeAttribute("id");
    n.removeAttribute("aria-pressed"), n.classList.remove("action-item__menutoggle"), n.removeAttribute("aria-haspopup"), n.removeAttribute("aria-expanded");
  } else
    n = document.createElement("button"), n.style.cssText = "border:0;background:transparent;color:inherit;width:44px;height:44px;display:flex;align-items:center;justify-content:center;cursor:pointer;border-radius:8px;padding:0;", n.innerHTML = '<span class="button-vue__icon"></span>';
  n.type = "button", n.classList.add(me), n.title = bt, n.setAttribute("aria-label", bt);
  const r = Number(t?.querySelector("svg")?.getAttribute("width")) || 20, l = n.querySelector(".button-vue__icon") ?? n;
  return l.innerHTML = `<span class="material-design-icon" role="img">${Et(bn, r)}</span>`, n.querySelector(".button-vue__text")?.replaceChildren(), n;
}
function Ln(t, n, r, l) {
  const c = t?.querySelector(`.${me}`);
  if (!t || n === null) {
    c?.remove();
    return;
  }
  c && c.dataset.fileId === String(n) || (c?.remove(), Qo(n).then((f) => {
    if (!f.sphere || r() !== n || !t.isConnected || t.querySelector(`.${me}`)) return;
    const h = l();
    h.dataset.fileId = String(n), h.addEventListener("click", (D) => {
      D.stopPropagation(), wn(n, f.etag ?? "");
    }), t.insertBefore(h, t.firstChild);
  }));
}
function _n() {
  const n = document.querySelector("#viewer .viewer__file--active img")?.getAttribute("src") ?? "", r = n.match(/[?&]fileId=(\d+)/) ?? n.match(/\/preview\/(\d+)/);
  return r ? Number(r[1]) : null;
}
function er() {
  const t = document.querySelector("#viewer .modal-header .header-actions");
  Ln(t, _n(), _n, () => On(t?.querySelector(`button:not(.${me})`) ?? null));
}
function mt() {
  if (!document.querySelector(".memories-viewer .pswp--open")) return null;
  const t = window.location.hash.match(/^#v\/[^/]+\/(\d+)/);
  return t ? Number(t[1]) : null;
}
function tr(t) {
  const n = globalThis._m?.viewer?.currentPhoto;
  return t !== null && n?.fileid === t && (n.pano ?? 0) > 0;
}
function nr() {
  const t = document.querySelector(".memories-viewer .top-bar .action-items");
  if (tr(mt())) {
    t?.querySelector(`.${me}`)?.remove();
    return;
  }
  Ln(t, mt(), mt, () => On(t?.querySelector(`button.action-item--single:not(.${me})`) ?? null));
}
let ht = !1;
function Tn() {
  ht || (ht = !0, requestAnimationFrame(() => {
    ht = !1, er(), nr();
  }));
}
vn.buttons && (new MutationObserver(Tn).observe(document.body, {
  childList: !0,
  subtree: !0,
  attributes: !0,
  attributeFilter: ["src", "class"]
}), window.addEventListener("hashchange", Tn));
