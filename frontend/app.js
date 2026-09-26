/* ABAN Real-estate — website (single-page app, no build step, no external libraries) */
(function () {
  "use strict";

  // ===========================================================================
  // Settings you may want to change
  // ===========================================================================
  const CONFIG = {
    appName: "ABAN Real-estate",
    currency: "USD",          // shown on prices, e.g. "USD", "AMD", "IRR", "EUR"
    defaultLanguage: "en",
    pageSize: 25,
    apiBase: "/api/v1",
  };

  const LOCALES = { en: "en-US", fa: "fa-IR", hy: "hy-AM", ru: "ru-RU" };
  const LANGS = [
    { code: "en", label: "English" },
    { code: "fa", label: "فارسی" },
    { code: "hy", label: "Հայերեն" },
    { code: "ru", label: "Русский" },
  ];
  const RTL = ["fa"];

  const PROPERTY_TYPES = ["apartment", "house", "villa", "condo", "townhouse", "land", "commercial", "office"];
  const PROPERTY_STATUSES = ["available", "pending", "reserved", "sold", "rented", "expired", "delisted"];
  const CLIENT_TYPES = ["buyer", "seller", "both"];
  const CLIENT_STATUSES = ["active", "inactive"];
  const INTERACTION_TYPES = ["call", "email", "meeting", "showing", "offer"];
  const DEAL_STAGES = ["lead", "offer", "negotiation", "inspection", "appraisal", "closed"];
  const DEAL_TYPES = ["sale", "rental", "lease"];
  const DEAL_STATUSES = ["active", "won", "lost", "inactive"];
  const CALL_TYPES = ["inbound", "outbound", "callback"];
  const SENTIMENTS = ["positive", "neutral", "negative"];
  const CALL_QUALITIES = ["excellent", "good", "fair", "poor"];
  const DOC_TYPES = ["contract", "disclosure", "proposal", "agreement", "deed", "inspection", "appraisal", "other"];
  const SHARE_PERMISSIONS = ["view", "comment", "edit"];
  const ROLES = ["viewer", "agent", "admin"];

  // ===========================================================================
  // Safe storage (never crashes if the browser blocks it)
  // ===========================================================================
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } },
    del(k) { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } },
  };

  const state = {
    lang: store.get("crm.lang") || CONFIG.defaultLanguage,
    access: store.get("crm.access"),
    refresh: store.get("crm.refresh"),
    user: JSON.parse(store.get("crm.user") || "null"),
    cache: {},
  };

  // ===========================================================================
  // Translation & formatting
  // ===========================================================================
  function t(key, vars) {
    const dict = (window.I18N && window.I18N[state.lang]) || {};
    const en = (window.I18N && window.I18N.en) || {};
    let s = dict[key] != null ? dict[key] : (en[key] != null ? en[key] : key);
    if (vars) Object.keys(vars).forEach((k) => { s = s.split("{" + k + "}").join(vars[k]); });
    return s;
  }
  function tv(group, value) {
    if (value == null || value === "") return "—";
    const key = group + "." + value;
    const s = t(key);
    return s === key ? String(value).replace(/_/g, " ") : s;
  }
  const locale = () => LOCALES[state.lang] || "en-US";

  function parseDate(v) {
    if (!v) return null;
    let s = String(v);
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s) && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) s += "Z";
    const d = new Date(s);
    return isNaN(d) ? null : d;
  }
  function fmtDate(v) { const d = parseDate(v); return d ? d.toLocaleDateString(locale(), { year: "numeric", month: "short", day: "numeric" }) : "—"; }
  function fmtDateTime(v) { const d = parseDate(v); return d ? d.toLocaleString(locale(), { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"; }
  function fmtNum(v, digits) {
    if (v == null || v === "" || isNaN(v)) return "—";
    return Number(v).toLocaleString(locale(), { maximumFractionDigits: digits == null ? 2 : digits });
  }
  function fmtMoney(v) {
    if (v == null || v === "" || isNaN(v)) return "—";
    try { return Number(v).toLocaleString(locale(), { style: "currency", currency: CONFIG.currency, maximumFractionDigits: 0 }); }
    catch (e) { return fmtNum(v, 0) + " " + CONFIG.currency; }
  }
  function fmtPct(v) { return v == null || isNaN(v) ? "—" : fmtNum(v, 1) + "%"; }
  function fmtDuration(sec) {
    if (sec == null) return "—";
    sec = Math.round(sec);
    const m = Math.floor(sec / 60), s = sec % 60;
    return fmtNum(m, 0) + ":" + s.toLocaleString(locale(), { minimumIntegerDigits: 2 });
  }
  function fmtSize(bytes) {
    if (bytes == null) return "—";
    if (bytes < 1024) return fmtNum(bytes, 0) + " B";
    if (bytes < 1048576) return fmtNum(bytes / 1024, 1) + " KB";
    return fmtNum(bytes / 1048576, 1) + " MB";
  }
  function toDateInput(v) { const d = parseDate(v); return d ? d.toISOString().slice(0, 10) : ""; }

  function esc(v) {
    if (v == null) return "";
    return String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function applyLanguage() {
    document.documentElement.lang = state.lang;
    document.documentElement.dir = RTL.includes(state.lang) ? "rtl" : "ltr";
    document.title = CONFIG.appName;
  }
  function setLanguage(code) {
    state.lang = code;
    store.set("crm.lang", code);
    applyLanguage();
    route();
  }
  function langSelect(cls) {
    return `<select class="lang-select ${cls || ""}" data-lang-select aria-label="${esc(t("common.language"))}">` +
      LANGS.map((l) => `<option value="${l.code}" ${l.code === state.lang ? "selected" : ""}>${l.label}</option>`).join("") +
      `</select>`;
  }

  // ===========================================================================
  // Roles
  // ===========================================================================
  const role = () => (state.user && state.user.role) || "viewer";
  const isAdmin = () => role() === "admin";
  const canEdit = () => role() === "admin" || role() === "agent";

  // ===========================================================================
  // API
  // ===========================================================================
  class ApiError extends Error {
    constructor(message, status) { super(message); this.status = status; }
  }

  function errorMessage(body, status) {
    if (body && typeof body.detail === "string") return body.detail;
    if (body && Array.isArray(body.detail)) {
      return body.detail.map((d) => {
        const field = (d.loc || []).filter((x) => x !== "body" && x !== "query").join(".");
        return (field ? field + ": " : "") + (d.msg || "");
      }).join("\n");
    }
    if (status === 403) return t("error.forbidden");
    if (status === 404) return t("error.notFound");
    return t("error.generic");
  }

  function saveSession(tokens, user) {
    if (tokens) {
      state.access = tokens.access_token; state.refresh = tokens.refresh_token;
      store.set("crm.access", state.access); store.set("crm.refresh", state.refresh);
    }
    if (user) { state.user = user; store.set("crm.user", JSON.stringify(user)); }
  }
  function clearSession() {
    state.access = state.refresh = state.user = null;
    state.cache = {};
    ["crm.access", "crm.refresh", "crm.user"].forEach(store.del);
  }

  let refreshing = null;
  async function refreshTokens() {
    if (!state.refresh) return false;
    if (!refreshing) {
      refreshing = fetch(CONFIG.apiBase + "/auth/refresh", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: state.refresh }),
      }).then(async (r) => {
        if (!r.ok) return false;
        const j = await r.json();
        saveSession(j.data.tokens);
        return true;
      }).catch(() => false).finally(() => { setTimeout(() => { refreshing = null; }, 0); });
    }
    return refreshing;
  }

  async function api(path, opts) {
    opts = opts || {};
    let url = CONFIG.apiBase + path;
    if (opts.query) {
      const q = new URLSearchParams();
      Object.keys(opts.query).forEach((k) => {
        const v = opts.query[k];
        if (v !== undefined && v !== null && v !== "") q.append(k, v);
      });
      const qs = q.toString();
      if (qs) url += (url.includes("?") ? "&" : "?") + qs;
    }
    const headers = {};
    let body;
    if (opts.form) body = opts.form;
    else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
    if (state.access && !opts.noAuth) headers.Authorization = "Bearer " + state.access;

    let res;
    try { res = await fetch(url, { method: opts.method || "GET", headers, body }); }
    catch (e) { throw new ApiError(t("error.network"), 0); }

    if (res.status === 401 && !opts.noAuth && !opts._retried) {
      if (await refreshTokens()) return api(path, Object.assign({}, opts, { _retried: true }));
      clearSession();
      go("#/login");
      throw new ApiError(t("error.sessionExpired"), 401);
    }
    if (opts.raw) {
      if (!res.ok) throw new ApiError(errorMessage(await res.json().catch(() => null), res.status), res.status);
      return res;
    }
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
    if (!res.ok) throw new ApiError(errorMessage(data, res.status), res.status);
    return data;
  }

  // Cached look-ups used to show names instead of IDs
  async function cached(key, loader, force) {
    if (!force && state.cache[key] && Date.now() - state.cache[key].at < 60000) return state.cache[key].data;
    const data = await loader();
    state.cache[key] = { at: Date.now(), data };
    return data;
  }
  function invalidate() { Array.from(arguments).forEach((k) => delete state.cache[k]); }

  const lookups = {
    clients: () => cached("clients", async () => (await api("/clients", { query: { limit: 100 } })).clients || []),
    properties: () => cached("properties", async () => (await api("/properties", { query: { limit: 500 } })).data.properties || []),
    deals: () => cached("deals", async () => (await api("/deals", { query: { limit: 100 } })).deals || []),
    users: () => cached("users", async () => {
      if (!isAdmin()) return state.user ? [state.user] : [];
      return (await api("/auth/admin/users")).data.users || [];
    }),
  };
  async function safe(p, fallback) { try { return await p; } catch (e) { return fallback; } }
  const byId = (list) => { const m = {}; (list || []).forEach((x) => { m[x.id] = x; }); return m; };

  const clientName = (c) => c ? `${c.first_name || ""} ${c.last_name || ""}`.trim() || c.email : "—";
  const propertyLabel = (p) => {
    if (!p) return "—";
    const a = p.address || {};
    return [a.street, a.city].filter(Boolean).join(", ") || tv("ptype", p.type);
  };
  const userName = (u) => u ? (u.full_name || u.email) : "—";

  // ===========================================================================
  // UI helpers
  // ===========================================================================
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  function toast(message, kind) {
    const box = document.getElementById("toasts");
    const div = document.createElement("div");
    div.className = "toast " + (kind || "");
    div.textContent = message;
    box.appendChild(div);
    while (box.children.length > 3) box.removeChild(box.firstChild);
    setTimeout(() => div.remove(), kind === "error" ? 7000 : 3500);
  }
  const toastError = (e) => toast(e && e.message ? e.message : t("error.generic"), "error");

  function badge(group, value) {
    const colors = {
      available: "green", active: "green", won: "green", closed: "green", positive: "green", excellent: "green", good: "green", admin: "purple",
      pending: "amber", reserved: "amber", negotiation: "amber", inspection: "amber", appraisal: "amber", offer: "blue", neutral: "amber", fair: "amber", agent: "blue",
      sold: "blue", rented: "blue", lead: "blue", buyer: "blue", seller: "purple", both: "purple",
      lost: "red", expired: "red", delisted: "red", negative: "red", poor: "red", inactive: "", archived: "",
    };
    return `<span class="badge ${colors[value] || ""}">${esc(tv(group, value))}</span>`;
  }

  function options(list, group, selected, withEmpty) {
    let html = withEmpty ? `<option value="">${esc(withEmpty === true ? t("common.all") : withEmpty)}</option>` : "";
    list.forEach((v) => {
      const val = typeof v === "object" ? v.value : v;
      const label = typeof v === "object" ? v.label : (group ? tv(group, v) : v);
      html += `<option value="${esc(val)}" ${String(val) === String(selected == null ? "" : selected) ? "selected" : ""}>${esc(label)}</option>`;
    });
    return html;
  }

  const icons = {
    dashboard: '<path d="M3 13h8V3H3zm0 8h8v-6H3zm10 0h8V11h-8zm0-18v6h8V3z"/>',
    properties: '<path d="M12 3 2 12h3v8h6v-6h2v6h6v-8h3z"/>',
    clients: '<path d="M16 11c1.7 0 3-1.3 3-3s-1.3-3-3-3-3 1.3-3 3 1.3 3 3 3m-8 0c1.7 0 3-1.3 3-3S9.7 5 8 5 5 6.3 5 8s1.3 3 3 3m0 2c-2.3 0-7 1.2-7 3.5V19h14v-2.5C15 14.2 10.3 13 8 13m8 0c-.3 0-.6 0-1 .1 1.2.8 2 2 2 3.4V19h6v-2.5c0-2.3-4.7-3.5-7-3.5"/>',
    deals: '<path d="M20 6h-4V4c0-1.1-.9-2-2-2h-4c-1.1 0-2 .9-2 2v2H4c-1.1 0-2 .9-2 2v11c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2m-6 0h-4V4h4z"/>',
    calls: '<path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1C10.6 21 3 13.4 3 4c0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1z"/>',
    documents: '<path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8zm2 16H8v-2h8zm0-4H8v-2h8zm-3-5V3.5L18.5 9z"/>',
    users: '<path d="M12 12c2.2 0 4-1.8 4-4s-1.8-4-4-4-4 1.8-4 4 1.8 4 4 4m0 2c-2.7 0-8 1.3-8 4v2h16v-2c0-2.7-5.3-4-8-4"/>',
    profile: '<path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20m0 4a3 3 0 1 1 0 6 3 3 0 0 1 0-6m0 14.2a7.2 7.2 0 0 1-6-3.2c0-2 4-3.1 6-3.1s6 1.1 6 3.1a7.2 7.2 0 0 1-6 3.2"/>',
    menu: '<path d="M3 18h18v-2H3zm0-5h18v-2H3zm0-7v2h18V6z"/>',
    back: '<path d="M20 11H7.8l5.6-5.6L12 4l-8 8 8 8 1.4-1.4L7.8 13H20z"/>',
  };
  const icon = (name, cls) => `<svg class="icon ${cls || ""}" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">${icons[name]}</svg>`;

  // ---------- Modal ----------
  function openModal(opts) {
    // opts: { title, body (html), submitLabel, wide, onSubmit(form) -> Promise, danger }
    const root = document.getElementById("modal-root");
    root.innerHTML = `
      <div class="modal-backdrop" data-close>
        <form class="modal ${opts.wide ? "wide" : ""}" novalidate>
          <div class="modal-head"><h2>${esc(opts.title)}</h2>
            <button type="button" class="btn btn-ghost btn-sm" data-close aria-label="${esc(t("common.close"))}">✕</button></div>
          <div class="modal-body">${opts.body}</div>
          <div class="modal-foot">
            <button type="button" class="btn" data-close>${esc(t("common.cancel"))}</button>
            ${opts.onSubmit ? `<button type="submit" class="btn ${opts.danger ? "btn-danger" : "btn-primary"}">${esc(opts.submitLabel || t("common.save"))}</button>` : ""}
          </div>
        </form>
      </div>`;
    const form = $("form", root);
    const close = () => { root.innerHTML = ""; };
    $$("[data-close]", root).forEach((b) => b.addEventListener("click", (ev) => { if (ev.target === b) close(); }));
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (!opts.onSubmit) return close();
      const btn = $('button[type="submit"]', form);
      btn.disabled = true;
      try {
        const ok = await opts.onSubmit(form);
        if (ok !== false) close();
      } catch (e) { toastError(e); }
      finally { btn.disabled = false; }
    });
    if (opts.onOpen) opts.onOpen(form);
    const first = $("input:not([type=hidden]), select, textarea", form);
    if (first) first.focus();
    return { close, form };
  }
  function confirmDialog(message, onYes, label) {
    openModal({ title: t("common.confirm"), body: `<p>${esc(message)}</p>`, submitLabel: label || t("common.yes"), danger: true, onSubmit: onYes });
  }

  // Form value helpers
  const val = (form, name) => { const el = form.elements[name]; return el ? String(el.value).trim() : ""; };
  const num = (form, name) => { const v = val(form, name); return v === "" ? null : Number(v); };
  const int = (form, name) => { const v = val(form, name); return v === "" ? null : parseInt(v, 10); };
  const list = (form, name) => val(form, name).split(",").map((s) => s.trim()).filter(Boolean);
  const dateIso = (form, name) => { const v = val(form, name); return v ? v + "T00:00:00" : null; };
  function compact(obj) { const o = {}; Object.keys(obj).forEach((k) => { if (obj[k] !== null && obj[k] !== "" && obj[k] !== undefined) o[k] = obj[k]; }); return o; }

  const field = (label, input, extra) => `<div class="field ${extra || ""}"><label>${esc(label)}</label>${input}</div>`;
  const input = (name, value, attrs) => `<input name="${name}" value="${esc(value == null ? "" : value)}" ${attrs || ""}>`;
  const select = (name, html, attrs) => `<select name="${name}" ${attrs || ""}>${html}</select>`;
  const textarea = (name, value, attrs) => `<textarea name="${name}" ${attrs || ""}>${esc(value || "")}</textarea>`;

  // ===========================================================================
  // Router
  // ===========================================================================
  function go(hash) { if (location.hash === hash) route(); else location.hash = hash; }

  const routes = [
    [/^#\/login$/, viewLogin, true],
    [/^#\/setup$/, viewSetup, true],
    [/^#\/dashboard$/, viewDashboard],
    [/^#\/properties$/, viewProperties],
    [/^#\/properties\/([\w-]+)$/, viewProperty],
    [/^#\/clients$/, viewClients],
    [/^#\/clients\/([\w-]+)$/, viewClient],
    [/^#\/deals$/, viewDeals],
    [/^#\/deals\/([\w-]+)$/, viewDeal],
    [/^#\/calls$/, viewCalls],
    [/^#\/calls\/([\w-]+)$/, viewCall],
    [/^#\/documents$/, viewDocuments],
    [/^#\/documents\/([\w-]+)$/, viewDocument],
    [/^#\/users$/, viewUsers],
    [/^#\/profile$/, viewProfile],
  ];

  let routeToken = 0;
  async function route() {
    applyLanguage();
    document.getElementById("modal-root").innerHTML = "";
    const hash = location.hash || "";
    const myToken = ++routeToken;
    for (const [re, fn, isPublic] of routes) {
      const m = hash.match(re);
      if (!m) continue;
      if (!isPublic && !state.access) return go("#/login");
      if (isPublic && state.access && hash === "#/login") return go("#/dashboard");
      try { await fn(m[1], () => myToken === routeToken); }
      catch (e) {
        if (myToken !== routeToken) return;
        if (e.status === 401) return;
        setContent(`<div class="card"><div class="empty">${esc(e.message)}</div></div>`);
      }
      return;
    }
    go(state.access ? "#/dashboard" : "#/login");
  }
  window.addEventListener("hashchange", route);

  // ===========================================================================
  // Layout
  // ===========================================================================
  function navItems() {
    const items = [
      ["dashboard", "#/dashboard"], ["properties", "#/properties"], ["clients", "#/clients"], ["deals", "#/deals"],
    ];
    if (canEdit()) items.push(["calls", "#/calls"], ["documents", "#/documents"]);
    if (isAdmin()) items.push(["users", "#/users"]);
    items.push(["profile", "#/profile"]);
    return items;
  }

  function renderShell(section, title) {
    const app = document.getElementById("app");
    app.innerHTML = `
      <div class="shell">
        <aside class="sidebar">
          <div class="brand"><div class="brand-mark">A</div><div>${esc(CONFIG.appName)}</div></div>
          <nav class="nav">
            ${navItems().map(([k, href]) => `<a href="${href}" class="${k === section ? "active" : ""}">${icon(k)}<span>${esc(t("nav." + k))}</span></a>`).join("")}
          </nav>
          <div class="sidebar-foot">
            <div class="who">${esc(userName(state.user))}</div>
            <div>${esc(tv("role", role()))}</div>
          </div>
        </aside>
        <div class="main">
          <header class="topbar">
            <div class="topbar-left">
              <button class="btn btn-ghost btn-sm menu-btn" data-menu aria-label="${esc(t("common.menu"))}">${icon("menu")}</button>
              <strong>${esc(title || "")}</strong>
            </div>
            <div class="topbar-right">
              ${langSelect()}
              <button class="btn btn-sm" data-logout>${esc(t("auth.logout"))}</button>
            </div>
          </header>
          <main class="content" id="content"><div class="loading">${esc(t("common.loading"))}</div></main>
        </div>
      </div>`;
    wireCommon(app);
    $("[data-menu]", app).addEventListener("click", () => $(".shell", app).classList.toggle("nav-open"));
    $$(".nav a", app).forEach((a) => a.addEventListener("click", () => $(".shell", app).classList.remove("nav-open")));
    $("[data-logout]", app).addEventListener("click", async () => {
      try { await api("/auth/logout", { method: "POST" }); } catch (e) { /* ignore */ }
      clearSession();
      go("#/login");
    });
  }
  function wireCommon(root) {
    $$("[data-lang-select]", root).forEach((s) => s.addEventListener("change", () => setLanguage(s.value)));
  }
  function setContent(html) {
    const c = document.getElementById("content");
    if (c) c.innerHTML = html;
    return c;
  }
  function pageHead(title, sub, actions, backHref) {
    return `${backHref ? `<a class="back" href="${backHref}">${icon("back", "flip")} ${esc(t("common.back"))}</a>` : ""}
      <div class="page-head"><div><h1>${esc(title)}</h1>${sub ? `<div class="sub">${sub}</div>` : ""}</div>
      <div class="actions">${actions || ""}</div></div>`;
  }
  const emptyRow = (cols, msg) => `<tr><td colspan="${cols}"><div class="empty">${esc(msg || t("common.noResults"))}</div></td></tr>`;
  function pager(total, skip, limit) {
    if (!total || total <= limit) return "";
    const from = skip + 1, to = Math.min(skip + limit, total);
    return `<div class="pager"><span class="muted">${esc(t("common.showing", { from: fmtNum(from, 0), to: fmtNum(to, 0), total: fmtNum(total, 0) }))}</span>
      <span class="actions"><button class="btn btn-sm" data-page="prev" ${skip <= 0 ? "disabled" : ""}>${esc(t("common.prev"))}</button>
      <button class="btn btn-sm" data-page="next" ${to >= total ? "disabled" : ""}>${esc(t("common.next"))}</button></span></div>`;
  }
  function wirePager(root, onPage) {
    $$("[data-page]", root).forEach((b) => b.addEventListener("click", () => onPage(b.dataset.page)));
  }
  function wireRowLinks(root) {
    $$("tr[data-href]", root).forEach((tr) => tr.addEventListener("click", () => go(tr.dataset.href)));
  }

  // ===========================================================================
  // Auth pages
  // ===========================================================================
  function authPage(inner) {
    document.getElementById("app").innerHTML = `
      <div class="auth-wrap"><div class="auth-card">
        <div class="brand-line"><div class="brand-mark">A</div><div>${esc(CONFIG.appName)}</div></div>
        ${inner}
      </div></div>`;
    wireCommon(document.getElementById("app"));
  }

  async function viewLogin() {
    authPage(`
      <h2>${esc(t("auth.signIn"))}</h2>
      <p class="muted">${esc(t("auth.signInHelp"))}</p>
      <form class="form" id="login-form" novalidate>
        ${field(t("field.email"), input("email", "", 'type="email" autocomplete="username" required'))}
        ${field(t("field.password"), input("password", "", 'type="password" autocomplete="current-password" required'))}
        <button class="btn btn-primary btn-block" type="submit">${esc(t("auth.signIn"))}</button>
      </form>
      <div class="auth-foot"><a href="#/setup">${esc(t("auth.firstTime"))}</a>${langSelect()}</div>`);
    const form = $("#login-form");
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const btn = $("button[type=submit]", form);
      btn.disabled = true;
      try {
        const res = await api("/auth/login", { method: "POST", noAuth: true, body: { email: val(form, "email"), password: form.elements.password.value } });
        saveSession(res.data.tokens, res.data.user);
        if (!store.get("crm.lang") && res.data.user.preferred_language && LOCALES[res.data.user.preferred_language]) {
          state.lang = res.data.user.preferred_language;
        }
        go("#/dashboard");
      } catch (e) { toastError(e); }
      finally { btn.disabled = false; }
    });
  }

  async function viewSetup() {
    authPage(`
      <h2>${esc(t("auth.setupTitle"))}</h2>
      <p class="muted">${esc(t("auth.setupHelp"))}</p>
      <form class="form" id="setup-form" novalidate>
        ${field(t("field.companyName"), input("organization_name", "", "required"))}
        <div class="form-grid">
          ${field(t("field.firstName"), input("first_name", "", "required"))}
          ${field(t("field.lastName"), input("last_name", "", "required"))}
        </div>
        ${field(t("field.email"), input("email", "", 'type="email" required'))}
        ${field(t("field.phone"), input("phone", "", 'type="tel"'))}
        ${field(t("field.password"), input("password", "", 'type="password" autocomplete="new-password" required') + `<span class="help">${esc(t("auth.passwordRules"))}</span>`)}
        ${field(t("field.confirmPassword"), input("confirm", "", 'type="password" autocomplete="new-password" required'))}
        <button class="btn btn-primary btn-block" type="submit">${esc(t("auth.createAccount"))}</button>
      </form>
      <div class="auth-foot"><a href="#/login">${esc(t("auth.backToLogin"))}</a>${langSelect()}</div>`);
    const form = $("#setup-form");
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (form.elements.password.value !== form.elements.confirm.value) return toast(t("auth.passwordsDontMatch"), "error");
      const btn = $("button[type=submit]", form);
      btn.disabled = true;
      try {
        await api("/auth/setup", { method: "POST", noAuth: true, body: compact({
          organization_name: val(form, "organization_name"), first_name: val(form, "first_name"), last_name: val(form, "last_name"),
          email: val(form, "email"), phone: val(form, "phone"), password: form.elements.password.value,
        }) });
        toast(t("auth.setupDone"), "success");
        go("#/login");
      } catch (e) {
        if (e.status === 403) toast(t("auth.setupAlreadyDone"), "error"); else toastError(e);
      } finally { btn.disabled = false; }
    });
  }

  // ===========================================================================
  // Dashboard
  // ===========================================================================
  async function viewDashboard(_, alive) {
    renderShell("dashboard", t("nav.dashboard"));
    const [pStats, cStats, dStats, pipeline, forecast, followups, callStats, deals, clients, properties] = await Promise.all([
      safe(api("/properties/stats/organization").then((r) => r.data.statistics), null),
      isAdmin() ? safe(api("/clients/admin/stats"), null) : null,
      isAdmin() ? safe(api("/deals/admin/stats"), null) : null,
      isAdmin() ? safe(api("/deals/admin/pipeline"), null) : null,
      isAdmin() ? safe(api("/deals/admin/forecast"), null) : null,
      canEdit() ? safe(api("/clients/admin/pending-follow-ups"), []) : [],
      isAdmin() ? safe(api("/calls/admin/stats").then((r) => r.stats), null) : null,
      safe(lookups.deals(), []),
      safe(lookups.clients(), []),
      safe(lookups.properties(), []),
    ]);
    if (!alive()) return;
    const cmap = byId(clients), pmap = byId(properties);
    const activeDeals = deals.filter((d) => d.status === "active");

    const kpi = (label, value, hint) => `<div class="card kpi"><div class="label">${esc(label)}</div><div class="value">${value}</div>${hint ? `<div class="hint">${hint}</div>` : ""}</div>`;
    const kpis = [
      kpi(t("dash.properties"), fmtNum(pStats ? pStats.total_properties : properties.length, 0),
        pStats ? esc(t("dash.availableCount", { n: fmtNum(pStats.available, 0) })) : ""),
      kpi(t("dash.clients"), fmtNum(cStats ? cStats.total_clients : clients.length, 0),
        cStats ? esc(t("dash.activeCount", { n: fmtNum(cStats.active, 0) })) : ""),
      kpi(t("dash.activeDeals"), fmtNum(dStats ? dStats.active_deals : activeDeals.length, 0),
        dStats ? esc(t("dash.winRate", { n: fmtPct(dStats.win_rate) })) : ""),
      kpi(t("dash.pipelineValue"), fmtMoney(pipeline ? pipeline.total_pipeline_value : activeDeals.reduce((s, d) => s + (d.offer_price || d.proposed_price || 0), 0)),
        forecast ? esc(t("dash.probableCommission", { n: fmtMoney(forecast.probable) })) : ""),
    ];
    if (pStats) kpis.push(kpi(t("dash.avgPrice"), fmtMoney(pStats.average_price), esc(t("dash.soldCount", { n: fmtNum(pStats.sold, 0) }))));
    if (callStats) kpis.push(kpi(t("dash.calls30"), fmtNum(callStats.total_calls, 0), esc(t("dash.avgDuration", { n: fmtDuration(callStats.average_duration) }))));
    if (forecast) kpis.push(kpi(t("dash.forecastBest"), fmtMoney(forecast.best_case), esc(t("dash.forecastHint"))));

    // Pipeline by stage (from the deals themselves so every role sees it)
    const byStage = {};
    DEAL_STAGES.forEach((s) => { byStage[s] = { count: 0, value: 0 }; });
    activeDeals.forEach((d) => { if (byStage[d.stage]) { byStage[d.stage].count++; byStage[d.stage].value += Number(d.offer_price || d.proposed_price || 0); } });
    const maxCount = Math.max(1, ...DEAL_STAGES.map((s) => byStage[s].count));
    const bars = DEAL_STAGES.map((s) => `<div class="bar-row"><span>${esc(tv("stage", s))}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${(byStage[s].count / maxCount) * 100}%"></div></div>
      <span class="v">${fmtNum(byStage[s].count, 0)} · ${fmtMoney(byStage[s].value)}</span></div>`).join("");

    const fu = (followups || []).slice(0, 8).map((f) => `<li><a href="#/clients/${f.client_id}"><strong>${esc(clientName(cmap[f.client_id]))}</strong></a>
      · ${esc(tv("interaction", f.type))}<div class="muted small">${esc(t("dash.dueOn", { d: fmtDate(f.follow_up_date) }))}${f.description ? " · " + esc(f.description) : ""}</div></li>`).join("");

    const recent = deals.slice(0, 6).map((d) => `<tr class="clickable" data-href="#/deals/${d.id}">
      <td>${esc(clientName(cmap[d.client_id]))}</td><td class="hide-sm">${esc(propertyLabel(pmap[d.property_id]))}</td>
      <td>${badge("stage", d.stage)}</td><td class="num">${fmtMoney(d.offer_price || d.proposed_price)}</td></tr>`).join("");

    const c = setContent(`
      ${pageHead(t("dash.welcome", { name: (state.user && state.user.first_name) || "" }), esc(t("dash.subtitle")))}
      <div class="grid grid-4">${kpis.join("")}</div>
      <div class="grid grid-2" style="margin-top:16px">
        <div class="card"><div class="card-head"><h2>${esc(t("dash.pipeline"))}</h2><a href="#/deals">${esc(t("common.viewAll"))}</a></div>
          <div class="card-body"><div class="bars">${bars}</div></div></div>
        <div class="card"><div class="card-head"><h2>${esc(t("dash.followups"))}</h2></div>
          <div class="card-body">${fu ? `<ul class="list-plain">${fu}</ul>` : `<div class="empty">${esc(t("dash.noFollowups"))}</div>`}</div></div>
      </div>
      <div class="card" style="margin-top:16px"><div class="card-head"><h2>${esc(t("dash.recentDeals"))}</h2><a href="#/deals">${esc(t("common.viewAll"))}</a></div>
        <div class="table-wrap"><table><thead><tr><th>${esc(t("field.client"))}</th><th class="hide-sm">${esc(t("field.property"))}</th><th>${esc(t("field.stage"))}</th><th class="num">${esc(t("field.price"))}</th></tr></thead>
        <tbody>${recent || emptyRow(4, t("deals.none"))}</tbody></table></div></div>`);
    wireRowLinks(c);
  }

  // ===========================================================================
  // Properties
  // ===========================================================================
  const propFilters = { skip: 0 };

  async function viewProperties(_, alive) {
    renderShell("properties", t("nav.properties"));
    const f = propFilters;
    let data, total = 0;
    if (f.q) {
      const r = await api("/properties/search/text", { query: { q: f.q, limit: 100 } });
      data = r.data.properties; total = r.data.total;
    } else {
      const r = await api("/properties", { query: {
        skip: f.skip, limit: CONFIG.pageSize, status: f.status, property_type: f.type,
        min_price: f.min_price, max_price: f.max_price, min_bedrooms: f.min_bedrooms, city: f.city,
      } });
      data = r.data.properties; total = r.data.pagination.total;
    }
    if (!alive()) return;
    const rows = data.map((p) => `<tr class="clickable" data-href="#/properties/${p.id}">
      <td><strong>${esc(propertyLabel(p))}</strong><div class="muted small">${esc([p.address && p.address.state, p.address && p.address.country].filter(Boolean).join(", "))}</div></td>
      <td>${esc(tv("ptype", p.type))}</td><td>${badge("pstatus", p.status)}</td>
      <td class="num">${fmtMoney(p.list_price)}</td><td class="num hide-sm">${fmtNum(p.bedrooms, 0)}</td>
      <td class="num hide-sm">${fmtNum(p.bathrooms, 1)}</td><td class="num hide-sm">${fmtNum(p.square_feet, 0)}</td></tr>`).join("");

    const c = setContent(`
      ${pageHead(t("nav.properties"), esc(t("props.subtitle", { n: fmtNum(total, 0) })),
        canEdit() ? `<button class="btn btn-primary" data-add>${esc(t("props.add"))}</button>` : "")}
      <form class="filters" id="pf">
        ${field(t("common.search"), input("q", f.q, `placeholder="${esc(t("props.searchHint"))}"`), "grow")}
        ${field(t("field.status"), select("status", options(PROPERTY_STATUSES, "pstatus", f.status, true)))}
        ${field(t("field.type"), select("type", options(PROPERTY_TYPES, "ptype", f.type, true)))}
        ${field(t("field.city"), input("city", f.city))}
        ${field(t("field.minPrice"), input("min_price", f.min_price, 'type="number" min="0"'))}
        ${field(t("field.maxPrice"), input("max_price", f.max_price, 'type="number" min="0"'))}
        ${field(t("field.minBedrooms"), input("min_bedrooms", f.min_bedrooms, 'type="number" min="0"'))}
        <div class="actions"><button class="btn btn-primary" type="submit">${esc(t("common.apply"))}</button><button class="btn" type="button" data-reset>${esc(t("common.reset"))}</button></div>
      </form>
      <div class="card"><div class="table-wrap"><table>
        <thead><tr><th>${esc(t("field.address"))}</th><th>${esc(t("field.type"))}</th><th>${esc(t("field.status"))}</th><th class="num">${esc(t("field.price"))}</th>
        <th class="num hide-sm">${esc(t("field.bedrooms"))}</th><th class="num hide-sm">${esc(t("field.bathrooms"))}</th><th class="num hide-sm">${esc(t("field.area"))}</th></tr></thead>
        <tbody>${rows || emptyRow(7, t("props.none"))}</tbody></table></div>
        ${f.q ? "" : pager(total, f.skip, CONFIG.pageSize)}</div>`);
    wireRowLinks(c);
    const form = $("#pf", c);
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      Object.assign(propFilters, { skip: 0, q: val(form, "q"), status: val(form, "status"), type: val(form, "type"), city: val(form, "city"),
        min_price: val(form, "min_price"), max_price: val(form, "max_price"), min_bedrooms: val(form, "min_bedrooms") });
      route();
    });
    $("[data-reset]", c).addEventListener("click", () => { Object.keys(propFilters).forEach((k) => delete propFilters[k]); propFilters.skip = 0; route(); });
    wirePager(c, (dir) => { propFilters.skip = Math.max(0, propFilters.skip + (dir === "next" ? 1 : -1) * CONFIG.pageSize); route(); });
    const add = $("[data-add]", c);
    if (add) add.addEventListener("click", () => propertyForm());
  }

  function propertyForm() {
    openModal({
      title: t("props.add"), wide: true, submitLabel: t("common.create"),
      body: `<div class="form-grid">
        ${field(t("field.street"), input("street", "", "required"), "full")}
        ${field(t("field.city"), input("city", "", "required"))}
        ${field(t("field.state"), input("state", "", "required"))}
        ${field(t("field.zip"), input("zip_code", "", "required"))}
        ${field(t("field.country"), input("country", ""))}
        ${field(t("field.type"), select("property_type", options(PROPERTY_TYPES, "ptype", "apartment")))}
        ${field(t("field.listPrice"), input("list_price", "", 'type="number" min="1" step="any" required'))}
        ${field(t("field.bedrooms"), input("bedrooms", "", 'type="number" min="0"'))}
        ${field(t("field.bathrooms"), input("bathrooms", "", 'type="number" min="0" step="0.5"'))}
        ${field(t("field.area"), input("square_feet", "", 'type="number" min="0" step="any"'))}
        ${field(t("field.lotSize"), input("lot_size", "", 'type="number" min="0" step="any"'))}
        ${field(t("field.yearBuilt"), input("year_built", "", 'type="number" min="1800" max="2100"'))}
        ${field(t("field.features"), input("features", "", `placeholder="${esc(t("props.featuresHint"))}"`), "full")}
        ${field(t("field.description"), textarea("description", ""), "full")}
      </div>`,
      onSubmit: async (form) => {
        const required = ["street", "city", "state", "zip_code", "list_price"];
        if (required.some((n) => !val(form, n))) { toast(t("error.required"), "error"); return false; }
        const res = await api("/properties", { method: "POST", body: compact({
          address: { street: val(form, "street"), city: val(form, "city"), state: val(form, "state"), zip_code: val(form, "zip_code"), country: val(form, "country") || undefined },
          property_type: val(form, "property_type"), list_price: num(form, "list_price"), bedrooms: int(form, "bedrooms"),
          bathrooms: num(form, "bathrooms"), square_feet: num(form, "square_feet"), lot_size: num(form, "lot_size"),
          year_built: int(form, "year_built"), features: list(form, "features"), description: val(form, "description"),
        }) });
        invalidate("properties");
        toast(t("common.saved"), "success");
        go("#/properties/" + res.data.property.id);
      },
    });
  }

  async function viewProperty(id, alive) {
    renderShell("properties", t("nav.properties"));
    const [pr, hist, deals, clients, docs] = await Promise.all([
      api("/properties/" + id),
      safe(api(`/properties/${id}/history`), null),
      safe(lookups.deals(), []),
      safe(lookups.clients(), []),
      canEdit() ? safe(api("/documents", { query: { property_id: id, limit: 50 } }), null) : null,
    ]);
    if (!alive()) return;
    const p = pr.data.property;
    const a = p.address || {};
    const cmap = byId(clients);
    const pDeals = deals.filter((d) => d.property_id === id);

    const priceHist = (p.price_history || []).slice().reverse().map((h) => `<li><div><strong>${fmtMoney(h.price)}</strong>${h.reason ? " · " + esc(h.reason === "initial_listing" ? t("props.initialListing") : h.reason) : ""}</div>
      <div class="when">${fmtDateTime(h.changed_at || h.date)}</div></li>`).join("");
    const statusHist = ((hist && hist.data.status_history) || []).map((h) => `<li><div>${badge("pstatus", h.status_from)} → ${badge("pstatus", h.status_to)}${h.reason ? " · " + esc(h.reason) : ""}</div>
      <div class="when">${fmtDateTime(h.changed_at)}</div></li>`).join("");
    const dealRows = pDeals.map((d) => `<tr class="clickable" data-href="#/deals/${d.id}"><td>${esc(clientName(cmap[d.client_id]))}</td>
      <td>${badge("stage", d.stage)}</td><td>${badge("dstatus", d.status)}</td><td class="num">${fmtMoney(d.offer_price || d.proposed_price)}</td></tr>`).join("");
    const docRows = docs ? (docs.data || []).map((d) => `<tr class="clickable" data-href="#/documents/${d.id}"><td>${esc(d.name)}</td><td>${esc(tv("doctype", d.document_type))}</td><td class="muted">${fmtDate(d.created_at)}</td></tr>`).join("") : "";

    const actions = [
      canEdit() ? `<button class="btn" data-act="edit">${esc(t("common.edit"))}</button>` : "",
      canEdit() ? `<button class="btn" data-act="price">${esc(t("props.changePrice"))}</button>` : "",
      canEdit() ? `<button class="btn" data-act="status">${esc(t("props.changeStatus"))}</button>` : "",
      isAdmin() ? `<button class="btn btn-danger" data-act="delete">${esc(t("common.delete"))}</button>` : "",
    ].join("");

    const c = setContent(`
      ${pageHead(propertyLabel(p), `${badge("pstatus", p.status)} &nbsp; <strong>${fmtMoney(p.list_price)}</strong>`, actions, "#/properties")}
      <div class="grid grid-2">
        <div class="card"><div class="card-head"><h2>${esc(t("common.details"))}</h2></div><div class="card-body"><dl class="dl">
          <dt>${esc(t("field.address"))}</dt><dd>${esc([a.street, a.city, a.state, a.zip_code, a.country].filter(Boolean).join(", "))}</dd>
          <dt>${esc(t("field.type"))}</dt><dd>${esc(tv("ptype", p.type))}</dd>
          <dt>${esc(t("field.bedrooms"))}</dt><dd>${fmtNum(p.bedrooms, 0)}</dd>
          <dt>${esc(t("field.bathrooms"))}</dt><dd>${fmtNum(p.bathrooms, 1)}</dd>
          <dt>${esc(t("field.area"))}</dt><dd>${fmtNum(p.square_feet, 0)}</dd>
          <dt>${esc(t("field.lotSize"))}</dt><dd>${fmtNum(p.lot_size, 0)}</dd>
          <dt>${esc(t("field.yearBuilt"))}</dt><dd>${p.year_built || "—"}</dd>
          <dt>${esc(t("field.features"))}</dt><dd>${(p.features || []).length ? `<div class="chips">${p.features.map((x) => `<span class="chip">${esc(x)}</span>`).join("")}</div>` : "—"}</dd>
          <dt>${esc(t("field.description"))}</dt><dd>${esc(p.description || "—")}</dd>
          <dt>${esc(t("field.created"))}</dt><dd>${fmtDateTime(p.created_at)}</dd>
        </dl></div></div>
        <div class="stack">
          <div class="card"><div class="card-head"><h2>${esc(t("props.priceHistory"))}</h2></div><div class="card-body">${priceHist ? `<ul class="timeline">${priceHist}</ul>` : `<div class="empty">—</div>`}</div></div>
          <div class="card"><div class="card-head"><h2>${esc(t("props.statusHistory"))}</h2></div><div class="card-body">${statusHist ? `<ul class="timeline">${statusHist}</ul>` : `<div class="empty">${esc(t("props.noStatusChanges"))}</div>`}</div></div>
        </div>
      </div>
      <div class="card" style="margin-top:16px"><div class="card-head"><h2>${esc(t("nav.deals"))}</h2></div>
        <div class="table-wrap"><table><thead><tr><th>${esc(t("field.client"))}</th><th>${esc(t("field.stage"))}</th><th>${esc(t("field.status"))}</th><th class="num">${esc(t("field.price"))}</th></tr></thead>
        <tbody>${dealRows || emptyRow(4, t("deals.none"))}</tbody></table></div></div>
      ${docs ? `<div class="card" style="margin-top:16px"><div class="card-head"><h2>${esc(t("nav.documents"))}</h2></div>
        <div class="table-wrap"><table><thead><tr><th>${esc(t("field.name"))}</th><th>${esc(t("field.type"))}</th><th>${esc(t("field.created"))}</th></tr></thead>
        <tbody>${docRows || emptyRow(3, t("docs.none"))}</tbody></table></div></div>` : ""}`);
    wireRowLinks(c);

    const act = (name, fn) => { const b = $(`[data-act="${name}"]`, c); if (b) b.addEventListener("click", fn); };
    act("edit", () => openModal({
      title: t("common.edit"), wide: true,
      body: `<div class="form-grid">
        ${field(t("field.bedrooms"), input("bedrooms", p.bedrooms, 'type="number" min="0"'))}
        ${field(t("field.bathrooms"), input("bathrooms", p.bathrooms, 'type="number" min="0" step="0.5"'))}
        ${field(t("field.area"), input("square_feet", p.square_feet, 'type="number" min="0" step="any"'))}
        ${field(t("field.lotSize"), input("lot_size", p.lot_size, 'type="number" min="0" step="any"'))}
        ${field(t("field.features"), input("features", (p.features || []).join(", ")), "full")}
        ${field(t("field.description"), textarea("description", p.description), "full")}
        <p class="muted small full">${esc(t("props.editNote"))}</p></div>`,
      onSubmit: async (form) => {
        await api("/properties/" + id, { method: "PATCH", body: compact({
          bedrooms: int(form, "bedrooms"), bathrooms: num(form, "bathrooms"), square_feet: num(form, "square_feet"),
          lot_size: num(form, "lot_size"), features: list(form, "features"), description: val(form, "description"),
        }) });
        invalidate("properties"); toast(t("common.saved"), "success"); route();
      },
    }));
    act("price", () => openModal({
      title: t("props.changePrice"),
      body: `<div class="form">${field(t("field.newPrice"), input("new_price", p.list_price, 'type="number" min="1" step="any" required'))}
        ${field(t("field.reason"), input("reason", ""))}</div>`,
      onSubmit: async (form) => {
        if (!num(form, "new_price")) { toast(t("error.required"), "error"); return false; }
        await api(`/properties/${id}/price`, { method: "PATCH", body: compact({ new_price: num(form, "new_price"), reason: val(form, "reason") }) });
        invalidate("properties"); toast(t("common.saved"), "success"); route();
      },
    }));
    act("status", () => openModal({
      title: t("props.changeStatus"),
      body: `<div class="form">${field(t("field.status"), select("status", options(PROPERTY_STATUSES, "pstatus", p.status)))}
        ${field(t("field.notes"), input("notes", ""))}</div>`,
      onSubmit: async (form) => {
        await api(`/properties/${id}/status`, { method: "PATCH", body: compact({ status: val(form, "status"), notes: val(form, "notes") }) });
        invalidate("properties"); toast(t("common.saved"), "success"); route();
      },
    }));
    act("delete", () => confirmDialog(t("props.confirmDelete"), async () => {
      await api("/properties/" + id, { method: "DELETE" });
      invalidate("properties"); toast(t("common.deleted"), "success"); go("#/properties");
    }, t("common.delete")));
  }

  // ===========================================================================
  // Clients
  // ===========================================================================
  const clientFilters = { skip: 0, sort_by: "created_at", sort_order: "desc" };

  async function viewClients(_, alive) {
    renderShell("clients", t("nav.clients"));
    const f = clientFilters;
    const r = await api("/clients", { query: { skip: f.skip, limit: CONFIG.pageSize, client_type: f.type, status: f.status, search: f.search, sort_by: f.sort_by, sort_order: f.sort_order } });
    if (!alive()) return;
    const budget = (c) => (c.budget_min || c.budget_max) ? `${fmtMoney(c.budget_min)} – ${fmtMoney(c.budget_max)}` : "—";
    const rows = (r.clients || []).map((cl) => `<tr class="clickable" data-href="#/clients/${cl.id}">
      <td><strong>${esc(clientName(cl))}</strong><div class="muted small">${esc(cl.email || "")}</div></td>
      <td class="hide-sm">${esc(cl.phone || "—")}</td><td>${badge("ctype", cl.type)}</td><td>${badge("cstatus", cl.status)}</td>
      <td class="hide-sm">${budget(cl)}</td><td class="num hide-sm">${fmtNum(cl.interaction_count || 0, 0)}</td>
      <td class="hide-sm muted">${fmtDate(cl.last_interaction_at)}</td></tr>`).join("");
    const c = setContent(`
      ${pageHead(t("nav.clients"), esc(t("clients.subtitle", { n: fmtNum(r.total, 0) })),
        canEdit() ? `<button class="btn btn-primary" data-add>${esc(t("clients.add"))}</button>` : "")}
      <form class="filters" id="cf">
        ${field(t("common.search"), input("search", f.search, `placeholder="${esc(t("clients.searchHint"))}"`), "grow")}
        ${field(t("field.type"), select("type", options(CLIENT_TYPES, "ctype", f.type, true)))}
        ${field(t("field.status"), select("status", options(CLIENT_STATUSES, "cstatus", f.status, true)))}
        ${field(t("common.sortBy"), select("sort_by", options([
          { value: "created_at", label: t("clients.sortNewest") }, { value: "name", label: t("clients.sortName") }, { value: "last_interaction", label: t("clients.sortLastContact") },
        ], null, f.sort_by)))}
        <div class="actions"><button class="btn btn-primary" type="submit">${esc(t("common.apply"))}</button><button class="btn" type="button" data-reset>${esc(t("common.reset"))}</button></div>
      </form>
      <div class="card"><div class="table-wrap"><table>
        <thead><tr><th>${esc(t("field.name"))}</th><th class="hide-sm">${esc(t("field.phone"))}</th><th>${esc(t("field.type"))}</th><th>${esc(t("field.status"))}</th>
        <th class="hide-sm">${esc(t("field.budget"))}</th><th class="num hide-sm">${esc(t("clients.interactions"))}</th><th class="hide-sm">${esc(t("clients.lastContact"))}</th></tr></thead>
        <tbody>${rows || emptyRow(7, t("clients.none"))}</tbody></table></div>${pager(r.total, f.skip, CONFIG.pageSize)}</div>`);
    wireRowLinks(c);
    const form = $("#cf", c);
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      Object.assign(clientFilters, { skip: 0, search: val(form, "search"), type: val(form, "type"), status: val(form, "status"), sort_by: val(form, "sort_by"),
        sort_order: val(form, "sort_by") === "name" ? "asc" : "desc" });
      route();
    });
    $("[data-reset]", c).addEventListener("click", () => { Object.keys(clientFilters).forEach((k) => delete clientFilters[k]); Object.assign(clientFilters, { skip: 0, sort_by: "created_at", sort_order: "desc" }); route(); });
    wirePager(c, (dir) => { clientFilters.skip = Math.max(0, clientFilters.skip + (dir === "next" ? 1 : -1) * CONFIG.pageSize); route(); });
    const add = $("[data-add]", c);
    if (add) add.addEventListener("click", () => clientForm());
  }

  function typeCheckboxes(selected) {
    return `<div class="chips">${PROPERTY_TYPES.map((pt) => `<label class="chip"><input type="checkbox" name="pt_${pt}" ${(selected || []).includes(pt) ? "checked" : ""}> ${esc(tv("ptype", pt))}</label>`).join("")}</div>`;
  }
  const checkedTypes = (form) => PROPERTY_TYPES.filter((pt) => form.elements["pt_" + pt] && form.elements["pt_" + pt].checked);

  function clientForm(existing) {
    const cl = existing || {};
    const isNew = !existing;
    openModal({
      title: isNew ? t("clients.add") : t("common.edit"), wide: true, submitLabel: isNew ? t("common.create") : t("common.save"),
      body: `<div class="form-grid">
        ${field(t("field.firstName"), input("first_name", cl.first_name, "required"))}
        ${field(t("field.lastName"), input("last_name", cl.last_name, "required"))}
        ${field(t("field.email"), input("email", cl.email, 'type="email" required'))}
        ${field(t("field.phone"), input("phone", cl.phone, 'type="tel"'))}
        ${field(t("field.type"), select("client_type", options(CLIENT_TYPES, "ctype", cl.type || "buyer")))}
        ${field(t("field.status"), select("status", options(CLIENT_STATUSES, "cstatus", cl.status || "active")))}
        ${isNew ? `
          ${field(t("field.budgetMin"), input("budget_min", "", 'type="number" min="1" step="any"'))}
          ${field(t("field.budgetMax"), input("budget_max", "", 'type="number" min="1" step="any"'))}
          ${field(t("field.bedrooms"), input("bedrooms", "", 'type="number" min="0"'))}
          ${field(t("field.cities"), input("cities", "", `placeholder="${esc(t("clients.citiesHint"))}"`))}
          ${field(t("field.propertyTypes"), typeCheckboxes([]), "full")}` : ""}
        ${field(t("field.notes"), textarea("notes", cl.notes), "full")}
      </div>`,
      onSubmit: async (form) => {
        if (!val(form, "first_name") || !val(form, "last_name") || !val(form, "email")) { toast(t("error.required"), "error"); return false; }
        const base = { first_name: val(form, "first_name"), last_name: val(form, "last_name"), email: val(form, "email"), phone: val(form, "phone"),
          client_type: val(form, "client_type"), status: val(form, "status"), notes: val(form, "notes") };
        if (isNew) {
          const cities = list(form, "cities");
          const prefs = compact({ budget_min: num(form, "budget_min"), budget_max: num(form, "budget_max"), bedrooms: int(form, "bedrooms"),
            property_types: checkedTypes(form).length ? checkedTypes(form) : null, location_preferences: cities.length ? { cities } : null });
          const res = await api("/clients", { method: "POST", body: compact(Object.assign(base, { preferences: Object.keys(prefs).length ? prefs : null })) });
          invalidate("clients"); toast(t("common.saved"), "success"); go("#/clients/" + res.id);
        } else {
          await api("/clients/" + cl.id, { method: "PATCH", body: compact(base) });
          invalidate("clients"); toast(t("common.saved"), "success"); route();
        }
      },
    });
  }

  async function viewClient(id, alive) {
    renderShell("clients", t("nav.clients"));
    const [cl, interactions, deals, properties, calls, docs] = await Promise.all([
      api("/clients/" + id),
      safe(api(`/clients/${id}/interactions`, { query: { limit: 100 } }), []),
      safe(lookups.deals(), []),
      safe(lookups.properties(), []),
      canEdit() ? safe(api(`/calls/client/${id}/history`, { query: { limit: 50 } }), null) : null,
      canEdit() ? safe(api("/documents", { query: { client_id: id, limit: 50 } }), null) : null,
    ]);
    if (!alive()) return;
    const pmap = byId(properties);
    const cDeals = deals.filter((d) => d.client_id === id);
    const loc = cl.location_preferences || {};
    const callList = calls ? (calls.data || calls.calls || []) : [];

    const inter = (interactions || []).map((i) => `<li><div><strong>${esc(tv("interaction", i.type))}</strong>${i.duration_minutes ? " · " + esc(t("clients.minutes", { n: fmtNum(i.duration_minutes, 0) })) : ""}
      ${i.property_id && pmap[i.property_id] ? ` · <a href="#/properties/${i.property_id}">${esc(propertyLabel(pmap[i.property_id]))}</a>` : ""}</div>
      ${i.description ? `<div>${esc(i.description)}</div>` : ""}${i.notes ? `<div class="muted">${esc(i.notes)}</div>` : ""}
      <div class="when">${fmtDateTime(i.created_at)}${i.follow_up_date ? " · " + esc(t("clients.followUp")) + ": " + fmtDate(i.follow_up_date) : ""}</div></li>`).join("");
    const dealRows = cDeals.map((d) => `<tr class="clickable" data-href="#/deals/${d.id}"><td>${esc(propertyLabel(pmap[d.property_id]))}</td>
      <td>${badge("stage", d.stage)}</td><td>${badge("dstatus", d.status)}</td><td class="num">${fmtMoney(d.offer_price || d.proposed_price)}</td></tr>`).join("");
    const callRows = callList.map((x) => `<tr class="clickable" data-href="#/calls/${x.id}"><td>${fmtDateTime(x.created_at)}</td><td>${esc(tv("calltype", x.call_type))}</td><td class="num">${fmtDuration(x.duration_seconds)}</td></tr>`).join("");
    const docRows = docs ? (docs.data || []).map((d) => `<tr class="clickable" data-href="#/documents/${d.id}"><td>${esc(d.name)}</td><td>${esc(tv("doctype", d.document_type))}</td><td class="muted">${fmtDate(d.created_at)}</td></tr>`).join("") : "";

    const actions = [
      canEdit() ? `<button class="btn" data-act="edit">${esc(t("common.edit"))}</button>` : "",
      canEdit() ? `<button class="btn" data-act="prefs">${esc(t("clients.preferences"))}</button>` : "",
      canEdit() ? `<button class="btn" data-act="interaction">${esc(t("clients.logInteraction"))}</button>` : "",
      canEdit() ? `<button class="btn btn-primary" data-act="deal">${esc(t("deals.new"))}</button>` : "",
      isAdmin() ? `<button class="btn btn-danger" data-act="archive">${esc(t("clients.archive"))}</button>` : "",
    ].join("");

    const c = setContent(`
      ${pageHead(clientName(cl), `${badge("ctype", cl.type)} ${badge("cstatus", cl.status)}`, actions, "#/clients")}
      <div class="grid grid-2">
        <div class="stack">
          <div class="card"><div class="card-head"><h2>${esc(t("clients.contact"))}</h2></div><div class="card-body"><dl class="dl">
            <dt>${esc(t("field.email"))}</dt><dd>${cl.email ? `<a href="mailto:${esc(cl.email)}">${esc(cl.email)}</a>` : "—"}</dd>
            <dt>${esc(t("field.phone"))}</dt><dd>${cl.phone ? `<a href="tel:${esc(cl.phone)}">${esc(cl.phone)}</a>` : "—"}</dd>
            <dt>${esc(t("field.notes"))}</dt><dd>${esc(cl.notes || "—")}</dd>
            <dt>${esc(t("clients.interactions"))}</dt><dd>${fmtNum(cl.interaction_count || 0, 0)}</dd>
            <dt>${esc(t("clients.lastContact"))}</dt><dd>${fmtDateTime(cl.last_interaction_at)}</dd>
            <dt>${esc(t("field.created"))}</dt><dd>${fmtDateTime(cl.created_at)}</dd>
          </dl></div></div>
          <div class="card"><div class="card-head"><h2>${esc(t("clients.preferences"))}</h2></div><div class="card-body"><dl class="dl">
            <dt>${esc(t("field.budget"))}</dt><dd>${(cl.budget_min || cl.budget_max) ? `${fmtMoney(cl.budget_min)} – ${fmtMoney(cl.budget_max)}` : "—"}</dd>
            <dt>${esc(t("field.propertyTypes"))}</dt><dd>${(cl.property_type_preferences || []).map((x) => esc(tv("ptype", x))).join(", ") || "—"}</dd>
            <dt>${esc(t("field.bedrooms"))}</dt><dd>${cl.bedroom_preferences != null ? fmtNum(cl.bedroom_preferences, 0) : "—"}</dd>
            <dt>${esc(t("field.cities"))}</dt><dd>${esc((loc.cities || []).join(", ") || "—")}</dd>
          </dl></div></div>
          <div class="card"><div class="card-head"><h2>${esc(t("clients.matches"))}</h2><button class="btn btn-sm" data-act="match">${esc(t("clients.findMatches"))}</button></div>
            <div class="card-body" id="matches"><div class="muted">${esc(t("clients.matchesHelp"))}</div></div></div>
        </div>
        <div class="stack">
          <div class="card"><div class="card-head"><h2>${esc(t("clients.history"))}</h2></div><div class="card-body">${inter ? `<ul class="timeline">${inter}</ul>` : `<div class="empty">${esc(t("clients.noInteractions"))}</div>`}</div></div>
          <div class="card"><div class="card-head"><h2>${esc(t("nav.deals"))}</h2></div><div class="table-wrap"><table>
            <thead><tr><th>${esc(t("field.property"))}</th><th>${esc(t("field.stage"))}</th><th>${esc(t("field.status"))}</th><th class="num">${esc(t("field.price"))}</th></tr></thead>
            <tbody>${dealRows || emptyRow(4, t("deals.none"))}</tbody></table></div></div>
          ${calls ? `<div class="card"><div class="card-head"><h2>${esc(t("nav.calls"))}</h2></div><div class="table-wrap"><table>
            <thead><tr><th>${esc(t("field.date"))}</th><th>${esc(t("field.type"))}</th><th class="num">${esc(t("field.duration"))}</th></tr></thead>
            <tbody>${callRows || emptyRow(3, t("calls.none"))}</tbody></table></div></div>` : ""}
          ${docs ? `<div class="card"><div class="card-head"><h2>${esc(t("nav.documents"))}</h2></div><div class="table-wrap"><table>
            <thead><tr><th>${esc(t("field.name"))}</th><th>${esc(t("field.type"))}</th><th>${esc(t("field.created"))}</th></tr></thead>
            <tbody>${docRows || emptyRow(3, t("docs.none"))}</tbody></table></div></div>` : ""}
        </div>
      </div>`);
    wireRowLinks(c);
    const act = (name, fn) => { const b = $(`[data-act="${name}"]`, c); if (b) b.addEventListener("click", fn); };
    act("edit", () => clientForm(cl));
    act("prefs", () => openModal({
      title: t("clients.preferences"), wide: true,
      body: `<div class="form-grid">
        ${field(t("field.budgetMin"), input("budget_min", cl.budget_min, 'type="number" min="1" step="any"'))}
        ${field(t("field.budgetMax"), input("budget_max", cl.budget_max, 'type="number" min="1" step="any"'))}
        ${field(t("field.bedrooms"), input("bedrooms", cl.bedroom_preferences, 'type="number" min="0"'))}
        ${field(t("field.cities"), input("cities", (loc.cities || []).join(", ")))}
        ${field(t("field.propertyTypes"), typeCheckboxes(cl.property_type_preferences), "full")}</div>`,
      onSubmit: async (form) => {
        const cities = list(form, "cities");
        await api(`/clients/${id}/preferences`, { method: "PATCH", body: compact({
          budget_min: num(form, "budget_min"), budget_max: num(form, "budget_max"), bedrooms: int(form, "bedrooms"),
          property_types: checkedTypes(form), location_preferences: cities.length ? Object.assign({}, loc, { cities }) : {},
        }) });
        invalidate("clients"); toast(t("common.saved"), "success"); route();
      },
    }));
    act("interaction", () => openModal({
      title: t("clients.logInteraction"),
      body: `<div class="form-grid">
        ${field(t("field.type"), select("interaction_type", options(INTERACTION_TYPES, "interaction", "call")))}
        ${field(t("field.durationMin"), input("duration_minutes", "", 'type="number" min="1"'))}
        ${field(t("field.property"), select("property_id", options(properties.map((p) => ({ value: p.id, label: propertyLabel(p) })), null, "", t("common.none"))), "full")}
        ${field(t("field.description"), textarea("description", ""), "full")}
        ${field(t("field.notes"), input("notes", ""), "full")}
        ${field(t("clients.followUp"), input("follow_up_date", "", 'type="date"'))}</div>`,
      onSubmit: async (form) => {
        await api(`/clients/${id}/interactions`, { method: "POST", body: compact({
          interaction_type: val(form, "interaction_type"), duration_minutes: int(form, "duration_minutes"), property_id: val(form, "property_id"),
          description: val(form, "description"), notes: val(form, "notes"), follow_up_date: dateIso(form, "follow_up_date"),
        }) });
        invalidate("clients"); toast(t("common.saved"), "success"); route();
      },
    }));
    act("deal", () => dealForm({ client_id: id }));
    act("archive", () => confirmDialog(t("clients.confirmArchive"), async () => {
      await api(`/clients/${id}/archive`, { method: "POST" });
      invalidate("clients"); toast(t("common.saved"), "success"); go("#/clients");
    }, t("clients.archive")));
    act("match", async () => {
      const box = $("#matches", c);
      box.innerHTML = `<div class="loading">${esc(t("common.loading"))}</div>`;
      try {
        const matches = await api(`/clients/${id}/match-properties`, { method: "POST", query: { limit: 20 } });
        const sorted = (matches || []).slice().sort((x, y) => y.match_score - x.match_score);
        box.innerHTML = sorted.length ? `<ul class="list-plain">${sorted.map((m) => `<li>
          <div style="display:flex;justify-content:space-between;gap:8px;align-items:center">
            <a href="#/properties/${m.property_id}"><strong>${esc(propertyLabel(pmap[m.property_id]))}</strong></a>
            <span class="score">${fmtNum(m.match_score, 0)}/100</span></div>
          <div class="muted small">${esc(pmap[m.property_id] ? fmtMoney(pmap[m.property_id].list_price) : "")}</div>
          <div class="chips" style="margin-top:4px">${(Array.isArray(m.match_reason) ? m.match_reason : (m.match_reason && m.match_reason.reasons) || []).map((r) => `<span class="chip">${esc(r)}</span>`).join("")}</div>
          ${canEdit() ? `<button class="btn btn-sm" style="margin-top:6px" data-deal-from="${m.property_id}">${esc(t("deals.new"))}</button>` : ""}
        </li>`).join("")}</ul>` : `<div class="empty">${esc(t("clients.noMatches"))}</div>`;
        $$("[data-deal-from]", box).forEach((b) => b.addEventListener("click", () => dealForm({ client_id: id, property_id: b.dataset.dealFrom })));
      } catch (e) { box.innerHTML = ""; toastError(e); }
    });
  }

  // ===========================================================================
  // Deals
  // ===========================================================================
  const dealFilters = { view: "board", status: "active" };

  async function viewDeals(_, alive) {
    renderShell("deals", t("nav.deals"));
    const f = dealFilters;
    const [r, clients, properties] = await Promise.all([
      api("/deals", { query: { limit: 100, status: f.status, deal_type: f.type } }),
      safe(lookups.clients(), []), safe(lookups.properties(), []),
    ]);
    if (!alive()) return;
    const cmap = byId(clients), pmap = byId(properties);
    const deals = r.deals || [];
    let body;
    if (f.view === "board") {
      body = `<div class="board">${DEAL_STAGES.map((s) => {
        const col = deals.filter((d) => d.stage === s);
        const total = col.reduce((sum, d) => sum + Number(d.offer_price || d.proposed_price || 0), 0);
        return `<div class="column"><div class="column-head"><span>${esc(tv("stage", s))}</span><span class="muted">${fmtNum(col.length, 0)} · ${fmtMoney(total)}</span></div>
          ${col.map((d) => `<div class="deal-card" data-href="#/deals/${d.id}"><div class="title">${esc(clientName(cmap[d.client_id]))}</div>
            <div class="muted small">${esc(propertyLabel(pmap[d.property_id]))}</div>
            <div class="price">${fmtMoney(d.offer_price || d.proposed_price)}</div>
            <div class="muted small">${esc(tv("dtype", d.type))}${d.expected_close_date ? " · " + fmtDate(d.expected_close_date) : ""}</div></div>`).join("")}</div>`;
      }).join("")}</div>`;
    } else {
      body = `<div class="card"><div class="table-wrap"><table><thead><tr><th>${esc(t("field.client"))}</th><th>${esc(t("field.property"))}</th><th>${esc(t("field.type"))}</th>
        <th>${esc(t("field.stage"))}</th><th>${esc(t("field.status"))}</th><th class="num">${esc(t("field.askingPrice"))}</th><th class="num">${esc(t("field.offerPrice"))}</th><th class="hide-sm">${esc(t("field.expectedClose"))}</th></tr></thead>
        <tbody>${deals.map((d) => `<tr class="clickable" data-href="#/deals/${d.id}"><td>${esc(clientName(cmap[d.client_id]))}</td><td>${esc(propertyLabel(pmap[d.property_id]))}</td>
          <td>${esc(tv("dtype", d.type))}</td><td>${badge("stage", d.stage)}</td><td>${badge("dstatus", d.status)}</td>
          <td class="num">${fmtMoney(d.proposed_price)}</td><td class="num">${fmtMoney(d.offer_price)}</td><td class="hide-sm">${fmtDate(d.expected_close_date)}</td></tr>`).join("") || emptyRow(8, t("deals.none"))}</tbody></table></div></div>`;
    }
    const c = setContent(`
      ${pageHead(t("nav.deals"), esc(t("deals.subtitle", { n: fmtNum(r.total, 0) })),
        canEdit() ? `<button class="btn btn-primary" data-add>${esc(t("deals.new"))}</button>` : "")}
      <div class="filters">
        ${field(t("common.view"), select("view", options([{ value: "board", label: t("deals.board") }, { value: "list", label: t("deals.list") }], null, f.view)))}
        ${field(t("field.status"), select("status", options(DEAL_STATUSES, "dstatus", f.status, true)))}
        ${field(t("field.type"), select("type", options(DEAL_TYPES, "dtype", f.type, true)))}
      </div>${body}`);
    $$(".filters select", c).forEach((s) => s.addEventListener("change", () => { dealFilters[s.name] = s.value; route(); }));
    wireRowLinks(c);
    $$(".deal-card", c).forEach((card) => card.addEventListener("click", () => go(card.dataset.href)));
    const add = $("[data-add]", c);
    if (add) add.addEventListener("click", () => dealForm({}));
  }

  async function dealForm(pre) {
    const [clients, properties] = await Promise.all([safe(lookups.clients(), []), safe(lookups.properties(), [])]);
    const sortedProps = properties.slice().sort((a, b) => (a.status === "available" ? 0 : 1) - (b.status === "available" ? 0 : 1));
    openModal({
      title: t("deals.new"), wide: true, submitLabel: t("common.create"),
      body: `<div class="form-grid">
        ${field(t("field.client"), select("client_id", options(clients.map((cl) => ({ value: cl.id, label: clientName(cl) })), null, pre.client_id, t("common.choose")), "required"))}
        ${field(t("field.property"), select("property_id", options(sortedProps.map((p) => ({ value: p.id, label: propertyLabel(p) + " · " + fmtMoney(p.list_price) })), null, pre.property_id, t("common.choose")), "required"))}
        ${field(t("field.type"), select("deal_type", options(DEAL_TYPES, "dtype", "sale")))}
        ${field(t("field.askingPrice"), input("proposed_price", "", `type="number" min="1" step="any" placeholder="${esc(t("deals.askingHint"))}"`))}
        ${field(t("field.offerPrice"), input("offer_price", "", 'type="number" min="1" step="any"'))}
        ${field(t("field.earnestMoney"), input("earnest_money", "", 'type="number" min="0" step="any"'))}
        ${field(t("field.expectedClose"), input("expected_close_date", "", 'type="date"'))}
        ${field(t("field.notes"), textarea("notes", ""), "full")}</div>`,
      onSubmit: async (form) => {
        if (!val(form, "client_id") || !val(form, "property_id")) { toast(t("error.required"), "error"); return false; }
        const res = await api("/deals", { method: "POST", body: compact({
          client_id: val(form, "client_id"), property_id: val(form, "property_id"), deal_type: val(form, "deal_type"),
          proposed_price: num(form, "proposed_price"), offer_price: num(form, "offer_price"), earnest_money: num(form, "earnest_money"),
          expected_close_date: dateIso(form, "expected_close_date"), notes: val(form, "notes"),
        }) });
        invalidate("deals"); toast(t("common.saved"), "success"); go("#/deals/" + res.id);
      },
    });
  }

  async function viewDeal(id, alive) {
    renderShell("deals", t("nav.deals"));
    const [d, hist, neg, comm, clients, properties] = await Promise.all([
      api("/deals/" + id),
      safe(api(`/deals/${id}/history`), []),
      safe(api(`/deals/${id}/negotiation`), null),
      safe(api(`/deals/${id}/commission`, { query: { rate: 0.05 } }), null),
      safe(lookups.clients(), []), safe(lookups.properties(), []),
    ]);
    if (!alive()) return;
    const cl = byId(clients)[d.client_id], p = byId(properties)[d.property_id];
    const open = d.status === "active";
    const stageIdx = DEAL_STAGES.indexOf(d.stage);
    const stepper = `<div class="chips">${DEAL_STAGES.map((s, i) => `<span class="badge ${i < stageIdx ? "green" : i === stageIdx ? "blue" : ""}">${i + 1}. ${esc(tv("stage", s))}</span>`).join("")}</div>`;
    const histItems = (hist || []).slice().reverse().map((h) => `<li><div>${h.from_stage ? badge("stage", h.from_stage) + " → " : ""}${badge("stage", h.to_stage)}${h.reason ? " · " + esc(h.reason === "Deal created" ? t("deals.created") : h.reason) : ""}</div>
      <div class="when">${fmtDateTime(h.created_at)}</div></li>`).join("");
    const actions = [
      canEdit() && open ? `<button class="btn" data-act="stage">${esc(t("deals.moveStage"))}</button>` : "",
      canEdit() && open ? `<button class="btn" data-act="offer">${esc(t("deals.updateOffer"))}</button>` : "",
      canEdit() ? `<button class="btn" data-act="edit">${esc(t("common.edit"))}</button>` : "",
      canEdit() && open ? `<button class="btn btn-primary" data-act="close">${esc(t("deals.markWon"))}</button>` : "",
      canEdit() && open ? `<button class="btn btn-danger" data-act="lose">${esc(t("deals.markLost"))}</button>` : "",
      isAdmin() && open ? `<button class="btn btn-danger" data-act="archive">${esc(t("deals.archive"))}</button>` : "",
    ].join("");

    const c = setContent(`
      ${pageHead(`${clientName(cl)} — ${propertyLabel(p)}`, `${badge("stage", d.stage)} ${badge("dstatus", d.status)} · ${esc(tv("dtype", d.type))}`, actions, "#/deals")}
      <div class="card" style="margin-bottom:16px"><div class="card-body">${stepper}</div></div>
      <div class="grid grid-2">
        <div class="card"><div class="card-head"><h2>${esc(t("common.details"))}</h2></div><div class="card-body"><dl class="dl">
          <dt>${esc(t("field.client"))}</dt><dd>${cl ? `<a href="#/clients/${cl.id}">${esc(clientName(cl))}</a>` : "—"}</dd>
          <dt>${esc(t("field.property"))}</dt><dd>${p ? `<a href="#/properties/${p.id}">${esc(propertyLabel(p))}</a>` : "—"}</dd>
          <dt>${esc(t("field.askingPrice"))}</dt><dd>${fmtMoney(d.proposed_price)}</dd>
          <dt>${esc(t("field.offerPrice"))}</dt><dd>${fmtMoney(d.offer_price)}</dd>
          <dt>${esc(t("field.earnestMoney"))}</dt><dd>${fmtMoney(d.earnest_money)}</dd>
          <dt>${esc(t("field.expectedClose"))}</dt><dd>${fmtDate(d.expected_close_date)}</dd>
          <dt>${esc(t("field.closedAt"))}</dt><dd>${fmtDate(d.closed_at)}</dd>
          <dt>${esc(t("field.notes"))}</dt><dd>${esc(d.notes || "—")}</dd>
          <dt>${esc(t("field.created"))}</dt><dd>${fmtDateTime(d.created_at)}</dd>
        </dl></div></div>
        <div class="stack">
          <div class="card"><div class="card-head"><h2>${esc(t("deals.negotiation"))}</h2></div><div class="card-body">${neg ? `<dl class="dl">
            <dt>${esc(t("field.askingPrice"))}</dt><dd>${fmtMoney(neg.proposed_price)}</dd>
            <dt>${esc(t("field.offerPrice"))}</dt><dd>${fmtMoney(neg.offer_price)}</dd>
            <dt>${esc(t("deals.difference"))}</dt><dd>${fmtMoney(neg.difference)} (${fmtPct(neg.percentage_below)})</dd></dl>` : "—"}</div></div>
          <div class="card"><div class="card-head"><h2>${esc(t("deals.commission"))}</h2>
            <span class="actions"><input id="rate" type="number" min="0" max="100" step="0.1" value="5" style="width:80px"> %</span></div>
            <div class="card-body" id="comm">${commissionHtml(comm)}</div></div>
          <div class="card"><div class="card-head"><h2>${esc(t("deals.stageHistory"))}</h2></div><div class="card-body">${histItems ? `<ul class="timeline">${histItems}</ul>` : "—"}</div></div>
        </div>
      </div>`);
    $("#rate", c).addEventListener("change", async (ev) => {
      const rate = Number(ev.target.value) / 100;
      try { $("#comm", c).innerHTML = commissionHtml(await api(`/deals/${id}/commission`, { query: { rate } })); } catch (e) { toastError(e); }
    });
    const act = (name, fn) => { const b = $(`[data-act="${name}"]`, c); if (b) b.addEventListener("click", fn); };
    const done = () => { invalidate("deals"); toast(t("common.saved"), "success"); route(); };
    act("stage", () => openModal({
      title: t("deals.moveStage"),
      body: `<div class="form">${field(t("field.stage"), select("new_stage", options(DEAL_STAGES, "stage", DEAL_STAGES[Math.min(stageIdx + 1, DEAL_STAGES.length - 1)])))}
        ${field(t("field.reason"), input("reason", ""))}</div>`,
      onSubmit: async (form) => { await api(`/deals/${id}/stage`, { method: "PATCH", body: compact({ new_stage: val(form, "new_stage"), reason: val(form, "reason") }) }); done(); },
    }));
    act("offer", () => openModal({
      title: t("deals.updateOffer"),
      body: `<div class="form">${field(t("field.offerPrice"), input("offer_price", d.offer_price, 'type="number" min="1" step="any" required'))}
        ${field(t("field.earnestMoney"), input("earnest_money", d.earnest_money, 'type="number" min="0" step="any"'))}</div>`,
      onSubmit: async (form) => {
        if (!num(form, "offer_price")) { toast(t("error.required"), "error"); return false; }
        await api(`/deals/${id}/offer`, { method: "PATCH", body: compact({ offer_price: num(form, "offer_price"), earnest_money: num(form, "earnest_money") }) }); done();
      },
    }));
    act("edit", () => openModal({
      title: t("common.edit"),
      body: `<div class="form-grid">${field(t("field.askingPrice"), input("proposed_price", d.proposed_price, 'type="number" min="1" step="any"'))}
        ${field(t("field.expectedClose"), input("expected_close_date", toDateInput(d.expected_close_date), 'type="date"'))}
        ${field(t("field.notes"), textarea("notes", d.notes), "full")}</div>`,
      onSubmit: async (form) => {
        await api("/deals/" + id, { method: "PATCH", body: compact({ proposed_price: num(form, "proposed_price"), expected_close_date: dateIso(form, "expected_close_date"), notes: val(form, "notes") }) }); done();
      },
    }));
    act("close", () => openModal({
      title: t("deals.markWon"), submitLabel: t("deals.markWon"),
      body: `<div class="form">${field(t("field.finalPrice"), input("final_price", d.offer_price || d.proposed_price, 'type="number" min="1" step="any"'))}
        ${field(t("field.closeDate"), input("actual_close_date", new Date().toISOString().slice(0, 10), 'type="date"'))}
        ${field(t("field.notes"), input("notes", ""))}</div>`,
      onSubmit: async (form) => {
        await api(`/deals/${id}/close`, { method: "POST", body: compact({ final_price: num(form, "final_price"), actual_close_date: dateIso(form, "actual_close_date"), notes: val(form, "notes") }) }); done();
      },
    }));
    act("lose", () => openModal({
      title: t("deals.markLost"), submitLabel: t("deals.markLost"), danger: true,
      body: `<div class="form">${field(t("field.reason"), input("reason", ""))}</div>`,
      onSubmit: async (form) => { await api(`/deals/${id}/lose`, { method: "POST", query: { reason: val(form, "reason") } }); done(); },
    }));
    act("archive", () => openModal({
      title: t("deals.archive"), submitLabel: t("deals.archive"), danger: true,
      body: `<div class="form">${field(t("field.reason"), input("reason", ""))}</div>`,
      onSubmit: async (form) => { await api(`/deals/${id}/archive`, { method: "POST", query: { reason: val(form, "reason") } }); done(); },
    }));
  }
  function commissionHtml(comm) {
    if (!comm) return "—";
    return `<dl class="dl"><dt>${esc(t("field.salePrice"))}</dt><dd>${fmtMoney(comm.sale_price)}</dd>
      <dt>${esc(t("deals.totalCommission"))}</dt><dd><strong>${fmtMoney(comm.total_commission)}</strong></dd>
      <dt>${esc(t("deals.agentShare"))}</dt><dd>${fmtMoney(comm.agent_commission)}</dd>
      <dt>${esc(t("deals.brokerShare"))}</dt><dd>${fmtMoney(comm.broker_commission)}</dd></dl>`;
  }

  // ===========================================================================
  // Calls
  // ===========================================================================
  const callFilters = { skip: 0 };

  async function viewCalls(_, alive) {
    renderShell("calls", t("nav.calls"));
    const f = callFilters;
    const [r, stats, clients] = await Promise.all([
      api("/calls", { query: { skip: f.skip, limit: CONFIG.pageSize, call_type: f.type, date_from: f.from, date_to: f.to } }),
      isAdmin() ? safe(api("/calls/admin/stats").then((x) => x.stats), null) : null,
      safe(lookups.clients(), []),
    ]);
    if (!alive()) return;
    const cmap = byId(clients);
    const kpi = (label, value) => `<div class="card kpi"><div class="label">${esc(label)}</div><div class="value">${value}</div></div>`;
    const rows = (r.data || []).map((x) => `<tr class="clickable" data-href="#/calls/${x.id}"><td>${fmtDateTime(x.created_at)}</td><td>${esc(tv("calltype", x.call_type))}</td>
      <td>${esc(x.client_id ? clientName(cmap[x.client_id]) : "—")}</td><td class="hide-sm">${esc(x.phone_number || "—")}</td>
      <td class="num">${fmtDuration(x.duration_seconds)}</td><td class="hide-sm">${x.sentiment ? badge("sentiment", x.sentiment) : "—"}</td>
      <td class="hide-sm">${x.call_quality ? badge("quality", x.call_quality) : "—"}</td></tr>`).join("");
    const c = setContent(`
      ${pageHead(t("nav.calls"), esc(t("calls.subtitle")), `<button class="btn btn-primary" data-add>${esc(t("calls.log"))}</button>`)}
      ${stats ? `<div class="grid grid-4" style="margin-bottom:16px">
        ${kpi(t("calls.total30"), fmtNum(stats.total_calls, 0))}${kpi(t("calls.avgDuration"), fmtDuration(stats.average_duration))}
        ${kpi(t("calls.withTranscript"), fmtNum(stats.calls_with_transcript, 0))}${kpi(t("calls.withSummary"), fmtNum(stats.calls_with_summary, 0))}</div>` : ""}
      <form class="filters" id="callf">
        ${field(t("field.type"), select("type", options(CALL_TYPES, "calltype", f.type, true)))}
        ${field(t("field.from"), input("from", f.from, 'type="date"'))}
        ${field(t("field.to"), input("to", f.to, 'type="date"'))}
        <div class="actions"><button class="btn btn-primary" type="submit">${esc(t("common.apply"))}</button></div>
      </form>
      <div class="card"><div class="table-wrap"><table><thead><tr><th>${esc(t("field.date"))}</th><th>${esc(t("field.type"))}</th><th>${esc(t("field.client"))}</th>
        <th class="hide-sm">${esc(t("field.phone"))}</th><th class="num">${esc(t("field.duration"))}</th><th class="hide-sm">${esc(t("field.sentiment"))}</th><th class="hide-sm">${esc(t("field.quality"))}</th></tr></thead>
        <tbody>${rows || emptyRow(7, t("calls.none"))}</tbody></table></div>${pager(r.total, f.skip, CONFIG.pageSize)}</div>`);
    wireRowLinks(c);
    const form = $("#callf", c);
    form.addEventListener("submit", (ev) => { ev.preventDefault(); Object.assign(callFilters, { skip: 0, type: val(form, "type"), from: val(form, "from"), to: val(form, "to") }); route(); });
    wirePager(c, (dir) => { callFilters.skip = Math.max(0, callFilters.skip + (dir === "next" ? 1 : -1) * CONFIG.pageSize); route(); });
    $("[data-add]", c).addEventListener("click", () => callForm());
  }

  async function callForm() {
    const [clients, properties] = await Promise.all([safe(lookups.clients(), []), safe(lookups.properties(), [])]);
    openModal({
      title: t("calls.log"), wide: true, submitLabel: t("common.save"),
      body: `<div class="form-grid">
        ${field(t("field.type"), select("call_type", options(CALL_TYPES, "calltype", "outbound")))}
        ${field(t("field.phone"), input("phone_number", "", 'type="tel"'))}
        ${field(t("field.client"), select("client_id", options(clients.map((cl) => ({ value: cl.id, label: clientName(cl) })), null, "", t("common.none"))))}
        ${field(t("field.property"), select("property_id", options(properties.map((p) => ({ value: p.id, label: propertyLabel(p) })), null, "", t("common.none"))))}
        ${field(t("field.durationMin"), input("minutes", "", 'type="number" min="0"'))}
        ${field(t("field.durationSec"), input("seconds", "", 'type="number" min="0" max="59"'))}
        ${field(t("field.recordingUrl"), input("recording_url", "", 'type="url"'), "full")}</div>`,
      onSubmit: async (form) => {
        const secs = (int(form, "minutes") || 0) * 60 + (int(form, "seconds") || 0);
        const phone = val(form, "phone_number");
        const selected = val(form, "client_id");
        const clientPhone = selected && byId(clients)[selected] ? byId(clients)[selected].phone : "";
        const res = await api("/calls/log", { method: "POST", query: {
          call_type: val(form, "call_type"), duration_seconds: secs, client_id: selected, property_id: val(form, "property_id"),
          phone_number: phone || clientPhone, recording_url: val(form, "recording_url"),
        } });
        toast(t("common.saved"), "success"); go("#/calls/" + res.id);
      },
    });
  }

  async function viewCall(id, alive) {
    renderShell("calls", t("nav.calls"));
    const [x, clients, properties] = await Promise.all([api("/calls/" + id), safe(lookups.clients(), []), safe(lookups.properties(), [])]);
    if (!alive()) return;
    const cl = byId(clients)[x.client_id], p = byId(properties)[x.property_id];
    const items = x.action_items || [];
    const c = setContent(`
      ${pageHead(`${tv("calltype", x.call_type)} · ${fmtDateTime(x.created_at)}`, cl ? esc(clientName(cl)) : "",
        `<button class="btn" data-act="transcript">${esc(x.transcript ? t("calls.editTranscript") : t("calls.addTranscript"))}</button>
         <button class="btn" data-act="summary">${esc(t("calls.editSummary"))}</button>
         <button class="btn btn-danger" data-act="delete">${esc(t("common.delete"))}</button>`, "#/calls")}
      <div class="grid grid-2">
        <div class="stack">
          <div class="card"><div class="card-head"><h2>${esc(t("common.details"))}</h2></div><div class="card-body"><dl class="dl">
            <dt>${esc(t("field.client"))}</dt><dd>${cl ? `<a href="#/clients/${cl.id}">${esc(clientName(cl))}</a>` : "—"}</dd>
            <dt>${esc(t("field.property"))}</dt><dd>${p ? `<a href="#/properties/${p.id}">${esc(propertyLabel(p))}</a>` : "—"}</dd>
            <dt>${esc(t("field.phone"))}</dt><dd>${esc(x.phone_number || "—")}</dd>
            <dt>${esc(t("field.duration"))}</dt><dd>${fmtDuration(x.duration_seconds)}</dd>
            <dt>${esc(t("field.recordingUrl"))}</dt><dd>${x.recording_url ? `<a href="${esc(x.recording_url)}" target="_blank" rel="noopener">${esc(t("calls.listen"))}</a>` : "—"}</dd>
          </dl></div></div>
          <div class="card"><div class="card-head"><h2>${esc(t("calls.summary"))}</h2></div><div class="card-body"><dl class="dl">
            <dt>${esc(t("calls.summary"))}</dt><dd>${esc(x.summary || "—")}</dd>
            <dt>${esc(t("field.sentiment"))}</dt><dd>${x.sentiment_label ? badge("sentiment", x.sentiment_label) : "—"}${x.sentiment_score != null ? " " + fmtNum(x.sentiment_score, 2) : ""}</dd>
            <dt>${esc(t("field.quality"))}</dt><dd>${x.call_quality ? badge("quality", x.call_quality) : "—"}</dd>
            <dt>${esc(t("calls.topics"))}</dt><dd>${(x.key_topics || []).length ? `<div class="chips">${x.key_topics.map((k) => `<span class="chip">${esc(k)}</span>`).join("")}</div>` : "—"}</dd>
          </dl></div></div>
        </div>
        <div class="stack">
          <div class="card"><div class="card-head"><h2>${esc(t("calls.actionItems"))}</h2></div><div class="card-body">
            ${items.length ? `<ul class="list-plain">${items.map((it, i) => `<li style="display:flex;justify-content:space-between;gap:8px"><span>${esc(typeof it === "string" ? it : it.description || JSON.stringify(it))}</span>
              <button class="btn btn-ghost btn-sm" data-remove="${i}" aria-label="${esc(t("common.delete"))}">✕</button></li>`).join("")}</ul>` : `<div class="muted">${esc(t("calls.noActionItems"))}</div>`}
            <form id="ai-form" class="actions" style="margin-top:10px"><input name="action_text" placeholder="${esc(t("calls.newActionItem"))}" style="flex:1;min-width:160px">
              <button class="btn btn-sm btn-primary" type="submit">${esc(t("common.add"))}</button></form></div></div>
          <div class="card"><div class="card-head"><h2>${esc(t("calls.transcript"))}</h2></div><div class="card-body" style="white-space:pre-wrap">${esc(x.transcript || "—")}</div></div>
        </div>
      </div>`);
    const saveItems = async (newItems) => {
      try { await api(`/calls/${id}/action-items`, { method: "POST", body: newItems }); toast(t("common.saved"), "success"); route(); } catch (e) { toastError(e); }
    };
    $("#ai-form", c).addEventListener("submit", (ev) => {
      ev.preventDefault();
      const v = val(ev.target, "action_text");
      if (v) saveItems(items.map((it) => (typeof it === "string" ? it : it.description || "")).concat([v]));
    });
    $$("[data-remove]", c).forEach((b) => b.addEventListener("click", () => {
      const idx = Number(b.dataset.remove);
      saveItems(items.filter((_, i) => i !== idx).map((it) => (typeof it === "string" ? it : it.description || "")));
    }));
    const act = (name, fn) => { const b = $(`[data-act="${name}"]`, c); if (b) b.addEventListener("click", fn); };
    act("transcript", () => openModal({
      title: t("calls.transcript"), wide: true,
      body: `<div class="form">${field(t("calls.transcript"), textarea("transcript", x.transcript, 'style="min-height:220px"'))}</div>`,
      onSubmit: async (form) => {
        if (!val(form, "transcript")) { toast(t("error.required"), "error"); return false; }
        await api(`/calls/${id}/transcript`, { method: "POST", query: { transcript: val(form, "transcript"), transcript_provider: "manual" } });
        toast(t("common.saved"), "success"); route();
      },
    }));
    act("summary", () => openModal({
      title: t("calls.editSummary"), wide: true,
      body: `<div class="form-grid">${field(t("calls.summary"), textarea("summary", x.summary), "full")}
        ${field(t("field.sentiment"), select("sentiment_label", options(SENTIMENTS, "sentiment", x.sentiment_label, t("common.none"))))}
        ${field(t("field.quality"), select("call_quality", options(CALL_QUALITIES, "quality", x.call_quality, t("common.none"))))}
        ${field(t("calls.topics"), input("topics", (x.key_topics || []).join(", "), `placeholder="${esc(t("props.featuresHint"))}"`), "full")}</div>`,
      onSubmit: async (form) => {
        if (!val(form, "summary")) { toast(t("error.required"), "error"); return false; }
        const label = val(form, "sentiment_label");
        const score = { positive: 0.8, neutral: 0.5, negative: 0.2 }[label];
        await api(`/calls/${id}/summary`, { method: "POST", body: list(form, "topics"), query: {
          summary: val(form, "summary"), sentiment_label: label, sentiment_score: score, call_quality: val(form, "call_quality"),
        } });
        toast(t("common.saved"), "success"); route();
      },
    }));
    act("delete", () => confirmDialog(t("calls.confirmDelete"), async () => {
      await api("/calls/" + id, { method: "DELETE" }); toast(t("common.deleted"), "success"); go("#/calls");
    }, t("common.delete")));
  }

  // ===========================================================================
  // Documents
  // ===========================================================================
  const docFilters = { skip: 0 };

  async function viewDocuments(_, alive) {
    renderShell("documents", t("nav.documents"));
    const f = docFilters;
    const [r, stats, clients, properties] = await Promise.all([
      api("/documents", { query: { skip: f.skip, limit: CONFIG.pageSize, document_type: f.type, search_term: f.q } }),
      isAdmin() ? safe(api("/documents/admin/stats").then((x) => x.stats), null) : null,
      safe(lookups.clients(), []), safe(lookups.properties(), []),
    ]);
    if (!alive()) return;
    const cmap = byId(clients), pmap = byId(properties);
    const rows = (r.data || []).map((d) => `<tr class="clickable" data-href="#/documents/${d.id}"><td><strong>${esc(d.name)}</strong></td>
      <td>${esc(tv("doctype", d.document_type))}</td><td class="num">${fmtNum(d.version, 0)}</td><td class="num hide-sm">${fmtSize(d.file_size)}</td>
      <td class="hide-sm">${esc([d.client_id && clientName(cmap[d.client_id]), d.property_id && propertyLabel(pmap[d.property_id])].filter(Boolean).join(" · ") || "—")}</td>
      <td class="muted">${fmtDate(d.created_at)}</td></tr>`).join("");
    const kpi = (label, value) => `<div class="card kpi"><div class="label">${esc(label)}</div><div class="value">${value}</div></div>`;
    const c = setContent(`
      ${pageHead(t("nav.documents"), esc(t("docs.subtitle", { n: fmtNum(r.total, 0) })), `<button class="btn btn-primary" data-add>${esc(t("docs.upload"))}</button>`)}
      ${stats ? `<div class="grid grid-3" style="margin-bottom:16px">${kpi(t("docs.total30"), fmtNum(stats.total_documents, 0))}
        ${kpi(t("docs.versions"), fmtNum(stats.total_versions, 0))}${kpi(t("docs.storage"), fmtNum(stats.total_size_mb, 2) + " MB")}</div>` : ""}
      <form class="filters" id="docf">
        ${field(t("common.search"), input("q", f.q, `placeholder="${esc(t("docs.searchHint"))}"`), "grow")}
        ${field(t("field.type"), select("type", options(DOC_TYPES, "doctype", f.type, true)))}
        <div class="actions"><button class="btn btn-primary" type="submit">${esc(t("common.apply"))}</button></div>
      </form>
      <div class="card"><div class="table-wrap"><table><thead><tr><th>${esc(t("field.name"))}</th><th>${esc(t("field.type"))}</th><th class="num">${esc(t("docs.version"))}</th>
        <th class="num hide-sm">${esc(t("docs.size"))}</th><th class="hide-sm">${esc(t("docs.linkedTo"))}</th><th>${esc(t("field.created"))}</th></tr></thead>
        <tbody>${rows || emptyRow(6, t("docs.none"))}</tbody></table></div>${pager(r.total, f.skip, CONFIG.pageSize)}</div>`);
    wireRowLinks(c);
    const form = $("#docf", c);
    form.addEventListener("submit", (ev) => { ev.preventDefault(); Object.assign(docFilters, { skip: 0, q: val(form, "q"), type: val(form, "type") }); route(); });
    wirePager(c, (dir) => { docFilters.skip = Math.max(0, docFilters.skip + (dir === "next" ? 1 : -1) * CONFIG.pageSize); route(); });
    $("[data-add]", c).addEventListener("click", () => uploadForm());
  }

  async function uploadForm() {
    const [clients, properties, deals] = await Promise.all([safe(lookups.clients(), []), safe(lookups.properties(), []), safe(lookups.deals(), [])]);
    const cmap = byId(clients), pmap = byId(properties);
    openModal({
      title: t("docs.upload"), wide: true, submitLabel: t("docs.upload"),
      body: `<div class="form-grid">
        ${field(t("docs.file"), `<input type="file" name="file" required>`, "full")}
        ${field(t("field.name"), input("name", ""))}
        ${field(t("field.type"), select("document_type", options(DOC_TYPES, "doctype", "contract")))}
        ${field(t("field.client"), select("client_id", options(clients.map((cl) => ({ value: cl.id, label: clientName(cl) })), null, "", t("common.none"))))}
        ${field(t("field.property"), select("property_id", options(properties.map((p) => ({ value: p.id, label: propertyLabel(p) })), null, "", t("common.none"))))}
        ${field(t("field.deal"), select("deal_id", options(deals.map((d) => ({ value: d.id, label: clientName(cmap[d.client_id]) + " — " + propertyLabel(pmap[d.property_id]) })), null, "", t("common.none"))), "full")}
        <p class="muted small full">${esc(t("docs.maxSize"))}</p></div>`,
      onOpen: (form) => {
        form.elements.file.addEventListener("change", () => {
          const fl = form.elements.file.files[0];
          if (fl && !form.elements.name.value) form.elements.name.value = fl.name.replace(/\.[^.]+$/, "");
        });
      },
      onSubmit: async (form) => {
        const fl = form.elements.file.files[0];
        if (!fl) { toast(t("docs.chooseFile"), "error"); return false; }
        const fd = new FormData();
        fd.append("file", fl);
        const res = await api("/documents/upload", { method: "POST", form: fd, query: {
          name: val(form, "name") || fl.name, document_type: val(form, "document_type"),
          client_id: val(form, "client_id"), property_id: val(form, "property_id"), deal_id: val(form, "deal_id"),
        } });
        toast(t("common.saved"), "success"); go("#/documents/" + res.id);
      },
    });
  }

  async function downloadDoc(id, version, fallbackName) {
    try {
      const res = await api(`/documents/${id}/download`, { raw: true, query: { version } });
      const blob = await res.blob();
      let name = fallbackName || "document";
      const cd = res.headers.get("Content-Disposition") || "";
      const m = cd.match(/filename\*=UTF-8''([^;]+)/) || cd.match(/filename="([^"]+)"/);
      if (m) name = decodeURIComponent(m[1]);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    } catch (e) { toastError(e); }
  }

  async function viewDocument(id, alive) {
    renderShell("documents", t("nav.documents"));
    const [d, v, clients, properties, deals] = await Promise.all([
      api("/documents/" + id), safe(api(`/documents/${id}/versions`), { versions: [] }),
      safe(lookups.clients(), []), safe(lookups.properties(), []), safe(lookups.deals(), []),
    ]);
    if (!alive()) return;
    const cl = byId(clients)[d.client_id], p = byId(properties)[d.property_id], deal = byId(deals)[d.deal_id];
    const vrows = (v.versions || []).map((x) => `<tr><td>${fmtNum(x.version, 0)}${x.version === d.total_versions ? ` <span class="badge green">${esc(t("docs.current"))}</span>` : ""}</td>
      <td class="hide-sm">${esc(x.change_notes || "—")}</td><td class="num hide-sm nowrap">${fmtSize(x.file_size)}</td><td class="nowrap">${fmtDate(x.created_at)}</td>
      <td class="nowrap"><button class="btn btn-sm" data-dl="${x.version}">${esc(t("docs.download"))}</button>
      ${x.version !== d.total_versions ? `<button class="btn btn-sm" data-rollback="${x.version}">${esc(t("docs.restore"))}</button>` : ""}</td></tr>`).join("");
    const c = setContent(`
      ${pageHead(d.name, `${esc(tv("doctype", d.document_type))} · ${esc(t("docs.versionN", { n: fmtNum(d.total_versions, 0) }))}`,
        `<button class="btn btn-primary" data-act="download">${esc(t("docs.download"))}</button>
         <button class="btn" data-act="version">${esc(t("docs.newVersion"))}</button>
         <button class="btn" data-act="share">${esc(t("docs.share"))}</button>
         ${isAdmin() ? `<button class="btn" data-act="retention">${esc(t("docs.retention"))}</button>` : ""}
         <button class="btn btn-danger" data-act="delete">${esc(t("common.delete"))}</button>`, "#/documents")}
      <div class="grid grid-2">
        <div class="card"><div class="card-head"><h2>${esc(t("common.details"))}</h2></div><div class="card-body"><dl class="dl">
          <dt>${esc(t("field.type"))}</dt><dd>${esc(tv("doctype", d.document_type))}</dd>
          <dt>${esc(t("docs.size"))}</dt><dd>${fmtSize(d.file_size)}</dd>
          <dt>${esc(t("docs.fileType"))}</dt><dd>${esc(d.mime_type || "—")}</dd>
          <dt>${esc(t("field.client"))}</dt><dd>${cl ? `<a href="#/clients/${cl.id}">${esc(clientName(cl))}</a>` : "—"}</dd>
          <dt>${esc(t("field.property"))}</dt><dd>${p ? `<a href="#/properties/${p.id}">${esc(propertyLabel(p))}</a>` : "—"}</dd>
          <dt>${esc(t("field.deal"))}</dt><dd>${deal ? `<a href="#/deals/${deal.id}">${esc(t("docs.openDeal"))}</a>` : "—"}</dd>
          <dt>${esc(t("docs.keepUntil"))}</dt><dd>${fmtDate(d.retention_until)}</dd>
          <dt>${esc(t("field.created"))}</dt><dd>${fmtDateTime(d.created_at)}</dd>
          <dt>${esc(t("field.updated"))}</dt><dd>${fmtDateTime(d.updated_at)}</dd>
        </dl></div></div>
        <div class="card"><div class="card-head"><h2>${esc(t("docs.versions"))}</h2></div><div class="table-wrap"><table>
          <thead><tr><th>#</th><th class="hide-sm">${esc(t("docs.changeNotes"))}</th><th class="num hide-sm">${esc(t("docs.size"))}</th><th>${esc(t("field.date"))}</th><th></th></tr></thead>
          <tbody>${vrows || emptyRow(5)}</tbody></table></div></div>
      </div>`);
    $$("[data-dl]", c).forEach((b) => b.addEventListener("click", () => downloadDoc(id, b.dataset.dl, d.name)));
    $$("[data-rollback]", c).forEach((b) => b.addEventListener("click", () => confirmDialog(t("docs.confirmRestore", { n: b.dataset.rollback }), async () => {
      await api(`/documents/${id}/rollback/${b.dataset.rollback}`, { method: "POST" }); toast(t("common.saved"), "success"); route();
    }, t("docs.restore"))));
    const act = (name, fn) => { const b = $(`[data-act="${name}"]`, c); if (b) b.addEventListener("click", fn); };
    act("download", () => downloadDoc(id, null, d.name));
    act("version", () => openModal({
      title: t("docs.newVersion"),
      body: `<div class="form">${field(t("docs.file"), `<input type="file" name="file" required>`)}${field(t("docs.changeNotes"), input("change_notes", ""))}</div>`,
      onSubmit: async (form) => {
        const fl = form.elements.file.files[0];
        if (!fl) { toast(t("docs.chooseFile"), "error"); return false; }
        const fd = new FormData(); fd.append("file", fl);
        await api(`/documents/${id}/new-version`, { method: "POST", form: fd, query: { change_notes: val(form, "change_notes") } });
        toast(t("common.saved"), "success"); route();
      },
    }));
    act("share", async () => {
      const users = (await safe(lookups.users(), [])).filter((u) => !state.user || u.id !== state.user.id);
      openModal({
        title: t("docs.share"),
        body: `<div class="form">
          ${users.length ? field(t("docs.shareWithUser"), select("user_id", options(users.map((u) => ({ value: u.id, label: userName(u) })), null, "", t("common.none")))) : ""}
          ${field(t("docs.shareWithEmail"), input("email", "", 'type="email"'))}
          ${field(t("docs.permission"), select("permission", options(SHARE_PERMISSIONS, "perm", "view")))}
          ${field(t("docs.expiresInDays"), input("expiry_days", "30", 'type="number" min="1"'))}</div>`,
        onSubmit: async (form) => {
          if (!val(form, "user_id") && !val(form, "email")) { toast(t("docs.shareNeedsTarget"), "error"); return false; }
          await api(`/documents/${id}/share`, { method: "POST", query: {
            share_with_user_id: val(form, "user_id"), share_with_email: val(form, "email"), permission: val(form, "permission"), expiry_days: int(form, "expiry_days"),
          } });
          toast(t("docs.shared"), "success");
        },
      });
    });
    act("retention", () => openModal({
      title: t("docs.retention"),
      body: `<div class="form">${field(t("docs.retentionDays"), input("retention_days", "365", 'type="number" min="1" required'))}
        ${field(t("field.reason"), select("retention_reason", options(["compliance", "regulatory", "archive"], "retention", "compliance")))}</div>`,
      onSubmit: async (form) => {
        await api(`/documents/${id}/retention`, { method: "POST", query: { retention_days: int(form, "retention_days"), retention_reason: val(form, "retention_reason") } });
        toast(t("common.saved"), "success"); route();
      },
    }));
    act("delete", () => confirmDialog(t("docs.confirmDelete"), async () => {
      await api("/documents/" + id, { method: "DELETE" }); toast(t("common.deleted"), "success"); go("#/documents");
    }, t("common.delete")));
  }

  // ===========================================================================
  // Users (admin)
  // ===========================================================================
  async function viewUsers(_, alive) {
    renderShell("users", t("nav.users"));
    if (!isAdmin()) { setContent(`<div class="card"><div class="empty">${esc(t("error.forbidden"))}</div></div>`); return; }
    const users = await lookups.users();
    if (!alive()) return;
    const rows = users.map((u) => `<tr><td><strong>${esc(userName(u))}</strong><div class="muted small">${esc(u.email)}</div></td>
      <td>${u.id === state.user.id ? badge("role", u.role) : `<select data-role="${u.id}" style="width:auto">${options(ROLES, "role", u.role)}</select>`}</td>
      <td class="hide-sm">${esc(u.phone || "—")}</td><td class="hide-sm muted">${fmtDateTime(u.last_login)}</td><td class="hide-sm muted">${fmtDate(u.created_at)}</td></tr>`).join("");
    const c = setContent(`
      ${pageHead(t("nav.users"), esc(t("users.subtitle")), `<button class="btn btn-primary" data-add>${esc(t("users.add"))}</button>`)}
      <div class="card"><div class="table-wrap"><table><thead><tr><th>${esc(t("field.name"))}</th><th>${esc(t("field.role"))}</th>
        <th class="hide-sm">${esc(t("field.phone"))}</th><th class="hide-sm">${esc(t("users.lastLogin"))}</th><th class="hide-sm">${esc(t("field.created"))}</th></tr></thead>
        <tbody>${rows}</tbody></table></div></div>
      <div class="card" style="margin-top:16px"><div class="card-body"><h3>${esc(t("users.rolesTitle"))}</h3>
        <ul><li>${esc(t("users.roleViewer"))}</li><li>${esc(t("users.roleAgent"))}</li><li>${esc(t("users.roleAdmin"))}</li></ul>
        <p class="muted small">${esc(t("users.orgId"))}: <code>${esc(state.user.organization_id)}</code></p></div></div>`);
    $$("[data-role]", c).forEach((s) => s.addEventListener("change", async () => {
      try {
        await api(`/auth/admin/users/${s.dataset.role}/role`, { method: "PATCH", body: { role: s.value } });
        invalidate("users"); toast(t("common.saved"), "success");
      } catch (e) { toastError(e); route(); }
    }));
    $("[data-add]", c).addEventListener("click", () => openModal({
      title: t("users.add"), wide: true, submitLabel: t("common.create"),
      body: `<div class="form-grid">
        ${field(t("field.firstName"), input("first_name", "", "required"))}${field(t("field.lastName"), input("last_name", "", "required"))}
        ${field(t("field.email"), input("email", "", 'type="email" required'))}${field(t("field.phone"), input("phone", "", 'type="tel"'))}
        ${field(t("field.password"), input("password", "", 'type="password" autocomplete="new-password" required'))}
        ${field(t("field.confirmPassword"), input("confirm", "", 'type="password" autocomplete="new-password" required'))}
        ${field(t("field.role"), select("role", options(ROLES, "role", "agent")))}
        <p class="muted small full">${esc(t("auth.passwordRules"))}</p></div>`,
      onSubmit: async (form) => {
        if (form.elements.password.value !== form.elements.confirm.value) { toast(t("auth.passwordsDontMatch"), "error"); return false; }
        const res = await api("/auth/register", { method: "POST", noAuth: true, query: { organization_id: state.user.organization_id }, body: compact({
          email: val(form, "email"), password: form.elements.password.value, confirm_password: form.elements.confirm.value,
          first_name: val(form, "first_name"), last_name: val(form, "last_name"), phone: val(form, "phone"),
        }) });
        const newRole = val(form, "role");
        if (newRole !== "viewer") await api(`/auth/admin/users/${res.data.user.id}/role`, { method: "PATCH", body: { role: newRole } });
        invalidate("users"); toast(t("users.added"), "success"); route();
      },
    }));
  }

  // ===========================================================================
  // Profile
  // ===========================================================================
  async function viewProfile(_, alive) {
    renderShell("profile", t("nav.profile"));
    const me = (await api("/auth/me")).data.user;
    if (!alive()) return;
    saveSession(null, me);
    const c = setContent(`
      ${pageHead(t("nav.profile"), esc(me.email))}
      <div class="grid grid-2">
        <div class="card"><div class="card-head"><h2>${esc(t("profile.details"))}</h2></div><div class="card-body">
          <form class="form" id="pf">
            <div class="form-grid">${field(t("field.firstName"), input("first_name", me.first_name))}${field(t("field.lastName"), input("last_name", me.last_name))}</div>
            ${field(t("field.phone"), input("phone", me.phone, 'type="tel"'))}
            ${field(t("profile.language"), select("preferred_language", options(LANGS.map((l) => ({ value: l.code, label: l.label })), null, me.preferred_language || "en")))}
            <div><button class="btn btn-primary" type="submit">${esc(t("common.save"))}</button></div>
          </form></div></div>
        <div class="card"><div class="card-head"><h2>${esc(t("profile.changePassword"))}</h2></div><div class="card-body">
          <form class="form" id="pw">
            ${field(t("profile.currentPassword"), input("old_password", "", 'type="password" autocomplete="current-password"'))}
            ${field(t("profile.newPassword"), input("new_password", "", 'type="password" autocomplete="new-password"') + `<span class="help">${esc(t("auth.passwordRules"))}</span>`)}
            ${field(t("field.confirmPassword"), input("confirm_password", "", 'type="password" autocomplete="new-password"'))}
            <div><button class="btn btn-primary" type="submit">${esc(t("profile.changePassword"))}</button></div>
          </form></div></div>
      </div>
      <div class="card" style="margin-top:16px"><div class="card-body"><dl class="dl">
        <dt>${esc(t("field.role"))}</dt><dd>${badge("role", me.role)}</dd>
        <dt>${esc(t("users.lastLogin"))}</dt><dd>${fmtDateTime(me.last_login)}</dd>
        <dt>${esc(t("field.created"))}</dt><dd>${fmtDateTime(me.created_at)}</dd></dl></div></div>`);
    $("#pf", c).addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const form = ev.target;
      try {
        const res = await api("/auth/me/profile", { method: "PATCH", body: compact({
          first_name: val(form, "first_name"), last_name: val(form, "last_name"), phone: val(form, "phone"), preferred_language: val(form, "preferred_language"),
        }) });
        saveSession(null, res.data.user);
        toast(t("common.saved"), "success");
        if (val(form, "preferred_language") !== state.lang) setLanguage(val(form, "preferred_language")); else route();
      } catch (e) { toastError(e); }
    });
    $("#pw", c).addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const form = ev.target;
      try {
        await api("/auth/change-password", { method: "POST", body: {
          old_password: form.elements.old_password.value, new_password: form.elements.new_password.value, confirm_password: form.elements.confirm_password.value,
        } });
        form.reset();
        toast(t("profile.passwordChanged"), "success");
      } catch (e) { toastError(e); }
    });
  }

  // ===========================================================================
  // Start
  // ===========================================================================
  applyLanguage();
  route();
})();
