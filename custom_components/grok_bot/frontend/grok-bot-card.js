/*
 * Grok Bot card for Home Assistant (custom:grok-bot-card)
 * Original animated bot avatar (no third-party branding), ask box, last reply,
 * recent conversation, budget/status chips and repair quick actions.
 */
const CARD_VERSION = "0.1.4";
const DOMAIN = "grok_bot";

const KEYS = {
  last_reply: "sensor",
  last_status: "sensor",
  last_sent: "sensor",
  sends_hour: "sensor",
  sends_day: "sensor",
  pending: "sensor",
  pause: "switch",
  mark_handled: "button",
};

const I18N = {
  en: {
    idle: "Ready", thinking: "Thinking…", success: "Replied", error: "Problem",
    paused: "Paused", placeholder: "Ask Grok Bot anything…", send: "Send", awaiting: "awaiting", handled: "Mark replies handled",
    no_reply: "No reply yet. Ask something below.", issues: "Open repairs",
    no_issues: "No open repairs", diagnose: "Diagnose", fix: "Fix",
    history: "Recent conversation", you: "You", bot: "Grok Bot",
    hour: "h", day: "24h", report: "Report", mode_diagnose: "Diagnose",
    mode_fix: "Diagnose + fix", not_found: "Grok Bot entities not found. Is the integration set up?",
    sent: "Sent", dropped: "Not sent", ago: "ago",
    restarting: "Restarting after the reply…", restarted: "Restarted, waiting for the result…",
  },
  nl: {
    idle: "Klaar", thinking: "Denkt na…", success: "Beantwoord", error: "Probleem",
    paused: "Gepauzeerd", placeholder: "Vraag Grok Bot iets…", send: "Verstuur", awaiting: "wachtend", handled: "Antwoorden als afgehandeld markeren",
    no_reply: "Nog geen antwoord. Stel hieronder een vraag.", issues: "Open reparaties",
    no_issues: "Geen open reparaties", diagnose: "Diagnose", fix: "Repareer",
    history: "Recent gesprek", you: "Jij", bot: "Grok Bot",
    hour: "u", day: "24u", report: "Melden", mode_diagnose: "Diagnose",
    mode_fix: "Diagnose + repareren", not_found: "Grok Bot-entiteiten niet gevonden. Is de integratie ingesteld?",
    sent: "Verstuurd", dropped: "Niet verstuurd", ago: "geleden",
    restarting: "Herstart na het antwoord…", restarted: "Herstart, wacht op het resultaat…",
  },
};

const BOT_SVG = `
<svg class="bot" viewBox="0 0 120 120" aria-hidden="true">
  <defs>
    <linearGradient id="gbHead" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="var(--gb-accent-2)"/>
      <stop offset="1" stop-color="var(--gb-accent)"/>
    </linearGradient>
    <radialGradient id="gbGlow" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="var(--gb-eye)" stop-opacity="0.9"/>
      <stop offset="1" stop-color="var(--gb-eye)" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <g class="float">
    <line class="antenna" x1="60" y1="22" x2="60" y2="10" stroke="var(--gb-accent)" stroke-width="4" stroke-linecap="round"/>
    <circle class="antenna-ball" cx="60" cy="8" r="6" fill="var(--gb-eye)"/>
    <rect class="ear" x="12" y="50" width="10" height="24" rx="5" fill="var(--gb-accent)"/>
    <rect class="ear" x="98" y="50" width="10" height="24" rx="5" fill="var(--gb-accent)"/>
    <rect class="head" x="20" y="22" width="80" height="76" rx="26" fill="url(#gbHead)"/>
    <rect class="visor" x="30" y="40" width="60" height="34" rx="17" fill="var(--gb-visor)"/>
    <g class="eyes">
      <circle class="glow" cx="47" cy="57" r="12" fill="url(#gbGlow)"/>
      <circle class="glow" cx="73" cy="57" r="12" fill="url(#gbGlow)"/>
      <g class="eye-l"><ellipse class="eye" cx="47" cy="57" rx="6" ry="7" fill="var(--gb-eye)"/></g>
      <g class="eye-r"><ellipse class="eye" cx="73" cy="57" rx="6" ry="7" fill="var(--gb-eye)"/></g>
    </g>
    <path class="mouth" d="M48 84 Q60 92 72 84" stroke="var(--gb-visor)" stroke-width="4" fill="none" stroke-linecap="round"/>
  </g>
</svg>`;

