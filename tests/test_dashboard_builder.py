"""Testy generatora dashboardu (czysta logika, bez Home Assistant)."""

from __future__ import annotations

import copy
import json
import pathlib

import pytest

from core.dashboard import (
    EXTERNAL_METER_TEMPLATE_ID,
    build_dashboard,
    collect_entity_ids,
    load_template,
    make_resolver,
    template_key,
)

ROOT = pathlib.Path(__file__).parent.parent
PKG_TEMPLATE = ROOT / "custom_components" / "polish_energy_bill" / "dashboard_template.yaml"
REPO_COPY = ROOT / "dashboards" / "rachunek_za_prad.yaml"


@pytest.fixture(scope="module")
def template() -> dict:
    return load_template()


def _walk(node):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _sections(config: dict) -> list[dict]:
    return config["views"][0]["sections"]


def _entity_keys(config: dict) -> set[str]:
    return {
        node["entity"].strip()
        for node in _walk(config)
        if isinstance(node, dict) and isinstance(node.get("entity"), str)
    }


def test_package_template_equals_repo_copy():
    # Szablon w pakiecie (instalowany przez HACS) i kopia w dashboards/ nie mogą się rozjechać.
    assert PKG_TEMPLATE.read_bytes() == REPO_COPY.read_bytes()


def test_every_template_entity_is_resolvable_by_name(template):
    ids = collect_entity_ids(template)
    assert len(ids) >= 35
    for entity_id in ids:
        assert entity_id == EXTERNAL_METER_TEMPLATE_ID or template_key(entity_id) is not None, entity_id


def test_collect_includes_ids_inside_jinja_and_js(template):
    ids = collect_entity_ids(template)
    # Jinja (markdown) i JS (apexcharts transform) też liczą się jako odwołania.
    assert "select.liczniki_rachunek_za_prad_tryb_zuzycia_okresu" in ids
    assert "sensor.liczniki_rachunek_za_prad_stawka_zmienna_brutto" in ids


def test_template_key_strips_both_prefixes():
    assert template_key("sensor.rachunek_za_prad_do_zaplaty_brutto") == ("sensor", "do_zaplaty_brutto")
    assert template_key("number.liczniki_rachunek_za_prad_ets_kurs_eur_pln") == ("number", "ets_kurs_eur_pln")
    assert template_key("sensor.pge_total_energy_consumption") is None
    assert template_key("light.kuchnia") is None


def test_identity_resolver_changes_nothing(template):
    snapshot = copy.deepcopy(template)
    build = build_dashboard(template, lambda entity_id: entity_id)
    assert build.config == snapshot
    assert build.missing == ()
    assert build.removed == ()
    assert build.degraded == ()
    assert template == snapshot  # szablon nie jest mutowany


def test_rename_rewrites_every_occurrence(template):
    build = build_dashboard(template, lambda entity_id: entity_id + "_x")
    dumped = json.dumps(build.config, ensure_ascii=False)
    for entity_id in collect_entity_ids(template):
        assert f"{entity_id}_x" in dumped
        # żadne nieprzepisane (stare, kończące się przed `_x`) odwołanie nie zostało
        assert f"{entity_id}'" not in dumped
        assert f"{entity_id}\"" not in dumped
    assert build.missing == ()


def test_prefix_ids_are_not_clobbered(template):
    # sensor.a i sensor.a_b: podmiana krótszego nie może uszkodzić dłuższego.
    mapping = {
        "sensor.rachunek_za_prad_vat": "sensor.X",
    }
    build = build_dashboard(template, lambda e: mapping.get(e, e))
    assert "sensor.X" in _entity_keys(build.config)
    assert "sensor.rachunek_za_prad_koszt_1_kwh_brutto" in _entity_keys(build.config)


def test_missing_external_meter_drops_only_its_cards(template):
    def resolve(entity_id):
        return None if entity_id == EXTERNAL_METER_TEMPLATE_ID else entity_id

    before = sum(1 for n in _walk(template) if isinstance(n, dict) and n.get("type") == "custom:apexcharts-card")
    build = build_dashboard(template, resolve)
    after = sum(1 for n in _walk(build.config) if isinstance(n, dict) and n.get("type") == "custom:apexcharts-card")
    assert build.missing == (EXTERNAL_METER_TEMPLATE_ID,)
    assert EXTERNAL_METER_TEMPLATE_ID not in _entity_keys(build.config)
    assert 0 < after < before
    assert build.removed  # raport, co usunięto


def test_missing_row_drops_row_but_keeps_card(template):
    target = "date.liczniki_rachunek_za_prad_okres_od"
    build = build_dashboard(template, lambda e: None if e == target else e)
    assert target not in _entity_keys(build.config)
    # reszta wiersza/karty zostaje — liczba kart typu entities nie spada
    count = lambda cfg: sum(1 for n in _walk(cfg) if isinstance(n, dict) and n.get("type") == "entities")
    assert count(build.config) == count(template)


