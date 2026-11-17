"""Instalacja dashboardu „Rachunek za prąd” w Lovelace.

Tworzy JEDNORAZOWĄ, edytowalną kopię dashboardu (zwykły dashboard w trybie
storage — można go przerobić w UI). Dodatek nie nadpisuje go sam z siebie;
nadpisanie następuje tylko na wyraźne żądanie (`overwrite: true`).

Entity_id w szablonie są podmieniane na rzeczywiste z rejestru encji tego wpisu
konfiguracji (patrz `core/dashboard.py`), więc dashboard działa niezależnie od
nazwy urządzenia i prefiksów encji.

Uwaga o stabilności: HA nie ma publicznego API do tworzenia dashboardów z poziomu
integracji. Używamy (1) `hass.data["lovelace"].dashboards` (to samo robi samo
Lovelace) i (2) kolekcji dashboardów odzyskanej z zarejestrowanej komendy WS
`lovelace/dashboards/create`. Gdy HA zmieni te szczegóły, instalacja nie psuje
niczego: zapisuje gotowy YAML do pliku w katalogu konfiguracji i o tym informuje.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
import yaml
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import CONF_ZONE_SENSORS, DOMAIN
from .core import Zone
from .core.dashboard import build_dashboard, load_template, make_resolver

_LOGGER = logging.getLogger(__name__)

DEFAULT_URL_PATH = "rachunek-za-prad"
DEFAULT_ICON = "mdi:cash-multiple"
FALLBACK_FILENAME = "polish_energy_bill_dashboard.yaml"

_LOVELACE_KEY = "lovelace"                       # = lovelace.const.LOVELACE_DATA
_WS_CREATE_COMMAND = "lovelace/dashboards/create"
_WS_HANDLERS_KEY = "websocket_api"               # = websocket_api.const.DOMAIN
_URL_PATH_RE = re.compile(r"^[a-z0-9_]+(-[a-z0-9_]+)+$")
_MAX_LISTED = 12


class DashboardInstallError(ServiceValidationError):
    """Błąd, który użytkownik może naprawić (komunikat po polsku)."""


@dataclass(frozen=True)
class InstallResult:
    """Wynik instalacji dashboardu."""

    url_path: str
    action: str                      # "created" | "updated" | "file"
    missing: tuple[str, ...]
    removed: int
    degraded: int
    apexcharts_found: bool | None    # None = nie da się ustalić
    fallback_file: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "url_path": self.url_path,
            "action": self.action,
            "missing_entities": list(self.missing),
            "removed_items": self.removed,
            "degraded_texts": self.degraded,
            "apexcharts_card_found": self.apexcharts_found,
            "fallback_file": self.fallback_file,
        }


# --- odczyt stanu Lovelace -------------------------------------------------------

def _lovelace_attr(hass: HomeAssistant, name: str) -> Any:
    """Pole z hass.data['lovelace'] (dataclass LovelaceData albo stary dict)."""
    data = hass.data.get(_LOVELACE_KEY)
    if data is None:
        return None
    if isinstance(data, dict):
        return data.get(name)
    return getattr(data, name, None)


def _dashboards(hass: HomeAssistant) -> dict[str | None, Any]:
    dashboards = _lovelace_attr(hass, "dashboards")
    if dashboards is None:
        raise DashboardInstallError(
            "Lovelace nie jest załadowany (brak hass.data['lovelace']). "
            "Sprawdź, czy panel „Dashboardy” działa."
        )
    return dashboards


def _find_dashboards_collection(hass: HomeAssistant) -> Any | None:
    """Kolekcja dashboardów storage — z zarejestrowanej komendy WS (przez __wrapped__)."""
    handlers = hass.data.get(_WS_HANDLERS_KEY)
    if not isinstance(handlers, dict):
        return None
    registered = handlers.get(_WS_CREATE_COMMAND)
    if not registered:
        return None
    func = registered[0]
    for _ in range(10):
        owner = getattr(func, "__self__", None)
        collection = getattr(owner, "storage_collection", None)
        if collection is not None and hasattr(collection, "async_create_item"):
            return collection
        func = getattr(func, "__wrapped__", None)
        if func is None:
            return None
    return None


async def _apexcharts_installed(hass: HomeAssistant) -> bool | None:
    resources = _lovelace_attr(hass, "resources")
    if resources is None:
        return None
    try:
        await resources.async_get_info()  # wymusza wczytanie zasobów ze storage
        items = resources.async_items() or []
    except Exception:  # noqa: BLE001 — diagnostyka pomocnicza, nie może blokować instalacji
        _LOGGER.debug("Nie udało się odczytać zasobów Lovelace", exc_info=True)
        return None
    return any("apexcharts-card" in str(item.get("url", "")) for item in items)


# --- encje wpisu -----------------------------------------------------------------

def _registry_entities(hass: HomeAssistant, entry: ConfigEntry) -> dict[tuple[str, str], str]:
    """(domena, slug nazwy encji) → entity_id dla encji tego wpisu konfiguracji."""
    registry = er.async_get(hass)
    out: dict[tuple[str, str], str] = {}
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        name = item.original_name
        if not name:
            continue
        out[(item.domain, slugify(name))] = item.entity_id
    return out


def _external_meter(entry: ConfigEntry) -> str | None:
    return (entry.data.get(CONF_ZONE_SENSORS) or {}).get(Zone.ALL.value)


# --- główna operacja ---------------------------------------------------------------

def validate_url_path(url_path: str) -> str:
    url_path = url_path.strip().lower()
    if not _URL_PATH_RE.match(url_path):
        raise DashboardInstallError(
            f"Nieprawidłowy url_path „{url_path}”: małe litery/cyfry, "
            "co najmniej jeden myślnik (np. rachunek-za-prad)."
        )
    return url_path


async def async_install_dashboard(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    url_path: str = DEFAULT_URL_PATH,
    title: str | None = None,
    overwrite: bool = False,
) -> InstallResult:
    """Tworzy (albo na żądanie nadpisuje) dashboard dla danego wpisu konfiguracji."""
    url_path = validate_url_path(url_path)

    template = await hass.async_add_executor_job(load_template)
    resolve = make_resolver(_registry_entities(hass, entry), _external_meter(entry))
    build = build_dashboard(template, resolve)
    config = build.config

    views = config.get("views") or []
    if not views:
        raise DashboardInstallError(
            "Nie znaleziono żadnych encji integracji — dashboard byłby pusty. "
            "Poczekaj, aż integracja utworzy encje, i spróbuj ponownie."
        )
    title = title or config.get("title") or "Rachunek za prąd"
    icon = (views[0].get("icon") if isinstance(views[0], dict) else None) or DEFAULT_ICON

    dashboards = _dashboards(hass)
    apex = await _apexcharts_installed(hass)
    fallback_file: str | None = None

    existing = dashboards.get(url_path)
    if existing is not None:
        if not overwrite:
            raise DashboardInstallError(
                f"Dashboard „{url_path}” już istnieje. Żeby go podmienić na świeży, "
                "wywołaj usługę polish_energy_bill.install_dashboard z overwrite: true "
                "(Twoje ręczne zmiany w nim przepadną) albo podaj inny url_path."
            )
        if getattr(existing, "mode", None) != "storage":
            raise DashboardInstallError(
                f"Dashboard „{url_path}” jest zdefiniowany w YAML — nie da się go "
                "nadpisać z poziomu HA. Podaj inny url_path."
            )
        await existing.async_save(config)
        action = "updated"
    else:
        collection = _find_dashboards_collection(hass)
        if collection is None:
            fallback_file = await _write_fallback(hass, config)
            action = "file"
        else:
            try:
                await collection.async_create_item(
                    {
                        "url_path": url_path,
                        "title": title,
                        "icon": icon,
                        "show_in_sidebar": True,
                        "require_admin": False,
                    }
                )
            except (vol.Invalid, HomeAssistantError) as err:
                raise DashboardInstallError(
                    f"Nie udało się utworzyć dashboardu „{url_path}”: {err}"
                ) from err
            created = dashboards.get(url_path)
            if created is None:
                raise DashboardInstallError(
                    f"HA utworzył wpis dashboardu „{url_path}”, ale nie zarejestrował "
                    "jego konfiguracji. Sprawdź log HA."
                )
            await created.async_save(config)
            action = "created"

    result = InstallResult(
        url_path=url_path,
        action=action,
        missing=build.missing,
        removed=len(build.removed),
        degraded=len(build.degraded),
        apexcharts_found=apex,
        fallback_file=fallback_file,
    )
    _notify(hass, entry, title, result)
    return result


async def _write_fallback(hass: HomeAssistant, config: dict[str, Any]) -> str:
    path = hass.config.path(FALLBACK_FILENAME)

    def _write() -> None:
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(config, handle, allow_unicode=True, sort_keys=False, width=100)

    await hass.async_add_executor_job(_write)
    return path


# --- powiadomienie -----------------------------------------------------------------

def _notify(hass: HomeAssistant, entry: ConfigEntry, title: str, result: InstallResult) -> None:
    lines: list[str] = []
    if result.action == "file":
        lines.append(
            "Nie mogłem automatycznie utworzyć dashboardu (zmieniło się wewnętrzne API "
            f"Lovelace). Gotowa konfiguracja jest w pliku `{result.fallback_file}`. "
            "Utwórz pusty dashboard (Ustawienia → Dashboardy → Dodaj), wejdź w niego, "
            "⋮ → Edytuj → ⋮ → Edytor surowej konfiguracji i wklej zawartość pliku."
        )
    else:
        verb = "zaktualizowany" if result.action == "updated" else "gotowy"
        lines.append(
            f"Dashboard **{title}** jest {verb}: [otwórz](/{result.url_path}). "
            "To zwykły dashboard — możesz go edytować w UI. Dodatek nie zmienia go sam "
            "z siebie; świeżą wersję wgrasz usługą `polish_energy_bill.install_dashboard` "
            "z `overwrite: true`."
        )
    if result.apexcharts_found is False:
        lines.append(
            "⚠️ Nie znalazłem zasobu **apexcharts-card** — wykresy pokażą błąd karty. "
            "Zainstaluj „ApexCharts Card” (Katalog społeczności / HACS) i odśwież stronę."
        )
    if result.missing:
        shown = ", ".join(f"`{item}`" for item in result.missing[:_MAX_LISTED])
        more = len(result.missing) - _MAX_LISTED
        suffix = f" (+{more} więcej)" if more > 0 else ""
        lines.append(
            f"⚠️ Nie znalazłem {len(result.missing)} encji z szablonu: {shown}{suffix}. "
            f"Usunięto z dashboardu {result.removed} powiązanych elementów"
            + (f"; w {result.degraded} tekstach (markdown/JS) odwołania zostały." if result.degraded else ".")
        )
    persistent_notification.async_create(
        hass,
        "\n\n".join(lines),
        title="Rachunek za prąd — dashboard",
        notification_id=f"{DOMAIN}_dashboard_{entry.entry_id}",
    )
