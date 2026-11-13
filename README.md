# Grok Bot for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.1+-blue.svg)](https://www.home-assistant.io/)
[![Discord](https://img.shields.io/badge/Discord-join%20community-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/qaHPTTKHae)
[![Liberapay patrons](https://img.shields.io/liberapay/patrons/Malosaaa.svg?logo=liberapay)](https://liberapay.com/Malosaaa/donate)

Let Home Assistant talk to your **Grok Bot** assistant. Home Assistant sends tasks, questions, events and problems to a Grok Bot **routine webhook**. Grok Bot then acts in Home Assistant through its own Home Assistant connector and answers back with the `grok_bot.reply` action.

![Grok Bot card](docs/images/grok-bot-card.png)

> **Every message Home Assistant sends to the webhook costs Grok Bot usage.** Nothing is sent automatically until you allow it, and a send budget (20 per hour, 100 per 24 hours by default) drops anything over the limit instead of queueing it.

> **Status: private test version (0.1.0).** There is no public Grok Bot API. The only transport is an HTTPS POST to a routine webhook, so replies are asynchronous: they take seconds to minutes, not milliseconds.

## Features

* ✅ **UI setup** with a test ping, reauthentication and reconfigure flows.
* ✅ **Simple mode** with presets for beginners: *Ask only*, *Errors only*, *Errors + repairs, diagnose*, or *Custom*.
* ✅ **Advanced mode** with every option: allowlists, per-entity filters, Jinja message templates, a per-trigger action mode, quiet hours, budgets, debounce, a payload size limit and an attribute toggle.
* ✅ **Actions:** `grok_bot.ask`, `send_event`, `diagnose`, `fix_issue`, `health_report`, `ping` (all return the delivery status), and `grok_bot.reply` for Grok Bot's answers.
* ✅ **Problem watchers** (opt-in): logged errors and warnings, repair issues, entities that stay unavailable, failed automations and scripts, and integration setup failures. You choose per watcher whether Grok Bot only **reports**, **diagnoses**, or may **diagnose and fix**.
* ✅ **Budget guard:** hourly and 24-hour limits, a **Pause sending** switch, counter sensors, and `grok_bot_dropped` events. Nothing is queued and nothing is retried automatically.
* ✅ **Optional entities:** a notify entity (`notify.send_message` to Grok Bot) and an **Assist conversation agent**.
* ✅ **Replies:** a *Last reply* sensor with recent history, a `grok_bot_reply` event, and delivery to an `input_text`, a notify entity or service, or a persistent notification. An optional inbound webhook is also available.
* ✅ **Dashboard card** `custom:grok-bot-card`: an animated bot avatar (idle, thinking, success, error and paused states), an ask box, the last reply, the recent conversation, budget chips, and Diagnose/Fix buttons for open repairs. It comes with a visual editor, follows the dark or light theme, and accepts a custom avatar image.
* ✅ **Blueprints:** threshold alert, nightly health report, and replies pushed to your phone.
* ✅ Diagnostics with every secret redacted, plus English and Dutch translations.

## Installation

### Method 1: Marketplace (Home Assistant 2026.11 and newer, recommended)

[![Open your Home Assistant instance and open this repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=DonTranQuiL&repository=grok-bot-ha&category=integration)

1. In Home Assistant, go to **Settings > Marketplace** and search for **Grok Bot** (or use the button above).
2. Open it and select **Install**. The setup starts right away, no restart needed.

> **Not in the Marketplace catalog yet?** Grok Bot is not in the HACS default list yet, so it does not show up in the Marketplace search. Until it is, select **Add from link** in the upper-right corner of the Marketplace, enter `https://github.com/DonTranQuiL/grok-bot-ha`, select **Add**, then open Grok Bot and select **Install**. (While this repository is private, this only works with a GitHub token that can read it. Use Method 3 instead.)

### Method 2: HACS (Home Assistant before 2026.11)

1. In HACS, open the three-dot menu and select **Custom repositories**.
2. Add `https://github.com/DonTranQuiL/grok-bot-ha` with the category **Integration**.
3. Install **Grok Bot**, then restart Home Assistant.

### Method 3: Manual installation

1. Copy the `custom_components/grok_bot` folder (or unzip `grok_bot.zip`) into `config/custom_components/`, so you end up with `config/custom_components/grok_bot/manifest.json`.
2. Restart Home Assistant.

---

## Beginner quickstart

1. **Create the webhook in Grok Bot.** In the Grok Bot app, create (or open) a routine that is triggered by a **webhook**. Copy two values: the **Webhook URL** and the **Authorization header** value.
2. **Add the integration.** Go to **Settings > Devices & services > Add integration > Grok Bot**. Paste the URL and the header value exactly as shown (`Bearer …`; a pasted `Authorization:` prefix is removed automatically). Leave **Send a test ping** on to check that it works. This costs one Grok Bot run.
3. **Pick a preset:**
   | Preset | What gets sent automatically |
   | --- | --- |
   | **Ask only** (default) | Nothing. Only your own actions, buttons and the card. |
   | **Errors only** | Logged errors, failed automations or scripts, and integration setup failures (*report*). |
   | **Errors + repairs, diagnose** | The above plus new repair issues. Grok Bot investigates each one (*diagnose*). |
   | **Custom** | Opens Advanced mode. |
4. **Add the card.** Edit a dashboard, select **Add card**, and choose **Grok Bot** (or use `type: custom:grok-bot-card`).
5. **Ask something** in the card, or call the action from a script:
   ```yaml
   action: grok_bot.ask
   data:
     message: "The solar tilt looks stuck, can you check it?"
     context_entities: [cover.solar_tilt]
     action_mode: diagnose
     reply_to: persistent_notification
   ```
6. The answer appears in the card and in `sensor.grok_bot_last_reply`. It is also sent to `reply_to`.

To stop all sending at once, turn on **switch.grok_bot_pause_sending**.

---

## Power user reference

### Options (Settings > Devices & services > Grok Bot > Configure)

| Menu | Options |
| --- | --- |
| **Preset** | Simple presets (see above). *Custom* switches to Advanced mode. |
| **Features** | Notify entity, Assist agent, inbound reply webhook, and attaching entity attributes (all **off** by default except attributes). |
| **Budget** | Max sends per hour (20) and per 24 h (100). Advanced only: minimum interval per entity or event (300 s), quiet hours (drop automatic sends), payload size limit (16 kB). |
| **State and event forwarding** | Allowlisted entities and event types, an action mode for each, and whether to ignore unavailable/unknown. `state_changed`, `call_service` and other high-volume or loop-prone events, and every `grok_bot_*` event, are blocked. |
| **Per-entity filters** | Per entity: *only when the new state is one of …*, *use attribute X instead of the state*, *above/below* thresholds (these fire on **crossing** into the range, not on every change), and a minimum interval. |
| **Problem watchers** | **Logs**: minimum level, all/allowlist/denylist of loggers, grouping identical errors for N seconds (the repeat count is sent with the next one), action mode. **Repairs**: new issues, action mode. **Unavailable**: entities and minutes. **Automations/scripts**: errors, action mode. **Setup**: integrations entering setup error or retry, action mode. |
| **Message templates** | Jinja templates for the `message` field of state, event and problem sends. Variables are `entity_id`, `from_state`, `to_state`, `event_type`, `event_data`, `kind` and `issue`. |

**Action modes:** `report` (just tell me), `diagnose` (investigate and reply, change nothing), `fix` (diagnose and try **safe, reversible** fixes such as reloading a config entry or retrying; the payload sets `allow_fix: true`).

### Budget rules

* Every POST counts. That includes manual actions, buttons, the card, notify and Assist.
* Over the limit, the message is **dropped** (`grok_bot_dropped` event, *Dropped total* sensor). It is never queued.
* Manual actions can set `bypass_budget: true`. They are still counted, and the pause switch still applies.
* Automatic sends also respect quiet hours and the per-entity or per-event minimum interval.
* Nothing is retried automatically. After an authorization failure (401/403), Home Assistant asks you to reauthenticate.

### Actions

| Action | Fields | Response |
| --- | --- | --- |
| `grok_bot.ask` | `message`, `action_mode`, `data`, `context_entities`, `reply_to`, `conversation_id`, `notify_user`, `bypass_budget`, `config_entry_id` | delivery status |
| `grok_bot.send_event` | `event_type`, `message`, `data`, `action_mode` + common fields | delivery status |
| `grok_bot.diagnose` | `message`, `issue_id`, `issue_domain`, `target_config_entry_id` + common | delivery status |
| `grok_bot.fix_issue` | same as diagnose (`allow_fix: true`) | delivery status |
| `grok_bot.health_report` | `action_mode` + common. Sends open repairs, failed integrations, unavailable entities and recent errors. | delivery status |
| `grok_bot.ping` | `bypass_budget` | delivery status |
| `grok_bot.reply` | `message`, `conversation_id`, `title`, `reply_to`, `data` (used by Grok Bot) | – |

The delivery status looks like this: `{"status": "sent" | "failed" | "auth_failed" | "dropped_budget" | "dropped_paused" | "dropped_quiet_hours" | "dropped_too_large", "conversation_id": "…", "http_status": 200, "sends_last_hour": 3, "sends_last_24h": 27, "remaining_last_hour": 17, "remaining_last_24h": 73}`.

`reply_to` accepts an `input_text.*` entity (cut to its max length), a `notify.*` entity, a legacy `notify.<service>`, or `persistent_notification`. A reply can never be routed back to Grok Bot's own notify entity.

### Events

| Event | When |
| --- | --- |
| `grok_bot_sent` | A message was accepted by the webhook. |
| `grok_bot_failed` | The webhook was unreachable or returned an error. |
| `grok_bot_dropped` | Dropped. `reason` is `dropped_budget`, `dropped_paused`, `dropped_quiet_hours`, `dropped_cooldown` or `dropped_too_large`. |
| `grok_bot_reply` | Grok Bot answered (`message`, `title`, `conversation_id`, `reply_to`, `data`). |

### Entities

`sensor.grok_bot_last_reply` (with `history`), `last_status`, `last_sent`, `sends_last_hour` and `sends_last_24_hours` (with `limit`/`remaining`), plus the diagnostic counters `sent_total`, `failed_total`, `dropped_total` and `awaiting_reply`. There is also `switch.grok_bot_pause_sending`, the buttons *Send test ping*, *Send health report*, *Fix open repairs* and *Reset budget counters*, and, when enabled, `notify.grok_bot` and `conversation.grok_bot`.

**Assist:** pick *Grok Bot* as the conversation agent of a voice assistant. Assist answers right away with *"Sent to Grok Bot. I'll answer shortly."* The real answer arrives later in the reply sensor, the card and the `grok_bot_reply` event, with the same `conversation_id`.

### Payload schema (what the webhook receives)

```json
{
  "schema": 1,
  "type": "ask | custom_event | notify | conversation | diagnose | fix_issue | health_report | ping | state_changed | event | log_error | automation_error | setup_error | setup_failed | repair_issue | entity_unavailable",
  "message": "Human-readable text (template output when configured)",
  "source": "service | assist | <entity_id> | <event_type> | <logger>",
  "context": [{"entity_id": "sensor.attic", "state": "31.2", "name": "Attic", "last_changed": "…", "attributes": {}}],
  "reply_to": "input_text.grok_answer",
  "conversation_id": "8f3c…",
  "notify_user": false,
  "action_mode": "report | diagnose | fix",
  "allow_fix": false,
  "data": {"…": "type-specific details: issue, event_data, logger, traceback, repeats_suppressed, …"},
  "timestamp": "2026-11-13T08:40:00+00:00",
  "ha_instance": {"name": "Home", "version": "2026.11.0", "integration_version": "0.1.0", "config_entry_id": "…", "time_zone": "Europe/Amsterdam"},
  "reply_with": {"service": "grok_bot.reply", "data": {"config_entry_id": "…", "conversation_id": "8f3c…", "message": "<your answer>"}},
  "truncated": true
}
```

`truncated` only appears when the payload had to be shrunk to fit the size limit. The integration first drops attributes, then large detail fields, then shortens the message.

**Telling Grok Bot what to do.** Put this in the routine's instructions: *"Handle the Home Assistant payload. Respect `action_mode`: for `report`, only summarise; for `diagnose`, investigate with the Home Assistant connector without changing anything; for `fix`, only perform safe, reversible fixes (reload a config entry, retry, toggle back). Always answer by calling `grok_bot.reply` with the given `conversation_id`. Message me only when `notify_user` is true or something failed."*

### Inbound webhook (optional)

When enabled under **Features**, Grok Bot (or anything else) can POST `{"message": "…", "conversation_id": "…", "title": "…"}` to `https://<your-ha>/api/webhook/<id>`. The path is shown on the Features page. Treat the id as a secret. `grok_bot.reply` through the Home Assistant connector is the primary path and needs no open webhook.

### Card options

```yaml
type: custom:grok-bot-card
title: Grok Bot            # optional
avatar_url: /local/me.png  # optional: your own picture instead of the animated bot
config_entry_id: …         # optional, only with several Grok Bot entries
show_chips: true
show_ask: true
show_history: true
show_issues: true
max_history: 6
max_issues: 4
default_mode: report       # report | diagnose | fix
```

### Blueprints

[![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FDonTranQuiL%2Fgrok-bot-ha%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fgrok_bot%2Fask_on_threshold.yaml)

* `blueprints/automation/grok_bot/ask_on_threshold.yaml`: ask Grok Bot when a sensor stays above or below a value, with a cooldown.
* `blueprints/automation/grok_bot/nightly_health_report.yaml`: one health report per day.
* `blueprints/automation/grok_bot/reply_to_phone.yaml`: push every reply to the companion app (free, no Grok Bot usage).

(The blueprint import button needs a public repository. While this one is private, copy the files to `config/blueprints/automation/grok_bot/`.)

## Privacy and security

* The Authorization header value is stored in the config entry, sent only to the webhook URL, never logged, and redacted in diagnostics along with the webhook URL and the inbound webhook id.
* Only https webhook URLs are accepted.
* The integration never forwards its own log lines or events, so it can't loop.

## Limitations

* There is no public Grok Bot API. Delivery is a webhook POST, and answers arrive asynchronously through `grok_bot.reply`.
* Grok Bot can only act in Home Assistant if its Home Assistant connector has access.
* Because the transport is a private webhook, this integration is meant for the Marketplace and HACS, not Home Assistant core.
