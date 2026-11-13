"""Transport to the Grok Bot routine webhook.

There is no public Grok Bot API. The only transport is an HTTPS POST of a JSON
payload to the routine's webhook URL, with the Authorization header value the
user copied from the Grok Bot app. The header value is a secret and is never
logged.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
from typing import Any
from urllib.parse import urlparse

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEFAULT_TIMEOUT, INTEGRATION_VERSION

_LOGGER = logging.getLogger(__name__)


class GrokBotError(Exception):
    """Base error."""


class GrokBotConnectionError(GrokBotError):
    """The webhook could not be reached or returned an error."""


class GrokBotAuthError(GrokBotError):
    """The webhook rejected the Authorization header."""


@dataclass(slots=True)
class DeliveryResult:
    """Outcome of one POST."""

    ok: bool
    http_status: int | None = None
    error: str | None = None
    auth_failed: bool = False


def normalize_auth_header(value: str) -> str:
    """Accept 'Bearer x' as well as a pasted 'Authorization: Bearer x' line."""
    value = (value or "").strip()
    if value.lower().startswith("authorization:"):
        value = value.split(":", 1)[1].strip()
    return value


def is_valid_webhook_url(url: str) -> bool:
    """Only absolute https URLs are allowed (the header is a secret)."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.netloc)


def redact_url(url: str) -> str:
    """Scheme + host only, for logs."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/…"


class GrokBotClient:
    """Posts payloads to the Grok Bot routine webhook."""

    def __init__(
        self,
        hass: HomeAssistant,
        webhook_url: str,
        auth_header: str,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._hass = hass
        self._url = webhook_url.strip()
        self._auth = normalize_auth_header(auth_header)
        self._timeout = timeout

    @property
    def host(self) -> str:
        """Host part of the webhook URL (safe to show)."""
        return urlparse(self._url).netloc

    async def async_post(self, payload: dict[str, Any]) -> DeliveryResult:
        """POST one payload. Never retries: every POST costs Grok Bot usage."""
        session = async_get_clientsession(self._hass)
        body = json.dumps(payload, default=str, ensure_ascii=False)
        headers = {
            "Authorization": self._auth,
            "Content-Type": "application/json",
            "User-Agent": f"HomeAssistant-GrokBot/{INTEGRATION_VERSION}",
        }
        try:
            async with asyncio.timeout(self._timeout):
                resp = await session.post(self._url, data=body, headers=headers)
                status = resp.status
                resp.release()
        except TimeoutError:
            return DeliveryResult(False, error="timeout")
        except aiohttp.ClientError as err:
            _LOGGER.debug("Grok Bot webhook %s unreachable: %s", redact_url(self._url), err)
            return DeliveryResult(False, error=type(err).__name__)
        if status in (401, 403):
            return DeliveryResult(False, status, "unauthorized", auth_failed=True)
        if status >= 400:
            return DeliveryResult(False, status, f"http_{status}")
        return DeliveryResult(True, status)

    async def async_validate(self, payload: dict[str, Any]) -> None:
        """Send a ping, raising a typed error on failure (config flow)."""
        result = await self.async_post(payload)
        if result.auth_failed:
            raise GrokBotAuthError
        if not result.ok:
            raise GrokBotConnectionError(result.error)
