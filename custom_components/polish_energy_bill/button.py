"""Przyciski: punkt zero licznika oraz instalacja dashboardu."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODE_SENSOR
from .coordinator import BillCoordinator
from .core import Zone
from .dashboard_install import async_install_dashboard

ZONE_LABEL = {
    Zone.ALL: "całodobowa",
    Zone.DAY: "dzień",
    Zone.NIGHT: "noc",
    Zone.PEAK: "szczyt",
    Zone.OFF_PEAK: "poza szczytem",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: BillCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = [InstallDashboardButton(coordinator, entry)]
    if coordinator.mode == MODE_SENSOR:
        # „Ustaw jako zero” ma sens tylko gdy zużycie pochodzi z sensora
        entities += [
            SetZeroButton(coordinator, entry, zone)
            for zone in coordinator.base_profile.zones
        ]
    async_add_entities(entities)


class SetZeroButton(ButtonEntity):
    """Zapisuje aktualny odczyt licznika jako nowy punkt zero (start okresu)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: BillCoordinator, entry: ConfigEntry, zone: Zone
    ) -> None:
        self.coordinator = coordinator
        self._entry = entry
        self._zone = zone
        self._attr_name = f"Ustaw jako zero ({ZONE_LABEL.get(zone, zone.value)})"
        self._attr_unique_id = f"{entry.entry_id}_setzero_{zone.value}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": self.coordinator.base_profile.seller,
            "model": self.coordinator.base_profile.name,
        }

    async def async_press(self) -> None:
        await self.coordinator.capture_zero(self._zone)


class InstallDashboardButton(ButtonEntity):
    """Tworzy dashboard „Rachunek za prąd” (jednorazowa, edytowalna kopia).

    Nie nadpisuje istniejącego dashboardu — do podmiany służy usługa
    `polish_energy_bill.install_dashboard` z `overwrite: true`.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:view-dashboard-outline"
    _attr_name = "Zainstaluj dashboard"

    def __init__(self, coordinator: BillCoordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_install_dashboard"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": self.coordinator.base_profile.seller,
            "model": self.coordinator.base_profile.name,
        }

    async def async_press(self) -> None:
        await async_install_dashboard(self.hass, self._entry)
