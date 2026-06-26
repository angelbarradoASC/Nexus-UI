"""
tests/unit/test_skills_registry.py
------------------------------------
Tests unitarios para SkillsRegistry — validación, carga, duplicados y errores.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_skill(directory: Path, filename: str, data: dict) -> Path:
    """Escribe un fichero JSON de skill en el directorio indicado."""
    p = directory / filename
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


_VALID_SKILL = {
    "id": "test.skill",
    "name": "Test Skill",
    "description": "Un skill de prueba",
    "execution": {"type": "agent", "target": "GenerationAgent"},
    "llm": {"model": "local", "temperature": 0.7},
    "triggers": ["test", "prueba"],
    "examples": ["ejemplo de activación"],
    "inputs": {
        "query": {"type": "string", "required": True, "description": "Consulta del usuario"},
    },
    "outputs": {
        "response": {"type": "string", "description": "Respuesta generada"},
    },
}


# ── Tests de _validate_skill ──────────────────────────────────────────────────

class TestValidateSkill:
    """Tests para la función de validación interna _validate_skill."""

    def test_skill_valido_no_lanza(self):
        from skills.skills_registry import _validate_skill
        _validate_skill(_VALID_SKILL.copy(), "test.json")  # No debe lanzar

    def test_campo_obligatorio_ausente_lanza(self):
        from skills.skills_registry import SkillValidationError, _validate_skill
        data = {k: v for k, v in _VALID_SKILL.items() if k != "name"}
        with pytest.raises(SkillValidationError, match="name"):
            _validate_skill(data, "test.json")

    def test_multiples_campos_ausentes_mencionados(self):
        from skills.skills_registry import SkillValidationError, _validate_skill
        data = {"id": "x"}  # Faltan name, description, execution, llm
        with pytest.raises(SkillValidationError) as exc:
            _validate_skill(data, "test.json")
        msg = str(exc.value)
        assert "name" in msg
        assert "description" in msg

    def test_id_vacio_lanza(self):
        from skills.skills_registry import SkillValidationError, _validate_skill
        data = {**_VALID_SKILL, "id": ""}
        with pytest.raises(SkillValidationError, match="id"):
            _validate_skill(data, "test.json")

    def test_id_solo_espacios_lanza(self):
        from skills.skills_registry import SkillValidationError, _validate_skill
        data = {**_VALID_SKILL, "id": "   "}
        with pytest.raises(SkillValidationError, match="id"):
            _validate_skill(data, "test.json")

    def test_tipo_incorrecto_en_triggers_lanza(self):
        from skills.skills_registry import SkillValidationError, _validate_skill
        data = {**_VALID_SKILL, "triggers": "no-es-lista"}
        with pytest.raises(SkillValidationError, match="triggers"):
            _validate_skill(data, "test.json")

    def test_tipo_incorrecto_en_execution_lanza(self):
        from skills.skills_registry import SkillValidationError, _validate_skill
        data = {**_VALID_SKILL, "execution": "string-invalido"}
        with pytest.raises(SkillValidationError, match="execution"):
            _validate_skill(data, "test.json")

    def test_tipo_incorrecto_en_llm_lanza(self):
        from skills.skills_registry import SkillValidationError, _validate_skill
        data = {**_VALID_SKILL, "llm": 42}
        with pytest.raises(SkillValidationError, match="llm"):
            _validate_skill(data, "test.json")

    def test_mensaje_incluye_nombre_fichero(self):
        from skills.skills_registry import SkillValidationError, _validate_skill
        data = {"id": "x"}  # Faltan campos
        with pytest.raises(SkillValidationError) as exc:
            _validate_skill(data, "mi_fichero.json")
        assert "mi_fichero.json" in str(exc.value)

    def test_campos_opcionales_ausentes_no_lanza(self):
        """triggers, examples, inputs, outputs son opcionales."""
        from skills.skills_registry import _validate_skill
        data = {
            "id": "minimal.skill",
            "name": "Minimal",
            "description": "Sin campos opcionales",
            "execution": {},
            "llm": {},
        }
        _validate_skill(data, "minimal.json")  # No debe lanzar


# ── Tests de SkillDefinition ──────────────────────────────────────────────────

class TestSkillDefinition:
    """Tests para la clase SkillDefinition."""

    def test_atributos_basicos(self):
        from skills.skills_registry import SkillDefinition
        skill = SkillDefinition(_VALID_SKILL)
        assert skill.id == "test.skill"
        assert skill.name == "Test Skill"
        assert skill.description == "Un skill de prueba"

    def test_atributos_opcionales_con_defaults(self):
        from skills.skills_registry import SkillDefinition
        minimal = {
            "id": "minimal",
            "name": "Min",
            "description": "desc",
            "execution": {},
            "llm": {},
        }
        skill = SkillDefinition(minimal)
        assert skill.triggers == []
        assert skill.examples == []
        assert skill.inputs == {}
        assert skill.outputs == {}
        assert skill.cost == {}

    def test_to_dict_devuelve_raw(self):
        from skills.skills_registry import SkillDefinition
        skill = SkillDefinition(_VALID_SKILL)
        assert skill.to_dict() == _VALID_SKILL

    def test_to_prompt_text_contiene_id(self):
        from skills.skills_registry import SkillDefinition
        skill = SkillDefinition(_VALID_SKILL)
        text = skill.to_prompt_text()
        assert "test.skill" in text
        assert "Test Skill" in text
        assert "Un skill de prueba" in text

    def test_to_prompt_text_lista_parametros_obligatorios(self):
        from skills.skills_registry import SkillDefinition
        skill = SkillDefinition(_VALID_SKILL)
        text = skill.to_prompt_text()
        assert "query" in text  # Es el campo obligatorio en _VALID_SKILL.inputs

    def test_to_prompt_text_incluye_ejemplos(self):
        from skills.skills_registry import SkillDefinition
        skill = SkillDefinition(_VALID_SKILL)
        text = skill.to_prompt_text()
        assert "ejemplo de activación" in text

    def test_repr(self):
        from skills.skills_registry import SkillDefinition
        skill = SkillDefinition(_VALID_SKILL)
        assert "test.skill" in repr(skill)


# ── Tests de SkillsRegistry ───────────────────────────────────────────────────

class TestSkillsRegistry:
    """Tests para SkillsRegistry — carga desde directorio temporal."""

    def test_carga_skill_valido(self, tmp_path):
        from skills.skills_registry import SkillsRegistry
        _write_skill(tmp_path, "skill1.json", _VALID_SKILL)
        registry = SkillsRegistry(catalogue_dir=tmp_path)
        assert len(registry) == 1
        assert registry.get("test.skill") is not None

    def test_get_devuelve_none_si_no_existe(self, tmp_path):
        from skills.skills_registry import SkillsRegistry
        registry = SkillsRegistry(catalogue_dir=tmp_path)
        assert registry.get("no.existe") is None

    def test_all_devuelve_lista(self, tmp_path):
        from skills.skills_registry import SkillsRegistry
        _write_skill(tmp_path, "skill1.json", _VALID_SKILL)
        registry = SkillsRegistry(catalogue_dir=tmp_path)
        skills = registry.all()
        assert isinstance(skills, list)
        assert len(skills) == 1

    def test_ids_devuelve_lista_de_ids(self, tmp_path):
        from skills.skills_registry import SkillsRegistry
        _write_skill(tmp_path, "skill1.json", _VALID_SKILL)
        registry = SkillsRegistry(catalogue_dir=tmp_path)
        assert "test.skill" in registry.ids()

    def test_multiples_skills_cargados(self, tmp_path):
        from skills.skills_registry import SkillsRegistry
        skill2 = {**_VALID_SKILL, "id": "test.skill2", "name": "Skill 2"}
        skill3 = {**_VALID_SKILL, "id": "test.skill3", "name": "Skill 3"}
        _write_skill(tmp_path, "a.json", _VALID_SKILL)
        _write_skill(tmp_path, "b.json", skill2)
        _write_skill(tmp_path, "c.json", skill3)
        registry = SkillsRegistry(catalogue_dir=tmp_path)
        assert len(registry) == 3

    def test_json_invalido_no_rompe_carga(self, tmp_path):
        """Un JSON malformado debe acumularse como error, no romper la carga."""
        from skills.skills_registry import SkillsRegistry
        bad = tmp_path / "bad.json"
        bad.write_text("{invalid json", encoding="utf-8")
        _write_skill(tmp_path, "good.json", _VALID_SKILL)
        registry = SkillsRegistry(catalogue_dir=tmp_path)
        assert len(registry) == 1          # El skill válido sí se carga
        assert len(registry.load_errors()) == 1  # El error se acumula

    def test_skill_invalido_acumula_error(self, tmp_path):
        """Un skill sin campos obligatorios se descarta y acumula error."""
        from skills.skills_registry import SkillsRegistry
        bad_skill = {"id": "incomplete"}  # Falta name, description, execution, llm
        _write_skill(tmp_path, "bad_skill.json", bad_skill)
        _write_skill(tmp_path, "good_skill.json", _VALID_SKILL)
        registry = SkillsRegistry(catalogue_dir=tmp_path)
        assert len(registry) == 1
        assert len(registry.load_errors()) >= 1

    def test_id_duplicado_ignora_segundo(self, tmp_path):
        """Si dos ficheros tienen el mismo id, el segundo se ignora."""
        from skills.skills_registry import SkillsRegistry
        skill_dup = {**_VALID_SKILL, "name": "Duplicado"}
        _write_skill(tmp_path, "a.json", _VALID_SKILL)
        _write_skill(tmp_path, "b.json", skill_dup)
        registry = SkillsRegistry(catalogue_dir=tmp_path)
        assert len(registry) == 1
        assert registry.get("test.skill").name == "Test Skill"  # El primero prevalece
        assert len(registry.load_errors()) == 1  # Duplicado reportado como error

    def test_directorio_inexistente_no_rompe(self, tmp_path):
        """Si el directorio no existe, el registry arranca vacío sin excepción."""
        from skills.skills_registry import SkillsRegistry
        non_existent = tmp_path / "no_existe"
        registry = SkillsRegistry(catalogue_dir=non_existent)
        assert len(registry) == 0

    def test_load_errors_devuelve_lista(self, tmp_path):
        from skills.skills_registry import SkillsRegistry
        registry = SkillsRegistry(catalogue_dir=tmp_path)
        assert isinstance(registry.load_errors(), list)

    def test_reload_recarga_desde_disco(self, tmp_path):
        """reload() recarga el catálogo — detecta ficheros añadidos después de la carga inicial."""
        from skills.skills_registry import SkillsRegistry
        registry = SkillsRegistry(catalogue_dir=tmp_path)
        assert len(registry) == 0

        _write_skill(tmp_path, "new_skill.json", _VALID_SKILL)
        registry.reload()
        assert len(registry) == 1

    def test_catalogue_as_prompt_text(self, tmp_path):
        """catalogue_as_prompt_text() devuelve texto con los skills formateados."""
        from skills.skills_registry import SkillsRegistry
        _write_skill(tmp_path, "skill1.json", _VALID_SKILL)
        registry = SkillsRegistry(catalogue_dir=tmp_path)
        text = registry.catalogue_as_prompt_text()
        assert "test.skill" in text
        assert "Test Skill" in text

    def test_catalogue_vacio_devuelve_string(self, tmp_path):
        from skills.skills_registry import SkillsRegistry
        registry = SkillsRegistry(catalogue_dir=tmp_path)
        text = registry.catalogue_as_prompt_text()
        assert isinstance(text, str)

    def test_repr(self, tmp_path):
        from skills.skills_registry import SkillsRegistry
        _write_skill(tmp_path, "skill1.json", _VALID_SKILL)
        registry = SkillsRegistry(catalogue_dir=tmp_path)
        assert "test.skill" in repr(registry)


# ── Tests del singleton get_registry ─────────────────────────────────────────

class TestGetRegistry:
    """Tests para la instancia global get_registry()."""

    def test_get_registry_devuelve_instancia(self):
        from skills.skills_registry import SkillsRegistry, get_registry
        registry = get_registry()
        assert isinstance(registry, SkillsRegistry)

    def test_get_registry_singleton(self):
        from skills.skills_registry import get_registry
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2
