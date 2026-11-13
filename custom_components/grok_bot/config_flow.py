"""Config, reauth, reconfigure and options flows for Grok Bot."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from homeassistant.components import webhook
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .api import (
    GrokBotAuthError,
    GrokBotClient,
    GrokBotConnectionError,
    is_valid_webhook_url,
    normalize_auth_header,
)
from .const import (
    ACTION_MODES,
    CONF_AUTH_HEADER,
    CONF_AUTOMATIONS_ACTION,
    CONF_ENABLE_CONVERSATION,
    CONF_ENABLE_INBOUND_WEBHOOK,
    CONF_ENABLE_NOTIFY,
    CONF_EVENT_ACTION,
    CONF_FILTERS,
    CONF_FORWARD_ENTITIES,
    CONF_FORWARD_EVENTS,
    CONF_IGNORE_UNAVAILABLE,
    CONF_INBOUND_WEBHOOK_ID,
    CONF_INCLUDE_ATTRIBUTES,
    CONF_LOG_ACTION,
    CONF_LOG_DEDUPE,
    CONF_LOG_LEVEL,
    CONF_LOG_LOGGER_MODE,
    CONF_LOG_LOGGERS,
    CONF_MAX_PAYLOAD,
    CONF_MAX_PER_DAY,
    CONF_MAX_PER_HOUR,
    CONF_MIN_INTERVAL,
    CONF_MODE,
    CONF_PRESET,
    CONF_QUIET_END,
    CONF_QUIET_HOURS,
    CONF_QUIET_START,
    CONF_REPAIRS_ACTION,
    CONF_SETUP_ACTION,
    CONF_STATE_ACTION,
    CONF_TEMPLATE_EVENT,
    CONF_TEMPLATE_ISSUE,
    CONF_TEMPLATE_STATE,
    CONF_UNAVAILABLE_ACTION,
    CONF_UNAVAILABLE_MINUTES,
    CONF_WATCH_AUTOMATIONS,
    CONF_WATCH_LOGS,
    CONF_WATCH_REPAIRS,
    CONF_WATCH_SETUP,
    CONF_WATCH_UNAVAILABLE,
    CONF_WEBHOOK_URL,
    DEFAULT_OPTIONS,
    DOMAIN,
    FILTER_ABOVE,
    FILTER_ATTRIBUTE,
    FILTER_BELOW,
    FILTER_MIN_INTERVAL,
    FILTER_TO_STATES,
    INTEGRATION_VERSION,
    LOG_LEVELS,
    LOGGER_MODE_ALL,
    LOGGER_MODE_ALLOW,
    LOGGER_MODE_DENY,
    MODE_ADVANCED,
    MODE_SIMPLE,
    PAYLOAD_SCHEMA_VERSION,
    PRESET_CUSTOM,
    PRESET_OPTIONS,
    PRESETS,
)
from .triggers import event_type_allowed

CONF_SEND_TEST = "send_test"
CONF_REMOVE = "remove"
CONF_FILTER_ENTITY = "filter_entity"
SECTIONS = ("logs", "repairs", "unavailable", "automations", "setup")


def unique_id_for(url: str) -> str:
    """Stable id for a webhook URL without storing the URL in the id."""
    return hashlib.sha256(url.strip().encode()).hexdigest()[:16]


def ping_payload() -> dict[str, Any]:
    return {
        "schema": PAYLOAD_SCHEMA_VERSION,
        "type": "ping",
        "message": "Grok Bot integration setup test",
        "source": "config_flow",
        "timestamp": dt_util.utcnow().isoformat(),
        "ha_instance": {"integration_version": INTEGRATION_VERSION},
    }


def apply_preset(options: dict[str, Any], preset: str) -> dict[str, Any]:
    """Options after choosing a preset (Custom switches to Advanced mode)."""
    out = {**options, CONF_PRESET: preset}
    if preset == PRESET_CUSTOM:
        out[CONF_MODE] = MODE_ADVANCED
        return out
    out[CONF_MODE] = MODE_SIMPLE
    out.update(PRESET_OPTIONS[preset])
    return out


def _select(options: list[str], key: str, multiple: bool = False, custom: bool = False):
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            translation_key=key,
            multiple=multiple,
            custom_value=custom,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _action(key: str = "action_mode"):
    return _select(ACTION_MODES, key)


def _num(minimum: float, maximum: float, step: float = 1, unit: str | None = None):
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


async def _validate(hass, url: str, header: str, send_test: bool) -> str | None:
    """Return an error key, or None when the webhook accepted the ping."""
    if not is_valid_webhook_url(url):
        return "invalid_url"
    if not normalize_auth_header(header):
        return "invalid_auth"
    if not send_test:
        return None
    try:
        await GrokBotClient(hass, url, header).async_validate(ping_payload())
    except GrokBotAuthError:
        return "invalid_auth"
    except GrokBotConnectionError:
        return "cannot_connect"
    except Exception:
        return "unknown"
    return None


class GrokBotConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up Grok Bot."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> GrokBotOptionsFlow:
        return GrokBotOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_WEBHOOK_URL].strip()
            await self.async_set_unique_id(unique_id_for(url))
            self._abort_if_unique_id_configured()
            error = await _validate(
                self.hass, url, user_input[CONF_AUTH_HEADER], user_input[CONF_SEND_TEST]
            )
            if error:
                errors["base"] = error
            else:
                self._data = {
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_WEBHOOK_URL: url,
                    CONF_AUTH_HEADER: normalize_auth_header(user_input[CONF_AUTH_HEADER]),
                    CONF_INBOUND_WEBHOOK_ID: webhook.async_generate_id(),
                }
                return await self.async_step_preset()
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Grok Bot"): str,
                vol.Required(CONF_WEBHOOK_URL): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                ),
                vol.Required(CONF_AUTH_HEADER): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_SEND_TEST, default=True): bool,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_preset(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            options = apply_preset(dict(DEFAULT_OPTIONS), user_input[CONF_PRESET])
            return self.async_create_entry(
                title=self._data[CONF_NAME], data=self._data, options=options
            )
        return self.async_show_form(
            step_id="preset",
            data_schema=vol.Schema(
                {vol.Required(CONF_PRESET, default=PRESETS[0]): _select(PRESETS, "preset")}
            ),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _validate(
                self.hass,
                entry.data[CONF_WEBHOOK_URL],
                user_input[CONF_AUTH_HEADER],
                user_input[CONF_SEND_TEST],
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_AUTH_HEADER: normalize_auth_header(user_input[CONF_AUTH_HEADER])
                    },
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTH_HEADER): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_SEND_TEST, default=True): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_WEBHOOK_URL].strip()
            new_id = unique_id_for(url)
            if new_id != entry.unique_id:
                await self.async_set_unique_id(new_id)
                self._abort_if_unique_id_configured()
            error = await _validate(
                self.hass, url, user_input[CONF_AUTH_HEADER], user_input[CONF_SEND_TEST]
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=new_id,
                    data_updates={
                        CONF_WEBHOOK_URL: url,
                        CONF_AUTH_HEADER: normalize_auth_header(user_input[CONF_AUTH_HEADER]),
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_WEBHOOK_URL, default=entry.data[CONF_WEBHOOK_URL]
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                    ),
                    vol.Required(CONF_AUTH_HEADER): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_SEND_TEST, default=True): bool,
                }
            ),
            errors=errors,
        )


class GrokBotOptionsFlow(OptionsFlow):
    """Simple mode (presets) and Advanced mode (every option)."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._filter_entity: str | None = None

    @property
    def _opts(self) -> dict[str, Any]:
        if not self._options:
            self._options = {**DEFAULT_OPTIONS, **self.config_entry.options}
            self._options[CONF_FILTERS] = dict(self._options[CONF_FILTERS])
        return self._options

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._opts[CONF_MODE] == MODE_ADVANCED:
            menu = [
                "preset",
                "features",
                "budget",
                "forwarding",
                "entity_filter",
                "watchers",
                "templates",
                "simple_mode",
                "finish",
            ]
        else:
            menu = ["preset", "features", "budget", "advanced_mode", "finish"]
        return self.async_show_menu(
            step_id="init",
            menu_options=menu,
            description_placeholders={
                "mode": self._opts[CONF_MODE],
                "preset": self._opts[CONF_PRESET],
            },
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_create_entry(data=self._opts)

    async def async_step_advanced_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._opts[CONF_MODE] = MODE_ADVANCED
        return await self.async_step_init()

    async def async_step_simple_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._opts[CONF_MODE] = MODE_SIMPLE
        return await self.async_step_init()

    async def async_step_preset(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._options = apply_preset(self._opts, user_input[CONF_PRESET])
            return await self.async_step_init()
        return self.async_show_form(
            step_id="preset",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PRESET, default=self._opts[CONF_PRESET]): _select(
                        PRESETS, "preset"
                    )
                }
            ),
        )

    async def async_step_features(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._opts.update(user_input)
            return await self.async_step_init()
        o = self._opts
        webhook_id = self.config_entry.data.get(CONF_INBOUND_WEBHOOK_ID, "")
        return self.async_show_form(
            step_id="features",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENABLE_NOTIFY, default=o[CONF_ENABLE_NOTIFY]): bool,
                    vol.Required(
                        CONF_ENABLE_CONVERSATION, default=o[CONF_ENABLE_CONVERSATION]
                    ): bool,
                    vol.Required(
                        CONF_ENABLE_INBOUND_WEBHOOK,
                        default=o[CONF_ENABLE_INBOUND_WEBHOOK],
                    ): bool,
                    vol.Required(CONF_INCLUDE_ATTRIBUTES, default=o[CONF_INCLUDE_ATTRIBUTES]): bool,
                }
            ),
            description_placeholders={
                "webhook_path": webhook.async_generate_path(webhook_id) if webhook_id else "-"
            },
        )

    async def async_step_budget(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        advanced = self._opts[CONF_MODE] == MODE_ADVANCED
        if user_input is not None:
            values = {k: int(v) if isinstance(v, float) else v for k, v in user_input.items()}
            if values[CONF_MAX_PER_HOUR] > values[CONF_MAX_PER_DAY]:
                errors["base"] = "hour_over_day"
            else:
                self._opts.update(values)
                return await self.async_step_init()
        o = self._opts
        fields: dict[Any, Any] = {
            vol.Required(CONF_MAX_PER_HOUR, default=o[CONF_MAX_PER_HOUR]): _num(
                1, 1000, unit="sends"
            ),
            vol.Required(CONF_MAX_PER_DAY, default=o[CONF_MAX_PER_DAY]): _num(
                1, 10000, unit="sends"
            ),
        }
        if advanced:
            fields.update(
                {
                    vol.Required(CONF_MIN_INTERVAL, default=o[CONF_MIN_INTERVAL]): _num(
                        0, 86400, unit="s"
                    ),
                    vol.Required(CONF_QUIET_HOURS, default=o[CONF_QUIET_HOURS]): bool,
                    vol.Required(
                        CONF_QUIET_START, default=o[CONF_QUIET_START]
                    ): selector.TimeSelector(),
                    vol.Required(
                        CONF_QUIET_END, default=o[CONF_QUIET_END]
                    ): selector.TimeSelector(),
                    vol.Required(CONF_MAX_PAYLOAD, default=o[CONF_MAX_PAYLOAD]): _num(
                        1000, 256000, unit="B"
                    ),
                }
            )
        return self.async_show_form(step_id="budget", data_schema=vol.Schema(fields), errors=errors)

    async def async_step_forwarding(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            events = [e.strip() for e in user_input.get(CONF_FORWARD_EVENTS, []) if e.strip()]
            if any(not event_type_allowed(e) for e in events):
                errors[CONF_FORWARD_EVENTS] = "event_blocked"
            else:
                user_input[CONF_FORWARD_EVENTS] = events
                self._opts.update(user_input)
                # drop filters for entities that are no longer forwarded
                self._opts[CONF_FILTERS] = {
                    k: v
                    for k, v in self._opts[CONF_FILTERS].items()
                    if k in user_input[CONF_FORWARD_ENTITIES]
                }
                return await self.async_step_init()
        o = self._opts
        return self.async_show_form(
            step_id="forwarding",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_FORWARD_ENTITIES, default=o[CONF_FORWARD_ENTITIES]
                    ): selector.EntitySelector(selector.EntitySelectorConfig(multiple=True)),
                    vol.Required(CONF_STATE_ACTION, default=o[CONF_STATE_ACTION]): _action(),
                    vol.Required(CONF_IGNORE_UNAVAILABLE, default=o[CONF_IGNORE_UNAVAILABLE]): bool,
                    vol.Optional(CONF_FORWARD_EVENTS, default=o[CONF_FORWARD_EVENTS]): _select(
                        [], "forward_events", multiple=True, custom=True
                    ),
                    vol.Required(CONF_EVENT_ACTION, default=o[CONF_EVENT_ACTION]): _action(),
                }
            ),
            errors=errors,
        )

    async def async_step_entity_filter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entities = self._opts[CONF_FORWARD_ENTITIES]
        if not entities:
            return self.async_abort(reason="no_forward_entities")
        if user_input is not None:
            self._filter_entity = user_input[CONF_FILTER_ENTITY]
            return await self.async_step_filter_details()
        return self.async_show_form(
            step_id="entity_filter",
            data_schema=vol.Schema(
                {vol.Required(CONF_FILTER_ENTITY): _select(entities, "filter_entity")}
            ),
        )

    async def async_step_filter_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entity_id = self._filter_entity or ""
        current = self._opts[CONF_FILTERS].get(entity_id, {})
        if user_input is not None:
            if user_input.get(CONF_REMOVE):
                self._opts[CONF_FILTERS].pop(entity_id, None)
            else:
                rule = {
                    FILTER_TO_STATES: [s for s in user_input.get(FILTER_TO_STATES, []) if s],
                    FILTER_ATTRIBUTE: (user_input.get(FILTER_ATTRIBUTE) or "").strip(),
                    FILTER_ABOVE: user_input.get(FILTER_ABOVE),
                    FILTER_BELOW: user_input.get(FILTER_BELOW),
                    FILTER_MIN_INTERVAL: user_input.get(FILTER_MIN_INTERVAL),
                }
                self._opts[CONF_FILTERS][entity_id] = {
                    k: v for k, v in rule.items() if v not in (None, "", [])
                }
            return await self.async_step_init()
        schema = vol.Schema(
            {
                vol.Optional(FILTER_TO_STATES): _select(
                    [], "to_states", multiple=True, custom=True
                ),
                vol.Optional(FILTER_ATTRIBUTE): str,
                vol.Optional(FILTER_ABOVE): vol.Coerce(float),
                vol.Optional(FILTER_BELOW): vol.Coerce(float),
                vol.Optional(FILTER_MIN_INTERVAL): _num(0, 86400, unit="s"),
                vol.Optional(CONF_REMOVE, default=False): bool,
            }
        )
        return self.async_show_form(
            step_id="filter_details",
            data_schema=self.add_suggested_values_to_schema(schema, current),
            description_placeholders={"entity_id": entity_id},
        )

    async def async_step_watchers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            for name in SECTIONS:
                values = dict(user_input.get(name, {}))
                if CONF_LOG_DEDUPE in values:
                    values[CONF_LOG_DEDUPE] = int(values[CONF_LOG_DEDUPE])
                self._opts.update(values)
            self._opts[CONF_PRESET] = PRESET_CUSTOM
            return await self.async_step_init()
        o = self._opts
        schema = vol.Schema(
            {
                vol.Required("logs"): section(
                    vol.Schema(
                        {
                            vol.Required(CONF_WATCH_LOGS, default=o[CONF_WATCH_LOGS]): bool,
                            vol.Required(CONF_LOG_LEVEL, default=o[CONF_LOG_LEVEL]): _select(
                                LOG_LEVELS, "log_level"
                            ),
                            vol.Required(
                                CONF_LOG_LOGGER_MODE, default=o[CONF_LOG_LOGGER_MODE]
                            ): _select(
                                [LOGGER_MODE_ALL, LOGGER_MODE_ALLOW, LOGGER_MODE_DENY],
                                "logger_mode",
                            ),
                            vol.Optional(CONF_LOG_LOGGERS, default=o[CONF_LOG_LOGGERS]): _select(
                                [], "log_loggers", multiple=True, custom=True
                            ),
                            vol.Required(CONF_LOG_DEDUPE, default=o[CONF_LOG_DEDUPE]): _num(
                                0, 604800, unit="s"
                            ),
                            vol.Required(CONF_LOG_ACTION, default=o[CONF_LOG_ACTION]): _action(),
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required("repairs"): section(
                    vol.Schema(
                        {
                            vol.Required(CONF_WATCH_REPAIRS, default=o[CONF_WATCH_REPAIRS]): bool,
                            vol.Required(
                                CONF_REPAIRS_ACTION, default=o[CONF_REPAIRS_ACTION]
                            ): _action(),
                        }
                    ),
                    {"collapsed": True},
                ),
                vol.Required("unavailable"): section(
                    vol.Schema(
                        {
                            vol.Optional(
                                CONF_WATCH_UNAVAILABLE, default=o[CONF_WATCH_UNAVAILABLE]
                            ): selector.EntitySelector(
                                selector.EntitySelectorConfig(multiple=True)
                            ),
                            vol.Required(
                                CONF_UNAVAILABLE_MINUTES,
                                default=o[CONF_UNAVAILABLE_MINUTES],
                            ): _num(1, 1440, unit="min"),
                            vol.Required(
                                CONF_UNAVAILABLE_ACTION,
                                default=o[CONF_UNAVAILABLE_ACTION],
                            ): _action(),
                        }
                    ),
                    {"collapsed": True},
                ),
                vol.Required("automations"): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_WATCH_AUTOMATIONS, default=o[CONF_WATCH_AUTOMATIONS]
                            ): bool,
                            vol.Required(
                                CONF_AUTOMATIONS_ACTION,
                                default=o[CONF_AUTOMATIONS_ACTION],
                            ): _action(),
                        }
                    ),
                    {"collapsed": True},
                ),
                vol.Required("setup"): section(
                    vol.Schema(
                        {
                            vol.Required(CONF_WATCH_SETUP, default=o[CONF_WATCH_SETUP]): bool,
                            vol.Required(
                                CONF_SETUP_ACTION, default=o[CONF_SETUP_ACTION]
                            ): _action(),
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )
        return self.async_show_form(step_id="watchers", data_schema=schema)

    async def async_step_templates(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            for key in (CONF_TEMPLATE_STATE, CONF_TEMPLATE_EVENT, CONF_TEMPLATE_ISSUE):
                self._opts[key] = (user_input.get(key) or "").strip()
            return await self.async_step_init()
        schema = vol.Schema(
            {
                vol.Optional(key): selector.TemplateSelector()
                for key in (CONF_TEMPLATE_STATE, CONF_TEMPLATE_EVENT, CONF_TEMPLATE_ISSUE)
            }
        )
        return self.async_show_form(
            step_id="templates",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    k: self._opts[k]
                    for k in (CONF_TEMPLATE_STATE, CONF_TEMPLATE_EVENT, CONF_TEMPLATE_ISSUE)
                    if self._opts[k]
                },
            ),
        )
