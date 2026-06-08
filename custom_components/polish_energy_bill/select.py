"""Select: tryb ustalania zużycia w okresie."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN,
    MODE_SENSOR,
    PERIOD_MODE_HISTORY,
    PERIOD_MODE_READINGS,
    PERIOD_MODE_ZERO,
    PERIOD_MODES,
)
from .coordinator import BillCoordinator

# Czytelne etykiety trybów (opcje selecta to surowe klucze; tłumaczenie w UI).
LABELS = {
    PERIOD_MODE_ZERO: "Punkt zero (bieżący − zero)",
    PERIOD_MODE_HISTORY: "Auto z historii (zakres dat)",
    PERIOD_MODE_READINGS: "Ręczne odczyty (koniec − początek)",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: BillCoordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.mode != MODE_SENSOR:
        return  # tryby okresu mają sens tylko przy zużyciu z sensora
    async_add_entities([PeriodModeSelect(coordinator, entry)])


class PeriodModeSelect(RestoreEntity, SelectEntity):
    """Wybór sposobu liczenia zużycia w okresie."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = [LABELS[m] for m in PERIOD_MODES]

    def __init__(self, coordinator: BillCoordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._entry = entry
        self._attr_name = "Tryb zużycia okresu"
        self._attr_unique_id = f"{entry.entry_id}_period_mode"
        self._attr_current_option = LABELS[PERIOD_MODE_ZERO]
        self._rev = {v: k for k, v in LABELS.items()}

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
        if last is not None and last.state in self._rev:
            self._attr_current_option = last.state
        self.coordinator.set_period_mode(self._rev[self._attr_current_option])
        await self.coordinator.async_request_refresh()

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.coordinator.set_period_mode(self._rev[option])
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
