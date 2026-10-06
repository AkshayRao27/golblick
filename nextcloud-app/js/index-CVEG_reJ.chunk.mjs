function V(n) {
  return n && n.__esModule && Object.prototype.hasOwnProperty.call(n, "default") ? n.default : n;
}
var A, C;
function H() {
  return C || (C = 1, A = typeof process == "object" && process.env && process.env.NODE_DEBUG && /\bsemver\b/i.test(process.env.NODE_DEBUG) ? (...r) => console.error("SEMVER", ...r) : () => {
  }), A;
}
var w, F;
function z() {
  if (F) return w;
  F = 1;
  const n = "2.0.0", r = 256, o = Number.MAX_SAFE_INTEGER || /* istanbul ignore next */
  9007199254740991, E = 16, u = r - 6;
  return w = {
    MAX_LENGTH: r,
    MAX_SAFE_COMPONENT_LENGTH: E,
    MAX_SAFE_BUILD_LENGTH: u,
    MAX_SAFE_INTEGER: o,
    RELEASE_TYPES: [
      "major",
      "premajor",
      "minor",
      "preminor",
      "patch",
      "prepatch",
      "prerelease"
    ],
    SEMVER_SPEC_VERSION: n,
    FLAG_INCLUDE_PRERELEASE: 1,
    FLAG_LOOSE: 2
  }, w;
}
var T = { exports: {} }, G;
function Y() {
  return G || (G = 1, (function(n, r) {
    const {
      MAX_SAFE_COMPONENT_LENGTH: o,
      MAX_SAFE_BUILD_LENGTH: E,
      MAX_LENGTH: u
    } = z(), h = H();
    r = n.exports = {};
    const p = r.re = [], R = r.safeRe = [], t = r.src = [], I = r.safeSrc = [], e = r.t = {};
    let i = 0;
    const a = "[a-zA-Z0-9-]", c = [
      ["\\s", 1],
      ["\\d", u],
      [a, E]
    ], l = (d) => {
      for (const [f, N] of c)
        d = d.split(`${f}*`).join(`${f}{0,${N}}`).split(`${f}+`).join(`${f}{1,${N}}`);
      return d;
    }, s = (d, f, N) => {
      const D = l(f), L = i++;
      h(d, L, f), e[d] = L, t[L] = f, I[L] = D, p[L] = new RegExp(f, N ? "g" : void 0), R[L] = new RegExp(D, N ? "g" : void 0);
    };
    s("NUMERICIDENTIFIER", "0|[1-9]\\d*"), s("NUMERICIDENTIFIERLOOSE", "\\d+"), s("NONNUMERICIDENTIFIER", `\\d*[a-zA-Z-]${a}*`), s("MAINVERSION", `(${t[e.NUMERICIDENTIFIER]})\\.(${t[e.NUMERICIDENTIFIER]})\\.(${t[e.NUMERICIDENTIFIER]})`), s("MAINVERSIONLOOSE", `(${t[e.NUMERICIDENTIFIERLOOSE]})\\.(${t[e.NUMERICIDENTIFIERLOOSE]})\\.(${t[e.NUMERICIDENTIFIERLOOSE]})`), s("PRERELEASEIDENTIFIER", `(?:${t[e.NONNUMERICIDENTIFIER]}|${t[e.NUMERICIDENTIFIER]})`), s("PRERELEASEIDENTIFIERLOOSE", `(?:${t[e.NONNUMERICIDENTIFIER]}|${t[e.NUMERICIDENTIFIERLOOSE]})`), s("PRERELEASE", `(?:-(${t[e.PRERELEASEIDENTIFIER]}(?:\\.${t[e.PRERELEASEIDENTIFIER]})*))`), s("PRERELEASELOOSE", `(?:-?(${t[e.PRERELEASEIDENTIFIERLOOSE]}(?:\\.${t[e.PRERELEASEIDENTIFIERLOOSE]})*))`), s("BUILDIDENTIFIER", `${a}+`), s("BUILD", `(?:\\+(${t[e.BUILDIDENTIFIER]}(?:\\.${t[e.BUILDIDENTIFIER]})*))`), s("FULLPLAIN", `v?${t[e.MAINVERSION]}${t[e.PRERELEASE]}?${t[e.BUILD]}?`), s("FULL", `^${t[e.FULLPLAIN]}$`), s("LOOSEPLAIN", `[v=\\s]*${t[e.MAINVERSIONLOOSE]}${t[e.PRERELEASELOOSE]}?${t[e.BUILD]}?`), s("LOOSE", `^${t[e.LOOSEPLAIN]}$`), s("GTLT", "((?:<|>)?=?)"), s("XRANGEIDENTIFIERLOOSE", `${t[e.NUMERICIDENTIFIERLOOSE]}|x|X|\\*`), s("XRANGEIDENTIFIER", `${t[e.NUMERICIDENTIFIER]}|x|X|\\*`), s("XRANGEPLAIN", `[v=\\s]*(${t[e.XRANGEIDENTIFIER]})(?:\\.(${t[e.XRANGEIDENTIFIER]})(?:\\.(${t[e.XRANGEIDENTIFIER]})(?:${t[e.PRERELEASE]})?${t[e.BUILD]}?)?)?`), s("XRANGEPLAINLOOSE", `[v=\\s]*(${t[e.XRANGEIDENTIFIERLOOSE]})(?:\\.(${t[e.XRANGEIDENTIFIERLOOSE]})(?:\\.(${t[e.XRANGEIDENTIFIERLOOSE]})(?:${t[e.PRERELEASELOOSE]})?${t[e.BUILD]}?)?)?`), s("XRANGE", `^${t[e.GTLT]}\\s*${t[e.XRANGEPLAIN]}$`), s("XRANGELOOSE", `^${t[e.GTLT]}\\s*${t[e.XRANGEPLAINLOOSE]}$`), s("COERCEPLAIN", `(^|[^\\d])(\\d{1,${o}})(?:\\.(\\d{1,${o}}))?(?:\\.(\\d{1,${o}}))?`), s("COERCE", `${t[e.COERCEPLAIN]}(?:$|[^\\d])`), s("COERCEFULL", t[e.COERCEPLAIN] + `(?:${t[e.PRERELEASE]})?(?:${t[e.BUILD]})?(?:$|[^\\d])`), s("COERCERTL", t[e.COERCE], !0), s("COERCERTLFULL", t[e.COERCEFULL], !0), s("LONETILDE", "(?:~>?)"), s("TILDETRIM", `(\\s*)${t[e.LONETILDE]}\\s+`, !0), r.tildeTrimReplace = "$1~", s("TILDE", `^${t[e.LONETILDE]}${t[e.XRANGEPLAIN]}$`), s("TILDELOOSE", `^${t[e.LONETILDE]}${t[e.XRANGEPLAINLOOSE]}$`), s("LONECARET", "(?:\\^)"), s("CARETTRIM", `(\\s*)${t[e.LONECARET]}\\s+`, !0), r.caretTrimReplace = "$1^", s("CARET", `^${t[e.LONECARET]}${t[e.XRANGEPLAIN]}$`), s("CARETLOOSE", `^${t[e.LONECARET]}${t[e.XRANGEPLAINLOOSE]}$`), s("COMPARATORLOOSE", `^${t[e.GTLT]}\\s*(${t[e.LOOSEPLAIN]})$|^$`), s("COMPARATOR", `^${t[e.GTLT]}\\s*(${t[e.FULLPLAIN]})$|^$`), s("COMPARATORTRIM", `(\\s*)${t[e.GTLT]}\\s*(${t[e.LOOSEPLAIN]}|${t[e.XRANGEPLAIN]})`, !0), r.comparatorTrimReplace = "$1$2$3", s("HYPHENRANGE", `^\\s*(${t[e.XRANGEPLAIN]})\\s+-\\s+(${t[e.XRANGEPLAIN]})\\s*$`), s("HYPHENRANGELOOSE", `^\\s*(${t[e.XRANGEPLAINLOOSE]})\\s+-\\s+(${t[e.XRANGEPLAINLOOSE]})\\s*$`), s("STAR", "(<|>)?=?\\s*\\*"), s("GTE0", "^\\s*>=\\s*0\\.0\\.0\\s*$"), s("GTE0PRE", "^\\s*>=\\s*0\\.0\\.0-0\\s*$");
  })(T, T.exports)), T.exports;
}
var g, U;
function Z() {
  if (U) return g;
  U = 1;
  const n = Object.freeze({ loose: !0 }), r = Object.freeze({});
  return g = (E) => E ? typeof E != "object" ? n : E : r, g;
}
var b, y;
function J() {
  if (y) return b;
  y = 1;
  const n = /^[0-9]+$/, r = (E, u) => {
    if (typeof E == "number" && typeof u == "number")
      return E === u ? 0 : E < u ? -1 : 1;
    const h = n.test(E), p = n.test(u);
    return h && p && (E = +E, u = +u), E === u ? 0 : h && !p ? -1 : p && !h ? 1 : E < u ? -1 : 1;
  };
  return b = {
    compareIdentifiers: r,
    rcompareIdentifiers: (E, u) => r(u, E)
  }, b;
}
var S, M;
function K() {
  if (M) return S;
  M = 1;
  const n = H(), { MAX_LENGTH: r, MAX_SAFE_INTEGER: o } = z(), { safeRe: E, t: u } = Y(), h = Z(), { compareIdentifiers: p } = J(), R = (I, e) => {
    const i = e.split(".");
    if (i.length > I.length)
      return !1;
    for (let a = 0; a < i.length; a++)
      if (p(I[a], i[a]) !== 0)
        return !1;
    return !0;
  };
  class t {
    constructor(e, i) {
      if (i = h(i), e instanceof t) {
        if (e.loose === !!i.loose && e.includePrerelease === !!i.includePrerelease)
          return e;
        e = e.version;
      } else if (typeof e != "string")
        throw new TypeError(`Invalid version. Must be a string. Got type "${typeof e}".`);
      if (e.length > r)
        throw new TypeError(
          `version is longer than ${r} characters`
        );
      n("SemVer", e, i), this.options = i, this.loose = !!i.loose, this.includePrerelease = !!i.includePrerelease;
      const a = e.trim().match(i.loose ? E[u.LOOSE] : E[u.FULL]);
      if (!a)
        throw new TypeError(`Invalid Version: ${e}`);
      if (this.raw = e, this.major = +a[1], this.minor = +a[2], this.patch = +a[3], this.major > o || this.major < 0)
        throw new TypeError("Invalid major version");
      if (this.minor > o || this.minor < 0)
        throw new TypeError("Invalid minor version");
      if (this.patch > o || this.patch < 0)
        throw new TypeError("Invalid patch version");
      a[4] ? this.prerelease = a[4].split(".").map((c) => {
        if (/^[0-9]+$/.test(c)) {
          const l = +c;
          if (l >= 0 && l < o)
            return l;
        }
        return c;
      }) : this.prerelease = [], this.build = a[5] ? a[5].split(".") : [], this.format();
    }
    format() {
      return this.version = `${this.major}.${this.minor}.${this.patch}`, this.prerelease.length && (this.version += `-${this.prerelease.join(".")}`), this.version;
    }
    toString() {
      return this.version;
    }
    compare(e) {
      if (n("SemVer.compare", this.version, this.options, e), !(e instanceof t)) {
        if (typeof e == "string" && e === this.version)
          return 0;
        e = new t(e, this.options);
      }
      return e.version === this.version ? 0 : this.compareMain(e) || this.comparePre(e);
    }
    compareMain(e) {
      return e instanceof t || (e = new t(e, this.options)), this.major < e.major ? -1 : this.major > e.major ? 1 : this.minor < e.minor ? -1 : this.minor > e.minor ? 1 : this.patch < e.patch ? -1 : this.patch > e.patch ? 1 : 0;
    }
    comparePre(e) {
      if (e instanceof t || (e = new t(e, this.options)), this.prerelease.length && !e.prerelease.length)
        return -1;
      if (!this.prerelease.length && e.prerelease.length)
        return 1;
      if (!this.prerelease.length && !e.prerelease.length)
        return 0;
      let i = 0;
      do {
        const a = this.prerelease[i], c = e.prerelease[i];
        if (n("prerelease compare", i, a, c), a === void 0 && c === void 0)
          return 0;
        if (c === void 0)
          return 1;
        if (a === void 0)
          return -1;
        if (a === c)
          continue;
        return p(a, c);
      } while (++i);
    }
    compareBuild(e) {
      e instanceof t || (e = new t(e, this.options));
      let i = 0;
      do {
        const a = this.build[i], c = e.build[i];
        if (n("build compare", i, a, c), a === void 0 && c === void 0)
          return 0;
        if (c === void 0)
          return 1;
        if (a === void 0)
          return -1;
        if (a === c)
          continue;
        return p(a, c);
      } while (++i);
    }
    // preminor will bump the version up to the next minor release, and immediately
    // down to pre-release. premajor and prepatch work the same way.
    inc(e, i, a) {
      if (e.startsWith("pre")) {
        if (!i && a === !1)
          throw new Error("invalid increment argument: identifier is empty");
        if (i) {
          const c = `-${i}`.match(this.options.loose ? E[u.PRERELEASELOOSE] : E[u.PRERELEASE]);
          if (!c || c[1] !== i)
            throw new Error(`invalid identifier: ${i}`);
        }
      }
      switch (e) {
        case "premajor":
          this.prerelease.length = 0, this.patch = 0, this.minor = 0, this.major++, this.inc("pre", i, a);
          break;
        case "preminor":
          this.prerelease.length = 0, this.patch = 0, this.minor++, this.inc("pre", i, a);
          break;
        case "prepatch":
          this.prerelease.length = 0, this.inc("patch", i, a), this.inc("pre", i, a);
          break;
        // If the input is a non-prerelease version, this acts the same as
        // prepatch.
        case "prerelease":
          this.prerelease.length === 0 && this.inc("patch", i, a), this.inc("pre", i, a);
          break;
        case "release":
          if (this.prerelease.length === 0)
            throw new Error(`version ${this.raw} is not a prerelease`);
          this.prerelease.length = 0;
          break;
        case "major":
          (this.minor !== 0 || this.patch !== 0 || this.prerelease.length === 0) && this.major++, this.minor = 0, this.patch = 0, this.prerelease = [];
          break;
        case "minor":
          (this.patch !== 0 || this.prerelease.length === 0) && this.minor++, this.patch = 0, this.prerelease = [];
          break;
        case "patch":
          this.prerelease.length === 0 && this.patch++, this.prerelease = [];
          break;
        // This probably shouldn't be used publicly.
        // 1.0.0 'pre' would become 1.0.0-0 which is the wrong direction.
        case "pre": {
          const c = Number(a) ? 1 : 0;
          if (this.prerelease.length === 0)
            this.prerelease = [c];
          else {
            let l = this.prerelease.length;
            for (; --l >= 0; )
              typeof this.prerelease[l] == "number" && (this.prerelease[l]++, l = -2);
            if (l === -1) {
              if (i === this.prerelease.join(".") && a === !1)
                throw new Error("invalid increment argument: identifier already exists");
              this.prerelease.push(c);
            }
          }
          if (i) {
            let l = [i, c];
            if (a === !1 && (l = [i]), R(this.prerelease, i)) {
              const s = this.prerelease[i.split(".").length];
              isNaN(s) && (this.prerelease = l);
            } else
              this.prerelease = l;
          }
          break;
        }
        default:
          throw new Error(`invalid increment argument: ${e}`);
      }
      return this.raw = this.format(), this.build.length && (this.raw += `+${this.build.join(".")}`), this;
    }
  }
  return S = t, S;
}
var _, j;
function Q() {
  if (j) return _;
  j = 1;
  const n = K();
  return _ = (o, E) => new n(o, E).major, _;
}
var ee = Q();
const X = /* @__PURE__ */ V(ee);
var v, q;
function te() {
  if (q) return v;
  q = 1;
  const n = K();
  return v = (o, E, u = !1) => {
    if (o instanceof n)
      return o;
    try {
      return new n(o, E);
    } catch (h) {
      if (!u)
        return null;
      throw h;
    }
  }, v;
}
var P, k;
function re() {
  if (k) return P;
  k = 1;
  const n = te();
  return P = (o, E) => {
    const u = n(o, E);
    return u ? u.version : null;
  }, P;
}
var ne = re();
const se = /* @__PURE__ */ V(ne);
class ie {
  bus;
  constructor(r) {
    typeof r.getVersion != "function" || !se(r.getVersion()) ? console.warn("Proxying an event bus with an unknown or invalid version") : X(r.getVersion()) !== X(this.getVersion()) && console.warn(
      "Proxying an event bus of version " + r.getVersion() + " with " + this.getVersion()
    ), this.bus = r;
  }
  getVersion() {
    return "3.3.3";
  }
  subscribe(r, o) {
    this.bus.subscribe(r, o);
  }
  unsubscribe(r, o) {
    this.bus.unsubscribe(r, o);
  }
  emit(r, ...o) {
    this.bus.emit(r, ...o);
  }
}
class oe {
  handlers = /* @__PURE__ */ new Map();
  getVersion() {
    return "3.3.3";
  }
  subscribe(r, o) {
    this.handlers.set(
      r,
      (this.handlers.get(r) || []).concat(
        o
      )
    );
  }
  unsubscribe(r, o) {
    this.handlers.set(
      r,
      (this.handlers.get(r) || []).filter((E) => E !== o)
    );
  }
  emit(r, ...o) {
    (this.handlers.get(r) || []).forEach((u) => {
      try {
        u(o[0]);
      } catch (h) {
        console.error("could not invoke event listener", h);
      }
    });
  }
}
let m = null;
function W() {
  return m !== null ? m : typeof window > "u" ? new Proxy({}, {
    get: () => () => console.error(
      "Window not available, EventBus can not be established!"
    )
  }) : (window.OC?._eventBus && typeof window._nc_event_bus > "u" && (console.warn(
    "found old event bus instance at OC._eventBus. Update your version!"
  ), window._nc_event_bus = window.OC._eventBus), typeof window?._nc_event_bus < "u" ? m = new ie(window._nc_event_bus) : m = window._nc_event_bus = new oe(), m);
}
function ae(n, r) {
  W().subscribe(n, r);
}
function Ee(n, ...r) {
  W().emit(n, ...r);
}
function B(n, r, o) {
  const E = { escape: !0 }, u = function(h, p) {
    return p = p || {}, h.replace(/{([^{}]*)}/g, function(R, t) {
      const I = p[t];
      return E.escape ? encodeURIComponent(typeof I == "string" || typeof I == "number" ? I.toString() : R) : typeof I == "string" || typeof I == "number" ? I.toString() : R;
    });
  };
  return n.charAt(0) !== "/" && (n = "/" + n), u(n, {});
}
function Re(n, r, o) {
  const E = { noRewrite: !1 };
  le(E);
  const u = ue();
  return !E.noRewrite && typeof window < "u" && window.OC?.config?.modRewriteWorking === !0 ? u + B(n) : u + "/index.php" + B(n);
}
function ue() {
  ce();
  let n = window._oc_webroot;
  if (typeof n > "u") {
    n = location.pathname;
    const r = n.indexOf("/index.php/");
    if (r !== -1)
      n = n.slice(0, r);
    else {
      const o = n.indexOf("/", 1);
      n = n.slice(0, o > 0 ? o : void 0);
    }
  }
  return n;
}
function ce() {
  if (typeof window > "u")
    throw new Error("This function is only available in a DOM environment");
}
function le(n) {
  if (typeof window > "u" && !n?.baseURL)
    throw new Error("This function requires baseURL option to be provided in non-DOM environments");
}
class $ {
  static GLOBAL_SCOPE_VOLATILE = "nextcloud_vol";
  static GLOBAL_SCOPE_PERSISTENT = "nextcloud_per";
  scope;
  wrapped;
  constructor(r, o, E) {
    this.scope = `${E ? $.GLOBAL_SCOPE_PERSISTENT : $.GLOBAL_SCOPE_VOLATILE}_${btoa(r)}_`, this.wrapped = o;
  }
  scopeKey(r) {
    return `${this.scope}${r}`;
  }
  setItem(r, o) {
    this.wrapped.setItem(this.scopeKey(r), o);
  }
  getItem(r) {
    return this.wrapped.getItem(this.scopeKey(r));
  }
  removeItem(r) {
    this.wrapped.removeItem(this.scopeKey(r));
  }
  clear() {
    Object.keys(this.wrapped).filter((r) => r.startsWith(this.scope)).map(this.wrapped.removeItem.bind(this.wrapped));
  }
}
class he {
  appId;
  persisted = !1;
  clearedOnLogout = !1;
  constructor(r) {
    this.appId = r;
  }
  persist(r = !0) {
    return this.persisted = r, this;
  }
  clearOnLogout(r = !0) {
    return this.clearedOnLogout = r, this;
  }
  build() {
    return new $(this.appId, this.persisted ? window.localStorage : window.sessionStorage, !this.clearedOnLogout);
  }
}
function pe(n) {
  return new he(n);
}
fe();
function de() {
  return globalThis._nc_auth_requestToken ? globalThis._nc_auth_requestToken : globalThis.document ? document.head.dataset.requesttoken ?? null : null;
}
function Ie(n) {
  if (!n || typeof n != "string")
    throw new Error("Invalid CSRF token given", { cause: { token: n } });
  globalThis._nc_auth_requestToken !== n && (globalThis._nc_auth_requestToken = n, globalThis.document && (document.head.dataset.requesttoken = n), Ee("csrf-token-update", { token: n, _internal: !0 }));
}
function fe() {
  ae("csrf-token-update", ({ token: n, _internal: r }) => {
    r || Ie(n);
  });
}
pe("public").persist().build();
let O;
function x(n, r) {
  return n ? n.getAttribute(r) : null;
}
function Le() {
  if (O !== void 0)
    return O;
  const n = document?.getElementsByTagName("head")[0];
  if (!n)
    return null;
  const r = x(n, "data-user");
  return r === null ? (O = null, O) : (O = {
    uid: r,
    displayName: x(n, "data-user-displayname"),
    isAdmin: !!window._oc_isadmin
  }, O);
}
export {
  de as a,
  Le as b,
  Re as g
};
