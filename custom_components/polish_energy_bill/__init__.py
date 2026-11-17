"""Integracja Polski Rachunek za Prąd."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_OVERWRITE,
    ATTR_TITLE,
    ATTR_URL_PATH,
    CONF_PROFILE,
    DOMAIN,
    PLATFORMS,
    SERVICE_INSTALL_DASHBOARD,
)
from .coordinator import BillCoordinator
from .core import ProfileError, load_builtin_profiles
from .dashboard_install import (
    DEFAULT_URL_PATH,
    DashboardInstallError,
    async_install_dashboard,
)

_LOGGER = logging.getLogger(__name__)

INSTALL_DASHBOARD_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_URL_PATH, default=DEFAULT_URL_PATH): cv.string,
        vol.Optional(ATTR_TITLE): cv.string,
        vol.Optional(ATTR_OVERWRITE, default=False): cv.boolean,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Rejestracja usług integracji (raz, niezależnie od liczby wpisów)."""

    async def _handle_install_dashboard(call: ServiceCall) -> ServiceResponse:
        entry = _select_entry(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        result = await async_install_dashboard(
            hass,
            entry,
            url_path=call.data[ATTR_URL_PATH],
            title=call.data.get(ATTR_TITLE),
            overwrite=call.data[ATTR_OVERWRITE],
        )
        return result.as_dict()

    hass.services.async_register(
        DOMAIN,
        SERVICE_INSTALL_DASHBOARD,
        _handle_install_dashboard,
        schema=INSTALL_DASHBOARD_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


def _select_entry(hass: HomeAssistant, entry_id: str | None) -> ConfigEntry:
    """Wpis konfiguracji dla usługi: wskazany albo jedyny załadowany."""
    loaded = [
        item
        for item in hass.config_entries.async_entries(DOMAIN)
        if item.state is ConfigEntryState.LOADED
    ]
    if entry_id is not None:
        for entry in loaded:
            if entry.entry_id == entry_id:
                return entry
        raise DashboardInstallError(
            f"Nie znaleziono załadowanego wpisu integracji o id {entry_id}."
        )
    if len(loaded) == 1:
        return loaded[0]
    if not loaded:
        raise DashboardInstallError("Integracja nie ma żadnego załadowanego wpisu.")
    names = ", ".join(f"{e.title} ({e.entry_id})" for e in loaded)
    raise DashboardInstallError(
        f"Jest kilka wpisów integracji — podaj config_entry_id: {names}."
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Konfiguracja wpisu integracji."""
    profile_key = entry.data[CONF_PROFILE]

    # Wczytanie profili to operacja I/O — wykonujemy poza pętlą zdarzeń.
    try:
        profiles = await hass.async_add_executor_job(load_builtin_profiles)
    except ProfileError as err:
        raise ConfigEntryError(f"Błąd profilu taryfowego: {err}") from err

    base_profile = profiles.get(profile_key)
    if base_profile is None:
        raise ConfigEntryError(f"Nieznany profil taryfowy: {profile_key}")

    coordinator = BillCoordinator(hass, entry, base_profile)
    # Pierwsze odświeżenie po dodaniu encji (number muszą najpierw wnieść stawki),
    # więc nie wymuszamy refresh tutaj — zrobi to platforma number po starcie.

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Usunięcie wpisu integracji."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Przeładowanie po zmianie opcji (sensory, billing, włączone pozycje)."""
    await hass.config_entries.async_reload(entry.entry_id)
