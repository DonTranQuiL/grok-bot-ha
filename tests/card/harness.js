// Headless-Chrome checks for the Grok Bot card (see tests/test_card.py).
const results = { errors: [], checks: {} };
const origError = console.error;
console.error = (...a) => { results.errors.push(a.map(String).join(" ")); origError(...a); };
window.addEventListener("error", (ev) => results.errors.push(String(ev.message)));
window.addEventListener("unhandledrejection", (ev) => results.errors.push(String(ev.reason)));

customElements.define("ha-form", class extends HTMLElement {});
customElements.define("ha-card", class extends HTMLElement {});
customElements.define("ha-icon", class extends HTMLElement {});

const F = window.GB_FIXTURE;
const flush = () => new Promise((r) => setTimeout(r, 0));
const clone = (v) => JSON.parse(JSON.stringify(v));
const calls = [];

function makeHass(states, extra = {}) {
  return {
    states, entities: F.entities, devices: F.devices, language: "en", locale: { language: "en" },
    callWS: async () => ({ issues: F.issues }),
    callService: async (domain, service, data) => {
      calls.push({ domain, service, data });
      return { response: { status: extra.dropStatus || "sent" } };
    },
    ...extra,
  };
}

const q = (c, s) => c.shadowRoot.querySelector(s);
const qa = (c, s) => [...c.shadowRoot.querySelectorAll(s)];
const txt = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : null);

async function newCard(config, hass) {
  const card = document.createElement("grok-bot-card");
  card.setConfig({ type: "custom:grok-bot-card", ...config });
  document.body.appendChild(card);
  card.hass = hass;
  await flush(); await flush();
  return card;
}

(async () => {
  const c = results.checks;
  try {
    const states = clone(F.states);
    const card = await newCard({}, makeHass(states));
    c.title = txt(q(card, ".title"));
    c.mood = q(card, ".wrap").className;
    c.svg = !!q(card, "svg.bot");
    c.chips = qa(card, ".chip").map(txt);
    c.bubble = txt(q(card, ".bubble"));
    c.history = qa(card, ".msg").length;
    c.issues = qa(card, ".issue .name").map(txt);
    c.bad = ["undefined", "NaN", "[object Object]"].filter((x) => txt(q(card, ".wrap")).includes(x));

    // Ask: calls grok_bot.ask with the chosen mode, then shows the thinking state.
    q(card, "textarea").value = "Why is the attic warm?";
    q(card, "select").value = "diagnose";
    q(card, '[data-action="send"]').click();
    await flush(); await flush();
    c.ask_call = calls.find((x) => x.service === "ask");
    c.thinking = q(card, ".wrap").classList.contains("thinking");
    c.typing = !!q(card, ".typing");

    // A new reply arrives -> success state.
    const next = clone(states);
    next["sensor.grok_bot_last_reply"].last_changed = new Date().toISOString();
    next["sensor.grok_bot_last_reply"].last_updated = new Date().toISOString();
    next["sensor.grok_bot_last_reply"].attributes.message = "Sun on the roof; I closed the attic blind.";
    card.hass = makeHass(next);
    await flush();
    c.success = q(card, ".wrap").classList.contains("success");
    c.new_bubble = txt(q(card, ".bubble"));

    // Fix button on a repair issue.
    qa(card, '.issue [data-action="fix"]')[0].click();
    await flush();
    c.fix_call = calls.find((x) => x.service === "fix_issue");

    // Pause chip toggles the switch.
    q(card, '[data-action="pause"]').click();
    await flush();
    c.pause_call = calls.find((x) => x.domain === "switch");

    // Paused state + dropped status.
    const paused = clone(F.states);
    paused["switch.grok_bot_pause_sending"].state = "on";
    const pcard = await newCard({ show_issues: false, title: "House bot" }, makeHass(paused));
    c.paused = q(pcard, ".wrap").classList.contains("paused");
    c.paused_title = txt(q(pcard, ".title"));
    c.send_disabled = q(pcard, '[data-action="send"]').disabled;

    // Error state when the last send failed.
    const failed = clone(F.states);
    failed["sensor.grok_bot_last_status"].state = "failed";
    const ecard = await newCard({}, makeHass(failed));
    c.error = q(ecard, ".wrap").classList.contains("error");

    // Dropped by budget -> shows the reason.
    const dcard = await newCard({}, makeHass(clone(F.states), { dropStatus: "dropped_budget" }));
    q(dcard, "textarea").value = "x";
    q(dcard, '[data-action="send"]').click();
    await flush(); await flush();
    c.dropped_text = txt(q(dcard, ".wrap .muted"));

    // Custom avatar image.
    const icard = await newCard({ avatar_url: "/local/me.png" }, makeHass(clone(F.states)));
    c.avatar_img = q(icard, ".avatar img")?.getAttribute("src");

    // Dutch.
    const ncard = await newCard({}, makeHass(clone(F.states), { language: "nl", locale: { language: "nl" } }));
    c.nl_send = txt(q(ncard, '[data-action="send"]'));

    // Not set up.
    const none = await newCard({}, { states: {}, entities: {}, language: "en" });
    c.not_found = txt(q(none, ".muted"));

    // Editor + registration.
    const ed = document.createElement("grok-bot-card-editor");
    ed.setConfig({ title: "x" });
    document.body.appendChild(ed);
    c.editor_form = !!ed.querySelector("ha-form");
    c.custom_cards = (window.customCards || []).map((x) => x.type);
    c.stub = customElements.get("grok-bot-card").getStubConfig();

    // Awaiting replies: a chip that presses "Mark replies handled".
    const waiting = clone(F.states);
    waiting["sensor.grok_bot_awaiting_reply"].state = "2";
    waiting["button.grok_bot_mark_replies_handled"] = { entity_id: "button.grok_bot_mark_replies_handled", state: "unknown", last_updated: new Date().toISOString(), attributes: {} };
    const wcard = await newCard({}, makeHass(waiting));
    c.awaiting_chip = txt(q(wcard, '[data-action="handled"]'));
    q(wcard, '[data-action="handled"]').click();
    await flush();
    c.handled_call = calls[calls.length - 1];
  } catch (err) {
    results.errors.push(String(err && err.stack || err));
  }
  const out = document.createElement("pre");
  out.id = "out";
  out.textContent = JSON.stringify(results);
  document.body.appendChild(out);
})();
