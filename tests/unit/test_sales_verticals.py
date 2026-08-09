"""Tests for the BBDD-backed sales verticals — resolucion por aliases, fallback
custom, scoring configurable y CRUD. Sustituye el hardcoding que antes vivia en
if/elif de Python (models.py, service.py, extractors.py, google_places.py).
"""

from __future__ import annotations

import pytest

from nexus.prospecting.sales_verticals import (
    DuplicateVerticalError,
    ProtectedVerticalError,
    SalesVerticalsRepository,
    VerticalNotFoundError,
)


@pytest.fixture
def verticals(tmp_path) -> SalesVerticalsRepository:
    return SalesVerticalsRepository(tmp_path / "prospecting")


# ── Seed ───────────────────────────────────────────────────────────────────

def test_seed_creates_the_eight_default_verticals(verticals):
    slugs = {v.slug for v in verticals.list_all()}
    assert slugs == {
        "asesoria", "inmobiliaria", "public_administration", "restaurants",
        "salud", "zapaterias", "talleres", "custom",
    }
    custom = verticals.get("custom")
    assert custom.is_fallback is True
    assert custom.nombre == "Otros"


def test_seed_is_idempotent_across_repository_instances(tmp_path):
    first = SalesVerticalsRepository(tmp_path / "prospecting")
    first.create(slug="grabaciones", nombre="Estudios de grabacion")
    second = SalesVerticalsRepository(tmp_path / "prospecting")
    slugs = {v.slug for v in second.list_all()}
    assert "grabaciones" in slugs  # no re-seedea sobre datos ya existentes
    assert len(second.list_all()) == 9


# ── Resolucion por lenguaje natural (nombre + aliases) ──────────────────────

def test_resolve_trusts_an_explicit_valid_slug(verticals):
    resolved = verticals.resolve("restaurants")
    assert resolved.slug == "restaurants"


def test_resolve_matches_by_alias_in_free_text(verticals):
    resolved = verticals.resolve(fallback_text="quiero clinicas dentales en Toledo")
    assert resolved.slug == "salud"


def test_resolve_matches_zapaterias_from_natural_language(verticals):
    """La prueba explicita del ticket: 'zapaterias' se resuelve desde BBDD,
    usando sus aliases configurados, sin ningun conocimiento de zapaterias
    hardcodeado en Python.
    """
    resolved = verticals.resolve(
        raw_vertical="",
        fallback_text="búscame zapaterías en Zaragoza, barrio del Actur",
    )
    assert resolved.slug == "zapaterias"


def test_resolve_falls_back_to_custom_when_nothing_matches(verticals):
    resolved = verticals.resolve(fallback_text="quiero academias de baile en Toledo")
    assert resolved.slug == "custom"
    assert resolved.is_fallback is True


def test_resolve_ignores_inactive_verticals(verticals):
    verticals.set_active("zapaterias", False)
    resolved = verticals.resolve(fallback_text="busco zapaterias en Zaragoza")
    assert resolved.slug == "custom"


def test_resolve_finds_a_vertical_created_at_runtime_without_restart(verticals):
    """CRUD desde la UI debe reflejarse en la siguiente resolucion sin cache ni
    reinicio — no hay TTL ni proceso intermedio entre escritura y lectura.
    """
    verticals.create(
        slug="peluquerias",
        nombre="Peluquerias",
        aliases=["peluqueria", "peluquero", "salon de belleza"],
    )
    resolved = verticals.resolve(fallback_text="busco peluquerias en Alicante")
    assert resolved.slug == "peluquerias"


# ── CRUD ─────────────────────────────────────────────────────────────────────

def test_create_duplicate_slug_is_rejected(verticals):
    with pytest.raises(DuplicateVerticalError):
        verticals.create(slug="restaurants", nombre="Otro nombre")


def test_create_duplicate_alias_is_rejected(verticals):
    with pytest.raises(DuplicateVerticalError):
        verticals.create(slug="hosteleria2", nombre="Hosteleria 2", aliases=["gastro"])  # ya usado por restaurants


def test_update_duplicate_alias_is_rejected(verticals):
    verticals.create(slug="cafeterias", nombre="Cafeterias", aliases=["cafeteria"])
    with pytest.raises(DuplicateVerticalError):
        verticals.update("cafeterias", aliases=["gastro"])  # ya usado por restaurants


def test_cannot_delete_the_fallback_vertical(verticals):
    with pytest.raises(ProtectedVerticalError):
        verticals.delete("custom")


def test_cannot_deactivate_the_fallback_vertical(verticals):
    with pytest.raises(ProtectedVerticalError):
        verticals.set_active("custom", False)


def test_delete_a_custom_vertical(verticals):
    verticals.create(slug="gimnasios", nombre="Gimnasios")
    verticals.delete("gimnasios")
    assert verticals.get("gimnasios") is None


def test_update_unknown_vertical_raises(verticals):
    with pytest.raises(VerticalNotFoundError):
        verticals.update("no-existe", nombre="x")


def test_create_new_vertical_activates_immediately_in_list_active(verticals):
    verticals.create(slug="floristerias", nombre="Floristerias", activo=True)
    assert "floristerias" in {v.slug for v in verticals.list_active()}


# ── Scoring configurable (sin if/elif por vertical) ─────────────────────────

def test_scoring_rules_come_from_the_vertical_row_not_from_code(verticals):
    verticals.create(
        slug="veterinarias",
        nombre="Veterinarias",
        aliases=["veterinaria", "veterinario", "clinica veterinaria"],
        scoring_rules={
            "relevance_signals": ["veterinaria", "mascotas", "animales"],
            "reason_relevant": "veterinaria con señales de mascotas",
            "reason_irrelevant": "no parece veterinaria",
        },
    )
    vertical = verticals.get("veterinarias")
    assert vertical.scoring_rules["relevance_signals"] == ["veterinaria", "mascotas", "animales"]
    # zapaterias, en cambio, no tiene relevance_signals propios — usa el
    # fallback generico (relevant=True siempre), igual que antes del refactor.
    zapaterias = verticals.get("zapaterias")
    assert not zapaterias.scoring_rules.get("relevance_signals")


def test_default_tags_include_geography(verticals):
    vertical = verticals.get("restaurants")
    tags = vertical.default_tags("Zaragoza")
    assert "restaurante" in tags
    assert "zaragoza" in tags