const STYLE = `
:host { display: block; }
ha-card { overflow: hidden; }
.wrap { padding: 16px; display: flex; flex-direction: column; gap: 14px;
  --gb-accent: var(--gb-accent-color, var(--primary-color, #4f7cff));
  --gb-accent-2: var(--gb-accent-color-2, var(--accent-color, #8a5cff));
  --gb-eye: #7df9ff; --gb-visor: #0d1424;
  --gb-ok: var(--success-color, #2e9d5b); --gb-err: var(--error-color, #db4437);
  --gb-warn: var(--warning-color, #f4a100);
  --gb-bubble: var(--secondary-background-color, rgba(127,127,127,.12));
  --gb-text: var(--primary-text-color); --gb-muted: var(--secondary-text-color);
  color: var(--gb-text); }
.header { display: flex; align-items: center; gap: 14px; }
.avatar { position: relative; width: 76px; height: 76px; flex: none; }
.avatar .ring { position: absolute; inset: -4px; border-radius: 50%;
  border: 3px solid transparent; transition: border-color .3s, box-shadow .3s; }
.avatar svg, .avatar img { width: 100%; height: 100%; display: block; }
.avatar img { border-radius: 50%; object-fit: cover; }
.bot .float { animation: gb-float 4s ease-in-out infinite; transform-origin: 60px 60px; }
.bot .eye { transform-box: fill-box; transform-origin: center; animation: gb-blink 5s infinite; }
.bot .glow { opacity: .55; }
.bot .antenna-ball { transform-box: fill-box; transform-origin: center; }
.thinking .ring { border-color: var(--gb-accent); animation: gb-pulse 1.2s ease-out infinite; }
.thinking .bot .antenna-ball { animation: gb-beacon .8s ease-in-out infinite alternate; }
.thinking .bot .eyes { animation: gb-look 2.4s ease-in-out infinite; }
.thinking .bot .mouth { d: path("M50 86 L70 86"); }
.thinking img { animation: gb-breathe 1.2s ease-in-out infinite; }
.success .ring { border-color: var(--gb-ok); box-shadow: 0 0 16px var(--gb-ok); }
.success .bot .eye { animation: none; transform: scaleY(.45); }
.success .bot .mouth { d: path("M44 82 Q60 98 76 82"); }
.error .ring { border-color: var(--gb-err); box-shadow: 0 0 14px var(--gb-err); }
.error .avatar-inner { animation: gb-shake .5s ease-in-out 2; }
.error .bot { --gb-eye: #ff7a7a; }
.error .bot .mouth { d: path("M48 90 Q60 80 72 90"); }
.paused .bot { filter: grayscale(.85); opacity: .75; }
.paused .bot .float, .paused .bot .eye { animation: none; }
.titles { flex: 1; min-width: 0; }
.title { font-size: 1.25em; font-weight: 600; line-height: 1.2; }
.state { color: var(--gb-muted); font-size: .9em; margin-top: 2px; display: flex; align-items: center; gap: 6px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--gb-muted); }
.idle .dot { background: var(--gb-ok); }
.thinking .dot { background: var(--gb-accent); animation: gb-beacon .6s infinite alternate; }
.success .dot { background: var(--gb-ok); }
.error .dot { background: var(--gb-err); }
.paused .dot { background: var(--gb-warn); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.chip { display: inline-flex; align-items: center; gap: 4px; font-size: .78em; padding: 3px 9px;
  border-radius: 999px; background: var(--gb-bubble); color: var(--gb-text); border: none;
  cursor: default; font-family: inherit; }
.chip.btn { cursor: pointer; }
.chip.warn { background: color-mix(in srgb, var(--gb-warn) 22%, transparent); }
.chip.bad { background: color-mix(in srgb, var(--gb-err) 22%, transparent); }
.chip ha-icon { --mdc-icon-size: 14px; }
.bar { height: 4px; border-radius: 2px; background: var(--gb-bubble); overflow: hidden; margin-top: 8px; }
.bar > div { height: 100%; background: linear-gradient(90deg, var(--gb-accent), var(--gb-accent-2)); transition: width .4s; }
.bubble { background: var(--gb-bubble); border-radius: 16px 16px 16px 4px; padding: 12px 14px;
  position: relative; white-space: pre-wrap; word-break: break-word; line-height: 1.45; }
.bubble .meta { color: var(--gb-muted); font-size: .75em; margin-top: 6px; }
.bubble .rtitle { font-weight: 600; margin-bottom: 4px; }
.bubble.empty { color: var(--gb-muted); font-style: italic; }
.typing span { display: inline-block; width: 7px; height: 7px; margin-right: 4px; border-radius: 50%;
  background: var(--gb-muted); animation: gb-typing 1.2s infinite; }
.typing span:nth-child(2) { animation-delay: .2s; } .typing span:nth-child(3) { animation-delay: .4s; }
.ask { display: flex; gap: 8px; align-items: flex-end; }
.ask textarea { flex: 1; resize: none; min-height: 40px; max-height: 120px; padding: 10px 12px;
  border-radius: 12px; border: 1px solid var(--divider-color, rgba(127,127,127,.3));
  background: var(--card-background-color, transparent); color: var(--gb-text); font: inherit; }
.ask select { border-radius: 10px; padding: 8px; border: 1px solid var(--divider-color, rgba(127,127,127,.3));
  background: var(--card-background-color, transparent); color: var(--gb-text); font: inherit; }
.send { border: none; border-radius: 12px; padding: 10px 14px; cursor: pointer; font: inherit; font-weight: 600;
  color: #fff; background: linear-gradient(135deg, var(--gb-accent), var(--gb-accent-2)); }
.send[disabled] { opacity: .5; cursor: default; }
.section-title { font-size: .8em; text-transform: uppercase; letter-spacing: .06em; color: var(--gb-muted); margin-bottom: 6px; }
.history { display: flex; flex-direction: column; gap: 6px; max-height: 220px; overflow-y: auto; }
.msg { max-width: 85%; padding: 7px 11px; border-radius: 14px; font-size: .88em; background: var(--gb-bubble); }
.msg.out { align-self: flex-end; color: #fff; background: linear-gradient(135deg, var(--gb-accent), var(--gb-accent-2)); border-bottom-right-radius: 4px; }
.msg.in { align-self: flex-start; border-bottom-left-radius: 4px; }
.msg .t { display: block; font-size: .72em; opacity: .75; margin-top: 2px; }
.issues { display: flex; flex-direction: column; gap: 6px; }
.issue { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 12px; background: var(--gb-bubble); }
.issue .name { flex: 1; min-width: 0; font-size: .88em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.issue .sev { width: 8px; height: 8px; border-radius: 50%; background: var(--gb-warn); flex: none; }
.issue .sev.error, .issue .sev.critical { background: var(--gb-err); }
.mini { border: 1px solid var(--divider-color, rgba(127,127,127,.35)); background: transparent; color: var(--gb-text);
  border-radius: 999px; padding: 3px 10px; font: inherit; font-size: .78em; cursor: pointer; }
.mini.fix { border-color: var(--gb-accent); color: var(--gb-accent); }
.muted { color: var(--gb-muted); font-size: .85em; }
@keyframes gb-float { 0%,100% { transform: translateY(0) } 50% { transform: translateY(-3px) } }
@keyframes gb-blink { 0%,92%,100% { transform: scaleY(1) } 95% { transform: scaleY(.1) } }
@keyframes gb-pulse { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--gb-accent) 60%, transparent) } 100% { box-shadow: 0 0 0 14px transparent } }
@keyframes gb-beacon { from { opacity: .35; transform: scale(.85) } to { opacity: 1; transform: scale(1.15) } }
@keyframes gb-look { 0%,100% { transform: translateX(0) } 30% { transform: translateX(-4px) } 70% { transform: translateX(4px) } }
@keyframes gb-shake { 0%,100% { transform: translateX(0) } 25% { transform: translateX(-4px) } 75% { transform: translateX(4px) } }
@keyframes gb-breathe { 0%,100% { transform: scale(1) } 50% { transform: scale(.95) } }
@keyframes gb-typing { 0%,60%,100% { transform: translateY(0); opacity: .4 } 30% { transform: translateY(-4px); opacity: 1 } }
@media (prefers-reduced-motion: reduce) { * { animation: none !important; } }
`;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function timeAgo(iso, lang) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  try {
    const rtf = new Intl.RelativeTimeFormat(lang || "en", { numeric: "auto" });
    if (diff < 60) return rtf.format(-Math.round(diff), "second");
    if (diff < 3600) return rtf.format(-Math.round(diff / 60), "minute");
    if (diff < 86400) return rtf.format(-Math.round(diff / 3600), "hour");
    return rtf.format(-Math.round(diff / 86400), "day");
  } catch (_e) {
    return new Date(iso).toLocaleString();
  }
}

class GrokBotCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("grok-bot-card-editor");
  }

  static getStubConfig() {
    return { type: "custom:grok-bot-card" };
  }

  setConfig(config) {
    if (!config) throw new Error("Invalid configuration");
    this._config = {
      show_chips: true, show_ask: true, show_history: true, show_issues: true,
      max_history: 6, max_issues: 4, default_mode: "report",
      ...config,
    };
    this._waiting = false;
    this._flash = null;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._sig = null;
    this._render();
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    this._resolve();
    const reply = this._state("last_reply");
    const marker = reply ? reply.last_changed + (reply.attributes.received || "") : "";
    if (this._replyMarker !== undefined && marker !== this._replyMarker && this._waiting) {
      this._waiting = false;
      this._setFlash("success");
    }
    this._replyMarker = marker;
    if (first || Date.now() - (this._issuesAt || 0) > 60000) this._loadIssues();
    this._render();
  }

  get _t() {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").split("-")[0];
    return I18N[lang] || I18N.en;
  }

  _resolve() {
    const hass = this._hass;
    const found = {};
    const entries = hass.entities || {};
    const wantEntry = this._config.config_entry_id;
    for (const [entityId, ent] of Object.entries(entries)) {
      if (ent.platform !== DOMAIN || !ent.translation_key || !(ent.translation_key in KEYS)) continue;
      if (wantEntry) {
        const dev = hass.devices?.[ent.device_id];
        if (!dev || !(dev.config_entries || []).includes(wantEntry)) continue;
      }
      if (!found[ent.translation_key]) found[ent.translation_key] = entityId;
    }
    // Fallback for older frontends: default entity ids.
    const fallback = {
      last_reply: "sensor.grok_bot_last_reply", last_status: "sensor.grok_bot_last_status",
      last_sent: "sensor.grok_bot_last_sent", sends_hour: "sensor.grok_bot_sends_last_hour",
      sends_day: "sensor.grok_bot_sends_last_24_hours", pending: "sensor.grok_bot_awaiting_reply",
      pause: "switch.grok_bot_pause_sending", mark_handled: "button.grok_bot_mark_replies_handled",
    };
    for (const key of Object.keys(KEYS)) {
      const override = this._config[`entity_${key}`];
      this._ids = this._ids || {};
      found[key] = override || found[key] || (hass.states[fallback[key]] ? fallback[key] : undefined);
    }
    this._ids = found;
  }

  _state(key) {
    const id = this._ids?.[key];
    return id ? this._hass.states[id] : undefined;
  }

  async _loadIssues() {
    if (!this._config.show_issues || !this._hass?.callWS) return;
    this._issuesAt = Date.now();
    try {
      const res = await this._hass.callWS({ type: "repairs/list_issues" });
      this._issues = (res.issues || []).filter((i) => !i.ignored && i.domain !== DOMAIN);
    } catch (_e) {
      this._issues = [];
    }
    this._render();
  }

  _setFlash(kind) {
    this._flash = kind;
    clearTimeout(this._flashTimer);
    this._flashTimer = setTimeout(() => { this._flash = null; this._render(); }, 6000);
  }

  _mood() {
    const paused = this._state("pause")?.state === "on";
    if (paused) return "paused";
    if (this._waiting) return "thinking";
    if (this._restartPhase()) return "thinking";
    if (this._flash) return this._flash;
    const status = this._state("last_status")?.state;
    if (["failed", "auth_failed"].includes(status)) return "error";
    return "idle";
  }

  _restartPhase() {
    // Survives a page reload and an HA restart: read from the awaiting-reply sensor.
    const attrs = this._state("pending")?.attributes || {};
    const status = this._state("last_status")?.state;
    if (attrs.restarted_waiting || status === "restarted_waiting") return "restarted";
    if (attrs.restart_scheduled || status === "restarting") return "restarting";
    return null;
  }

  async _call(service, data) {
    const payload = { ...data };
    if (this._config.config_entry_id) payload.config_entry_id = this._config.config_entry_id;
    try {
      const res = await this._hass.callService(DOMAIN, service, payload, undefined, false, true);
      const status = res?.response?.status;
      if (status && status !== "sent") {
        this._waiting = false;
        this._lastDrop = status;
        this._setFlash("error");
      } else {
        this._lastDrop = null;
        this._waiting = true;
        clearTimeout(this._waitTimer);
        this._waitTimer = setTimeout(() => { this._waiting = false; this._render(); }, 180000);
      }
    } catch (err) {
      this._waiting = false;
      this._lastDrop = err?.message || "error";
      this._setFlash("error");
    }
    this._render();
  }

  _send() {
    const area = this.shadowRoot.querySelector("textarea");
    const text = (area?.value || "").trim();
    if (!text) return;
    const mode = this.shadowRoot.querySelector("select")?.value || this._config.default_mode;
    area.value = "";
    this._draft = "";
    this._call("ask", { message: text, action_mode: mode });
  }

  _togglePause() {
    const id = this._ids.pause;
    if (!id) return;
    const on = this._hass.states[id]?.state === "on";
    this._hass.callService("switch", on ? "turn_off" : "turn_on", { entity_id: id });
  }

  _markHandled() {
    const id = this._ids.mark_handled;
    this._waiting = false;
    if (id) this._hass.callService("button", "press", { entity_id: id });
    this._render();
  }

  _chips(t) {
    const hour = this._state("sends_hour");
    const day = this._state("sends_day");
    const status = this._state("last_status");
    const paused = this._state("pause")?.state === "on";
    const chips = [];
    chips.push(`<button class="chip btn ${paused ? "warn" : ""}" data-action="pause" title="${esc(this._ids.pause || "")}">
      <ha-icon icon="${paused ? "mdi:pause-circle" : "mdi:play-circle"}"></ha-icon>${paused ? t.paused : "Live"}</button>`);
    if (hour) {
      const lim = hour.attributes.limit;
      chips.push(`<span class="chip ${Number(hour.state) >= lim ? "bad" : ""}"><ha-icon icon="mdi:counter"></ha-icon>${esc(hour.state)}/${esc(lim)} ${t.hour}</span>`);
    }
    if (day) {
      const lim = day.attributes.limit;
      chips.push(`<span class="chip ${Number(day.state) >= lim ? "bad" : ""}"><ha-icon icon="mdi:calendar-clock"></ha-icon>${esc(day.state)}/${esc(lim)} ${t.day}</span>`);
    }
    if (status && status.state !== "unknown") {
      const bad = ["failed", "auth_failed"].includes(status.state);
      const warn = status.state.startsWith("dropped");
      const label = this._hass.formatEntityState ? this._hass.formatEntityState(status) : status.state;
      chips.push(`<span class="chip ${bad ? "bad" : warn ? "warn" : ""}"><ha-icon icon="mdi:send-check"></ha-icon>${esc(label)}</span>`);
    }
    const pending = this._state("pending");
    if (pending && Number(pending.state) > 0) {
      chips.push(`<button class="chip btn warn" data-action="handled" title="${esc(t.handled)}">
        <ha-icon icon="mdi:message-processing"></ha-icon>${esc(pending.state)} ${t.awaiting}</button>`);
    }
    let bar = "";
    if (day && day.attributes.limit) {
      const pct = Math.min(100, (Number(day.state) / day.attributes.limit) * 100);
      bar = `<div class="bar" title="${esc(day.state)}/${esc(day.attributes.limit)}"><div style="width:${pct}%"></div></div>`;
    }
    return `<div class="chips">${chips.join("")}</div>${bar}`;
  }

  _signature() {
    const parts = Object.values(this._ids || {}).map((id) => {
      const st = this._hass.states[id];
      return st ? `${id}:${st.last_updated}` : id;
    });
    return [parts.join("|"), this._mood(), this._waiting, this._lastDrop,
      (this._issues || []).map((i) => i.issue_id).join(","), this._hass.locale?.language,
      Math.floor(Date.now() / 30000)].join("#");
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    if (this._hass) {
      const sig = this._signature();
      if (sig === this._sig) return;
      this._sig = sig;
    }
    const focused = this.shadowRoot.activeElement?.tagName === "TEXTAREA";
    const caret = focused ? this.shadowRoot.activeElement.selectionStart : 0;
    const t = this._t;
    const cfg = this._config;
    if (!this._hass) {
      this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card><div class="wrap"></div></ha-card>`;
      return;
    }
    const lang = this._hass.locale?.language || this._hass.language;
    const reply = this._state("last_reply");
    const mood = this._mood();
    const phase = mood === "thinking" ? this._restartPhase() : null;
    const moodText = phase ? t[phase] : { idle: t.idle, thinking: t.thinking, success: t.success, error: t.error, paused: t.paused }[mood];
    const avatar = cfg.avatar_url
      ? `<img src="${esc(cfg.avatar_url)}" alt="">`
      : BOT_SVG;
    const name = cfg.title || t.bot;
    if (!this._ids.last_reply && !this._ids.last_status) {
      this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card><div class="wrap idle"><div class="header"><div class="avatar"><div class="avatar-inner">${avatar}</div></div><div class="titles"><div class="title">${esc(name)}</div><div class="muted">${t.not_found}</div></div></div></div></ha-card>`;
      return;
    }
    const message = reply?.attributes?.message || (reply && !["unknown", "unavailable"].includes(reply.state) ? reply.state : "");
    let bubble;
    if (this._waiting || phase) {
      bubble = `<div class="bubble">${phase ? `<div class="rtitle">${esc(t[phase])}</div>` : ""}<div class="typing"><span></span><span></span><span></span></div></div>`;
    } else if (message) {
      bubble = `<div class="bubble">${reply.attributes.title ? `<div class="rtitle">${esc(reply.attributes.title)}</div>` : ""}${esc(message)}<div class="meta">${esc(timeAgo(reply.attributes.received, lang))}</div></div>`;
    } else {
      bubble = `<div class="bubble empty">${t.no_reply}</div>`;
    }
    if (this._lastDrop && !this._waiting) {
      bubble += `<div class="muted">${t.dropped}: ${esc(this._lastDrop)}</div>`;
    }

    let history = "";
    if (cfg.show_history) {
      const items = (reply?.attributes?.history || []).slice(-cfg.max_history);
      if (items.length) {
        history = `<div><div class="section-title">${t.history}</div><div class="history">${items
          .map((h) => `<div class="msg ${h.direction === "out" ? "out" : "in"}">${esc(h.message)}<span class="t">${h.direction === "out" ? esc(h.type) + " · " : ""}${esc(timeAgo(h.time, lang))}</span></div>`)
          .join("")}</div></div>`;
      }
    }

    let issues = "";
    if (cfg.show_issues && this._issues) {
      const list = this._issues.slice(0, cfg.max_issues);
      issues = `<div><div class="section-title">${t.issues}${this._issues.length ? ` · ${this._issues.length}` : ""}</div><div class="issues">${
        list.length
          ? list.map((i, idx) => `<div class="issue"><span class="sev ${esc(i.severity)}"></span><span class="name" title="${esc(i.domain)}.${esc(i.issue_id)}">${esc(i.domain)} · ${esc(i.translation_key || i.issue_id)}</span><button class="mini" data-action="diagnose" data-idx="${idx}">${t.diagnose}</button><button class="mini fix" data-action="fix" data-idx="${idx}">${t.fix}</button></div>`).join("")
          : `<div class="muted">${t.no_issues}</div>`
      }</div></div>`;
    }

    const ask = cfg.show_ask
      ? `<div class="ask"><textarea rows="1" placeholder="${esc(t.placeholder)}">${esc(this._draft || "")}</textarea>
         <select title="action_mode">
           <option value="report" ${cfg.default_mode === "report" ? "selected" : ""}>${t.report}</option>
           <option value="diagnose" ${cfg.default_mode === "diagnose" ? "selected" : ""}>${t.mode_diagnose}</option>
           <option value="fix" ${cfg.default_mode === "fix" ? "selected" : ""}>${t.mode_fix}</option>
         </select>
         <button class="send" data-action="send" ${mood === "paused" ? "disabled" : ""}>${t.send}</button></div>`
      : "";

    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card><div class="wrap ${mood}">
      <div class="header">
        <div class="avatar"><div class="ring"></div><div class="avatar-inner">${avatar}</div></div>
        <div class="titles"><div class="title">${esc(name)}</div>
          <div class="state"><span class="dot"></span>${esc(moodText)}</div>
          ${cfg.show_chips ? this._chips(t) : ""}
        </div>
      </div>
      ${bubble}
      ${ask}
      ${history}
      ${issues}
    </div></ha-card>`;

    const root = this.shadowRoot;
    root.querySelector('[data-action="send"]')?.addEventListener("click", () => this._send());
    root.querySelector('[data-action="pause"]')?.addEventListener("click", () => this._togglePause());
    root.querySelector('[data-action="handled"]')?.addEventListener("click", () => this._markHandled());
    const area = root.querySelector("textarea");
    if (area && focused) {
      area.focus();
      area.setSelectionRange(caret, caret);
    }
    if (area) {
      area.addEventListener("input", () => { this._draft = area.value; });
      area.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); this._send(); }
      });
    }
    root.querySelectorAll('.issue [data-action]').forEach((btn) => {
      btn.addEventListener("click", () => {
        const issue = this._issues[Number(btn.dataset.idx)];
        if (!issue) return;
        this._call(btn.dataset.action === "fix" ? "fix_issue" : "diagnose", {
          issue_id: issue.issue_id, issue_domain: issue.domain,
        });
      });
    });
  }
}

const EDITOR_SCHEMA = [
  { name: "title", selector: { text: {} } },
  { name: "avatar_url", selector: { text: { type: "url" } } },
  { name: "config_entry_id", selector: { config_entry: { integration: DOMAIN } } },
  {
    type: "grid", name: "", schema: [
      { name: "show_chips", selector: { boolean: {} } },
      { name: "show_ask", selector: { boolean: {} } },
      { name: "show_history", selector: { boolean: {} } },
      { name: "show_issues", selector: { boolean: {} } },
    ],
  },
  {
    type: "grid", name: "", schema: [
      { name: "max_history", selector: { number: { min: 1, max: 20, mode: "box" } } },
      { name: "max_issues", selector: { number: { min: 1, max: 20, mode: "box" } } },
    ],
  },
  {
    name: "default_mode",
    selector: { select: { mode: "dropdown", options: [
      { value: "report", label: "Report" },
      { value: "diagnose", label: "Diagnose" },
      { value: "fix", label: "Diagnose + fix" },
    ] } },
  },
];

const EDITOR_LABELS = {
  title: "Title", avatar_url: "Custom avatar image URL (optional)",
  config_entry_id: "Grok Bot entry (optional)", show_chips: "Status chips",
  show_ask: "Ask box", show_history: "Recent conversation", show_issues: "Open repairs",
  max_history: "Messages shown", max_issues: "Repairs shown", default_mode: "Default action mode",
};

class GrokBotCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
    else this._render();
  }

  _render() {
    if (!this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => EDITOR_LABELS[s.name] || s.name;
      this._form.addEventListener("value-changed", (ev) => {
        const config = { ...ev.detail.value };
        Object.keys(config).forEach((k) => (config[k] === "" || config[k] === undefined) && delete config[k]);
        this._config = config;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.schema = EDITOR_SCHEMA;
    this._form.data = {
      show_chips: true, show_ask: true, show_history: true, show_issues: true,
      max_history: 6, max_issues: 4, default_mode: "report", ...this._config,
    };
    if (this._hass) this._form.hass = this._hass;
  }
}

if (!customElements.get("grok-bot-card")) customElements.define("grok-bot-card", GrokBotCard);
if (!customElements.get("grok-bot-card-editor")) customElements.define("grok-bot-card-editor", GrokBotCardEditor);

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "grok-bot-card")) {
  window.customCards.push({
    type: "grok-bot-card",
    name: "Grok Bot",
    description: "Animated Grok Bot assistant: ask, replies, budget and repair quick actions.",
    preview: true,
    documentationURL: "https://github.com/DonTranQuiL/grok-bot-ha",
  });
}
console.info(`%c GROK-BOT-CARD %c ${CARD_VERSION} `, "color:#fff;background:#4f7cff;border-radius:3px 0 0 3px", "color:#4f7cff;background:#eef2ff;border-radius:0 3px 3px 0");
