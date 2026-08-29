"""
tests/unit/test_desktop_skill_router.py
------------------------------------------
Guardarraíl contra el bug de "assets.crear_ticket_operador" creando tickets
por preguntas de solo lectura: la descripción que ve el clasificador LLM se
genera desde app/skills/catalogue/*.json (una sola fuente de verdad). Si un
skill_id se añade a DesktopSkillRouter sin su fichero de catálogo, el
clasificador se queda sin poder elegirlo — este test lo detecta en CI en vez
de descubrirlo en producción como la vez anterior.
"""

from __future__ import annotations

from desktop.runtime.capabilities import PermissionLevel
from desktop.runtime.skill_router import DesktopSkillRouter


def test_every_permission_skill_has_a_catalogue_entry():
    router = DesktopSkillRouter()
    catalogue_ids = set(router.catalogue.ids())
    missing = [skill_id for skill_id in router._SKILL_PERMISSION if skill_id not in catalogue_ids]
    assert not missing, f"Skills sin ficha en app/skills/catalogue/: {missing}"


def test_catalogue_descriptions_are_not_empty():
    router = DesktopSkillRouter()
    empty = [skill.skill_id for skill in router.catalogue.all() if not skill.description.strip()]
    assert not empty, f"Skills con descripcion vacia (el LLM no sabria cuando usarlos): {empty}"


def test_as_prompt_options_includes_every_skill_id():
    router = DesktopSkillRouter()
    rendered = router.catalogue.as_prompt_options()
    missing = [skill_id for skill_id in router._SKILL_PERMISSION if f'"{skill_id}"' not in rendered]
    assert not missing, f"Skills que no aparecen en el prompt generado: {missing}"


def test_ticket_creation_skills_require_operate_permission():
    """Regresion: PEPO creo un ticket real en Assets como respuesta a una
    pregunta de "que permisos tienes" (pregunta sobre PEPO, no una orden).
    assets.crear_ticket_operador estaba en ASSIST — el mismo nivel que
    'general.respuesta' o una consulta de solo lectura — sin exigir
    confirmacion antes de escribir en un sistema externo. Debe estar al
    mismo nivel que mouse_speed/system_task (OPERATE), que si la piden.
    """
    router = DesktopSkillRouter()
    for skill_id in ("assets.crear_ticket_operador", "jira.crear_ticket"):
        resolution = router._build_resolution(skill_id, 0.9, "test", {})
        assert resolution.permission_level >= int(PermissionLevel.OPERATE), (
            f"{skill_id} deberia exigir OPERATE (crea algo real en un sistema externo)"
        )
        assert resolution.needs_confirmation is True, (
            f"{skill_id} deberia marcar needs_confirmation=True"
        )
