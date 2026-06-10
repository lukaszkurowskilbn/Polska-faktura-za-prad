"""Encje number: edytowalne stawki pozycji + ręczne zużycie per strefa.

To jest mechanizm "podstawiania pozycji" — każda stawka taryfy jest osobną,
edytowalną encją number. Zmieniasz w UI, rachunek przelicza się natychmiast.
"""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEFAULT_ETS_EMISSION_FACTOR,
    DEFAULT_ETS_EUA_PRICE,
    DEFAULT_ETS_EUR_PLN,
    DEFAULT_ETS_PERCENT,
    DOMAIN,
    MODE_MANUAL,
    MODE_SENSOR,
)
from .coordinator import BillCoordinator
from .core import Zone

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
    profile = coordinator.base_profile

    entities: list = [
        RateNumber(coordinator, entry, pos.key, pos.name, float(pos.rate))
        for pos in profile.positions
    ]

    # ETS — edytowalne parametry (niezależne od trybu zużycia).
    entities += [
        EtsParamNumber(
            coordinator, entry, "ets_percent", "ETS: udział w cenie energii",
            DEFAULT_ETS_PERCENT, coordinator.set_ets_percent,
            min_value=0.0, max_value=100.0, step=0.1, unit="%",
        ),
        EtsParamNumber(
            coordinator, entry, "ets_emission_factor", "ETS: wskaźnik emisji CO₂",
            DEFAULT_ETS_EMISSION_FACTOR, coordinator.set_ets_emission_factor,
            min_value=0.0, max_value=2.0, step=0.0001, unit="t/MWh",
        ),
        EtsParamNumber(
            coordinator, entry, "ets_eua_price", "ETS: cena uprawnienia EUA",
            DEFAULT_ETS_EUA_PRICE, coordinator.set_ets_eua_price,
            min_value=0.0, max_value=10000.0, step=0.01, unit="EUR/t",
        ),
        EtsParamNumber(
            coordinator, entry, "ets_eur_pln", "ETS: kurs EUR/PLN",
            DEFAULT_ETS_EUR_PLN, coordinator.set_ets_eur_pln,
            min_value=0.0, max_value=100.0, step=0.0001, unit="PLN/EUR",
        ),
    ]

    if coordinator.mode == MODE_MANUAL:
        entities += [
            ConsumptionNumber(coordinator, entry, zone) for zone in profile.zones
        ]
    elif coordinator.mode == MODE_SENSOR:
        # Punkt zero (bazowy odczyt licznika) — można wpisać ręcznie albo
        # ustawić przyciskiem "Ustaw jako zero".
        entities += [
            BaselineNumber(coordinator, entry, zone) for zone in profile.zones
        ]
        # Ręczne odczyty licznika (tryb 'reczne_odczyty').
        for zone in profile.zones:
            entities.append(ReadingNumber(coordinator, entry, zone, "start", "Odczyt początkowy"))
            entities.append(ReadingNumber(coordinator, entry, zone, "end", "Odczyt końcowy"))

    async_add_entities(entities)


class _Base(RestoreNumber):
    """Wspólna baza encji number tej integracji."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: BillCoordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._entry = entry

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": self.coordinator.base_profile.seller,
            "model": self.coordinator.base_profile.name,
        }


class RateNumber(_Base):
    """Edytowalna stawka netto pojedynczej pozycji taryfy."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100000.0
    _attr_native_step = 0.00001
    _attr_native_unit_of_measurement = "zł"

    def __init__(
        self,
        coordinator: BillCoordinator,
        entry: ConfigEntry,
        key: str,
        label: str,
        default: float,
    ) -> None:
        super().__init__(coordinator, entry)
        self._key = key
        self._default = default
        self._attr_name = f"Stawka: {label}"
        self._attr_unique_id = f"{entry.entry_id}_rate_{key}"
        self._attr_native_value = default

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = last.native_value
        self.coordinator.set_rate_override(self._key, self._attr_native_value)
        await self.coordinator.async_request_refresh()

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.coordinator.set_rate_override(self._key, value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class ConsumptionNumber(_Base):
    """Ręcznie wpisywane zużycie [kWh] dla danej strefy (tryb manualny)."""

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.0
    _attr_native_max_value = 1000000.0
    _attr_native_step = 0.001
    _attr_native_unit_of_measurement = "kWh"

    def __init__(
        self, coordinator: BillCoordinator, entry: ConfigEntry, zone: Zone
    ) -> None:
        super().__init__(coordinator, entry)
        self._zone = zone
        self._attr_name = f"Zużycie ({ZONE_LABEL.get(zone, zone.value)})"
        self._attr_unique_id = f"{entry.entry_id}_consumption_{zone.value}"
        self._attr_native_value = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = last.native_value
        self.coordinator.set_manual_consumption(self._zone, self._attr_native_value)
        await self.coordinator.async_request_refresh()

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.coordinator.set_manual_consumption(self._zone, value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class BaselineNumber(_Base):
    """Bazowy odczyt licznika [kWh] = punkt zero, od którego liczymy zużycie."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100000000.0
    _attr_native_step = 0.001
    _attr_native_unit_of_measurement = "kWh"

    def __init__(
        self, coordinator: BillCoordinator, entry: ConfigEntry, zone: Zone
    ) -> None:
        super().__init__(coordinator, entry)
        self._zone = zone
        self._attr_name = f"Odczyt zero ({ZONE_LABEL.get(zone, zone.value)})"
        self._attr_unique_id = f"{entry.entry_id}_baseline_{zone.value}"
        self._attr_native_value = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.coordinator.register_baseline_entity(self._zone, self)
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = last.native_value
        self.coordinator.set_baseline(self._zone, self._attr_native_value)
        await self.coordinator.async_request_refresh()

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.coordinator.set_baseline(self._zone, value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class ReadingNumber(_Base):
    """Ręczny odczyt licznika [kWh] — początkowy lub końcowy okresu."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100000000.0
    _attr_native_step = 0.001
    _attr_native_unit_of_measurement = "kWh"

    def __init__(
        self,
        coordinator: BillCoordinator,
        entry: ConfigEntry,
        zone: Zone,
        which: str,
        label: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._zone = zone
        self._which = which  # "start" | "end"
        self._attr_name = f"{label} ({ZONE_LABEL.get(zone, zone.value)})"
        self._attr_unique_id = f"{entry.entry_id}_reading_{which}_{zone.value}"
        self._attr_native_value = 0.0

    def _push(self, value: float) -> None:
        if self._which == "start":
            self.coordinator.set_start_reading(self._zone, value)
        else:
            self.coordinator.set_end_reading(self._zone, value)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = last.native_value
        self._push(self._attr_native_value)
        await self.coordinator.async_request_refresh()

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self._push(value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class EtsParamNumber(_Base):
    """Edytowalny parametr ETS (udział %, wskaźnik emisji, cena EUA, kurs).

    Te wartości zmieniają się w czasie (udział kwartalnie, EUA i kurs ciągle),
    więc są polami do uzupełnienia — nie stałymi w kodzie. RestoreNumber
    zapamiętuje ostatnią wartość między restartami HA.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: BillCoordinator,
        entry: ConfigEntry,
        key: str,
        label: str,
        default: float,
        setter,
        *,
        min_value: float,
        max_value: float,
        step: float,
        unit: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._key = key
        self._default = default
        self._setter = setter
        self._attr_name = label
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_native_value = default
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = last.native_value
        self._setter(self._attr_native_value)
        await self.coordinator.async_request_refresh()

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self._setter(value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
