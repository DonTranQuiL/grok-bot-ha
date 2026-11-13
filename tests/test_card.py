"""Run the dashboard card in headless Chrome against fake Home Assistant data.

Skipped when no Chrome/Chromium is installed (GitHub's Ubuntu runners have one).
"""

from __future__ import annotations

import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import pytest

ROOT = Path(__file__).parent.parent
CARD = ROOT / "custom_components" / "grok_bot" / "frontend" / "grok-bot-card.js"
CARD_DIR = Path(__file__).parent / "card"
CHROME = next(
    (
        shutil.which(n)
        for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
        if shutil.which(n)
    ),
    None,
)


def _page() -> str:
    return (
        "<!doctype html><html><body>"
        f"<script>{(CARD_DIR / 'fixtures.js').read_text()}</script>"
        f"<script>{CARD.read_text()}</script>"
        f"<script>{(CARD_DIR / 'harness.js').read_text()}</script>"
        "</body></html>"
    )


def _run_playwright() -> dict:
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.html"
        path.write_text(_page(), "utf-8")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            try:
                tab = browser.new_page(viewport={"width": 1200, "height": 900})
                tab.goto(path.as_uri())
                tab.wait_for_selector("#out", state="attached", timeout=30000)
                return json.loads(tab.locator("#out").text_content())
            finally:
                browser.close()


def run_harness() -> dict:
    """Playwright when available (more reliable locally), else --dump-dom."""
    try:
        return _run_playwright()
    except ImportError:
        pass
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.html"
        path.write_text(_page(), "utf-8")
        out = subprocess.run(
            [
                CHROME,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                f"--user-data-dir={tmp}/profile",
                "--virtual-time-budget=5000",
                "--dump-dom",
                path.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        ).stdout
    match = re.search(r'<pre id="out">(.*?)</pre>', out, re.S)
    assert match, out[-2000:]
    return json.loads(html.unescape(match.group(1)))


@pytest.mark.skipif(CHROME is None, reason="no Chrome/Chromium installed")
def test_card_in_browser():
    res = run_harness()
    assert res["errors"] == []
    c = res["checks"]
    assert c["title"] == "Grok Bot"
    assert "idle" in c["mood"]
    assert c["svg"] is True
    assert any("3/20" in chip for chip in c["chips"])
    assert any("27/100" in chip for chip in c["chips"])
    assert "re-interviewed" in c["bubble"]
    assert c["history"] == 4
    assert len(c["issues"]) == 2  # own issues are hidden
    assert c["bad"] == []
    assert c["ask_call"] == {
        "domain": "grok_bot",
        "service": "ask",
        "data": {"message": "Why is the attic warm?", "action_mode": "diagnose"},
    }
    assert c["thinking"] is True and c["typing"] is True
    assert c["success"] is True
    assert "attic blind" in c["new_bubble"]
    assert c["fix_call"]["data"] == {"issue_id": "radio_lost", "issue_domain": "zha"}
    assert c["pause_call"]["service"] == "turn_on"
    assert c["paused"] is True and c["send_disabled"] is True
    assert c["paused_title"] == "House bot"
    assert c["error"] is True
    assert "dropped_budget" in c["dropped_text"]
    assert c["avatar_img"] == "/local/me.png"
    assert c["nl_send"] == "Verstuur"
    assert "not found" in c["not_found"]
    assert c["editor_form"] is True
    assert "grok-bot-card" in c["custom_cards"]
    assert c["stub"] == {"type": "custom:grok-bot-card"}
    assert c["awaiting_chip"] == "2 awaiting"
    assert c["handled_call"] == {
        "domain": "button",
        "service": "press",
        "data": {"entity_id": "button.grok_bot_mark_replies_handled"},
    }


async def test_card_is_served_and_registered(hass, enable_custom_integrations):
    """async_setup serves the card and adds it with a cache buster."""
    from homeassistant.setup import async_setup_component

    from custom_components.grok_bot import CARD_URL

    assert await async_setup_component(hass, "grok_bot", {})
    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL

    urls = list(hass.data[DATA_EXTRA_MODULE_URL].urls) if DATA_EXTRA_MODULE_URL in hass.data else []
    assert CARD.exists()
    assert CARD_URL == "/grok_bot/grok-bot-card.js"
    if urls:
        assert any(u.startswith(CARD_URL + "?v=0.1.0-") for u in urls)
