"""DateTime: punkt zero jako data i godzina odczytu licznika.

Tryb 'od odczytu do teraz' — wpisujesz moment odczytu z faktury, a integracja
liczy zużycie i koszt od tej chwili do teraz (z historii licznika).
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MODE_SENSOR
from .coordinator import BillCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: BillCoordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.mode != MODE_SENSOR:
        return
    async_add_entities([ZeroDateTime(coordinator, entry)])


class ZeroDateTime(RestoreEntity, DateTimeEntity):
    """Moment odczytu licznika = punkt zero w czasie."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: BillCoordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._entry = entry
        self._attr_name = "Punkt zero (data i godzina odczytu)"
        self._attr_unique_id = f"{entry.entry_id}_zero_datetime"
        self._attr_native_value: datetime | None = None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": self.coordinator.base_profile.seller,
            "model": self.coordinator.base_profile.name,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "unknown", "unavailable", ""):
            parsed = dt_util.parse_datetime(last.state)
            if parsed is not None:
                self._attr_native_value = parsed
        self.coordinator.set_zero_datetime(self._attr_native_value)
        await self.coordinator.async_request_refresh()

    async def async_set_value(self, value: datetime) -> None:
        # HA podaje wartość w UTC (aware); przechowujemy jak jest.
        self._attr_native_value = value
        self.coordinator.set_zero_datetime(value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
