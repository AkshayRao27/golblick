var Dr = "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z", Hn = "M22 8.1C21.7 8 21.3 7.8 21 7.7C19.4 4.3 16 2 12 2S4.6 4.3 3 7.7C2.7 7.8 2.3 8 2.1 8.1C1.4 8.5 1 9.2 1 9.9V14.1C1 14.8 1.4 15.5 2 15.9C2.3 16 2.7 16.2 3 16.3C4.6 19.7 8 22 12 22S19.4 19.7 21 16.3C21.3 16.2 21.6 16 21.9 15.8C22.5 15.4 23 14.8 23 14V9.9C23 9.2 22.6 8.5 22 8.1M21 9.9V14.1C18.8 15.3 15.5 16 12 16S5.2 15.3 3 14.1V9.9C5.2 8.7 8.5 8 12 8S18.8 8.7 21 9.9M12 4C14.4 4 16.5 5 18 6.7C16.2 6.2 14.1 6 12 6S7.8 6.2 6.1 6.7C7.5 5 9.6 4 12 4M12 20C9.6 20 7.5 19 6.1 17.3C7.8 17.8 9.9 18 12 18S16.2 17.8 18 17.3C16.5 19 14.4 20 12 20Z";
function Bn(t) {
  return t && t.__esModule && Object.prototype.hasOwnProperty.call(t, "default") ? t.default : t;
}
var mt, dn;
function Wn() {
  return dn || (dn = 1, mt = typeof process == "object" && process.env && process.env.NODE_DEBUG && /\bsemver\b/i.test(process.env.NODE_DEBUG) ? (...n) => console.error("SEMVER", ...n) : () => {
  }), mt;
}
var ht, mn;
function Xn() {
  if (mn) return ht;
  mn = 1;
  const t = "2.0.0", n = 256, o = Number.MAX_SAFE_INTEGER || /* istanbul ignore next */
  9007199254740991, s = 16, c = n - 6;
  return ht = {
    MAX_LENGTH: n,
    MAX_SAFE_COMPONENT_LENGTH: s,
    MAX_SAFE_BUILD_LENGTH: c,
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
    SEMVER_SPEC_VERSION: t,
    FLAG_INCLUDE_PRERELEASE: 1,
    FLAG_LOOSE: 2
  }, ht;
}
var Xe = { exports: {} }, hn;
function Cr() {
  return hn || (hn = 1, (function(t, n) {
    const {
      MAX_SAFE_COMPONENT_LENGTH: o,
      MAX_SAFE_BUILD_LENGTH: s,
      MAX_LENGTH: c
    } = Xn(), m = Wn();
    n = t.exports = {};
    const g = n.re = [], N = n.safeRe = [], l = n.src = [], L = n.safeSrc = [], i = n.t = {};
    let p = 0;
    const E = "[a-zA-Z0-9-]", b = [
      ["\\s", 1],
      ["\\d", c],
      [E, s]
    ], y = (G) => {
      for (const [P, Y] of b)
        G = G.split(`${P}*`).join(`${P}{0,${Y}}`).split(`${P}+`).join(`${P}{1,${Y}}`);
      return G;
    }, h = (G, P, Y) => {
      const se = y(P), k = p++;
      m(G, k, P), i[G] = k, l[k] = P, L[k] = se, g[k] = new RegExp(P, Y ? "g" : void 0), N[k] = new RegExp(se, Y ? "g" : void 0);
    };
    h("NUMERICIDENTIFIER", "0|[1-9]\\d*"), h("NUMERICIDENTIFIERLOOSE", "\\d+"), h("NONNUMERICIDENTIFIER", `\\d*[a-zA-Z-]${E}*`), h("MAINVERSION", `(${l[i.NUMERICIDENTIFIER]})\\.(${l[i.NUMERICIDENTIFIER]})\\.(${l[i.NUMERICIDENTIFIER]})`), h("MAINVERSIONLOOSE", `(${l[i.NUMERICIDENTIFIERLOOSE]})\\.(${l[i.NUMERICIDENTIFIERLOOSE]})\\.(${l[i.NUMERICIDENTIFIERLOOSE]})`), h("PRERELEASEIDENTIFIER", `(?:${l[i.NONNUMERICIDENTIFIER]}|${l[i.NUMERICIDENTIFIER]})`), h("PRERELEASEIDENTIFIERLOOSE", `(?:${l[i.NONNUMERICIDENTIFIER]}|${l[i.NUMERICIDENTIFIERLOOSE]})`), h("PRERELEASE", `(?:-(${l[i.PRERELEASEIDENTIFIER]}(?:\\.${l[i.PRERELEASEIDENTIFIER]})*))`), h("PRERELEASELOOSE", `(?:-?(${l[i.PRERELEASEIDENTIFIERLOOSE]}(?:\\.${l[i.PRERELEASEIDENTIFIERLOOSE]})*))`), h("BUILDIDENTIFIER", `${E}+`), h("BUILD", `(?:\\+(${l[i.BUILDIDENTIFIER]}(?:\\.${l[i.BUILDIDENTIFIER]})*))`), h("FULLPLAIN", `v?${l[i.MAINVERSION]}${l[i.PRERELEASE]}?${l[i.BUILD]}?`), h("FULL", `^${l[i.FULLPLAIN]}$`), h("LOOSEPLAIN", `[v=\\s]*${l[i.MAINVERSIONLOOSE]}${l[i.PRERELEASELOOSE]}?${l[i.BUILD]}?`), h("LOOSE", `^${l[i.LOOSEPLAIN]}$`), h("GTLT", "((?:<|>)?=?)"), h("XRANGEIDENTIFIERLOOSE", `${l[i.NUMERICIDENTIFIERLOOSE]}|x|X|\\*`), h("XRANGEIDENTIFIER", `${l[i.NUMERICIDENTIFIER]}|x|X|\\*`), h("XRANGEPLAIN", `[v=\\s]*(${l[i.XRANGEIDENTIFIER]})(?:\\.(${l[i.XRANGEIDENTIFIER]})(?:\\.(${l[i.XRANGEIDENTIFIER]})(?:${l[i.PRERELEASE]})?${l[i.BUILD]}?)?)?`), h("XRANGEPLAINLOOSE", `[v=\\s]*(${l[i.XRANGEIDENTIFIERLOOSE]})(?:\\.(${l[i.XRANGEIDENTIFIERLOOSE]})(?:\\.(${l[i.XRANGEIDENTIFIERLOOSE]})(?:${l[i.PRERELEASELOOSE]})?${l[i.BUILD]}?)?)?`), h("XRANGE", `^${l[i.GTLT]}\\s*${l[i.XRANGEPLAIN]}$`), h("XRANGELOOSE", `^${l[i.GTLT]}\\s*${l[i.XRANGEPLAINLOOSE]}$`), h("COERCEPLAIN", `(^|[^\\d])(\\d{1,${o}})(?:\\.(\\d{1,${o}}))?(?:\\.(\\d{1,${o}}))?`), h("COERCE", `${l[i.COERCEPLAIN]}(?:$|[^\\d])`), h("COERCEFULL", l[i.COERCEPLAIN] + `(?:${l[i.PRERELEASE]})?(?:${l[i.BUILD]})?(?:$|[^\\d])`), h("COERCERTL", l[i.COERCE], !0), h("COERCERTLFULL", l[i.COERCEFULL], !0), h("LONETILDE", "(?:~>?)"), h("TILDETRIM", `(\\s*)${l[i.LONETILDE]}\\s+`, !0), n.tildeTrimReplace = "$1~", h("TILDE", `^${l[i.LONETILDE]}${l[i.XRANGEPLAIN]}$`), h("TILDELOOSE", `^${l[i.LONETILDE]}${l[i.XRANGEPLAINLOOSE]}$`), h("LONECARET", "(?:\\^)"), h("CARETTRIM", `(\\s*)${l[i.LONECARET]}\\s+`, !0), n.caretTrimReplace = "$1^", h("CARET", `^${l[i.LONECARET]}${l[i.XRANGEPLAIN]}$`), h("CARETLOOSE", `^${l[i.LONECARET]}${l[i.XRANGEPLAINLOOSE]}$`), h("COMPARATORLOOSE", `^${l[i.GTLT]}\\s*(${l[i.LOOSEPLAIN]})$|^$`), h("COMPARATOR", `^${l[i.GTLT]}\\s*(${l[i.FULLPLAIN]})$|^$`), h("COMPARATORTRIM", `(\\s*)${l[i.GTLT]}\\s*(${l[i.LOOSEPLAIN]}|${l[i.XRANGEPLAIN]})`, !0), n.comparatorTrimReplace = "$1$2$3", h("HYPHENRANGE", `^\\s*(${l[i.XRANGEPLAIN]})\\s+-\\s+(${l[i.XRANGEPLAIN]})\\s*$`), h("HYPHENRANGELOOSE", `^\\s*(${l[i.XRANGEPLAINLOOSE]})\\s+-\\s+(${l[i.XRANGEPLAINLOOSE]})\\s*$`), h("STAR", "(<|>)?=?\\s*\\*"), h("GTE0", "^\\s*>=\\s*0\\.0\\.0\\s*$"), h("GTE0PRE", "^\\s*>=\\s*0\\.0\\.0-0\\s*$");
  })(Xe, Xe.exports)), Xe.exports;
}
var Et, En;
function Mr() {
  if (En) return Et;
  En = 1;
  const t = Object.freeze({ loose: !0 }), n = Object.freeze({});
  return Et = (s) => s ? typeof s != "object" ? t : s : n, Et;
}
var gt, gn;
function Pr() {
  if (gn) return gt;
  gn = 1;
  const t = /^[0-9]+$/, n = (s, c) => {
    if (typeof s == "number" && typeof c == "number")
      return s === c ? 0 : s < c ? -1 : 1;
    const m = t.test(s), g = t.test(c);
    return m && g && (s = +s, c = +c), s === c ? 0 : m && !g ? -1 : g && !m ? 1 : s < c ? -1 : 1;
  };
  return gt = {
    compareIdentifiers: n,
    rcompareIdentifiers: (s, c) => n(c, s)
  }, gt;
}
var Tt, Tn;
function qn() {
  if (Tn) return Tt;
  Tn = 1;
  const t = Wn(), { MAX_LENGTH: n, MAX_SAFE_INTEGER: o } = Xn(), { safeRe: s, t: c } = Cr(), m = Mr(), { compareIdentifiers: g } = Pr(), N = (L, i) => {
    const p = i.split(".");
    if (p.length > L.length)
      return !1;
    for (let E = 0; E < p.length; E++)
      if (g(L[E], p[E]) !== 0)
        return !1;
    return !0;
  };
  class l {
    constructor(i, p) {
      if (p = m(p), i instanceof l) {
        if (i.loose === !!p.loose && i.includePrerelease === !!p.includePrerelease)
          return i;
        i = i.version;
      } else if (typeof i != "string")
        throw new TypeError(`Invalid version. Must be a string. Got type "${typeof i}".`);
      if (i.length > n)
        throw new TypeError(
          `version is longer than ${n} characters`
        );
      t("SemVer", i, p), this.options = p, this.loose = !!p.loose, this.includePrerelease = !!p.includePrerelease;
      const E = i.trim().match(p.loose ? s[c.LOOSE] : s[c.FULL]);
      if (!E)
        throw new TypeError(`Invalid Version: ${i}`);
      if (this.raw = i, this.major = +E[1], this.minor = +E[2], this.patch = +E[3], this.major > o || this.major < 0)
        throw new TypeError("Invalid major version");
      if (this.minor > o || this.minor < 0)
        throw new TypeError("Invalid minor version");
      if (this.patch > o || this.patch < 0)
        throw new TypeError("Invalid patch version");
      E[4] ? this.prerelease = E[4].split(".").map((b) => {
        if (/^[0-9]+$/.test(b)) {
          const y = +b;
          if (y >= 0 && y < o)
            return y;
        }
        return b;
      }) : this.prerelease = [], this.build = E[5] ? E[5].split(".") : [], this.format();
    }
    format() {
      return this.version = `${this.major}.${this.minor}.${this.patch}`, this.prerelease.length && (this.version += `-${this.prerelease.join(".")}`), this.version;
    }
    toString() {
      return this.version;
    }
    compare(i) {
      if (t("SemVer.compare", this.version, this.options, i), !(i instanceof l)) {
        if (typeof i == "string" && i === this.version)
          return 0;
        i = new l(i, this.options);
      }
      return i.version === this.version ? 0 : this.compareMain(i) || this.comparePre(i);
    }
    compareMain(i) {
      return i instanceof l || (i = new l(i, this.options)), this.major < i.major ? -1 : this.major > i.major ? 1 : this.minor < i.minor ? -1 : this.minor > i.minor ? 1 : this.patch < i.patch ? -1 : this.patch > i.patch ? 1 : 0;
    }
    comparePre(i) {
      if (i instanceof l || (i = new l(i, this.options)), this.prerelease.length && !i.prerelease.length)
        return -1;
      if (!this.prerelease.length && i.prerelease.length)
        return 1;
      if (!this.prerelease.length && !i.prerelease.length)
        return 0;
      let p = 0;
      do {
        const E = this.prerelease[p], b = i.prerelease[p];
        if (t("prerelease compare", p, E, b), E === void 0 && b === void 0)
          return 0;
        if (b === void 0)
          return 1;
        if (E === void 0)
          return -1;
        if (E === b)
          continue;
        return g(E, b);
      } while (++p);
    }
    compareBuild(i) {
      i instanceof l || (i = new l(i, this.options));
      let p = 0;
      do {
        const E = this.build[p], b = i.build[p];
        if (t("build compare", p, E, b), E === void 0 && b === void 0)
          return 0;
        if (b === void 0)
          return 1;
        if (E === void 0)
          return -1;
        if (E === b)
          continue;
        return g(E, b);
      } while (++p);
    }
    // preminor will bump the version up to the next minor release, and immediately
    // down to pre-release. premajor and prepatch work the same way.
    inc(i, p, E) {
      if (i.startsWith("pre")) {
        if (!p && E === !1)
          throw new Error("invalid increment argument: identifier is empty");
        if (p) {
          const b = `-${p}`.match(this.options.loose ? s[c.PRERELEASELOOSE] : s[c.PRERELEASE]);
          if (!b || b[1] !== p)
            throw new Error(`invalid identifier: ${p}`);
        }
      }
      switch (i) {
        case "premajor":
          this.prerelease.length = 0, this.patch = 0, this.minor = 0, this.major++, this.inc("pre", p, E);
          break;
        case "preminor":
          this.prerelease.length = 0, this.patch = 0, this.minor++, this.inc("pre", p, E);
          break;
        case "prepatch":
          this.prerelease.length = 0, this.inc("patch", p, E), this.inc("pre", p, E);
          break;
        // If the input is a non-prerelease version, this acts the same as
        // prepatch.
        case "prerelease":
          this.prerelease.length === 0 && this.inc("patch", p, E), this.inc("pre", p, E);
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
          const b = Number(E) ? 1 : 0;
          if (this.prerelease.length === 0)
            this.prerelease = [b];
          else {
            let y = this.prerelease.length;
            for (; --y >= 0; )
              typeof this.prerelease[y] == "number" && (this.prerelease[y]++, y = -2);
            if (y === -1) {
              if (p === this.prerelease.join(".") && E === !1)
                throw new Error("invalid increment argument: identifier already exists");
              this.prerelease.push(b);
            }
          }
          if (p) {
            let y = [p, b];
            if (E === !1 && (y = [p]), N(this.prerelease, p)) {
              const h = this.prerelease[p.split(".").length];
              isNaN(h) && (this.prerelease = y);
            } else
              this.prerelease = y;
          }
          break;
        }
        default:
          throw new Error(`invalid increment argument: ${i}`);
      }
      return this.raw = this.format(), this.build.length && (this.raw += `+${this.build.join(".")}`), this;
    }
  }
  return Tt = l, Tt;
}
var _t, _n;
function xr() {
  if (_n) return _t;
  _n = 1;
  const t = qn();
  return _t = (o, s) => new t(o, s).major, _t;
}
var $r = xr();
const An = /* @__PURE__ */ Bn($r);
var At, bn;
function kr() {
  if (bn) return At;
  bn = 1;
  const t = qn();
  return At = (o, s, c = !1) => {
    if (o instanceof t)
      return o;
    try {
      return new t(o, s);
    } catch (m) {
      if (!c)
        return null;
      throw m;
    }
  }, At;
}
var bt, yn;
function Ur() {
  if (yn) return bt;
  yn = 1;
  const t = kr();
  return bt = (o, s) => {
    const c = t(o, s);
    return c ? c.version : null;
  }, bt;
}
var Fr = Ur();
const Gr = /* @__PURE__ */ Bn(Fr);
class zr {
  bus;
  constructor(n) {
    typeof n.getVersion != "function" || !Gr(n.getVersion()) ? console.warn("Proxying an event bus with an unknown or invalid version") : An(n.getVersion()) !== An(this.getVersion()) && console.warn(
      "Proxying an event bus of version " + n.getVersion() + " with " + this.getVersion()
    ), this.bus = n;
  }
  getVersion() {
    return "3.3.3";
  }
  subscribe(n, o) {
    this.bus.subscribe(n, o);
  }
  unsubscribe(n, o) {
    this.bus.unsubscribe(n, o);
  }
  emit(n, ...o) {
    this.bus.emit(n, ...o);
  }
}
class jr {
  handlers = /* @__PURE__ */ new Map();
  getVersion() {
    return "3.3.3";
  }
  subscribe(n, o) {
    this.handlers.set(
      n,
      (this.handlers.get(n) || []).concat(
        o
      )
    );
  }
  unsubscribe(n, o) {
    this.handlers.set(
      n,
      (this.handlers.get(n) || []).filter((s) => s !== o)
    );
  }
  emit(n, ...o) {
    (this.handlers.get(n) || []).forEach((c) => {
      try {
        c(o[0]);
      } catch (m) {
        console.error("could not invoke event listener", m);
      }
    });
  }
}
let we = null;
function Vn() {
  return we !== null ? we : typeof window > "u" ? new Proxy({}, {
    get: () => () => console.error(
      "Window not available, EventBus can not be established!"
    )
  }) : (window.OC?._eventBus && typeof window._nc_event_bus > "u" && (console.warn(
    "found old event bus instance at OC._eventBus. Update your version!"
  ), window._nc_event_bus = window.OC._eventBus), typeof window?._nc_event_bus < "u" ? we = new zr(window._nc_event_bus) : we = window._nc_event_bus = new jr(), we);
}
function Hr(t, n) {
  Vn().subscribe(t, n);
}
function Br(t, ...n) {
  Vn().emit(t, ...n);
}
function In(t, n, o) {
  const s = { escape: !0 }, c = function(m, g) {
    return g = g || {}, m.replace(/{([^{}]*)}/g, function(N, l) {
      const L = g[l];
      return s.escape ? encodeURIComponent(typeof L == "string" || typeof L == "number" ? L.toString() : N) : typeof L == "string" || typeof L == "number" ? L.toString() : N;
    });
  };
  return t.charAt(0) !== "/" && (t = "/" + t), c(t, {});
}
function Nt(t, n, o) {
  const s = { noRewrite: !1 };
  qr(s);
  const c = Wr();
  return !s.noRewrite && typeof window < "u" && window.OC?.config?.modRewriteWorking === !0 ? c + In(t) : c + "/index.php" + In(t);
}
function Wr() {
  Xr();
  let t = window._oc_webroot;
  if (typeof t > "u") {
    t = location.pathname;
    const n = t.indexOf("/index.php/");
    if (n !== -1)
      t = t.slice(0, n);
    else {
      const o = t.indexOf("/", 1);
      t = t.slice(0, o > 0 ? o : void 0);
    }
  }
  return t;
}
function Xr() {
  if (typeof window > "u")
    throw new Error("This function is only available in a DOM environment");
}
function qr(t) {
  if (typeof window > "u" && !t?.baseURL)
    throw new Error("This function requires baseURL option to be provided in non-DOM environments");
}
class Ye {
  static GLOBAL_SCOPE_VOLATILE = "nextcloud_vol";
  static GLOBAL_SCOPE_PERSISTENT = "nextcloud_per";
  scope;
  wrapped;
  constructor(n, o, s) {
    this.scope = `${s ? Ye.GLOBAL_SCOPE_PERSISTENT : Ye.GLOBAL_SCOPE_VOLATILE}_${btoa(n)}_`, this.wrapped = o;
  }
  scopeKey(n) {
    return `${this.scope}${n}`;
  }
  setItem(n, o) {
    this.wrapped.setItem(this.scopeKey(n), o);
  }
  getItem(n) {
    return this.wrapped.getItem(this.scopeKey(n));
  }
  removeItem(n) {
    this.wrapped.removeItem(this.scopeKey(n));
  }
  clear() {
    Object.keys(this.wrapped).filter((n) => n.startsWith(this.scope)).map(this.wrapped.removeItem.bind(this.wrapped));
  }
}
class Vr {
  appId;
  persisted = !1;
  clearedOnLogout = !1;
  constructor(n) {
    this.appId = n;
  }
  persist(n = !0) {
    return this.persisted = n, this;
  }
  clearOnLogout(n = !0) {
    return this.clearedOnLogout = n, this;
  }
  build() {
    return new Ye(this.appId, this.persisted ? window.localStorage : window.sessionStorage, !this.clearedOnLogout);
  }
}
function Yr(t) {
  return new Vr(t);
}
Zr();
function Kr(t) {
  if (!t || typeof t != "string")
    throw new Error("Invalid CSRF token given", { cause: { token: t } });
  globalThis._nc_auth_requestToken !== t && (globalThis._nc_auth_requestToken = t, globalThis.document && (document.head.dataset.requesttoken = t), Br("csrf-token-update", { token: t, _internal: !0 }));
}
function Zr() {
  Hr("csrf-token-update", ({ token: t, _internal: n }) => {
    n || Kr(t);
  });
}
Yr("public").persist().build();
let ge;
function Rn(t, n) {
  return t ? t.getAttribute(n) : null;
}
function Jr() {
  if (ge !== void 0)
    return ge;
  const t = document?.getElementsByTagName("head")[0];
  if (!t)
    return null;
  const n = Rn(t, "data-user");
  return n === null ? (ge = null, ge) : (ge = {
    uid: n,
    displayName: Rn(t, "data-user-displayname"),
    isAdmin: !!window._oc_isadmin
  }, ge);
}
var v = /* @__PURE__ */ ((t) => (t[t.Debug = 0] = "Debug", t[t.Info = 1] = "Info", t[t.Warn = 2] = "Warn", t[t.Error = 3] = "Error", t[t.Fatal = 4] = "Fatal", t))(v || {});
class Qr {
  context;
  constructor(n) {
    this.context = n || {};
  }
  formatMessage(n, o, s) {
    let c = "[" + v[o].toUpperCase() + "] ";
    return s && s.app && (c += s.app + ": "), typeof n == "string" ? c + n : (c += `Unexpected ${n.name}`, n.message && (c += ` "${n.message}"`), o === v.Debug && n.stack && (c += `

Stack trace:
${n.stack}`), c);
  }
  log(n, o, s) {
    if (!(typeof this.context?.level == "number" && n < this.context?.level))
      switch (typeof o == "object" && s?.error === void 0 && (s.error = o), n) {
        case v.Debug:
          console.debug(this.formatMessage(o, v.Debug, s), s);
          break;
        case v.Info:
          console.info(this.formatMessage(o, v.Info, s), s);
          break;
        case v.Warn:
          console.warn(this.formatMessage(o, v.Warn, s), s);
          break;
        case v.Error:
          console.error(this.formatMessage(o, v.Error, s), s);
          break;
        case v.Fatal:
        default:
          console.error(this.formatMessage(o, v.Fatal, s), s);
          break;
      }
  }
  debug(n, o) {
    this.log(v.Debug, n, Object.assign({}, this.context, o));
  }
  info(n, o) {
    this.log(v.Info, n, Object.assign({}, this.context, o));
  }
  warn(n, o) {
    this.log(v.Warn, n, Object.assign({}, this.context, o));
  }
  error(n, o) {
    this.log(v.Error, n, Object.assign({}, this.context, o));
  }
  fatal(n, o) {
    this.log(v.Fatal, n, Object.assign({}, this.context, o));
  }
}
function eo(t) {
  return new Qr(t);
}
class to {
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
    const n = Jr();
    return n !== null && (this.context.uid = n.uid), this;
  }
  /**
   * Detect and use logging level configured in nextcloud config
   */
  detectLogLevel() {
    const n = this, o = () => {
      document.readyState === "complete" || document.readyState === "interactive" ? (n.context.level = window._oc_config?.loglevel ?? v.Warn, window._oc_debug && (n.context.level = v.Debug), document.removeEventListener("readystatechange", o)) : document.addEventListener("readystatechange", o);
    };
    return o(), this;
  }
  /** Build a logger using the logging context and factory */
  build() {
    return this.context.level === void 0 && this.detectLogLevel(), this.factory(this.context);
  }
}
function no() {
  return new to(eo);
}
window._nc_files_scope ??= {};
window._nc_files_scope.v4_0 ??= {};
const De = window._nc_files_scope.v4_0, ro = no().setApp("@nextcloud/files").detectUser().build();
var oo = class extends EventTarget {
  dispatchTypedEvent(t, n) {
    return super.dispatchEvent(n);
  }
};
function Sn(t, n) {
  (n == null || n > t.length) && (n = t.length);
  for (var o = 0, s = Array(n); o < n; o++) s[o] = t[o];
  return s;
}
function io(t) {
  if (Array.isArray(t)) return t;
}
function so(t, n) {
  var o = t == null ? null : typeof Symbol < "u" && t[Symbol.iterator] || t["@@iterator"];
  if (o != null) {
    var s, c, m, g, N = [], l = !0, L = !1;
    try {
      if (m = (o = o.call(t)).next, n !== 0) for (; !(l = (s = m.call(o)).done) && (N.push(s.value), N.length !== n); l = !0) ;
    } catch (i) {
      L = !0, c = i;
    } finally {
      try {
        if (!l && o.return != null && (g = o.return(), Object(g) !== g)) return;
      } finally {
        if (L) throw c;
      }
    }
    return N;
  }
}
function ao() {
  throw new TypeError(`Invalid attempt to destructure non-iterable instance.
In order to be iterable, non-array objects must have a [Symbol.iterator]() method.`);
}
function lo(t, n) {
  return io(t) || so(t, n) || co(t, n) || ao();
}
function co(t, n) {
  if (t) {
    if (typeof t == "string") return Sn(t, n);
    var o = {}.toString.call(t).slice(8, -1);
    return o === "Object" && t.constructor && (o = t.constructor.name), o === "Map" || o === "Set" ? Array.from(t) : o === "Arguments" || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(o) ? Sn(t, n) : void 0;
  }
}
const Yn = Object.entries, wn = Object.setPrototypeOf, uo = Object.isFrozen, fo = Object.getPrototypeOf, po = Object.getOwnPropertyDescriptor;
let C = Object.freeze, M = Object.seal, Te = Object.create, Kn = typeof Reflect < "u" && Reflect, vt = Kn.apply, Dt = Kn.construct;
C || (C = function(n) {
  return n;
});
M || (M = function(n) {
  return n;
});
vt || (vt = function(n, o) {
  for (var s = arguments.length, c = new Array(s > 2 ? s - 2 : 0), m = 2; m < s; m++) c[m - 2] = arguments[m];
  return n.apply(o, c);
});
Dt || (Dt = function(n) {
  for (var o = arguments.length, s = new Array(o > 1 ? o - 1 : 0), c = 1; c < o; c++) s[c - 1] = arguments[c];
  return new n(...s);
});
const ie = D(Array.prototype.forEach), mo = D(Array.prototype.lastIndexOf), Ln = D(Array.prototype.pop), Le = D(Array.prototype.push), ho = D(Array.prototype.splice), _e = Array.isArray, ve = D(String.prototype.toLowerCase), yt = D(String.prototype.toString), On = D(String.prototype.match), Oe = D(String.prototype.replace), Nn = D(String.prototype.indexOf), Eo = D(String.prototype.trim), go = D(Number.prototype.toString), To = D(Boolean.prototype.toString), vn = typeof BigInt > "u" ? null : D(BigInt.prototype.toString), Dn = typeof Symbol > "u" ? null : D(Symbol.prototype.toString), F = D(Object.prototype.hasOwnProperty), Ne = D(Object.prototype.toString), x = D(RegExp.prototype.test), Q = _o(TypeError);
function D(t) {
  return function(n) {
    n instanceof RegExp && (n.lastIndex = 0);
    for (var o = arguments.length, s = new Array(o > 1 ? o - 1 : 0), c = 1; c < o; c++) s[c - 1] = arguments[c];
    return vt(t, n, s);
  };
}
function _o(t) {
  return function() {
    for (var n = arguments.length, o = new Array(n), s = 0; s < n; s++) o[s] = arguments[s];
    return Dt(t, o);
  };
}
function A(t, n) {
  let o = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : ve;
  if (wn && wn(t, null), !_e(n)) return t;
  let s = n.length;
  for (; s--; ) {
    let c = n[s];
    if (typeof c == "string") {
      const m = o(c);
      m !== c && (uo(n) || (n[s] = m), c = m);
    }
    t[c] = !0;
  }
  return t;
}
function Ao(t) {
  for (let n = 0; n < t.length; n++) F(t, n) || (t[n] = null);
  return t;
}
function H(t) {
  const n = Te(null);
  for (const s of Yn(t)) {
    var o = lo(s, 2);
    const c = o[0], m = o[1];
    F(t, c) && (_e(m) ? n[c] = Ao(m) : m && typeof m == "object" && m.constructor === Object ? n[c] = H(m) : n[c] = m);
  }
  return n;
}
function bo(t) {
  switch (typeof t) {
    case "string":
      return t;
    case "number":
      return go(t);
    case "boolean":
      return To(t);
    case "bigint":
      return vn ? vn(t) : "0";
    case "symbol":
      return Dn ? Dn(t) : "Symbol()";
    case "undefined":
      return Ne(t);
    case "function":
    case "object": {
      if (t === null) return Ne(t);
      const n = t, o = W(n, "toString");
      if (typeof o == "function") {
        const s = o(n);
        return typeof s == "string" ? s : Ne(s);
      }
      return Ne(t);
    }
    default:
      return Ne(t);
  }
}
function W(t, n) {
  for (; t !== null; ) {
    const s = po(t, n);
    if (s) {
      if (s.get) return D(s.get);
      if (typeof s.value == "function") return D(s.value);
    }
    t = fo(t);
  }
  function o() {
    return null;
  }
  return o;
}
function yo(t) {
  try {
    return x(t, ""), !0;
  } catch {
    return !1;
  }
}
const Cn = C([
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
]), It = C([
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
]), Rt = C([
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
]), Io = C([
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
]), St = C([
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
]), Ro = C([
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
]), Mn = C(["#text"]), Pn = C([
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
]), wt = C([
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
]), xn = C([
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
]), qe = C([
  "xlink:href",
  "xml:id",
  "xlink:title",
  "xml:space",
  "xmlns:xlink"
]), So = M(/{{[\w\W]*|^[\w\W]*}}/g), wo = M(/<%[\w\W]*|^[\w\W]*%>/g), Lo = M(/\${[\w\W]*/g), Oo = M(/^data-[\-\w.\u00B7-\uFFFF]+$/), No = M(/^aria-[\-\w]+$/), $n = M(/^(?:(?:(?:f|ht)tps?|mailto|tel|callto|sms|cid|xmpp|matrix):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i), vo = M(/^(?:\w+script|data):/i), Do = M(/[\u0000-\u0020\u00A0\u1680\u180E\u2000-\u2029\u205F\u3000]/g), Co = M(/^html$/i), Mo = M(/^[a-z][.\w]*(-[.\w]+)+$/i), kn = M(/<[/\w!]/g), Un = M(/<[/\w]/g), Po = M(/<\/no(script|embed|frames)/i), xo = M(/\/>/i), j = {
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
}, Zn = [
  "style",
  "script",
  "xmp",
  "iframe",
  "noembed",
  "noframes",
  "plaintext",
  "noscript"
], $o = C(A({}, Zn)), ko = (function() {
  const t = {};
  return ie(Zn, (n) => {
    t[n] = M(new RegExp("</" + n + "(?=[\\t\\n\\f\\r />])", "i"));
  }), C(t);
})(), Uo = function() {
  return typeof window > "u" ? null : window;
}, Fo = function(n, o) {
  if (typeof n != "object" || typeof n.createPolicy != "function") return null;
  let s = null;
  const c = "data-tt-policy-suffix";
  o && o.hasAttribute(c) && (s = o.getAttribute(c));
  const m = "dompurify" + (s ? "#" + s : "");
  try {
    return n.createPolicy(m, {
      createHTML(g) {
        return g;
      },
      createScriptURL(g) {
        return g;
      }
    });
  } catch {
    return console.warn("TrustedTypes policy " + m + " could not be created."), null;
  }
}, Fn = function() {
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
}, ee = function(n, o, s, c) {
  return F(n, o) && _e(n[o]) ? A(c.base ? H(c.base) : {}, n[o], c.transform) : s;
}, Lt = function(n, o, s) {
  const c = F(n, o) ? n[o] : void 0;
  return c && typeof c == "object" ? H(c) : s();
};
function Jn() {
  let t = arguments.length > 0 && arguments[0] !== void 0 ? arguments[0] : Uo();
  const n = (u) => Jn(u);
  if (n.version = "3.4.16", n.removed = [], !t || !t.document || t.document.nodeType !== j.document || !t.Element)
    return n.isSupported = !1, n;
  let o = t.document;
  const s = o, c = s.currentScript;
  t.DocumentFragment;
  const m = t.HTMLTemplateElement, g = t.Node, N = t.Element, l = t.NodeFilter;
  t.NamedNodeMap === void 0 && (t.NamedNodeMap || t.MozNamedAttrMap), t.HTMLFormElement;
  const L = t.DOMParser, i = t.trustedTypes, p = N.prototype, E = W(p, "cloneNode"), b = W(p, "remove"), y = W(p, "removeAttributeNode"), h = W(p, "nextSibling"), G = W(p, "childNodes"), P = W(p, "parentNode"), Y = W(p, "shadowRoot"), se = W(p, "attributes"), k = g && g.prototype ? W(g.prototype, "nodeType") : null, ae = g && g.prototype ? W(g.prototype, "nodeName") : null, Ce = g && g.prototype ? W(g.prototype, "ownerDocument") : null, be = function(e) {
    return k ? k(e) : e.nodeType;
  }, Ke = function(e) {
    return ae ? ae(e) : e.nodeName;
  };
  if (typeof m == "function") {
    const u = o.createElement("template");
    u.content && u.content.ownerDocument && (o = u.content.ownerDocument);
  }
  let U, te = "", Ze, Pt = !1, ye = 0;
  const xt = function() {
    if (ye > 0) throw Q('A configured TRUSTED_TYPES_POLICY callback (createHTML or createScriptURL) must not call DOMPurify.sanitize, as that causes infinite recursion. Do not pass a policy whose callbacks wrap DOMPurify as TRUSTED_TYPES_POLICY; see the "DOMPurify and Trusted Types" section of the README.');
  }, le = function(e) {
    xt(), ye++;
    try {
      return U.createHTML(e);
    } finally {
      ye--;
    }
  }, rr = function(e) {
    xt(), ye++;
    try {
      return U.createScriptURL(e);
    } finally {
      ye--;
    }
  }, or = function() {
    return Pt || (Ze = Fo(i, c), Pt = !0), Ze;
  }, Me = o, Je = Me.implementation, $t = Me.createNodeIterator, ir = Me.createDocumentFragment, sr = Me.getElementsByTagName, ar = s.importNode;
  let I = Fn();
  n.isSupported = typeof Yn == "function" && typeof P == "function" && Je && Je.createHTMLDocument !== void 0;
  const lr = So, cr = wo, ur = Lo, fr = Oo, pr = No, dr = vo, kt = Do, mr = Mo;
  let Ut = $n, R = null;
  const Qe = A({}, [
    ...Cn,
    ...It,
    ...Rt,
    ...St,
    ...Mn
  ]);
  let S = null;
  const et = A({}, [
    ...Pn,
    ...wt,
    ...xn,
    ...qe
  ]);
  let X = Object.seal(Te(null, {
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
  })), Ie = null, Ft = null;
  const K = Object.seal(Te(null, {
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
  let Gt = !0, tt = !0, zt = !1, jt = !0, Z = !1, ne = !0, re = !1, nt = !1, Pe = null, xe = null, rt = !1, ce = !1, $e = !1, ke = !1, Ht = !0, Bt = !1;
  const Wt = "user-content-";
  let ot = !0, it = !1, ue = {}, fe = null;
  const Xt = A({}, [
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
  let qt = null;
  const Vt = A({}, [
    "audio",
    "video",
    "img",
    "source",
    "image",
    "track"
  ]);
  let Yt = null;
  const Kt = A({}, [
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
  ]), Ue = "http://www.w3.org/1998/Math/MathML", Fe = "http://www.w3.org/2000/svg", q = "http://www.w3.org/1999/xhtml";
  let pe = q, st = !1, at = null;
  const hr = A({}, [
    Ue,
    Fe,
    q
  ], yt), Zt = C([
    "mi",
    "mo",
    "mn",
    "ms",
    "mtext"
  ]);
  let lt = A({}, Zt);
  const Jt = C(["annotation-xml"]);
  let ct = A({}, Jt);
  const Er = A({}, [
    "title",
    "style",
    "font",
    "a",
    "script"
  ]);
  let Re = null;
  const gr = ["application/xhtml+xml", "text/html"], Tr = "text/html";
  let O = null, de = null;
  const _r = o.createElement("form"), Qt = function(e) {
    return e instanceof RegExp || e instanceof Function;
  }, ut = function() {
    let e = arguments.length > 0 && arguments[0] !== void 0 ? arguments[0] : {};
    if (de && de === e) return;
    (!e || typeof e != "object") && (e = {}), e = H(e), Re = gr.indexOf(e.PARSER_MEDIA_TYPE) === -1 ? Tr : e.PARSER_MEDIA_TYPE, O = Re === "application/xhtml+xml" ? yt : ve, R = ee(e, "ALLOWED_TAGS", Qe, { transform: O }), S = ee(e, "ALLOWED_ATTR", et, { transform: O }), at = ee(e, "ALLOWED_NAMESPACES", hr, { transform: yt }), Yt = ee(e, "ADD_URI_SAFE_ATTR", Kt, {
      transform: O,
      base: Kt
    }), qt = ee(e, "ADD_DATA_URI_TAGS", Vt, {
      transform: O,
      base: Vt
    }), fe = ee(e, "FORBID_CONTENTS", Xt, { transform: O }), Ie = ee(e, "FORBID_TAGS", H({}), { transform: O }), Ft = ee(e, "FORBID_ATTR", H({}), { transform: O }), ue = F(e, "USE_PROFILES") ? e.USE_PROFILES && typeof e.USE_PROFILES == "object" ? H(e.USE_PROFILES) : e.USE_PROFILES : !1, Gt = e.ALLOW_ARIA_ATTR !== !1, tt = e.ALLOW_DATA_ATTR !== !1, zt = e.ALLOW_UNKNOWN_PROTOCOLS || !1, jt = e.ALLOW_SELF_CLOSE_IN_ATTR !== !1, Z = e.SAFE_FOR_TEMPLATES || !1, ne = e.SAFE_FOR_XML !== !1, re = e.WHOLE_DOCUMENT || !1, ce = e.RETURN_DOM || !1, $e = e.RETURN_DOM_FRAGMENT || !1, ke = e.RETURN_TRUSTED_TYPE || !1, rt = e.FORCE_BODY || !1, Ht = e.SANITIZE_DOM !== !1, Bt = e.SANITIZE_NAMED_PROPS || !1, ot = e.KEEP_CONTENT !== !1, it = e.IN_PLACE || !1, Ut = yo(e.ALLOWED_URI_REGEXP) ? e.ALLOWED_URI_REGEXP : $n, pe = typeof e.NAMESPACE == "string" ? e.NAMESPACE : q, lt = Lt(e, "MATHML_TEXT_INTEGRATION_POINTS", () => A({}, Zt)), ct = Lt(e, "HTML_INTEGRATION_POINTS", () => A({}, Jt));
    const r = Lt(e, "CUSTOM_ELEMENT_HANDLING", () => Te(null));
    if (X = Te(null), F(r, "tagNameCheck") && Qt(r.tagNameCheck) && (X.tagNameCheck = r.tagNameCheck), F(r, "attributeNameCheck") && Qt(r.attributeNameCheck) && (X.attributeNameCheck = r.attributeNameCheck), F(r, "allowCustomizedBuiltInElements") && typeof r.allowCustomizedBuiltInElements == "boolean" && (X.allowCustomizedBuiltInElements = r.allowCustomizedBuiltInElements), M(X), Z && (tt = !1), $e && (ce = !0), ue && (R = A({}, Mn), S = Te(null), ue.html === !0 && (A(R, Cn), A(S, Pn)), ue.svg === !0 && (A(R, It), A(S, wt), A(S, qe)), ue.svgFilters === !0 && (A(R, Rt), A(S, wt), A(S, qe)), ue.mathMl === !0 && (A(R, St), A(S, xn), A(S, qe))), K.tagCheck = null, K.attributeCheck = null, F(e, "ADD_TAGS") && (typeof e.ADD_TAGS == "function" ? K.tagCheck = e.ADD_TAGS : _e(e.ADD_TAGS) && (R === Qe && (R = H(R)), A(R, e.ADD_TAGS, O))), F(e, "ADD_ATTR") && (typeof e.ADD_ATTR == "function" ? K.attributeCheck = e.ADD_ATTR : _e(e.ADD_ATTR) && (S === et && (S = H(S)), A(S, e.ADD_ATTR, O))), F(e, "ADD_FORBID_CONTENTS") && _e(e.ADD_FORBID_CONTENTS) && (fe === Xt && (fe = H(fe)), A(fe, e.ADD_FORBID_CONTENTS, O)), ot && (R["#text"] = !0), re && A(R, [
      "html",
      "head",
      "body"
    ]), R.table && (A(R, ["tbody"]), delete Ie.tbody), e.TRUSTED_TYPES_POLICY) {
      if (typeof e.TRUSTED_TYPES_POLICY.createHTML != "function") throw Q('TRUSTED_TYPES_POLICY configuration option must provide a "createHTML" hook.');
      if (typeof e.TRUSTED_TYPES_POLICY.createScriptURL != "function") throw Q('TRUSTED_TYPES_POLICY configuration option must provide a "createScriptURL" hook.');
      const a = U;
      U = e.TRUSTED_TYPES_POLICY;
      try {
        te = le("");
      } catch (f) {
        throw U = a, f;
      }
    } else e.TRUSTED_TYPES_POLICY === null ? (U = void 0, te = "") : (U === void 0 && (U = or()), U && typeof te == "string" && (te = le("")));
    C && C(e), de = e;
  }, en = A({}, [
    ...It,
    ...Rt,
    ...Io
  ]), tn = A({}, [...St, ...Ro]), Ar = function(e, r, a) {
    return r.namespaceURI === q ? e === "svg" : r.namespaceURI === Ue ? e === "svg" && (a === "annotation-xml" || lt[a]) : !!en[e];
  }, br = function(e, r, a) {
    return r.namespaceURI === q ? e === "math" : r.namespaceURI === Fe ? e === "math" && ct[a] : !!tn[e];
  }, yr = function(e, r, a) {
    return r.namespaceURI === Fe && !ct[a] || r.namespaceURI === Ue && !lt[a] ? !1 : !tn[e] && (Er[e] || !en[e]);
  }, Ir = function(e) {
    let r = P(e);
    (!r || !r.tagName) && (r = {
      namespaceURI: pe,
      tagName: "template"
    });
    const a = ve(e.tagName), f = ve(r.tagName);
    return at[e.namespaceURI] ? e.namespaceURI === Fe ? Ar(a, r, f) : e.namespaceURI === Ue ? br(a, r, f) : e.namespaceURI === q ? yr(a, r, f) : !!(Re === "application/xhtml+xml" && at[e.namespaceURI]) : !1;
  }, J = function(e) {
    Le(n.removed, { element: e });
    try {
      P(e).removeChild(e);
    } catch {
      if (b(e), !P(e)) throw Q("a node selected for removal could not be detached from its tree and cannot be safely returned; refusing to sanitize in place");
    }
  }, nn = function(e, r, a) {
    try {
      y(e, r);
    } catch {
      try {
        e.removeAttribute(a);
      } catch {
      }
    }
  }, Ge = function(e) {
    ze(e);
    const r = G(e);
    if (r) {
      const f = [];
      ie(r, (d) => {
        Le(f, d);
      }), ie(f, (d) => {
        try {
          b(d);
        } catch {
        }
      });
    }
    const a = se(e);
    if (a) for (let f = a.length - 1; f >= 0; --f) {
      const d = a[f], T = d && d.name;
      typeof T == "string" && nn(e, d, T);
    }
  }, oe = function(e, r, a) {
    if (!a) try {
      a = r.getAttributeNode(e);
    } catch {
      a = null;
    }
    Le(n.removed, {
      attribute: a || null,
      from: r
    });
    try {
      a ? y(r, a) : r.removeAttribute(e);
    } catch {
      try {
        r.removeAttribute(e);
      } catch {
      }
    }
    if (e === "is")
      if (ce || $e) try {
        J(r);
      } catch {
      }
      else try {
        r.setAttribute(e, "");
      } catch {
      }
  }, Rr = function(e) {
    const r = se(e);
    if (r)
      for (let a = r.length - 1; a >= 0; --a) {
        const f = r[a], d = f && f.name;
        typeof d != "string" || S[O(d)] || nn(e, f, d);
      }
  }, ze = function(e) {
    const r = [e];
    for (; r.length > 0; ) {
      const a = r.pop();
      be(a) === j.element && Rr(a);
      const f = G(a);
      if (f) for (let d = f.length - 1; d >= 0; --d) r.push(f[d]);
    }
  }, rn = function(e, r) {
    return ne ? e === "patchsrc" ? !0 : e === "for" && r !== "label" && r !== "output" : !1;
  }, Sr = function(e) {
    if (!ne) return;
    const r = [e];
    for (; r.length > 0; ) {
      const a = r.pop(), f = be(a);
      if (f === j.processingInstruction || f === j.comment && x(Un, a.data)) {
        try {
          b(a);
        } catch {
        }
        continue;
      }
      if (f === j.element) {
        const T = a, _ = O(Ke(a));
        try {
          T.hasAttribute && T.hasAttribute("patchsrc") && T.removeAttribute("patchsrc"), T.hasAttribute && T.hasAttribute("for") && rn("for", _) && T.removeAttribute("for");
        } catch {
        }
      }
      const d = G(a);
      if (d) for (let T = d.length - 1; T >= 0; --T) r.push(d[T]);
    }
  }, on = function(e) {
    let r = null, a = null;
    if (rt) e = "<remove></remove>" + e;
    else {
      const T = On(e, /^[\r\n\t ]+/);
      a = T && T[0];
    }
    Re === "application/xhtml+xml" && pe === q && (e = '<html xmlns="http://www.w3.org/1999/xhtml"><head></head><body>' + e + "</body></html>");
    const f = U ? le(e) : e;
    if (pe === q) try {
      r = new L().parseFromString(f, Re);
    } catch {
    }
    if (!r || !r.documentElement) {
      r = Je.createDocument(pe, "template", null);
      try {
        r.documentElement.innerHTML = st ? te : f;
      } catch {
      }
    }
    const d = r.body || r.documentElement;
    return e && a && d.insertBefore(o.createTextNode(a), d.childNodes[0] || null), pe === q ? sr.call(r, re ? "html" : "body")[0] : re ? r.documentElement : d;
  }, sn = function(e) {
    const r = Ce ? Ce(e) : e.ownerDocument;
    return $t.call(r || e, e, l.SHOW_ELEMENT | l.SHOW_COMMENT | l.SHOW_TEXT | l.SHOW_PROCESSING_INSTRUCTION | l.SHOW_CDATA_SECTION, null);
  }, je = function(e) {
    return e = Oe(e, lr, " "), e = Oe(e, cr, " "), e = Oe(e, ur, " "), e;
  }, ft = function(e) {
    var r;
    e.normalize();
    const a = Ce ? Ce(e) : e.ownerDocument, f = $t.call(a || e, e, l.SHOW_TEXT | l.SHOW_COMMENT | l.SHOW_CDATA_SECTION | l.SHOW_PROCESSING_INSTRUCTION, null);
    let d = f.nextNode();
    for (; d; )
      d.data = je(d.data), d = f.nextNode();
    const T = (r = e.querySelectorAll) === null || r === void 0 ? void 0 : r.call(e, "template");
    T && ie(T, (_) => {
      me(_.content) && ft(_.content);
    });
  }, He = function(e) {
    const r = ae ? ae(e) : null;
    return typeof r != "string" || O(r) !== "form" ? !1 : typeof e.nodeName != "string" || typeof e.textContent != "string" || typeof e.removeChild != "function" || e.attributes !== se(e) || typeof e.removeAttribute != "function" || typeof e.removeAttributeNode != "function" || typeof e.getAttributeNode != "function" || typeof e.setAttribute != "function" || typeof e.namespaceURI != "string" || typeof e.insertBefore != "function" || typeof e.hasChildNodes != "function" || e.nodeType !== k(e) || e.childNodes !== G(e);
  }, me = function(e) {
    if (!k || typeof e != "object" || e === null) return !1;
    try {
      return k(e) === j.documentFragment;
    } catch {
      return !1;
    }
  }, Se = function(e) {
    if (!k || typeof e != "object" || e === null) return !1;
    try {
      return typeof k(e) == "number";
    } catch {
      return !1;
    }
  };
  function V(u, e, r) {
    u.length !== 0 && ie(u, (a) => {
      a.call(n, e, r, de);
    });
  }
  const wr = function(e, r) {
    return !!(ne && e.hasChildNodes() && !Se(e.firstElementChild) && x(kn, e.textContent) && x(kn, e.innerHTML) || ne && e.namespaceURI === q && $o[r] && (Se(e.firstElementChild) || typeof e.textContent == "string" && x(ko[r], e.textContent)) || e.nodeType === j.processingInstruction || ne && e.nodeType === j.comment && x(Un, e.data));
  }, Be = function(e, r) {
    if (e instanceof RegExp) return x(e, r);
    if (e instanceof Function) {
      for (var a = arguments.length, f = new Array(a > 2 ? a - 2 : 0), d = 2; d < a; d++) f[d - 2] = arguments[d];
      return !!e(r, ...f);
    }
    return !1;
  }, Lr = function(e, r, a) {
    if (!Ie[r] && un(r) && Be(X.tagNameCheck, r)) return !1;
    if (ot && !fe[r]) {
      const f = P(e), d = G(e);
      if (d && f) {
        const T = d.length;
        for (let _ = T - 1; _ >= 0; --_) {
          const w = e === a ? E(d[_], !0) : d[_];
          f.insertBefore(w, h(e));
        }
      }
    }
    return J(e), !0;
  }, an = function(e, r, a, f) {
    return e.length === 0 ? r : r === a || r === f ? H(r) : r;
  }, he = function(e, r) {
    return e === r || P(e) !== null ? !1 : (it && ze(e), !0);
  }, ln = function(e, r) {
    if (V(I.beforeSanitizeElements, e, null), he(e, r)) return !0;
    if (He(e))
      return J(e), !0;
    const a = O(Ke(e));
    if (R = an(I.uponSanitizeElement, R, Qe, Pe), V(I.uponSanitizeElement, e, {
      tagName: a,
      allowedTags: R
    }), he(e, r)) return !0;
    if (wr(e, a))
      return J(e), !0;
    if (Ie[a] || !(K.tagCheck instanceof Function && K.tagCheck(a)) && !R[a]) {
      const f = Lr(e, a, r);
      return f === !1 && (V(I.afterSanitizeElements, e, null), he(e, r)) ? !0 : f;
    }
    if (be(e) === j.element && !Ir(e) || (a === "noscript" || a === "noembed" || a === "noframes") && x(Po, e.innerHTML))
      return J(e), !0;
    if (Z && e.nodeType === j.text) {
      const f = je(e.textContent);
      e.textContent !== f && (Le(n.removed, { element: e.cloneNode() }), e.textContent = f);
    }
    return V(I.afterSanitizeElements, e, null), he(e, r);
  }, cn = function(e, r, a) {
    if (Ft[r] || rn(r, e) || Ht && (r === "id" || r === "name") && (a in o || a in _r)) return !1;
    const f = S[r] || K.attributeCheck instanceof Function && K.attributeCheck(r, e);
    return tt && x(fr, r) || Gt && x(pr, r) ? !0 : f ? Yt[r] || x(Ut, Oe(a, kt, "")) || (r === "src" || r === "xlink:href" || r === "href") && e !== "script" && Nn(a, "data:") === 0 && qt[e] || zt && !x(dr, Oe(a, kt, "")) ? !0 : !a : un(e) && Be(X.tagNameCheck, e) && Be(X.attributeNameCheck, r, e) || r === "is" && X.allowCustomizedBuiltInElements && Be(X.tagNameCheck, a);
  }, Or = A({}, [
    "annotation-xml",
    "color-profile",
    "font-face",
    "font-face-format",
    "font-face-name",
    "font-face-src",
    "font-face-uri",
    "missing-glyph"
  ]), un = function(e) {
    return !Or[ve(e)] && x(mr, e);
  }, Nr = function(e, r, a, f) {
    if (U && typeof i == "object" && typeof i.getAttributeType == "function" && !a) switch (i.getAttributeType(e, r)) {
      case "TrustedHTML":
        return le(f);
      case "TrustedScriptURL":
        return rr(f);
    }
    return f;
  }, vr = function(e, r, a, f) {
    try {
      return a ? e.setAttributeNS(a, r, f) : e.setAttribute(r, f), He(e) ? (J(e), !1) : !0;
    } catch {
      return oe(r, e), !1;
    }
  }, fn = function(e, r) {
    if (V(I.beforeSanitizeAttributes, e, null), he(e, r)) return;
    const a = e.attributes;
    if (!a || He(e)) return;
    S = an(I.uponSanitizeAttribute, S, et, xe);
    const f = {
      attrName: "",
      attrValue: "",
      keepAttr: !0,
      allowedAttributes: S,
      forceKeepAttr: void 0
    };
    let d = a.length;
    const T = O(e.nodeName);
    for (; d--; ) {
      const _ = a[d], w = _.name, B = _.namespaceURI, z = _.value, Ee = O(w), dt = z;
      let $ = w === "value" ? dt : Eo(dt), pn = !1;
      if (f.attrName = Ee, f.attrValue = $, f.keepAttr = !0, f.forceKeepAttr = void 0, V(I.uponSanitizeAttribute, e, f), $ = f.attrValue, Bt && (Ee === "id" || Ee === "name") && Nn($, Wt) !== 0 && (oe(w, e, _), $ = Wt + $, pn = !0), ne && x(/((--!?|])>)|<\/(style|script|title|xmp|textarea|noscript|iframe|noembed|noframes)/i, $)) {
        oe(w, e, _);
        continue;
      }
      if (Ee === "attributename" && On($, "href")) {
        oe(w, e, _);
        continue;
      }
      if (!f.forceKeepAttr) {
        if (!f.keepAttr) {
          oe(w, e, _);
          continue;
        }
        if (!jt && x(xo, $)) {
          oe(w, e, _);
          continue;
        }
        if (Z && ($ = je($)), !cn(T, Ee, $)) {
          oe(w, e, _);
          continue;
        }
        $ = Nr(T, Ee, B, $), $ !== dt && vr(e, w, B, $) && pn && Ln(n.removed);
      }
    }
    V(I.afterSanitizeAttributes, e, null), he(e, r);
  }, We = function(e) {
    let r = null;
    const a = sn(e);
    for (V(I.beforeSanitizeShadowDOM, e, null); r = a.nextNode(); )
      if (V(I.uponSanitizeShadowNode, r, null), ln(r, e), fn(r, e), me(r.content) && We(r.content), be(r) === j.element) {
        const f = Y(r);
        me(f) && (pt(f), We(f));
      }
    V(I.afterSanitizeShadowDOM, e, null);
  }, pt = function(e) {
    const r = [{
      node: e,
      shadow: null
    }];
    for (; r.length > 0; ) {
      const a = r.pop();
      if (a.shadow) {
        We(a.shadow);
        continue;
      }
      const f = a.node, d = be(f) === j.element, T = G(f);
      if (T) for (let _ = T.length - 1; _ >= 0; --_) r.push({
        node: T[_],
        shadow: null
      });
      if (d) {
        const _ = ae ? ae(f) : null;
        if (typeof _ == "string" && O(_) === "template") {
          const w = f.content;
          me(w) && r.push({
            node: w,
            shadow: null
          });
        }
      }
      if (d) {
        const _ = Y(f);
        me(_) && r.push({
          node: null,
          shadow: _
        }, {
          node: _,
          shadow: null
        });
      }
    }
  };
  return n.sanitize = function(u) {
    let e = arguments.length > 1 && arguments[1] !== void 0 ? arguments[1] : {}, r = null, a = null, f = null, d = null;
    if (st = !u, st && (u = "<!-->"), typeof u != "string" && !Se(u) && (u = bo(u), typeof u != "string"))
      throw Q("dirty is not a string, aborting");
    if (!n.isSupported) return u;
    nt ? (R = Pe, S = xe) : ut(e), (I.uponSanitizeElement.length > 0 || I.uponSanitizeAttribute.length > 0) && (R = H(R)), I.uponSanitizeAttribute.length > 0 && (S = H(S)), n.removed = [];
    const T = it && typeof u != "string" && Se(u);
    if (T) {
      Sr(u);
      const B = Ke(u);
      if (typeof B == "string") {
        const z = O(B);
        if (!R[z] || Ie[z])
          throw Ge(u), Q("root node is forbidden and cannot be sanitized in-place");
      }
      if (He(u))
        throw Ge(u), Q("root node is clobbered and cannot be sanitized in-place");
      try {
        pt(u);
      } catch (z) {
        throw Ge(u), z;
      }
    } else if (Se(u))
      r = on("<!---->"), a = r.ownerDocument.importNode(u, !0), a.nodeType === j.element && a.nodeName === "BODY" || a.nodeName === "HTML" ? r = a : r.appendChild(a), pt(r);
    else {
      if (!ce && !Z && !re && u.indexOf("<") === -1) return U && ke ? le(u) : u;
      if (r = on(u), !r) return ce ? null : ke ? te : "";
    }
    r && rt && J(r.firstChild);
    const _ = T ? u : r;
    try {
      const B = sn(_);
      for (; f = B.nextNode(); )
        ln(f, _), fn(f, _), me(f.content) && We(f.content);
    } catch (B) {
      throw T && (Ge(u), ie(n.removed, (z) => {
        z.element && ze(z.element);
      })), B;
    }
    if (T) {
      let B = !1;
      if (ie(n.removed, (z) => {
        z.element && (z.element === u && (B = !0), ze(z.element));
      }), B) throw Q("a node selected for removal could not be safely returned; refusing to sanitize in place");
      return Z && ft(u), u;
    }
    if (ce) {
      if (Z && ft(r), $e)
        for (d = ir.call(r.ownerDocument); r.firstChild; ) d.appendChild(r.firstChild);
      else d = r;
      return (S.shadowroot || S.shadowrootmode) && (d = ar.call(s, d, !0)), d;
    }
    let w = re ? r.outerHTML : r.innerHTML;
    return re && R["!doctype"] && r.ownerDocument && r.ownerDocument.doctype && r.ownerDocument.doctype.name && x(Co, r.ownerDocument.doctype.name) && (w = "<!DOCTYPE " + r.ownerDocument.doctype.name + `>
` + w), Z && (w = je(w)), U && ke ? le(w) : w;
  }, n.setConfig = function() {
    let u = arguments.length > 0 && arguments[0] !== void 0 ? arguments[0] : {};
    ut(u), nt = !0, Pe = R, xe = S;
  }, n.clearConfig = function() {
    de = null, nt = !1, Pe = null, xe = null, U = Ze, te = "";
  }, n.isValidAttribute = function(u, e, r) {
    de || ut({});
    const a = O(u), f = O(e);
    return cn(a, f, r);
  }, n.addHook = function(u, e) {
    typeof e == "function" && F(I, u) && Le(I[u], e);
  }, n.removeHook = function(u, e) {
    if (F(I, u)) {
      if (e !== void 0) {
        const r = mo(I[u], e);
        return r === -1 ? void 0 : ho(I[u], r, 1)[0];
      }
      return Ln(I[u]);
    }
  }, n.removeHooks = function(u) {
    F(I, u) && (I[u] = []);
  }, n.removeAllHooks = function() {
    I = Fn();
  }, n;
}
Jn();
globalThis._nc_l10n_locale ??= typeof document < "u" && document.documentElement.dataset.locale || Intl.DateTimeFormat().resolvedOptions().locale.replaceAll(/-/g, "_");
globalThis._nc_l10n_language ??= typeof document < "u" && document.documentElement.lang || (globalThis.navigator?.language ?? "en");
globalThis._oc_l10n_registry_translations ??= {};
globalThis._oc_l10n_registry_plural_functions ??= {};
class Go extends oo {
}
function zo() {
  return De.registry ??= new Go(), De.registry;
}
const jo = Object.freeze({
  DEFAULT: "default",
  HIDDEN: "hidden"
});
function Ho(t) {
  if (Bo(t), De.fileActions ??= /* @__PURE__ */ new Map(), De.fileActions.has(t.id)) {
    ro.error(`FileAction ${t.id} already registered`, { action: t });
    return;
  }
  De.fileActions.set(t.id, t), zo().dispatchTypedEvent("register:action", new CustomEvent("register:action", { detail: t }));
}
function Bo(t) {
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
  if (t.default && !Object.values(jo).includes(t.default))
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
let Ve = null;
function Mt(t, n = 20) {
  return `<svg viewBox="0 0 24 24" width="${n}" height="${n}" aria-hidden="true"><path fill="currentColor" d="${t}"/></svg>`;
}
async function Qn(t, n, o = "") {
  Ve?.();
  const s = document.createElement("div");
  s.className = "golblick-sphere", s.setAttribute("role", "dialog"), s.setAttribute("aria-label", o ? `${o}, as a sphere` : "Sphere view"), s.style.cssText = "position:fixed;inset:0;z-index:100000;background:#000;";
  const c = document.createElement("button");
  c.type = "button", c.title = "Close sphere view", c.setAttribute("aria-label", "Close sphere view"), c.innerHTML = Mt(Dr, 24), c.style.cssText = "position:absolute;top:12px;right:12px;z-index:1;width:44px;height:44px;border:0;border-radius:50%;background:rgba(0,0,0,.5);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;";
  const m = document.createElement("div");
  m.style.cssText = "position:absolute;left:50%;bottom:16px;transform:translateX(-50%);z-index:1;padding:6px 12px;border-radius:16px;background:rgba(0,0,0,.5);color:#fff;font-size:13px;pointer-events:none;", m.textContent = "Loading…", s.append(c, m), document.body.appendChild(s);
  let g = null, N = !1;
  const l = (y) => {
    y.key === "Escape" && L(), ["Escape", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", " "].includes(y.key) && (y.stopImmediatePropagation(), y.preventDefault());
  }, L = () => {
    N || (N = !0, window.removeEventListener("keydown", l, !0), g?.destroy(), s.remove(), Ve === L && (Ve = null));
  };
  Ve = L, c.addEventListener("click", L), window.addEventListener("keydown", l, !0);
  const i = `etag=${encodeURIComponent(n)}`, p = Nt("/core/preview") + `?fileId=${t}&x=2048&y=1024&a=1&${i}`, E = Nt(`/apps/golblick/sphere/${t}`) + `?${i}`;
  try {
    const { SphereView: y } = await import("./sphere-44dHSg5o.chunk.mjs");
    if (N) return;
    if (g = await y.create(s, p), N) {
      g.destroy();
      return;
    }
    s.append(c, m);
  } catch {
    m.textContent = "This photo could not be shown as a sphere.";
    return;
  }
  m.textContent = "Loading full resolution…";
  const b = await g.upgrade(E);
  N || (b ? m.remove() : m.textContent = "Full resolution is not available; showing the preview.");
}
const Ct = "View as sphere", Ae = "golblick-sphere-button", Wo = (t) => !!t && t.toLowerCase().endsWith(".insp");
Ho({
  id: "golblick-sphere",
  displayName: () => Ct,
  iconSvgInline: () => Mt(Hn),
  enabled: ({ nodes: t }) => t.length === 1 && Wo(t[0].basename) && t[0].fileid !== void 0,
  exec: async ({ nodes: t }) => {
    const n = t[0];
    return Qn(Number(n.fileid), String(n.attributes?.etag ?? ""), n.basename), null;
  },
  order: 50
});
const Gn = /* @__PURE__ */ new Map();
function Xo(t) {
  let n = Gn.get(t);
  return n || (n = fetch(Nt(`/apps/golblick/sphere/${t}/info`), { credentials: "same-origin" }).then((o) => o.ok ? o.json() : { sphere: !1, etag: null }).catch(() => ({ sphere: !1, etag: null })), Gn.set(t, n)), n;
}
function er(t) {
  let n;
  if (t instanceof HTMLButtonElement) {
    n = t.cloneNode(!0);
    for (const c of [n, ...n.querySelectorAll("[id]")]) c.removeAttribute("id");
    n.removeAttribute("aria-pressed"), n.classList.remove("action-item__menutoggle"), n.removeAttribute("aria-haspopup"), n.removeAttribute("aria-expanded");
  } else
    n = document.createElement("button"), n.style.cssText = "border:0;background:transparent;color:inherit;width:44px;height:44px;display:flex;align-items:center;justify-content:center;cursor:pointer;border-radius:8px;padding:0;", n.innerHTML = '<span class="button-vue__icon"></span>';
  n.type = "button", n.classList.add(Ae), n.title = Ct, n.setAttribute("aria-label", Ct);
  const o = Number(t?.querySelector("svg")?.getAttribute("width")) || 20, s = n.querySelector(".button-vue__icon") ?? n;
  return s.innerHTML = `<span class="material-design-icon" role="img">${Mt(Hn, o)}</span>`, n.querySelector(".button-vue__text")?.replaceChildren(), n;
}
function tr(t, n, o, s) {
  const c = t?.querySelector(`.${Ae}`);
  if (!t || n === null) {
    c?.remove();
    return;
  }
  c && c.dataset.fileId === String(n) || (c?.remove(), Xo(n).then((m) => {
    if (!m.sphere || o() !== n || !t.isConnected || t.querySelector(`.${Ae}`)) return;
    const g = s();
    g.dataset.fileId = String(n), g.addEventListener("click", (N) => {
      N.stopPropagation(), Qn(n, m.etag ?? "");
    }), t.insertBefore(g, t.firstChild);
  }));
}
function zn() {
  const n = document.querySelector("#viewer .viewer__file--active img")?.getAttribute("src") ?? "", o = n.match(/[?&]fileId=(\d+)/) ?? n.match(/\/preview\/(\d+)/);
  return o ? Number(o[1]) : null;
}
function qo() {
  const t = document.querySelector("#viewer .modal-header .header-actions");
  tr(t, zn(), zn, () => er(t?.querySelector(`button:not(.${Ae})`) ?? null));
}
function jn() {
  if (!document.querySelector(".memories-viewer .pswp--open")) return null;
  const t = window.location.hash.match(/^#v\/[^/]+\/(\d+)/);
  return t ? Number(t[1]) : null;
}
function Vo() {
  const t = document.querySelector(".memories-viewer .top-bar .action-items");
  if (t?.querySelector('[aria-label="View as panorama"]')) {
    t.querySelector(`.${Ae}`)?.remove();
    return;
  }
  tr(t, jn(), jn, () => er(t?.querySelector(`button.action-item--single:not(.${Ae})`) ?? null));
}
let Ot = !1;
function nr() {
  Ot || (Ot = !0, requestAnimationFrame(() => {
    Ot = !1, qo(), Vo();
  }));
}
new MutationObserver(nr).observe(document.body, {
  childList: !0,
  subtree: !0,
  attributes: !0,
  attributeFilter: ["src", "class"]
});
window.addEventListener("hashchange", nr);
