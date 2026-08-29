"""tests/unit/test_skill_router_campaign_qualify.py

Tests unitarios para la heurística nueva de campaign.qualify — debe ganar
a sales.prospecting cuando el mensaje habla de "cualificar"/"campaña"
para negocios, y no debe dispararse con una búsqueda genérica de Sales.
"""

from __future__ import annotations

from desktop.runtime.skill_router import DesktopSkillRouter


def _router() -> DesktopSkillRouter:
    return DesktopSkillRouter()


def test_cualificar_peluquerias_routes_to_campaign_qualify():
    result = _router().resolve("quiero cualificar peluquerías en Zaragoza a 12km")

    assert result.skill_id == "campaign.qualify"


def test_revisar_hoy_routes_to_campaign_qualify():
    result = _router().resolve("revisar hoy salones de belleza en Madrid")

    assert result.skill_id == "campaign.qualify"


def test_generic_search_still_routes_to_sales_prospecting():
    result = _router().resolve("busca asesorías fiscales en Toledo")

    assert result.skill_id == "sales.prospecting"


def test_campaign_qualify_is_observe_permission():
    from desktop.runtime.capabilities import PermissionLevel

    result = _router().resolve("cualificar talleres mecánicos en Zaragoza")

    assert result.permission_level == int(PermissionLevel.OBSERVE)
    assert result.needs_confirmation is False
