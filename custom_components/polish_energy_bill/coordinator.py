"""DataUpdateCoordinator — spina zużycie, stawki i kalkulator."""

from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BILLING_DAYS,
    CONF_BILLING_MONTHS,
    CONF_ENABLED_OVERRIDES,
    CONF_MODE,
    CONF_ZONE_SENSORS,
    DEFAULT_BILLING_MONTHS,
    DEFAULT_ETS_EMISSION_FACTOR,
    DEFAULT_ETS_EUA_PRICE,
    DEFAULT_ETS_EUR_PLN,
    DEFAULT_ETS_PERCENT,
    DOMAIN,
    ETS_ENERGY_KEY_PREFIX,
    ETS_METHOD_PERCENT,
    MODE_MANUAL,
    PERIOD_MODE_HISTORY,
    PERIOD_MODE_READINGS,
    PERIOD_MODE_SINCE,
    PERIOD_MODE_ZERO,
)
from .core import (
    Bill,
    BillingPeriod,
    Consumption,
    EtsEstimate,
    EtsMethod,
    EtsParams,
    TariffProfile,
    Unit,
    Zone,
    calculate,
    estimate_ets,
)

_LOGGER = logging.getLogger(__name__)
UPDATE_INTERVAL = timedelta(minutes=1)


class BillCoordinator(DataUpdateCoordinator[Bill]):
    """Liczy rachunek na bazie aktualnych danych i odświeża go cyklicznie."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        base_profile: TariffProfile,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=UPDATE_INTERVAL,
        )
        self.entry = entry
        self.base_profile = base_profile

        # Stan żywy, zasilany przez encje number (RestoreNumber):
        self.rate_overrides: dict[str, Decimal] = {}
        self.manual_consumption: dict[Zone, Decimal] = {}
        # Punkt zero (odczyt licznika bazowy) per strefa — tryb sensor:
        self.baseline: dict[Zone, Decimal] = {}
        # Rejestr encji baseline, by przycisk mógł je ustawić:
        self._baseline_entities: dict[Zone, Any] = {}

        # Zakres dat + tryb ustalania zużycia w okresie:
        self.period_mode: str = PERIOD_MODE_ZERO
        self.period_start: date | None = None
        self.period_end: date | None = None
        # Punkt zero jako moment w czasie (tryb 'od_odczytu'):
        self.zero_datetime: datetime | None = None
        # Ręczne odczyty licznika per strefa (tryb 'reczne_odczyty'):
        self.start_readings: dict[Zone, Decimal] = {}
        self.end_readings: dict[Zone, Decimal] = {}

        # ETS (koszty uprawnień do emisji CO₂) — żywy stan z encji number/select.
        # Wartości startowe; podmieniane w UI, bo zmieniają się w czasie.
        self.ets_method: str = ETS_METHOD_PERCENT
        self.ets_percent: Decimal = Decimal(str(DEFAULT_ETS_PERCENT))
        self.ets_emission_factor: Decimal = Decimal(str(DEFAULT_ETS_EMISSION_FACTOR))
        self.ets_eua_price: Decimal = Decimal(str(DEFAULT_ETS_EUA_PRICE))
        self.ets_eur_pln: Decimal = Decimal(str(DEFAULT_ETS_EUR_PLN))

    # --- API dla encji number ---

    @callback
    def set_rate_override(self, key: str, value: float) -> None:
        self.rate_overrides[key] = Decimal(str(value))

    @callback
    def set_manual_consumption(self, zone: Zone, value: float) -> None:
        self.manual_consumption[zone] = Decimal(str(value))

    @callback
    def set_baseline(self, zone: Zone, value: float) -> None:
        self.baseline[zone] = Decimal(str(value))

    @callback
    def set_period_mode(self, mode: str) -> None:
        self.period_mode = mode

    @callback
    def set_period_start(self, value: date | None) -> None:
        self.period_start = value

    @callback
    def set_period_end(self, value: date | None) -> None:
        self.period_end = value

    @callback
    def set_zero_datetime(self, value: datetime | None) -> None:
        self.zero_datetime = value

    @callback
    def set_start_reading(self, zone: Zone, value: float) -> None:
        self.start_readings[zone] = Decimal(str(value))

    @callback
    def set_end_reading(self, zone: Zone, value: float) -> None:
        self.end_readings[zone] = Decimal(str(value))

    @callback
    def register_baseline_entity(self, zone: Zone, entity: Any) -> None:
        self._baseline_entities[zone] = entity

    # --- API dla encji ETS ---

    @callback
    def set_ets_method(self, method: str) -> None:
        self.ets_method = method

    @callback
    def set_ets_percent(self, value: float) -> None:
        self.ets_percent = Decimal(str(value))

    @callback
    def set_ets_emission_factor(self, value: float) -> None:
        self.ets_emission_factor = Decimal(str(value))

    @callback
    def set_ets_eua_price(self, value: float) -> None:
        self.ets_eua_price = Decimal(str(value))

    @callback
    def set_ets_eur_pln(self, value: float) -> None:
        self.ets_eur_pln = Decimal(str(value))

    def ets_estimate(self) -> EtsEstimate | None:
        """Szacuje koszt ETS jako nakładkę na bieżący rachunek.

        Bazuje na gotowym Bill (self.data) i edytowalnych parametrach ETS.
        Nie modyfikuje rachunku. Zwraca None, dopóki nie ma policzonego rachunku.
        """
        bill = self.data
        if bill is None:
            return None

        # Suma netto/brutto pozycji „energia czynna" (baza metody procentowej).
        energy_lines = [
            l for l in bill.lines if l.key.startswith(ETS_ENERGY_KEY_PREFIX)
        ]
        energy_net = sum((l.net for l in energy_lines), Decimal("0"))
        energy_gross = sum((l.gross for l in energy_lines), Decimal("0"))
        energy_vat_rate = energy_lines[0].vat_rate if energy_lines else Decimal("0.23")

        # Stawka energii czynnej z cen [zł/kWh] (niezależna od zużycia) — z profilu,
        # by stawka ETS na wykresach działała też przy zerowym zużyciu.
        profile = self.effective_profile()
        energy_unit_rate_net = sum(
            (
                p.rate
                for p in profile.positions
                if p.enabled
                and p.unit is Unit.PER_KWH
                and p.key.startswith(ETS_ENERGY_KEY_PREFIX)
            ),
            Decimal("0"),
        )

        params = EtsParams(
            percent_share=self.ets_percent / Decimal("100"),
            emission_factor=self.ets_emission_factor,
            eua_price_eur=self.ets_eua_price,
            eur_pln=self.ets_eur_pln,
        )
        method = (
            EtsMethod.PERCENT
            if self.ets_method == ETS_METHOD_PERCENT
            else EtsMethod.EMISSION
        )
        return estimate_ets(
            method=method,
            params=params,
            energy_net=energy_net,
            energy_gross=energy_gross,
            energy_unit_rate_net=energy_unit_rate_net,
            energy_vat_rate=energy_vat_rate,
            consumption_kwh=bill.consumption_kwh,
            bill_gross=bill.gross,
        )

    async def capture_zero(self, zone: Zone) -> bool:
        """Zapisuje bieżący odczyt sensora strefy jako punkt zero.

        Zwraca True, jeśli udało się odczytać sensor. Aktualizuje też encję
        number 'Odczyt zero', by wartość była widoczna w UI.
        """
        entity_id = self.zone_sensors.get(zone.value)
        if not entity_id:
            return False
        value = self._read_sensor(entity_id)
        if value is None:
            return False
        entity = self._baseline_entities.get(zone)
        if entity is not None:
            await entity.async_set_native_value(float(value))
        else:
            self.set_baseline(zone, float(value))
            await self.async_request_refresh()
        return True

    # --- konfiguracja z opcji ---

    @property
    def mode(self) -> str:
        return self.entry.data.get(CONF_MODE, MODE_MANUAL)

    @property
    def zone_sensors(self) -> dict[str, str]:
        return self.entry.data.get(CONF_ZONE_SENSORS, {})

    @property
    def enabled_overrides(self) -> dict[str, bool]:
        return self.entry.options.get(CONF_ENABLED_OVERRIDES, {})

    def _billing_period(self) -> BillingPeriod:
        # Tryb 'od odczytu do teraz': okres od daty odczytu do bieżącej chwili.
        if self.period_mode == PERIOD_MODE_SINCE and self.zero_datetime:
            return BillingPeriod.from_dates(self.zero_datetime, dt_util.now())
        # Priorytet: jawny zakres dat z panelu.
        if self.period_start and self.period_end:
            return BillingPeriod.from_dates(self.period_start, self.period_end)
        months = Decimal(
            str(self.entry.options.get(CONF_BILLING_MONTHS, DEFAULT_BILLING_MONTHS))
        )
        days = self.entry.options.get(CONF_BILLING_DAYS)
        if not days:  # auto: liczba dni bieżącego miesiąca
            today = date.today()
            days = calendar.monthrange(today.year, today.month)[1]
        return BillingPeriod(days=int(days), months=months)

    # --- odczyt zużycia ---

    async def _read_consumption(self) -> Consumption:
        by_zone: dict[Zone, Decimal] = {}

        if self.mode == MODE_MANUAL:
            by_zone = dict(self.manual_consumption)

        elif self.period_mode == PERIOD_MODE_READINGS:
            # Różnica: odczyt końcowy - początkowy (per strefa).
            for zone_name in self.zone_sensors:
                zone = Zone(zone_name)
                start = self.start_readings.get(zone)
                end = self.end_readings.get(zone)
                if start is not None and end is not None:
                    by_zone[zone] = max(Decimal("0"), end - start)

        elif self.period_mode == PERIOD_MODE_SINCE and self.zero_datetime:
            # Od daty+godziny odczytu do teraz — przyrost licznika z historii.
            start_dt = dt_util.as_local(self.zero_datetime)
            end_dt = dt_util.now()
            for zone_name, entity_id in self.zone_sensors.items():
                used = await self._history_consumption(entity_id, start_dt, end_dt)
                if used is not None:
                    by_zone[Zone(zone_name)] = used

        elif self.period_mode == PERIOD_MODE_HISTORY and self.period_start and self.period_end:
            # Auto z historii licznika dla jawnego zakresu dat.
            start_dt = dt_util.start_of_local_day(self.period_start)
            end_dt = dt_util.start_of_local_day(self.period_end) + timedelta(days=1)
            for zone_name, entity_id in self.zone_sensors.items():
                used = await self._history_consumption(entity_id, start_dt, end_dt)
                if used is not None:
                    by_zone[Zone(zone_name)] = used

        else:
            # Punkt zero: bieżący odczyt - punkt zero.
            for zone_name, entity_id in self.zone_sensors.items():
                value = self._read_sensor(entity_id)
                if value is None:
                    continue
                zone = Zone(zone_name)
                base = self.baseline.get(zone, Decimal("0"))
                by_zone[zone] = max(Decimal("0"), value - base)

        if not by_zone:
            by_zone = {Zone.ALL: Decimal("0")}
        return Consumption(by_zone)

    async def _history_consumption(
        self, entity_id: str, start_dt: datetime, end_dt: datetime
    ) -> Decimal | None:
        """Zużycie [kWh] z long-term statistics licznika w zadanym oknie czasu.

        Zwraca sumę przyrostów (change) sensora między start_dt a end_dt.
        Odporne na różnice API recordera między wersjami HA — w razie błędu None.
        """
        if start_dt >= end_dt:
            return None
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.statistics import (
                statistics_during_period,
            )

            stats = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                start_dt,
                end_dt,
                {entity_id},
                "hour",
                None,
                {"change"},
            )
        except Exception as err:  # noqa: BLE001 - API recordera bywa zmienne
            _LOGGER.warning("Nie udało się pobrać historii dla %s: %s", entity_id, err)
            return None

        series = stats.get(entity_id) if stats else None
        if not series:
            return None
        total = Decimal("0")
        for row in series:
            change = row.get("change")
            if change is not None:
                total += Decimal(str(change))
        return total if total > 0 else Decimal("0")

    def _read_sensor(self, entity_id: str) -> Decimal | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", "", None):
            return None
        try:
            return Decimal(str(state.state))
        except (InvalidOperation, ValueError):
            _LOGGER.warning("Sensor %s ma niepoprawną wartość: %s", entity_id, state.state)
            return None

    # --- główna pętla ---

    async def _async_update_data(self) -> Bill:
        profile = self.base_profile.customize(
            rate_overrides=self.rate_overrides,
            enabled_overrides=self.enabled_overrides,
        )
        consumption = await self._read_consumption()
        period = self._billing_period()
        return calculate(profile, consumption, period)

    def effective_profile(self) -> TariffProfile:
        """Profil z aktualnymi override'ami — używany przez encje number."""
        return self.base_profile.customize(
            rate_overrides=self.rate_overrides,
            enabled_overrides=self.enabled_overrides,
        )
