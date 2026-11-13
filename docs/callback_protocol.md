# Grok Bot ↔ Home Assistant access protocol (v1)

How Grok Bot answers and acts in a Home Assistant instance that sent it a `grok_bot` payload.

## 1. Choose the path from `payload.access`

```json
"access": {
  "method": "mcp | webhook | none",
  "configured_method": "mcp | webhook | none",
  "mcp_ready": true,
  "mcp_provider": "ha_mcp | mcp_server | null",
  "connector_url_hint": "https://<external>/api/webhook/<HA-MCP webhook id>  |  https://<external>/api/mcp",
  "ha_instance": {"name": "Home", "external_url": "https://…", "config_entry_id": "…"}
}
```

| `method` | What Grok Bot does |
| --- | --- |
| `mcp` | Use the Home Assistant MCP connector configured in the Grok Bot app for this instance (HA-MCP preferred, core MCP Server fallback). Answer by calling the `grok_bot.reply` action with `config_entry_id` and `conversation_id`. Scope is decided by HA-MCP / MCP Server (LLM API, exposed entities). |
| `webhook` | Use the `callback` block below. |
| `none` | No path back. Answer in the Grok Bot app; the integration's reply timeout marks the request *Replied in Grok Bot app*. |

Match the instance by `ha_instance.name` / `external_url` when several Home Assistant connectors exist.

## 2. Access webhook (`method: webhook`)

Payloads carry:

```json
"callback": {
  "protocol": 1,
  "url": "https://<cloudhook or external URL>/api/webhook/<id>",
  "token": "<secret>",
  "token_header": "X-Grok-Bot-Token",
  "access_level": "reply | read | control | fix",
  "allowed_actions": ["reply", "get_states", "…"],
  "expires": "2026-11-13T10:15:00+00:00",
  "conversation_id": "8f3c…"
}
```

Request: `POST callback.url`, header `X-Grok-Bot-Token: <token>` (or `Authorization: Bearer <token>`, or `"token"` in the body), JSON body:

```json
{"conversation_id": "8f3c…", "actions": [{"type": "get_states", "domains": ["light"]}, {"type": "reply", "message": "Done"}]}
```

A 0.1.0 style body `{"message": "…", "conversation_id": "…"}` is treated as one `reply` action. At most 10 actions per request.

| Action | Fields | Level |
| --- | --- | --- |
| `reply` | `message`, `title`, `data`, `reply_to`, `conversation_id` | reply |
| `get_states` | `entity_ids` / `domains`, `state`, `attributes`, `limit` (≤1000) | read |
| `get_history` | `entity_ids` (≤10), `hours` (≤48) | read |
| `list_repairs` | – | read |
| `get_logs` | `level` (warning/error/critical), `limit` (≤100) | read |
| `list_entries` | `domain`, `state` | read |
| `call_service` | `domain`, `service`, `data`, `target`, `return_response` | control |
| `reload_entry` | `entry_id` | fix |
| `ignore_repair` | `domain`, `issue_id`, `ignore` | fix |
| `enable_entity` | `entity_id` | fix |

Response `200` (or `400` when nothing ran):

```json
{"ok": true, "access_level": "read", "conversation_id": "8f3c…", "results": [{"type": "get_states", "ok": true, "result": []}]}
```

Errors per action: `{"ok": false, "error": "denied", "reason": "…"}` or the exception name. `401` for a bad token. Responses are capped at the configured size (`truncated: true`).

Rules enforced by the integration:

* The action must be allowed by the level **and** the per-action toggles.
* By default the `conversation_id` must belong to an open session (opened when the payload was sent, TTL 15 min); a `reply` is also accepted while the conversation is still awaiting a reply.
* Always blocked: `homeassistant.restart/stop/reload_all`, `recorder.purge/purge_entities/disable`, `update.install`, and every action in `hassio`, `shell_command`, `python_script`, `pyscript`, `command_line` and `grok_bot`. Grok Bot can't reload its own entry.
* Optional domain and entity allowlists; with an entity allowlist only `entity_id` targets are allowed.
* Every action is audited (*Last Grok Bot action* sensor, `grok_bot_action` event, optional notification). *Rotate access token* invalidates the token and all sessions.

## 3. Awaiting reply

A send that expects an answer is "awaiting" until `grok_bot.reply` (or a `reply` action) arrives with its `conversation_id`, the reply timeout passes (default 10 min, `last_status: answered_elsewhere`), or the user presses *Mark replies handled*. The first reply of any kind also clears the *Grok Bot not connected yet* repair.
