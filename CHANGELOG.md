# Changelog

## 0.1.4 (2026-11-13)

First public release.

### Fixed
* **A fix that restarts Home Assistant no longer loses Grok Bot's reply.** `grok_bot.safe_restart` now waits for the reply of the conversation that asked for the restart (new optional `conversation_id` field; without it, any conversation still awaiting a reply). The restart goes ahead 2 seconds after that reply arrives, or after 25 seconds at the latest. When nothing awaits a reply it restarts right away, as before.

### Added
* Awaiting conversations (with their `reply_to`) are kept in storage, so a reply that arrives after a restart still lands in the right conversation. Their reply timeout starts again after the restart.
* After a restart through `grok_bot.safe_restart` the conversation history gets a *Restart done, Home Assistant is back* entry, and the audit sensor a `trusted_restart_done` record.
* New *Last status* states **Restarting after the reply** and **Restarted, waiting for the result**. The card shows them in the header and the reply bubble, also after a page reload.
* `sensor.grok_bot_awaiting_reply` attributes `restart_scheduled`, `restarted_waiting` and `conversations`.
* The setup prompt tells Grok Bot to pass the `conversation_id` to `safe_restart` and to reply right after it.
* README: demo GIF, screenshots of the Access page, the options menu and the device page.

## 0.1.3
* Every options page saves on Submit (Access/Trusted settings were lost when the dialog was closed before *Save and close*).
* Saved options are copied instead of aliased; reauthenticate and reconfigure reload through the update listener.

## 0.1.2
* Opt-in Trusted access: YAML edits and restarts for fix requests, with a window of 30 min, 2 h, 24 h or Always on (with a warning repair).
* `grok_bot.edit_yaml` (backup, validation, config check, automatic restore), `prepare_change`, `restore_backup` and `safe_restart` (config check first).
* `grok_bot.clear_history` and a *Clear conversation history* button.

## 0.1.1
* HA-MCP first access with core MCP Server as fallback, guided onboarding with a setup prompt (English and Dutch), *Grok Bot not connected yet* repair, reply timeout and *Mark replies handled*.

## 0.1.0
* First test build: webhook transport, triggers and problem watchers, budget guard, replies, card and blueprints.
