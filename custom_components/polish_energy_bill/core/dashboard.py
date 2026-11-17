"""Budowa dashboardu Lovelace z szablonu — czysta logika, bez Home Assistant.

Szablon (`dashboard_template.yaml`) odwołuje się do encji po ich nazwach
z instalacji autora (`sensor.rachunek_za_prad_…`, `number.liczniki_rachunek_za_prad_…`).
Na innej instalacji entity_id wyglądają inaczej (zależą od nazwy urządzenia), więc:

1. każde odwołanie do encji (też w Jinja i w JS wykresów) jest podmieniane na
   rzeczywiste entity_id znalezione przez `resolve`,
2. karty/wiersze/serie wskazujące encję, której nie ma (np. strefy G12 przy
   szablonie G11), są usuwane zamiast zostawiać puste kafelki,
3. sekcje, które po przycięciu mają już tylko nagłówek, są usuwane.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

TEMPLATE_PATH = Path(__file__).parent.parent / "dashboard_template.yaml"

# Zewnętrzny licznik energii (źródło zużycia) — w szablonie to sensor autora.
EXTERNAL_METER_TEMPLATE_ID = "sensor.pge_total_energy_consumption"

# Domeny encji, które tworzy integracja lub które szablon czyta.
_DOMAINS = "sensor|number|select|datetime|date|button"

# entity_id w dowolnym tekście: klucz YAML, Jinja `states('…')`, JS `hass.states['…']`.
# Lookbehind blokuje m.in. `as_datetime(` i `states.sensor.x`; lookahead — urwanie
# dłuższego id (sensor.a vs sensor.a_b).
ENTITY_ID_RE = re.compile(
    rf"(?<![A-Za-z0-9_.])((?:{_DOMAINS})\.[a-z0-9_]+)(?![A-Za-z0-9_])"
)

# Encje integracji w szablonie: <domena>.[liczniki_]rachunek_za_prad_<slug nazwy encji>
_TEMPLATE_ID_RE = re.compile(
    r"^(?P<domain>[a-z]+)\.(?:liczniki_)?rachunek_za_prad_(?P<slug>[a-z0-9_]+)$"
)

# Klucze list, których elementy-encje są usuwane, gdy encji brak.
_PRUNABLE_LISTS = ("entities", "series")


def load_template() -> dict[str, Any]:
    """Wczytuje szablon dashboardu z pakietu (operacja I/O)."""
    with TEMPLATE_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def template_key(template_id: str) -> tuple[str, str] | None:
    """(domena, slug nazwy encji) dla encji integracji z szablonu; inaczej None."""
    match = _TEMPLATE_ID_RE.match(template_id)
    if match is None:
        return None
    return match["domain"], match["slug"]


def make_resolver(
    registry_entities: Mapping[tuple[str, str], str],
    external_meter: str | None,
) -> Callable[[str], str | None]:
    """Resolver entity_id z szablonu → entity_id z tej instalacji (albo None).

    `registry_entities`: (domena, slug nazwy encji) → entity_id z rejestru encji
    wpisu konfiguracji. `external_meter`: sensor zużycia wskazany w konfiguracji.
    """

    def resolve(template_id: str) -> str | None:
        if template_id == EXTERNAL_METER_TEMPLATE_ID:
            return external_meter
        key = template_key(template_id)
        if key is None:
            return None
        return registry_entities.get(key)

    return resolve


def collect_entity_ids(node: Any) -> set[str]:
    """Wszystkie odwołania do encji w strukturze (klucze, Jinja, JS)."""
    found: set[str] = set()
    if isinstance(node, str):
        found.update(ENTITY_ID_RE.findall(node))
    elif isinstance(node, dict):
        for value in node.values():
            found |= collect_entity_ids(value)
    elif isinstance(node, list):
        for value in node:
            found |= collect_entity_ids(value)
    return found


@dataclass(frozen=True)
class DashboardBuild:
    """Wynik budowy dashboardu."""

    config: dict[str, Any]
    mapping: dict[str, str]          # id z szablonu → id z tej instalacji
    missing: tuple[str, ...]         # id z szablonu, których nie znaleziono
    removed: tuple[str, ...]         # co usunięto z powodu braków (opis)
    degraded: tuple[str, ...]        # miejsca, gdzie brakujące id zostało w tekście


def _describe(item: Any) -> str:
    if isinstance(item, dict):
        for key in ("entity", "heading", "title", "type"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return f"{key}={value.strip()}"
    return type(item).__name__


def _non_heading_cards(cards: list) -> int:
    return sum(
        1 for card in cards if not (isinstance(card, dict) and card.get("type") == "heading")
    )


def _prune(node: Any, missing: set[str], removed: list[str]) -> Any:
    """Zwraca kopię bez elementów wskazujących brakujące encje."""
    if isinstance(node, list):
        out = []
        for item in node:
            if isinstance(item, str) and item.strip() in missing:
                removed.append(f"wiersz {item.strip()}")
                continue
            pruned = _prune(item, missing, removed)
            if _is_dead(item, pruned, missing):
                removed.append(_describe(item))
                continue
            out.append(pruned)
        return out
    if isinstance(node, dict):
        return {key: _prune(value, missing, removed) for key, value in node.items()}
    return node


def _is_dead(original: Any, pruned: Any, missing: set[str]) -> bool:
    """Element listy do wycięcia: sam wskazuje brakującą encję albo opustoszał."""
    if not isinstance(original, dict):
        return False
    entity = original.get("entity")
    if isinstance(entity, str) and entity.strip() in missing:
        return True
    for key in _PRUNABLE_LISTS:
        if original.get(key) and not pruned.get(key):
            return True
    cards = original.get("cards")
    if isinstance(cards, list) and _non_heading_cards(cards) > 0:
        return _non_heading_cards(pruned.get("cards", [])) == 0
    return False


def _degraded(node: Any, missing: set[str], path: str = "") -> list[str]:
    """Teksty (markdown/Jinja/JS), w których zostały brakujące id."""
    out: list[str] = []
    if isinstance(node, str):
        hits = sorted(set(ENTITY_ID_RE.findall(node)) & missing)
        out.extend(f"{path}: {hit}" for hit in hits)
    elif isinstance(node, dict):
        for key, value in node.items():
            out.extend(_degraded(value, missing, f"{path}.{key}" if path else key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            out.extend(_degraded(value, missing, f"{path}[{index}]"))
    return out


def _rewrite(node: Any, mapping: Mapping[str, str]) -> Any:
    if isinstance(node, str):
        return ENTITY_ID_RE.sub(lambda m: mapping.get(m.group(1), m.group(1)), node)
    if isinstance(node, dict):
        return {key: _rewrite(value, mapping) for key, value in node.items()}
    if isinstance(node, list):
        return [_rewrite(value, mapping) for value in node]
    return node


def build_dashboard(
    template: Mapping[str, Any], resolve: Callable[[str], str | None]
) -> DashboardBuild:
    """Buduje konfigurację dashboardu dla konkretnej instalacji.

    Nie mutuje `template`.
    """
    source = copy.deepcopy(dict(template))
    ids = sorted(collect_entity_ids(source))

    mapping: dict[str, str] = {}
    missing: set[str] = set()
    for template_id in ids:
        resolved = resolve(template_id)
        if resolved is None:
            missing.add(template_id)
        else:
            mapping[template_id] = resolved

    removed: list[str] = []
    pruned = _prune(source, missing, removed) if missing else source
    degraded = _degraded(pruned, missing) if missing else []
    config = _rewrite(pruned, mapping)

    return DashboardBuild(
        config=config,
        mapping=mapping,
        missing=tuple(sorted(missing)),
        removed=tuple(removed),
        degraded=tuple(degraded),
    )
