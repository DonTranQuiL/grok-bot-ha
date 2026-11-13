"""The ready-to-paste setup prompt that connects Grok Bot to this Home Assistant.

Only offered when HA-MCP (``ha_mcp_tools``) is installed: Grok Bot then reaches
this instance through an HA-MCP connector in the Grok Bot app. The prompt never
contains the Authorization header or any HA token.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_EN = """Hi Grok Bot, please connect my Home Assistant "{name}" to you.

1. Connect it: add Home Assistant as a connector using HA-MCP (homeassistant-ai/ha-mcp). MCP URL: {mcp_url}
   (copy the exact remote URL from HA-MCP > Configure in Home Assistant if this one is a placeholder).
   Show me the one-time connector sign-in card: I log in on my own Home Assistant page, so my password never reaches you; the access token can be revoked any time in Home Assistant under Profile > Security.
2. Create or update a webhook routine for the Grok Bot Home Assistant integration. Its webhook URL is: {webhook_url}
   Each POST carries a JSON payload with schema, type (ask, event, state, issue, log, health_report, ping, ...), message, conversation_id, action_mode, allow_fix, context and an access block.
3. Rules for that routine:
   - Respect action_mode: report = just summarise; diagnose = investigate read-only; fix = only when allow_fix is true, and only safe, reversible fixes (reload an integration, re-enable an entity, dismiss a fixed repair).
   - Never delete integrations, devices or entities. Never restart Home Assistant Core and never edit configuration files, unless the payload's access block has trusted: true:
     - allow_yaml_edit: true lets you edit configuration.yaml, automations.yaml, scripts.yaml, scenes.yaml or files under packages/ (never secrets.yaml, .storage or custom_components). Always call {domain}.prepare_change with the file path first and keep the returned backup_path; if anything goes wrong call {domain}.restore_backup with it.
     - allow_restart: true lets you restart, but only through {domain}.safe_restart (it checks the configuration first and returns the errors instead of restarting when it is invalid).
   - Always answer through the {domain}.reply action on this Home Assistant (HA-MCP connector "{name}") with the payload's conversation_id, so the integration's sensors update.
   - Stay quiet in our chat for routine successes; only message me when something failed or needs my decision.
4. Confirm it works: call {domain}.reply with message "Connected" (no conversation_id needed).
"""

_NL = """Hoi Grok Bot, koppel alsjeblieft mijn Home Assistant "{name}" aan jou.

1. Koppelen: voeg Home Assistant toe als connector via HA-MCP (homeassistant-ai/ha-mcp). MCP-URL: {mcp_url}
   (kopieer de exacte externe URL uit HA-MCP > Configureren in Home Assistant als dit een voorbeeld is).
   Laat me de eenmalige aanmeldkaart van de connector zien: ik log in op de pagina van mijn eigen Home Assistant, dus mijn wachtwoord komt nooit bij jou; het toegangstoken kan ik altijd intrekken in Home Assistant onder Profiel > Beveiliging.
2. Maak of werk een webhook-routine bij voor de Grok Bot Home Assistant-integratie. De webhook-URL is: {webhook_url}
   Elke POST bevat JSON met schema, type (ask, event, state, issue, log, health_report, ping, ...), message, conversation_id, action_mode, allow_fix, context en een access-blok.
3. Regels voor die routine:
   - Volg action_mode: report = alleen samenvatten; diagnose = alleen-lezen onderzoeken; fix = alleen als allow_fix true is, en alleen veilige, omkeerbare oplossingen (integratie herladen, entiteit weer inschakelen, opgeloste reparatie negeren).
   - Verwijder nooit integraties, apparaten of entiteiten. Herstart nooit Home Assistant Core en bewerk nooit configuratiebestanden, behalve als het access-blok trusted: true bevat:
     - allow_yaml_edit: true staat bewerken toe van configuration.yaml, automations.yaml, scripts.yaml, scenes.yaml of bestanden onder packages/ (nooit secrets.yaml, .storage of custom_components). Roep altijd eerst {domain}.prepare_change aan met het bestandspad en bewaar het teruggegeven backup_path; gaat er iets mis, roep dan {domain}.restore_backup aan met dat pad.
     - allow_restart: true staat herstarten toe, maar alleen via {domain}.safe_restart (die controleert eerst de configuratie en geeft de fouten terug in plaats van te herstarten als die ongeldig is).
   - Antwoord altijd via de actie {domain}.reply op deze Home Assistant (HA-MCP-connector "{name}") met de conversation_id uit het bericht, zodat de sensoren van de integratie bijwerken.
   - Blijf stil in onze chat bij routinematige successen; stuur me alleen een bericht als iets mislukt of mijn beslissing nodig is.
4. Bevestig dat het werkt: roep {domain}.reply aan met het bericht "Connected" (zonder conversation_id).
"""


def setup_prompt(
    hass: HomeAssistant,
    *,
    webhook_url: str,
    mcp_url: str | None,
    language: str | None = None,
) -> str:
    """The prompt in the instance language (Dutch or English)."""
    lang = (language or hass.config.language or "en").lower()
    template = _NL if lang.startswith("nl") else _EN
    return template.format(
        name=hass.config.location_name or "Home",
        mcp_url=mcp_url
        or "https://<your-external-or-nabu-casa-url>/api/webhook/<HA-MCP webhook id>",
        webhook_url=webhook_url,
        domain=DOMAIN,
    )
