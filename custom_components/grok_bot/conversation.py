"""Conversation agent: forwards Assist text to Grok Bot (opt-in, async replies)."""

from __future__ import annotations

from typing import Literal

from homeassistant.components import conversation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GrokBotConfigEntry
from .const import (
    CONF_ENABLE_CONVERSATION,
    STATUS_DROPPED_BUDGET,
    STATUS_DROPPED_PAUSED,
    STATUS_SENT,
)
from .entity import GrokBotEntity

PARALLEL_UPDATES = 1

_TEXT = {
    "en": {
        STATUS_SENT: "Sent to Grok Bot. I'll answer shortly.",
        STATUS_DROPPED_BUDGET: "Not sent: the Grok Bot send budget is used up.",
        STATUS_DROPPED_PAUSED: "Not sent: sending to Grok Bot is paused.",
        "error": "Could not reach Grok Bot.",
    },
    "nl": {
        STATUS_SENT: "Doorgestuurd naar Grok Bot. Ik antwoord zo.",
        STATUS_DROPPED_BUDGET: "Niet verstuurd: het Grok Bot-budget is op.",
        STATUS_DROPPED_PAUSED: "Niet verstuurd: versturen naar Grok Bot is gepauzeerd.",
        "error": "Grok Bot is niet bereikbaar.",
    },
}


def response_text(language: str | None, status: str) -> str:
    texts = _TEXT.get((language or "en").split("-")[0].lower(), _TEXT["en"])
    return texts.get(status, texts["error"])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrokBotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data.hub
    if hub.options[CONF_ENABLE_CONVERSATION]:
        async_add_entities([GrokBotConversation(hub, "conversation")])


class GrokBotConversation(GrokBotEntity, conversation.ConversationEntity):
    """Assist agent that hands the request to Grok Bot."""

    _attr_name = None
    _attr_supports_streaming = False

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return "*"

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        result = await self.hub.async_send(
            "conversation",
            user_input.text,
            source="assist",
            conversation_id=chat_log.conversation_id,
            data={
                "language": user_input.language,
                "device_id": user_input.device_id,
                "satellite_id": getattr(user_input, "satellite_id", None),
            },
        )
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(
                agent_id=self.entity_id,
                content=response_text(user_input.language, result["status"]),
            )
        )
        return conversation.async_get_result_from_chat_log(user_input, chat_log)
