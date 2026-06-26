# app/skills/skills_registry.py
"""
Skills Registry — carga y gestiona el catálogo de skills.

El catálogo vive en app/skills/catalogue/*.json.
Cada fichero define un skill con su id, descripción, triggers,
parámetros de entrada/salida y configuración de ejecución.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from loguru import logger

# Ruta al directorio de catálogo (relativa a este fichero)
CATALOGUE_DIR = Path(__file__).parent / "catalogue"

# Campos obligatorios en el JSON de un skill
_REQUIRED_FIELDS: list[str] = ["id", "name", "description", "execution", "llm"]

# Tipos esperados por campo
_FIELD_TYPES: dict[str, type] = {
    "id":          str,
    "name":        str,
    "description": str,
    "execution":   dict,
    "llm":         dict,
    "inputs":      dict,
    "outputs":     dict,
    "triggers":    list,
    "examples":    list,
    "cost":        dict,
}


class SkillValidationError(ValueError):
    """Error de validación de un skill JSON."""
    pass


def _validate_skill(data: dict, source: str) -> None:
    """
    Valida que el dict de un skill tenga los campos obligatorios y los tipos correctos.
    Lanza SkillValidationError con mensaje claro si falla.

    Args:
        data:   Diccionario cargado desde el JSON.
        source: Nombre del fichero (para mensajes de error).
    """
    # Campos obligatorios presentes
    missing = [f for f in _REQUIRED_FIELDS if f not in data]
    if missing:
        raise SkillValidationError(
            f"[{source}] Campos obligatorios ausentes: {missing}"
        )

    # id no puede ser vacío
    if not isinstance(data["id"], str) or not data["id"].strip():
        raise SkillValidationError(
            f"[{source}] El campo 'id' debe ser un string no vacío"
        )

    # Tipos correctos para los campos presentes
    type_errors = []
    for field, expected_type in _FIELD_TYPES.items():
        if field in data and not isinstance(data[field], expected_type):
            type_errors.append(
                f"  '{field}': se esperaba {expected_type.__name__}, "
                f"se recibió {type(data[field]).__name__}"
            )
    if type_errors:
        raise SkillValidationError(
            f"[{source}] Errores de tipo:\n" + "\n".join(type_errors)
        )


class SkillDefinition:
    """Representa un skill cargado desde el catálogo."""

    def __init__(self, data: dict):
        self.id: str = data["id"]
        self.name: str = data["name"]
        self.description: str = data["description"]
        self.execution: dict = data.get("execution", {})
        self.llm: dict = data.get("llm", {})
        self.cost: dict = data.get("cost", {})
        self.inputs: dict = data.get("inputs", {})
        self.outputs: dict = data.get("outputs", {})
        self.triggers: list[str] = data.get("triggers", [])
        self.examples: list[str] = data.get("examples", [])
        self._raw = data

    def to_prompt_text(self) -> str:
        """
        Devuelve una representación en texto del skill para incluir
        en el system prompt del L0.
        """
        lines = [
            f"SKILL: {self.id}",
            f"Nombre: {self.name}",
            f"Descripción: {self.description}",
        ]
        if self.inputs:
            req = [k for k, v in self.inputs.items() if v.get("required")]
            opt = [k for k, v in self.inputs.items() if not v.get("required")]
            if req:
                lines.append(f"Parámetros obligatorios: {', '.join(req)}")
            if opt:
                lines.append(f"Parámetros opcionales: {', '.join(opt)}")
        if self.examples:
            lines.append(f"Ejemplos de activación: {' | '.join(self.examples[:3])}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return self._raw

    def __repr__(self):
        return f"<SkillDefinition id={self.id!r}>"


class SkillsRegistry:
    """
    Carga todos los skills del catálogo y provee acceso por id,
    búsqueda por texto y listado completo.

    Uso:
        registry = SkillsRegistry()
        skill = registry.get("fichaje.entrada")
        todos = registry.all()
        texto = registry.catalogue_as_prompt_text()
    """

    def __init__(self, catalogue_dir: Optional[Path] = None):
        self._dir = catalogue_dir or CATALOGUE_DIR
        self._skills: dict[str, SkillDefinition] = {}
        self._errors: list[str] = []   # errores de carga acumulados
        self._load()

    def _load(self) -> None:
        """Carga todos los ficheros JSON del directorio de catálogo."""
        if not self._dir.exists():
            logger.warning("SkillsRegistry: directorio de catálogo no encontrado: {}", self._dir)
            return

        loaded = 0
        for path in sorted(self._dir.glob("*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)

                # Validar estructura antes de construir el objeto
                _validate_skill(data, path.name)

                skill_id = data["id"]

                # Detectar duplicados
                if skill_id in self._skills:
                    msg = (
                        f"SkillsRegistry: ID duplicado '{skill_id}' en {path.name} "
                        f"(ya registrado). El segundo fichero se ignora."
                    )
                    logger.error(msg)
                    self._errors.append(msg)
                    continue

                skill = SkillDefinition(data)
                self._skills[skill_id] = skill
                loaded += 1
                logger.debug("SkillsRegistry: cargado '{}'", skill_id)

            except json.JSONDecodeError as e:
                msg = f"SkillsRegistry: JSON inválido en {path.name}: {e}"
                logger.error(msg)
                self._errors.append(msg)
            except SkillValidationError as e:
                logger.error("SkillsRegistry: validación fallida — {}", e)
                self._errors.append(str(e))
            except Exception as e:
                msg = f"SkillsRegistry: error inesperado cargando {path.name}: {e}"
                logger.error(msg)
                self._errors.append(msg)

        logger.info(
            "SkillsRegistry: {} skills cargados desde {} | {} errores",
            loaded, self._dir, len(self._errors),
        )

    def get(self, skill_id: str) -> Optional[SkillDefinition]:
        """Devuelve un skill por su id o None si no existe."""
        return self._skills.get(skill_id)

    def all(self) -> list[SkillDefinition]:
        """Devuelve todos los skills cargados."""
        return list(self._skills.values())

    def ids(self) -> list[str]:
        """Devuelve los ids de todos los skills."""
        return list(self._skills.keys())

    def load_errors(self) -> list[str]:
        """Devuelve los errores acumulados durante la carga."""
        return list(self._errors)

    def catalogue_as_prompt_text(self) -> str:
        """
        Devuelve el catálogo completo formateado como texto para
        incluirlo en el system prompt del L0.
        """
        blocks = [skill.to_prompt_text() for skill in self._skills.values()]
        return "\n\n".join(blocks)

    def reload(self) -> None:
        """Recarga el catálogo desde disco (útil en desarrollo)."""
        self._skills.clear()
        self._errors.clear()
        self._load()

    def __len__(self):
        return len(self._skills)

    def __repr__(self):
        return f"<SkillsRegistry skills={list(self._skills.keys())}>"


# ---------------------------------------------------------------------------
# Instancia global
# ---------------------------------------------------------------------------

_registry: Optional[SkillsRegistry] = None


def get_registry() -> SkillsRegistry:
    """Devuelve (o crea) la instancia global del registry."""
    global _registry
    if _registry is None:
        _registry = SkillsRegistry()
    return _registry
