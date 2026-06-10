"""Encje sensor: rachunek brutto/netto/VAT, sumy grup i pozycje."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BillCoordinator
from .core import Bill, Group

GROUP_LABEL = {
    Group.SALE: "Sprzedaż energii",
    Group.DISTRIBUTION: "Dystrybucja",
    Group.TAX: "Podatki i opłaty",
    Group.OTHER: "Pozostałe",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: BillCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        BillTotalSensor(coordinator, entry, "gross", "Do zapłaty (brutto)"),
        BillTotalSensor(coordinator, entry, "net", "Należność netto"),
        BillTotalSensor(coordinator, entry, "vat", "VAT"),
        BillTotalSensor(coordinator, entry, "variable_gross", "Koszt energii zmienny (brutto)"),
        BillTotalSensor(coordinator, entry, "fixed_gross", "Opłaty stałe (brutto)"),
        UnitCostSensor(coordinator, entry),
        UnitRateSensor(coordinator, entry),
        EnergyCostSensor(coordinator, entry),
        ConsumptionSensor(coordinator, entry),
        EtsCostSensor(coordinator, entry),
        EtsShareSensor(coordinator, entry),
        EtsRateSensor(coordinator, entry),
        EtsCo2Sensor(coordinator, entry),
    ]
    entities += [
        GroupSensor(coordinator, entry, group) for group in Group
    ]
    entities += [
        PositionSensor(coordinator, entry, pos.key, pos.name)
        for pos in coordinator.base_profile.positions
    ]
    async_add_entities(entities)


class _BillEntity(CoordinatorEntity[BillCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: BillCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": self.coordinator.base_profile.seller,
            "model": self.coordinator.base_profile.name,
        }

    @property
    def bill(self) -> Bill | None:
        return self.coordinator.data


class BillTotalSensor(_BillEntity):
    """Suma rachunku: brutto / netto / VAT."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "PLN"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry, field: str, label: str) -> None:
        super().__init__(coordinator, entry)
        self._field = field
        self._attr_name = label
        self._attr_unique_id = f"{entry.entry_id}_{field}"

    @property
    def native_value(self):
        if self.bill is None:
            return None
        return float(getattr(self.bill, self._field))

    @property
    def extra_state_attributes(self):
        if self.bill is None or self._field != "gross":
            return None
        # Pełny rozkład rachunku tylko na głównym sensorze brutto.
        return self.bill.as_dict()


class GroupSensor(_BillEntity):
    """Suma netto dla grupy (sprzedaż / dystrybucja / podatki)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "PLN"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry, group: Group) -> None:
        super().__init__(coordinator, entry)
        self._group = group
        self._attr_name = f"{GROUP_LABEL.get(group, group.value)} (netto)"
        self._attr_unique_id = f"{entry.entry_id}_group_{group.value}"

    @property
    def native_value(self):
        if self.bill is None:
            return None
        return float(self.bill.group_net(self._group))


class PositionSensor(_BillEntity):
    """Netto pojedynczej pozycji + szczegóły w atrybutach."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "PLN"
    _attr_suggested_display_precision = 2
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, key: str, label: str) -> None:
        super().__init__(coordinator, entry)
        self._key = key
        self._attr_name = label
        self._attr_unique_id = f"{entry.entry_id}_pos_{key}"

    @property
    def native_value(self):
        if self.bill is None:
            return None
        line = self.bill.line(self._key)
        return float(line.net) if line else None

    @property
    def extra_state_attributes(self):
        if self.bill is None:
            return None
        line = self.bill.line(self._key)
        return line.as_dict() if line else None


class UnitCostSensor(_BillEntity):
    """Średni koszt brutto 1 kWh (część zmienna) [zł/kWh]."""

    _attr_native_unit_of_measurement = "zł/kWh"
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Koszt 1 kWh (brutto)"
        self._attr_unique_id = f"{entry.entry_id}_unit_cost"

    @property
    def native_value(self):
        if self.bill is None:
            return None
        return float(self.bill.variable_unit_gross)


