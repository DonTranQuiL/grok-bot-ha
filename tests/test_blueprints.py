"""The bundled blueprints are valid automation blueprints."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.util.yaml import load_yaml
import pytest

BLUEPRINTS = sorted(
    (Path(__file__).parent.parent / "blueprints" / "automation" / "grok_bot").glob("*.yaml")
)


def test_blueprints_exist():
    assert {p.name for p in BLUEPRINTS} >= {
        "ask_on_threshold.yaml",
        "nightly_health_report.yaml",
        "reply_to_phone.yaml",
    }


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_blueprint_valid(path):
    bp = Blueprint(
        load_yaml(str(path)),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    assert bp.domain == "automation"
    assert bp.metadata["source_url"].endswith(path.name)


async def test_threshold_blueprint_runs(hass, webhook_mock, tmp_path, freezer):
    """The threshold blueprint calls grok_bot.ask once the sensor stays high."""
    from datetime import timedelta
    import shutil

    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    from .conftest import posted, setup_entry

    target = tmp_path / "blueprints" / "automation" / "grok_bot"
    target.mkdir(parents=True)
    for path in BLUEPRINTS:
        shutil.copy(path, target / path.name)
    hass.config.config_dir = str(tmp_path)
    hass.states.async_set("sensor.attic", "20")
    await setup_entry(hass)
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "id": "attic_hot",
                "alias": "attic hot",
                "use_blueprint": {
                    "path": "grok_bot/ask_on_threshold.yaml",
                    "input": {"sensor": "sensor.attic", "above": 30, "for_minutes": 1},
                },
            }
        },
    )
    await hass.async_block_till_done()
    hass.states.async_set("sensor.attic", "35")
    await hass.async_block_till_done()
    assert posted(webhook_mock) == []
    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    payloads = posted(webhook_mock)
    assert len(payloads) == 1
    assert payloads[0]["type"] == "ask"
    assert payloads[0]["context"][0]["entity_id"] == "sensor.attic"
    assert payloads[0]["action_mode"] == "diagnose"
    assert payloads[0]["reply_to"] is None
