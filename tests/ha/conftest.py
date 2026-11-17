"""Fixtures testów warstwy HA (uruchamiane tylko, gdy zainstalowano plugin HA)."""

import pytest

METER = "sensor.pge_total_energy_consumption"

try:  # plugin jest opcjonalny — bez niego testy z tests/ha są pomijane
    import pytest_homeassistant_custom_component  # noqa: F401
except ImportError:  # pragma: no cover
    collect_ignore_glob = ["test_*.py"]
else:
    from homeassistant.core import HomeAssistant
    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.polish_energy_bill.const import DOMAIN

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Pozwala HA ładować custom_components z repozytorium."""
        yield

    @pytest.fixture
    async def entry(hass: HomeAssistant) -> MockConfigEntry:
        """G11, tryb 'z sensora', załadowany Lovelace."""
        assert await async_setup_component(hass, "lovelace", {})
        hass.states.async_set(METER, "6200.0", {"unit_of_measurement": "kWh"})
        config_entry = MockConfigEntry(
            domain=DOMAIN,
            title="Liczniki Rachunek za prąd",
            data={
                "name": "Liczniki Rachunek za prąd",
                "profile": "pge_g11",
                "mode": "sensor",
                "zone_sensors": {"all": METER},
            },
        )
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        return config_entry
