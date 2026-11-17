"""Encje weryfikacji faktury i faktury teoretycznej na prawdziwym rdzeniu HA."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.polish_energy_bill.const import DOMAIN  # noqa: E402
from custom_components.polish_energy_bill.core import load_builtin_profiles  # noqa: E402
from custom_components.polish_energy_bill.core.invoice import theoretical_bill  # noqa: E402

from .conftest import METER  # noqa: E402


def _eid(hass: HomeAssistant, entry, domain: str, name: str) -> str:
    registry = er.async_get(hass)
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        if item.domain == domain and item.original_name == name:
            return item.entity_id
    raise AssertionError(f"brak encji {domain} „{name}”")


async def _set(hass, entry, domain, name, **data):
    if domain == "date" and "value" in data:  # date.set_value przyjmuje pole `date`
        data = {"date": data["value"]}
    await hass.services.async_call(
        domain,
        "set_value",
        {"entity_id": _eid(hass, entry, domain, name), **data},
        blocking=True,
    )
    await hass.async_block_till_done()


async def _enter_invoice(hass, entry, start, end, kwh, declared):
    await _set(hass, entry, "date", "Faktura: okres od", value=start)
    await _set(hass, entry, "date", "Faktura: okres do", value=end)
    await _set(hass, entry, "number", "Faktura: zużycie", value=kwh)
    await _set(hass, entry, "number", "Faktura: kwota do zapłaty", value=declared)


def _state(hass, entry, name):
    return hass.states.get(_eid(hass, entry, "sensor", name))


async def test_real_invoice_matches_to_the_grosz(hass, entry):
    # Faktura 470000065575 (21.07–20.09.2026, 793 kWh) przy domyślnym profilu G11
    # z opłatą mocową seg.4 24,05 — to samo, co w teście rdzenia.
    await _enter_invoice(hass, entry, "2026-07-21", "2026-09-20", 793, 960.86)
    assert _state(hass, entry, "Faktura: wyliczona kwota (brutto)").state == "960.86"
    assert _state(hass, entry, "Faktura: różnica kwoty").state == "0.0"
    assert _state(hass, entry, "Faktura: status weryfikacji").state == "zgodna"


async def test_difference_and_status_when_amounts_disagree(hass, entry):
    await _enter_invoice(hass, entry, "2026-07-21", "2026-09-20", 793, 950)
    assert _state(hass, entry, "Faktura: różnica kwoty").state == "10.86"
    assert _state(hass, entry, "Faktura: status weryfikacji").state == "odchyłka"


async def test_status_prompts_until_period_entered(hass, entry):
    assert _state(hass, entry, "Faktura: status weryfikacji").state == "wpisz okres faktury"
    assert _state(hass, entry, "Faktura: wyliczona kwota (brutto)").state == "unknown"


async def test_status_without_declared_amount(hass, entry):
    await _enter_invoice(hass, entry, "2026-07-21", "2026-09-20", 793, 0)
    assert _state(hass, entry, "Faktura: status weryfikacji").state == "brak kwoty z faktury"
    assert _state(hass, entry, "Faktura: wyliczona kwota (brutto)").state == "960.86"
    assert _state(hass, entry, "Faktura: różnica kwoty").state == "unknown"


async def test_reversed_dates_show_error_not_crash(hass, entry):
    await _enter_invoice(hass, entry, "2026-09-20", "2026-07-21", 793, 960.86)
    status = _state(hass, entry, "Faktura: status weryfikacji").state
    assert "późniejsza" in status
    assert _state(hass, entry, "Faktura: wyliczona kwota (brutto)").state == "unknown"


async def test_theoretical_invoice_now_and_forecast(hass, entry, freezer):
    await hass.config.async_set_time_zone("Europe/Warsaw")
    await _set(hass, entry, "datetime", "Punkt zero (data i godzina odczytu)", datetime="2026-09-20 00:00:00")
    await _set(hass, entry, "number", "Odczyt zero (całodobowa)", value=6136.3)
    freezer.move_to("2026-10-21 00:00:00+02:00")  # 31 dni po odczycie
    hass.states.async_set(METER, "6536.3")        # +400 kWh od odczytu
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    profile = load_builtin_profiles()["pge_g11"]
    now = _state(hass, entry, "Faktura teoretyczna: stan na dziś (brutto)")
    assert now.attributes["consumption_kwh"] == 400.0
    assert now.attributes["estimate"] is False
    assert now.attributes["period_end"] == "2026-11-20"  # domyślnie +2 miesiące
    expected_now = theoretical_bill(profile, D("400"), date(2026, 9, 20), date(2026, 11, 20))
    assert D(now.state) == expected_now.gross

    forecast = _state(hass, entry, "Faktura teoretyczna: prognoza na koniec okresu (brutto)")
    assert forecast.attributes["estimate"] is True
    assert forecast.attributes["consumption_kwh"] == 800.0  # 400 kWh w 31 z ~62 dni
    assert forecast.attributes["days_total"] == 62
    expected_fc = theoretical_bill(profile, D("800"), date(2026, 9, 20), date(2026, 11, 20))
    assert D(forecast.state) == expected_fc.gross


async def test_editing_period_end_changes_theoretical_invoice(hass, entry, freezer):
    await hass.config.async_set_time_zone("Europe/Warsaw")
    await _set(hass, entry, "datetime", "Punkt zero (data i godzina odczytu)", datetime="2026-09-20 00:00:00")
    await _set(hass, entry, "number", "Odczyt zero (całodobowa)", value=6136.3)
    freezer.move_to("2026-10-21 00:00:00+02:00")
    hass.states.async_set(METER, "6536.3")
    await _set(hass, entry, "date", "Okres do", value="2026-11-21")  # edytowalny koniec
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    forecast = _state(hass, entry, "Faktura teoretyczna: prognoza na koniec okresu (brutto)")
    assert forecast.attributes["period_end"] == "2026-11-21"
    assert forecast.attributes["consumption_kwh"] == 813.0  # 400 * 63,04 / 31 dni


async def test_forecast_unknown_before_first_day(hass, entry, freezer):
    await hass.config.async_set_time_zone("Europe/Warsaw")
    await _set(hass, entry, "datetime", "Punkt zero (data i godzina odczytu)", datetime="2026-09-20 00:00:00")
    freezer.move_to("2026-09-20 06:00:00+02:00")
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, entry, "Faktura teoretyczna: prognoza na koniec okresu (brutto)").state == "unknown"
    assert _state(hass, entry, "Faktura teoretyczna: stan na dziś (brutto)").state != "unknown"


async def test_multi_zone_profile_has_no_invoice_entities(hass):
    manual = MockConfigEntry(
        domain=DOMAIN,
        title="G12",
        data={"name": "G12", "profile": "pge_g12", "mode": "manual", "zone_sensors": {}},
    )
    manual.add_to_hass(hass)
    assert await hass.config_entries.async_setup(manual.entry_id)
    await hass.async_block_till_done()
    names = {
        item.original_name
        for item in er.async_entries_for_config_entry(er.async_get(hass), manual.entry_id)
    }
    assert not any(name and name.startswith("Faktura") for name in names)


async def test_manual_mode_single_zone_has_check_but_no_theoretical(hass):
    manual = MockConfigEntry(
        domain=DOMAIN,
        title="G11 ręczny",
        data={"name": "G11 ręczny", "profile": "pge_g11", "mode": "manual", "zone_sensors": {}},
    )
    manual.add_to_hass(hass)
    assert await hass.config_entries.async_setup(manual.entry_id)
    await hass.async_block_till_done()
    names = {
        item.original_name
        for item in er.async_entries_for_config_entry(er.async_get(hass), manual.entry_id)
    }
    assert "Faktura: okres od" in names
    assert "Faktura: status weryfikacji" in names
    assert not any(name and name.startswith("Faktura teoretyczna") for name in names)
