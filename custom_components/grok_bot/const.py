"""Constants for the Grok Bot integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "grok_bot"
INTEGRATION_VERSION: Final = "0.1.1"
PAYLOAD_SCHEMA_VERSION: Final = 1

# Config entry data
CONF_WEBHOOK_URL: Final = "webhook_url"
CONF_AUTH_HEADER: Final = "auth_header"

# Options: features (all opt-in, every send costs Grok Bot usage)
CONF_ENABLE_NOTIFY: Final = "enable_notify"
CONF_ENABLE_CONVERSATION: Final = "enable_conversation"
CONF_ENABLE_INBOUND_WEBHOOK: Final = "enable_inbound_webhook"
CONF_INCLUDE_ATTRIBUTES: Final = "include_attributes"

# Options: budget
CONF_MAX_PER_HOUR: Final = "max_per_hour"
CONF_MAX_PER_DAY: Final = "max_per_day"
CONF_MIN_INTERVAL: Final = "min_interval"

# Options: forwarding (all empty by default = nothing automatic is sent)
CONF_FORWARD_ENTITIES: Final = "forward_entities"
CONF_FORWARD_EVENTS: Final = "forward_events"
CONF_IGNORE_UNAVAILABLE: Final = "ignore_unavailable"
CONF_FILTERS: Final = "filters"

# Per-entity filter keys
FILTER_TO_STATES: Final = "to_states"
FILTER_ATTRIBUTE: Final = "attribute"
FILTER_ABOVE: Final = "above"
FILTER_BELOW: Final = "below"
FILTER_MIN_INTERVAL: Final = "min_interval"

# Options: setup mode / presets
CONF_MODE: Final = "mode"
MODE_SIMPLE: Final = "simple"
MODE_ADVANCED: Final = "advanced"
CONF_PRESET: Final = "preset"
PRESET_ASK_ONLY: Final = "ask_only"
PRESET_ERRORS_ONLY: Final = "errors_only"
PRESET_ERRORS_REPAIRS_DIAGNOSE: Final = "errors_repairs_diagnose"
PRESET_CUSTOM: Final = "custom"
PRESETS: Final = [
    PRESET_ASK_ONLY,
    PRESET_ERRORS_ONLY,
    PRESET_ERRORS_REPAIRS_DIAGNOSE,
    PRESET_CUSTOM,
]

# Action modes: what Grok Bot may do with a forwarded item
ACTION_REPORT: Final = "report"
ACTION_DIAGNOSE: Final = "diagnose"
ACTION_FIX: Final = "fix"
ACTION_MODES: Final = [ACTION_REPORT, ACTION_DIAGNOSE, ACTION_FIX]

# Options: per-trigger action modes for state/event forwarding
CONF_STATE_ACTION: Final = "state_action"
CONF_EVENT_ACTION: Final = "event_action"

# Options: watchers (all off by default)
CONF_WATCH_LOGS: Final = "watch_logs"
CONF_LOG_LEVEL: Final = "log_level"
CONF_LOG_LOGGERS: Final = "log_loggers"
CONF_LOG_LOGGER_MODE: Final = "log_logger_mode"
LOGGER_MODE_ALL: Final = "all"
LOGGER_MODE_ALLOW: Final = "allow"
LOGGER_MODE_DENY: Final = "deny"
CONF_LOG_DEDUPE: Final = "log_dedupe"
CONF_LOG_ACTION: Final = "log_action"
CONF_WATCH_REPAIRS: Final = "watch_repairs"
CONF_REPAIRS_ACTION: Final = "repairs_action"
CONF_WATCH_UNAVAILABLE: Final = "watch_unavailable"
CONF_UNAVAILABLE_MINUTES: Final = "unavailable_minutes"
CONF_UNAVAILABLE_ACTION: Final = "unavailable_action"
CONF_WATCH_AUTOMATIONS: Final = "watch_automations"
CONF_AUTOMATIONS_ACTION: Final = "automations_action"
CONF_WATCH_SETUP: Final = "watch_setup"
CONF_SETUP_ACTION: Final = "setup_action"

# Options: advanced delivery
CONF_QUIET_HOURS: Final = "quiet_hours"
CONF_QUIET_START: Final = "quiet_start"
CONF_QUIET_END: Final = "quiet_end"
CONF_MAX_PAYLOAD: Final = "max_payload_bytes"
CONF_TEMPLATE_STATE: Final = "template_state"
CONF_TEMPLATE_EVENT: Final = "template_event"
CONF_TEMPLATE_ISSUE: Final = "template_issue"

DEFAULT_LOG_DEDUPE: Final = 3600
DEFAULT_UNAVAILABLE_MINUTES: Final = 15
DEFAULT_MAX_PAYLOAD: Final = 16000

# Entry data (generated, not user-entered)
CONF_INBOUND_WEBHOOK_ID: Final = "inbound_webhook_id"

DEFAULT_MAX_PER_HOUR: Final = 20
DEFAULT_MAX_PER_DAY: Final = 100
DEFAULT_MIN_INTERVAL: Final = 300  # seconds between forwards of one entity/event
DEFAULT_TIMEOUT: Final = 15

DEFAULT_OPTIONS: Final[dict] = {
    CONF_MODE: MODE_SIMPLE,
    CONF_PRESET: PRESET_ASK_ONLY,
    CONF_STATE_ACTION: ACTION_REPORT,
    CONF_EVENT_ACTION: ACTION_REPORT,
    CONF_WATCH_LOGS: False,
    CONF_LOG_LEVEL: "error",
    CONF_LOG_LOGGERS: [],
    CONF_LOG_LOGGER_MODE: LOGGER_MODE_ALL,
    CONF_LOG_DEDUPE: DEFAULT_LOG_DEDUPE,
    CONF_LOG_ACTION: ACTION_REPORT,
    CONF_WATCH_REPAIRS: False,
    CONF_REPAIRS_ACTION: ACTION_REPORT,
    CONF_WATCH_UNAVAILABLE: [],
    CONF_UNAVAILABLE_MINUTES: DEFAULT_UNAVAILABLE_MINUTES,
    CONF_UNAVAILABLE_ACTION: ACTION_REPORT,
    CONF_WATCH_AUTOMATIONS: False,
    CONF_AUTOMATIONS_ACTION: ACTION_REPORT,
    CONF_WATCH_SETUP: False,
    CONF_SETUP_ACTION: ACTION_REPORT,
    CONF_QUIET_HOURS: False,
    CONF_QUIET_START: "23:00:00",
    CONF_QUIET_END: "07:00:00",
    CONF_MAX_PAYLOAD: DEFAULT_MAX_PAYLOAD,
    CONF_TEMPLATE_STATE: "",
    CONF_TEMPLATE_EVENT: "",
    CONF_TEMPLATE_ISSUE: "",
    CONF_ENABLE_NOTIFY: False,
    CONF_ENABLE_CONVERSATION: False,
    CONF_ENABLE_INBOUND_WEBHOOK: False,
    CONF_INCLUDE_ATTRIBUTES: True,
    CONF_MAX_PER_HOUR: DEFAULT_MAX_PER_HOUR,
    CONF_MAX_PER_DAY: DEFAULT_MAX_PER_DAY,
    CONF_MIN_INTERVAL: DEFAULT_MIN_INTERVAL,
    CONF_FORWARD_ENTITIES: [],
    CONF_FORWARD_EVENTS: [],
    CONF_IGNORE_UNAVAILABLE: True,
    CONF_FILTERS: {},
}

# Preset -> option overrides (applied on top of DEFAULT_OPTIONS' watcher keys)
PRESET_OPTIONS: Final[dict[str, dict]] = {
    PRESET_ASK_ONLY: {
        CONF_WATCH_LOGS: False,
        CONF_WATCH_REPAIRS: False,
        CONF_WATCH_AUTOMATIONS: False,
        CONF_WATCH_SETUP: False,
    },
    PRESET_ERRORS_ONLY: {
        CONF_WATCH_LOGS: True,
        CONF_LOG_LEVEL: "error",
        CONF_LOG_ACTION: ACTION_REPORT,
        CONF_WATCH_REPAIRS: False,
        CONF_WATCH_AUTOMATIONS: True,
        CONF_AUTOMATIONS_ACTION: ACTION_REPORT,
        CONF_WATCH_SETUP: True,
        CONF_SETUP_ACTION: ACTION_REPORT,
    },
    PRESET_ERRORS_REPAIRS_DIAGNOSE: {
        CONF_WATCH_LOGS: True,
        CONF_LOG_LEVEL: "error",
        CONF_LOG_ACTION: ACTION_DIAGNOSE,
        CONF_WATCH_REPAIRS: True,
        CONF_REPAIRS_ACTION: ACTION_DIAGNOSE,
        CONF_WATCH_AUTOMATIONS: True,
        CONF_AUTOMATIONS_ACTION: ACTION_DIAGNOSE,
        CONF_WATCH_SETUP: True,
        CONF_SETUP_ACTION: ACTION_DIAGNOSE,
    },
}

LOG_LEVELS: Final = ["warning", "error", "critical"]

# Events that may never be forwarded (loops / floods)
BLOCKED_EVENT_TYPES: Final = frozenset(
    {
        "state_changed",
        "call_service",
        "service_registered",
        "service_removed",
        "component_loaded",
        "core_config_updated",
        "entity_registry_updated",
        "device_registry_updated",
        "recorder_5min_statistics_generated",
        "recorder_hourly_statistics_generated",
        "logbook_entry",
        "system_log_event",
        "homeassistant_close",
        "homeassistant_final_write",
    }
)

# Fired events
EVENT_REPLY: Final = "grok_bot_reply"
EVENT_SENT: Final = "grok_bot_sent"
EVENT_DROPPED: Final = "grok_bot_dropped"
EVENT_FAILED: Final = "grok_bot_failed"

# Services
SERVICE_ASK: Final = "ask"
SERVICE_SEND_EVENT: Final = "send_event"
SERVICE_REPLY: Final = "reply"
SERVICE_PING: Final = "ping"
SERVICE_DIAGNOSE: Final = "diagnose"
SERVICE_FIX_ISSUE: Final = "fix_issue"
SERVICE_HEALTH_REPORT: Final = "health_report"

ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_MESSAGE: Final = "message"
ATTR_TITLE: Final = "title"
ATTR_CONTEXT_ENTITIES: Final = "context_entities"
ATTR_REPLY_TO: Final = "reply_to"
ATTR_CONVERSATION_ID: Final = "conversation_id"
ATTR_NOTIFY_USER: Final = "notify_user"
ATTR_BYPASS_BUDGET: Final = "bypass_budget"
ATTR_EVENT_TYPE: Final = "event_type"
ATTR_DATA: Final = "data"
ATTR_ISSUE_ID: Final = "issue_id"
ATTR_ISSUE_DOMAIN: Final = "issue_domain"
ATTR_TARGET_ENTRY: Final = "target_config_entry_id"
ATTR_ALLOW_FIX: Final = "allow_fix"
ATTR_ACTION_MODE: Final = "action_mode"

# Delivery statuses
STATUS_IDLE: Final = "idle"
STATUS_SENT: Final = "sent"
STATUS_FAILED: Final = "failed"
STATUS_AUTH_FAILED: Final = "auth_failed"
STATUS_DROPPED_BUDGET: Final = "dropped_budget"
STATUS_DROPPED_PAUSED: Final = "dropped_paused"
STATUS_DROPPED_COOLDOWN: Final = "dropped_cooldown"
STATUS_DROPPED_QUIET: Final = "dropped_quiet_hours"
STATUS_DROPPED_TOO_LARGE: Final = "dropped_too_large"
STATUSES: Final = [
    STATUS_IDLE,
    STATUS_SENT,
    STATUS_FAILED,
    STATUS_AUTH_FAILED,
    STATUS_DROPPED_BUDGET,
    STATUS_DROPPED_PAUSED,
    STATUS_DROPPED_COOLDOWN,
    STATUS_DROPPED_QUIET,
    STATUS_DROPPED_TOO_LARGE,
]

SIGNAL_UPDATE: Final = "grok_bot_update_{}"

MAX_MESSAGE_LEN: Final = 8000
MAX_STATE_LEN: Final = 255

# ------------------------------------------------------------------ access
# User-controlled access for Grok Bot back into this Home Assistant through a
# token-protected webhook (for instances Grok Bot's own connector can't reach).
CONF_ACCESS_LEVEL: Final = "access_level"
CONF_ACCESS_ACTIONS: Final = "access_actions"
CONF_ACCESS_DOMAINS: Final = "access_domains"
CONF_ACCESS_ENTITIES: Final = "access_entities"
CONF_ACCESS_REQUIRE_PENDING: Final = "access_require_pending"
CONF_ACCESS_TTL: Final = "access_ttl"
CONF_ACCESS_NOTIFY: Final = "access_notify"
CONF_ACCESS_MAX_RESPONSE: Final = "access_max_response_kb"

ACCESS_OFF: Final = "off"
ACCESS_REPLY: Final = "reply"
ACCESS_READ: Final = "read"
ACCESS_CONTROL: Final = "control"
ACCESS_FIX: Final = "fix"
ACCESS_LEVELS: Final = [ACCESS_OFF, ACCESS_REPLY, ACCESS_READ, ACCESS_CONTROL, ACCESS_FIX]

ACT_REPLY: Final = "reply"
ACT_GET_STATES: Final = "get_states"
ACT_GET_HISTORY: Final = "get_history"
ACT_LIST_REPAIRS: Final = "list_repairs"
ACT_GET_LOGS: Final = "get_logs"
ACT_LIST_ENTRIES: Final = "list_entries"
ACT_CALL_SERVICE: Final = "call_service"
ACT_RELOAD_ENTRY: Final = "reload_entry"
ACT_IGNORE_REPAIR: Final = "ignore_repair"
ACT_ENABLE_ENTITY: Final = "enable_entity"
READ_ACTIONS: Final = [
    ACT_GET_STATES,
    ACT_GET_HISTORY,
    ACT_LIST_REPAIRS,
    ACT_GET_LOGS,
    ACT_LIST_ENTRIES,
]
FIX_ACTIONS: Final = [ACT_RELOAD_ENTRY, ACT_IGNORE_REPAIR, ACT_ENABLE_ENTITY]
ALL_ACTIONS: Final = [ACT_REPLY, *READ_ACTIONS, ACT_CALL_SERVICE, *FIX_ACTIONS]
LEVEL_ACTIONS: Final[dict[str, frozenset[str]]] = {
    ACCESS_OFF: frozenset(),
    ACCESS_REPLY: frozenset({ACT_REPLY}),
    ACCESS_READ: frozenset({ACT_REPLY, *READ_ACTIONS}),
    ACCESS_CONTROL: frozenset({ACT_REPLY, *READ_ACTIONS, ACT_CALL_SERVICE}),
    ACCESS_FIX: frozenset(ALL_ACTIONS),
}

# Never callable through the access webhook, whatever the level or allowlist.
BLOCKED_SERVICE_DOMAINS: Final = frozenset(
    {"hassio", "shell_command", "python_script", "pyscript", "command_line", DOMAIN}
)
BLOCKED_SERVICES: Final = frozenset(
    {
        "homeassistant.restart",
        "homeassistant.stop",
        "homeassistant.reload_all",
        "recorder.purge",
        "recorder.purge_entities",
        "recorder.disable",
        "update.install",
    }
)

DEFAULT_ACCESS_TTL: Final = 15  # minutes
DEFAULT_ACCESS_MAX_RESPONSE: Final = 64  # kB
MAX_ACTIONS_PER_REQUEST: Final = 20
AUDIT_LEN: Final = 25
EVENT_ACTION: Final = "grok_bot_action"
SERVICE_ROTATE_TOKEN: Final = "rotate_token"
TOKEN_HEADER: Final = "X-Grok-Bot-Token"
CALLBACK_PROTOCOL_VERSION: Final = 1

DEFAULT_OPTIONS.update(
    {
        CONF_ACCESS_LEVEL: ACCESS_OFF,
        CONF_ACCESS_ACTIONS: list(ALL_ACTIONS),
        CONF_ACCESS_DOMAINS: [],
        CONF_ACCESS_ENTITIES: [],
        CONF_ACCESS_REQUIRE_PENDING: True,
        CONF_ACCESS_TTL: DEFAULT_ACCESS_TTL,
        CONF_ACCESS_NOTIFY: False,
        CONF_ACCESS_MAX_RESPONSE: DEFAULT_ACCESS_MAX_RESPONSE,
    }
)

# How Grok Bot reaches back into this instance.
CONF_ACCESS_METHOD: Final = "access_method"
METHOD_MCP: Final = "mcp"  # Home Assistant's own MCP Server integration (default)
METHOD_WEBHOOK: Final = "webhook"  # this integration's token-protected access webhook
METHOD_NONE: Final = "none"
ACCESS_METHODS: Final = [METHOD_MCP, METHOD_WEBHOOK, METHOD_NONE]
MCP_DOMAIN: Final = "mcp_server"
MCP_PATH: Final = "/api/mcp"
MCP_SETUP_URL: Final = "https://my.home-assistant.io/redirect/config_flow_start/?domain=mcp_server"
ISSUE_MCP_MISSING: Final = "mcp_server_missing"

# Awaiting-reply housekeeping: replies may happen in the Grok Bot app instead.
CONF_REPLY_TIMEOUT: Final = "reply_timeout"
DEFAULT_REPLY_TIMEOUT: Final = 10  # minutes, 0 = never
STATUS_ANSWERED_ELSEWHERE: Final = "answered_elsewhere"
STATUSES.append(STATUS_ANSWERED_ELSEWHERE)

DEFAULT_OPTIONS.update(
    {
        CONF_ACCESS_METHOD: METHOD_MCP,
        CONF_ACCESS_LEVEL: ACCESS_REPLY,
        CONF_REPLY_TIMEOUT: DEFAULT_REPLY_TIMEOUT,
    }
)

# HA-MCP (homeassistant-ai/ha-mcp, custom integration) is preferred over core
# mcp_server when both are present.
HA_MCP_DOMAIN: Final = "ha_mcp_tools"
HA_MCP_SERVER_ENTRY_TYPE: Final = "server"
HA_MCP_INSTALL_URL: Final = (
    "https://my.home-assistant.io/redirect/hacs_repository/"
    "?owner=homeassistant-ai&repository=ha-mcp&category=integration"
)
HA_MCP_SETUP_URL: Final = (
    "https://my.home-assistant.io/redirect/config_flow_start/?domain=ha_mcp_tools"
)
PROVIDER_HA_MCP: Final = "ha_mcp"
PROVIDER_MCP_SERVER: Final = "mcp_server"
ISSUE_NOT_CONNECTED: Final = "not_connected"
SETUP_NOTIFICATION_ID: Final = "grok_bot_setup_prompt_{}"
SIGNAL_CONNECTED: Final = "grok_bot_connected"
