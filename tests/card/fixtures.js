// Shared fake Home Assistant data for the card harness and the preview.
window.GB_FIXTURE = (() => {
  const now = Date.now();
  const iso = (minAgo) => new Date(now - minAgo * 60000).toISOString();
  const states = {
    "sensor.grok_bot_last_reply": {
      entity_id: "sensor.grok_bot_last_reply", state: "The tilt actuator lost its Zigbee route…",
      last_changed: iso(2), last_updated: iso(2),
      attributes: {
        message: "The tilt actuator lost its Zigbee route. I re-interviewed it in Zigbee2MQTT and moved the panel back to 35°. It responds again.",
        title: "Solar tilt fixed", conversation_id: "c42", received: iso(2),
        history: [
          { direction: "out", type: "ask", message: "Is the attic window closed?", time: iso(95) },
          { direction: "in", type: "reply", message: "Yes, contact sensor reports closed since 08:12.", time: iso(94) },
          { direction: "out", type: "entity_unavailable", message: "Solar tilt actuator has been unavailable for 15 minutes.", time: iso(6) },
          { direction: "in", type: "reply", message: "The tilt actuator lost its Zigbee route. I re-interviewed it and it responds again.", time: iso(2) },
        ],
      },
    },
    "sensor.grok_bot_last_status": { entity_id: "sensor.grok_bot_last_status", state: "sent", last_updated: iso(6), attributes: {} },
    "sensor.grok_bot_last_sent": { entity_id: "sensor.grok_bot_last_sent", state: iso(6), last_updated: iso(6), attributes: {} },
    "sensor.grok_bot_sends_last_hour": { entity_id: "sensor.grok_bot_sends_last_hour", state: "3", last_updated: iso(6), attributes: { limit: 20, remaining: 17 } },
    "sensor.grok_bot_sends_last_24_hours": { entity_id: "sensor.grok_bot_sends_last_24_hours", state: "27", last_updated: iso(6), attributes: { limit: 100, remaining: 73 } },
    "sensor.grok_bot_awaiting_reply": { entity_id: "sensor.grok_bot_awaiting_reply", state: "0", last_updated: iso(6), attributes: {} },
    "switch.grok_bot_pause_sending": { entity_id: "switch.grok_bot_pause_sending", state: "off", last_updated: iso(60), attributes: {} },
  };
  const tk = {
    "sensor.grok_bot_last_reply": "last_reply", "sensor.grok_bot_last_status": "last_status",
    "sensor.grok_bot_last_sent": "last_sent", "sensor.grok_bot_sends_last_hour": "sends_hour",
    "sensor.grok_bot_sends_last_24_hours": "sends_day", "sensor.grok_bot_awaiting_reply": "pending",
    "switch.grok_bot_pause_sending": "pause",
  };
  const entities = {};
  for (const [id, key] of Object.entries(tk)) {
    entities[id] = { entity_id: id, platform: "grok_bot", translation_key: key, device_id: "dev1" };
  }
  const issues = [
    { domain: "zha", issue_id: "radio_lost", translation_key: "radio_lost", severity: "error", ignored: false },
    { domain: "hacs", issue_id: "restart_required", translation_key: "restart_required", severity: "warning", ignored: false },
    { domain: "grok_bot", issue_id: "own", translation_key: "own", severity: "warning", ignored: false },
  ];
  return { states, entities, devices: { dev1: { id: "dev1", config_entries: ["entry1"] } }, issues };
})();