def test_section_with_only_heading_is_removed(template):
    def resolve(entity_id):
        return None if "_ets_" in entity_id else entity_id

    build = build_dashboard(template, resolve)
    for section in _sections(build.config):
        non_heading = [c for c in section["cards"] if c.get("type") != "heading"]
        assert non_heading, "sekcja zawiera tylko nagłówek"
    assert len(_sections(build.config)) <= len(_sections(template))


def test_markdown_with_missing_id_is_kept_and_reported(template):
    target = "select.liczniki_rachunek_za_prad_tryb_zuzycia_okresu"
    build = build_dashboard(template, lambda e: None if e == target else e)
    assert build.degraded, "karta markdown z brakującą encją powinna być zgłoszona"
    assert any(target in item for item in build.degraded)


def test_make_resolver_by_domain_and_slug():
    registry = {
        ("sensor", "do_zaplaty_brutto"): "sensor.moj_licznik_do_zaplaty_brutto",
        ("number", "ets_kurs_eur_pln"): "number.moj_licznik_ets_kurs_eur_pln",
    }
    resolve = make_resolver(registry, external_meter="sensor.moj_licznik_total")
    assert resolve("sensor.rachunek_za_prad_do_zaplaty_brutto") == "sensor.moj_licznik_do_zaplaty_brutto"
    assert resolve("number.liczniki_rachunek_za_prad_ets_kurs_eur_pln") == "number.moj_licznik_ets_kurs_eur_pln"
    assert resolve("sensor.rachunek_za_prad_nie_ma_takiej") is None
    # ten sam slug w innej domenie nie jest dopasowywany
    assert resolve("select.rachunek_za_prad_do_zaplaty_brutto") is None
    assert resolve(EXTERNAL_METER_TEMPLATE_ID) == "sensor.moj_licznik_total"
    assert make_resolver(registry, external_meter=None)(EXTERNAL_METER_TEMPLATE_ID) is None


# --- reguły przycinania na syntetycznym szablonie (deterministyczne) ------------

def _synthetic() -> dict:
    return {
        "title": "T",
        "views": [
            {
                "sections": [
                    {
                        "type": "grid",
                        "cards": [
                            {"type": "heading", "heading": "A"},
                            {"type": "tile", "entity": "sensor.rachunek_za_prad_brak"},
                        ],
                    },
                    {
                        "type": "grid",
                        "cards": [
                            {"type": "heading", "heading": "B"},
                            {"type": "markdown", "content": "bez encji"},
                            {
                                "type": "custom:apexcharts-card",
                                "series": [
                                    {"entity": "sensor.rachunek_za_prad_jest"},
                                    {"entity": "sensor.rachunek_za_prad_brak"},
                                ],
                            },
                            {
                                "type": "entities",
                                "entities": [
                                    "sensor.rachunek_za_prad_brak",
                                    {"entity": "sensor.rachunek_za_prad_jest", "name": "ok"},
                                ],
                            },
                            {
                                "type": "entities",
                                "entities": [{"entity": "sensor.rachunek_za_prad_brak"}],
                            },
                        ],
                    },
                ]
            }
        ],
    }


def _resolve_synthetic(entity_id: str) -> str | None:
    return None if entity_id.endswith("_brak") else "sensor.real_" + entity_id.rsplit("_", 1)[1]


def test_synthetic_heading_only_section_removed():
    build = build_dashboard(_synthetic(), _resolve_synthetic)
    sections = build.config["views"][0]["sections"]
    assert len(sections) == 1
    assert sections[0]["cards"][0]["heading"] == "B"


def test_synthetic_series_and_rows_pruned_partially():
    build = build_dashboard(_synthetic(), _resolve_synthetic)
    cards = build.config["views"][0]["sections"][0]["cards"]
    types = [c["type"] for c in cards]
    # card z jedyną brakującą encją znika, pozostałe zostają
    assert types == ["heading", "markdown", "custom:apexcharts-card", "entities"]
    apex = cards[2]
    assert apex["series"] == [{"entity": "sensor.real_jest"}]
    rows = cards[3]["entities"]
    assert rows == [{"entity": "sensor.real_jest", "name": "ok"}]
    assert build.missing == ("sensor.rachunek_za_prad_brak",)


def test_synthetic_all_missing_returns_empty_views_not_crash():
    build = build_dashboard(_synthetic(), lambda e: None)
    assert build.config["views"][0]["sections"] == [
        {"type": "grid", "cards": [{"type": "heading", "heading": "B"}, {"type": "markdown", "content": "bez encji"}]}
    ]
