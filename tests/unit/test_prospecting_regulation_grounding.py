"""tests/unit/test_prospecting_regulation_grounding.py

_ground_regulation / _regulations_context_block (app/nexus/api/routes/
prospecting.py) — pedido explicito del usuario: un criterio indirecto
("empresas afectadas por la normativa NIS2") debe traducirse a una
busqueda real con los sectores REALES de la normativa, nunca al nombre
literal de la ley (que ninguna empresa usa para describirse online) ni a
una lista de sectores inventada por el LLM.
"""

from __future__ import annotations

from types import SimpleNamespace

from nexus.api.routes.prospecting import _ground_regulation, _regulations_context_block
from nexus.prospecting.regulations import RegulationsRepository


def _prospecting_with_regulations(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(regulations=RegulationsRepository(tmp_path))


def test_ground_regulation_replaces_target_description_with_real_sectors(tmp_path):
    prospecting = _prospecting_with_regulations(tmp_path)
    brief = {
        "target_description": "empresas afectadas por la normativa NIS2",
        "regulation_slug": "nis2",
        "city": "Zaragoza",
    }

    grounded = _ground_regulation(brief, prospecting)

    assert "NIS2" not in grounded["target_description"]
    assert "energía" in grounded["target_description"]
    assert grounded["regulation_slug"] == "nis2"


def test_ground_regulation_discards_hallucinated_slug(tmp_path):
    prospecting = _prospecting_with_regulations(tmp_path)
    brief = {
        "target_description": "empresas afectadas por normativa inventada",
        "regulation_slug": "normativa_que_no_existe",
    }

    grounded = _ground_regulation(brief, prospecting)

    assert "regulation_slug" not in grounded
    assert grounded["target_description"] == "empresas afectadas por normativa inventada"


def test_ground_regulation_is_noop_without_slug(tmp_path):
    prospecting = _prospecting_with_regulations(tmp_path)
    brief = {"target_description": "peluquerías en Zaragoza"}

    grounded = _ground_regulation(brief, prospecting)

    assert grounded == {"target_description": "peluquerías en Zaragoza"}


def test_ground_regulation_skips_inactive_regulation(tmp_path):
    prospecting = _prospecting_with_regulations(tmp_path)
    prospecting.regulations.set_activo("nis2", False)
    brief = {"target_description": "empresas afectadas por NIS2", "regulation_slug": "nis2"}

    grounded = _ground_regulation(brief, prospecting)

    assert "regulation_slug" not in grounded
    assert grounded["target_description"] == "empresas afectadas por NIS2"


def test_regulations_context_block_lists_real_sectors_not_just_the_name(tmp_path):
    prospecting = _prospecting_with_regulations(tmp_path)

    block = _regulations_context_block(prospecting)

    assert "slug=nis2" in block
    assert "energía" in block
    assert "regulation_slug" in block  # instruye al LLM a usar el campo, no copiar el nombre


def test_regulations_context_block_empty_when_no_regulations_configured(tmp_path):
    prospecting = _prospecting_with_regulations(tmp_path)
    for reg in prospecting.regulations.list_all():
        prospecting.regulations.delete(reg.slug)

    assert _regulations_context_block(prospecting) == ""
