"""Testy instalacji dashboardu na prawdziwym rdzeniu Home Assistant."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import yaml

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.components.lovelace.dashboard import DashboardsCollection  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from homeassistant.setup import async_setup_component  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.polish_energy_bill import dashboard_install as di  # noqa: E402
from custom_components.polish_energy_bill.const import DOMAIN  # noqa: E402
from custom_components.polish_energy_bill.core.dashboard import (  # noqa: E402
    build_dashboard,
    collect_entity_ids,
    load_template,
    make_resolver,
)

from .conftest import METER  # noqa: E402
APEX_URL = "/hacsfiles/apexcharts-card/apexcharts-card.js"


async def _install(hass: HomeAssistant, **data):
    return await hass.services.async_call(
        DOMAIN, "install_dashboard", data, blocking=True, return_response=True
    )


async def test_every_template_entity_resolves_on_real_registry(hass, entry):
    """Nazwy encji w kodzie == slugi w szablonie: zero brakujących encji dla G11 + sensor."""
    resolve = make_resolver(di._registry_entities(hass, entry), di._external_meter(entry))
    build = build_dashboard(load_template(), resolve)
    assert build.missing == ()
    assert build.removed == ()
    registry = er.async_get(hass)
    for real_id in build.mapping.values():
        if real_id != METER:
            assert registry.async_get(real_id) is not None, real_id


async def test_collection_is_discoverable_from_ws_wrappers(hass, entry):
    """Pilnuje wewnętrznego założenia: kolekcję da się odzyskać przez __wrapped__."""
    collection = di._find_dashboards_collection(hass)
    assert isinstance(collection, DashboardsCollection)


async def test_install_creates_editable_dashboard(hass, entry):
    result = await _install(hass)
    assert result["action"] == "created"
    assert result["url_path"] == "rachunek-za-prad"
    assert result["missing_entities"] == []

    dashboard = hass.data["lovelace"].dashboards["rachunek-za-prad"]
    assert dashboard.mode == "storage"
    config = await dashboard.async_load(False)

    registry = er.async_get(hass)
    for entity_id in collect_entity_ids(config):
        assert entity_id == METER or registry.async_get(entity_id) is not None, entity_id

    # wpis jest też na liście dashboardów (Ustawienia → Dashboardy), czyli przetrwa restart
    collection = di._find_dashboards_collection(hass)
    assert "rachunek-za-prad" in {item["url_path"] for item in collection.async_items()}


async def test_installed_config_is_json_serializable(hass, entry):
    await _install(hass)
    config = await hass.data["lovelace"].dashboards["rachunek-za-prad"].async_load(False)
    json.dumps(config)  # Lovelace wysyła to do frontendu jako JSON


async def test_second_install_requires_overwrite(hass, entry):
    await _install(hass)
    with pytest.raises(di.DashboardInstallError, match="już istnieje"):
        await _install(hass)

    dashboard = hass.data["lovelace"].dashboards["rachunek-za-prad"]
    await dashboard.async_save({"title": "ręczna zmiana", "views": []})
    result = await _install(hass, overwrite=True)
    assert result["action"] == "updated"
    config = await dashboard.async_load(False)
    assert config["title"] != "ręczna zmiana"


async def test_custom_url_path_and_title(hass, entry):
    result = await _install(hass, url_path="moj-prad", title="Mój prąd")
    assert result["url_path"] == "moj-prad"
    collection = di._find_dashboards_collection(hass)
    titles = {item["url_path"]: item["title"] for item in collection.async_items()}
    assert titles["moj-prad"] == "Mój prąd"


@pytest.mark.parametrize("bad", ["rachunek", "Rachunek Za Prad", "../x-y", ""])
async def test_invalid_url_path_rejected(hass, entry, bad):
    with pytest.raises(di.DashboardInstallError, match="url_path"):
        await _install(hass, url_path=bad)


async def test_apexcharts_detection(hass, entry):
    first = await _install(hass, url_path="pierwszy-test")
    assert first["apexcharts_card_found"] is False

    await hass.data["lovelace"].resources.async_create_item({"res_type": "module", "url": APEX_URL})
    second = await _install(hass, url_path="drugi-test")
    assert second["apexcharts_card_found"] is True


async def test_missing_meter_prunes_charts_and_reports(hass):
    """Wpis bez sensora zużycia (tryb ręczny) → wykresy z licznika znikają, raport mówi czemu."""
    assert await async_setup_component(hass, "lovelace", {})
    manual = MockConfigEntry(
        domain=DOMAIN,
        title="Ręczny",
        data={"name": "Ręczny", "profile": "pge_g11", "mode": "manual", "zone_sensors": {}},
    )
    manual.add_to_hass(hass)
    assert await hass.config_entries.async_setup(manual.entry_id)
    await hass.async_block_till_done()

    result = await _install(hass)
    assert METER in result["missing_entities"]
    assert result["removed_items"] > 0
    config = await hass.data["lovelace"].dashboards["rachunek-za-prad"].async_load(False)
    assert METER not in collect_entity_ids(config)


async def test_fallback_writes_yaml_file_when_collection_unavailable(hass, entry):
    with patch.object(di, "_find_dashboards_collection", return_value=None):
        result = await _install(hass)
    assert result["action"] == "file"
    assert "rachunek-za-prad" not in hass.data["lovelace"].dashboards
    with open(result["fallback_file"], encoding="utf-8") as handle:
        written = yaml.safe_load(handle)
    assert written["views"], "plik z konfiguracją nie może być pusty"


async def test_button_installs_dashboard(hass, entry):
    registry = er.async_get(hass)
    button_id = next(
        item.entity_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.domain == "button" and item.original_name == "Zainstaluj dashboard"
    )
    await hass.services.async_call("button", "press", {"entity_id": button_id}, blocking=True)
    assert "rachunek-za-prad" in hass.data["lovelace"].dashboards


async def test_notification_is_created(hass, entry):
    with patch.object(di.persistent_notification, "async_create") as notify:
        await _install(hass)
    notify.assert_called_once()
    message = notify.call_args.args[1]
    assert "/rachunek-za-prad" in message
    assert notify.call_args.kwargs["notification_id"] == f"{DOMAIN}_dashboard_{entry.entry_id}"


async def test_unknown_config_entry_id_rejected(hass, entry):
    with pytest.raises(di.DashboardInstallError, match="Nie znaleziono"):
        await _install(hass, config_entry_id="nie-ma-takiego")


async def test_service_description_is_valid(hass, entry):
    """services.yaml wczytuje się i opisuje wszystkie pola usługi."""
    from homeassistant.helpers.service import async_get_all_descriptions

    descriptions = await async_get_all_descriptions(hass)
    fields = descriptions[DOMAIN]["install_dashboard"]["fields"]
    assert set(fields) == {"config_entry_id", "url_path", "title", "overwrite"}


async def test_several_entries_require_explicit_id(hass, entry):
    second = MockConfigEntry(
        domain=DOMAIN,
        title="Drugi",
        data={"name": "Drugi", "profile": "pge_g11", "mode": "manual", "zone_sensors": {}},
    )
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(di.DashboardInstallError, match="config_entry_id"):
        await _install(hass)
    result = await _install(hass, config_entry_id=entry.entry_id, url_path="pierwszy-dash")
    assert result["action"] == "created"