class UnitRateSensor(_BillEntity):
    """Stawka brutto za 1 kWh (część zmienna) [zł/kWh] — mnożnik na wykresach.

    Liczona wprost z cen, niezależnie od zużycia (działa też przy zerze).
    """

    _attr_native_unit_of_measurement = "zł/kWh"
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Stawka zmienna (brutto)"
        self._attr_unique_id = f"{entry.entry_id}_unit_rate"

    @property
    def native_value(self):
        if self.bill is None:
            return None
        return float(self.bill.unit_rate_gross)


class EnergyCostSensor(_BillEntity):
    """Koszt zmienny energii narastająco [PLN] — źródło wykresów i panelu Energia.

    Rośnie wraz ze zużyciem w okresie; przy ustawieniu nowego punktu zero
    spada — dlatego TOTAL_INCREASING, by statystyki poprawnie liczyły przyrosty.
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "PLN"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Koszt energii (narastająco)"
        self._attr_unique_id = f"{entry.entry_id}_energy_cost"

    @property
    def native_value(self):
        if self.bill is None:
            return None
        return float(self.bill.variable_gross)


class ConsumptionSensor(_BillEntity):
    """Łączne zużycie energii przyjęte do rachunku [kWh]."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Zużycie w rachunku"
        self._attr_unique_id = f"{entry.entry_id}_consumption_total"

    @property
    def native_value(self):
        if self.bill is None:
            return None
        return float(self.bill.consumption_kwh)


# --------------------------------------------------------------------------
#  ETS — koszty uprawnień do emisji CO₂ (dobudowana nakładka na rachunek)
# --------------------------------------------------------------------------


class _EtsEntity(_BillEntity):
    """Baza encji ETS — bierze szacunek z coordinatora (nakładka na Bill)."""

    @property
    def estimate(self):
        if self.bill is None:
            return None
        return self.coordinator.ets_estimate()


class EtsCostSensor(_EtsEntity):
    """Koszt ETS w okresie [PLN brutto] wg wybranej metody.

    W atrybutach: pełne rozbicie (obie metody, udziały, emisja CO₂).
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "PLN"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "ETS — koszt w rachunku (brutto)"
        self._attr_unique_id = f"{entry.entry_id}_ets_cost"

    @property
    def native_value(self):
        est = self.estimate
        return float(est.gross) if est else None

    @property
    def extra_state_attributes(self):
        est = self.estimate
        return est.as_dict() if est else None


class EtsShareSensor(_EtsEntity):
    """Udział kosztów ETS w całym rachunku brutto [%]."""

    _attr_native_unit_of_measurement = "%"
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:molecule-co2"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "ETS — udział w rachunku"
        self._attr_unique_id = f"{entry.entry_id}_ets_share"

    @property
    def native_value(self):
        est = self.estimate
        return float(est.share_of_bill * 100) if est else None


class EtsRateSensor(_EtsEntity):
    """Stawka ETS brutto [zł/kWh] — mnożnik na wykresach kosztu w czasie.

    Liczona z cen, niezależnie od zużycia (działa też przy zerze).
    """

    _attr_native_unit_of_measurement = "zł/kWh"
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "ETS — stawka (brutto)"
        self._attr_unique_id = f"{entry.entry_id}_ets_rate"

    @property
    def native_value(self):
        est = self.estimate
        return float(est.rate_gross) if est else None


class EtsCo2Sensor(_EtsEntity):
    """Masa CO₂ stojąca za zużyciem w okresie [kg] (pogląd)."""

    _attr_native_unit_of_measurement = "kg"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:cloud-outline"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "ETS — emisja CO₂"
        self._attr_unique_id = f"{entry.entry_id}_ets_co2"

    @property
    def native_value(self):
        est = self.estimate
        return float(est.co2_kg) if est else None
