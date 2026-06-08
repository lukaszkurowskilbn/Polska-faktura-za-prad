"""Date: początek i koniec okresu rozliczeniowego."""

from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, MODE_SENSOR
from .coordinator import BillCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: BillCoordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.mode != MODE_SENSOR:
        return
    async_add_entities(
        [
            PeriodDate(coordinator, entry, "start", "Okres od"),
            PeriodDate(coordinator, entry, "end", "Okres do"),
        ]
    )


class PeriodDate(RestoreEntity, DateEntity):
    """Granica okresu rozliczeniowego (data od / do)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: BillCoordinator, entry: ConfigEntry, which: str, label: str
    ) -> None:
        self.coordinator = coordinator
        self._entry = entry
        self._which = which  # "start" | "end"
        self._attr_name = label
        self._attr_unique_id = f"{entry.entry_id}_period_{which}"
        self._attr_native_value: date | None = None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": self.coordinator.base_profile.seller,
            "model": self.coordinator.base_profile.name,
        }

    def _push(self) -> None:
        if self._which == "start":
            self.coordinator.set_period_start(self._attr_native_value)
        else:
            self.coordinator.set_period_end(self._attr_native_value)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "unknown", "unavailable", ""):
            try:
                self._attr_native_value = date.fromisoformat(last.state)
            except ValueError:
                self._attr_native_value = None
        self._push()
        await self.coordinator.async_request_refresh()

    async def async_set_value(self, value: date) -> None:
        self._attr_native_value = value
        self._push()
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
