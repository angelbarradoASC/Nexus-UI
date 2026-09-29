"""Catalogo de ayudas/subvenciones reales, persistido en SQLite.

Mismo patron que sales_verticals.py (BBDD, no if/elif por programa) —
reutiliza el mismo SQLiteStore/prospecting.sqlite3, sin infraestructura
nueva. Nace de la decision del usuario de bifurcar la Campaña en dos vias
(IA/OT) explotando ayudas reales a la adopcion de IA y a la transformacion
industrial — ver _classify_grant_fit() en service.py para como se usa este
catalogo durante el enriquecimiento de un lead, y grants_discovery.py para
como se mantiene fresco (una ayuda sembrada a mano hoy caduca sola, mismo
problema que ya vimos con el .env desincronizado del build).

Datos sembrados verificados en vivo (WebSearch, 2026-09-29) — no
inventados: Kit Consulting (Red.es, 10-249 empleados, hasta 24.000€ por
tramos), CDTI (I+D, sin techo de tamaño), Ayudas Aragón PYME Digitalizacion
(regional, cubre IA entre varias areas). PAIP Linea TDI-FEDER (via OT) se
añade en la segunda fase del pivote.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nexus.persistence.prospecting_schema import ensure_prospecting_schema
from nexus.persistence.sqlite_store import SQLiteStore

# activo: se usa de verdad para clasificar leads.
# pendiente_revision: descubierta automaticamente, esperando que el usuario
#   la apruebe antes de que empiece a influir en ningun lead — mismo
#   principio que la cola de revision de leads (nada se activa solo).
# expirado: se detecto que ya no esta vigente — se conserva en el catalogo
#   (trazabilidad) pero deja de usarse para clasificar.
ESTADOS = ("activo", "pendiente_revision", "expirado")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Grant:
    slug: str
    nombre: str
    ambito: str = "estatal"  # "estatal" | "aragon" | ...
    estado: str = "activo"
    min_employees: int | None = None
    max_employees: int | None = None
    sectores_excluidos: list[str] = field(default_factory=list)
    importe_desc: str = ""
    criterios: str = ""
    url: str = ""
    vigente_hasta: str = ""
    fuente: str = "semilla_inicial"
    last_checked_at: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "nombre": self.nombre,
            "ambito": self.ambito,
            "estado": self.estado,
            "min_employees": self.min_employees,
            "max_employees": self.max_employees,
            "sectores_excluidos": list(self.sectores_excluidos),
            "importe_desc": self.importe_desc,
            "criterios": self.criterios,
            "url": self.url,
            "vigente_hasta": self.vigente_hasta,
            "fuente": self.fuente,
            "last_checked_at": self.last_checked_at,
        }

    @staticmethod
    def from_row(row: Any) -> "Grant":
        return Grant(
            slug=row["slug"],
            nombre=row["nombre"],
            ambito=row["ambito"],
            estado=row["estado"],
            min_employees=row["min_employees"],
            max_employees=row["max_employees"],
            sectores_excluidos=json.loads(row["sectores_excluidos_json"] or "[]"),
            importe_desc=row["importe_desc"],
            criterios=row["criterios"],
            url=row["url"],
            vigente_hasta=row["vigente_hasta"],
            fuente=row["fuente"],
            last_checked_at=row["last_checked_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# ── Semilla verificada en vivo (WebSearch, 2026-09-29) ──────────────────────
# criterios: frase corta que el LLM usa como contexto de encaje — no es
# texto legal, es la señal de negocio que distingue esta ayuda de las demas.
_DEFAULT_SEED: list[dict[str, Any]] = [
    {
        "slug": "kit_consulting",
        "nombre": "Kit Consulting",
        "ambito": "estatal",
        "min_employees": 10,
        "max_employees": 249,
        "sectores_excluidos": [],
        "importe_desc": "Bono de asesoramiento 100% subvencionado: 12.000€ (10-49 empleados), 18.000€ (50-99), 24.000€ (100-249).",
        "criterios": (
            "Pyme de 10 a 249 empleados que necesita una hoja de ruta de adopcion de IA "
            "(o ciberseguridad/ventas digitales/procesos/data driven) pero no tiene equipo "
            "tecnico propio para diseñarla — el bono paga consultoria externa, no herramientas."
        ),
        "url": "http://espanadigital.gob.es/en/measure/programa-kit-consulting",
        "vigente_hasta": "",
    },
    {
        "slug": "cdti_innovacion",
        "nombre": "CDTI — proyectos de innovacion/I+D",
        "ambito": "estatal",
        "min_employees": None,
        "max_employees": None,
        "sectores_excluidos": [],
        "importe_desc": "Financiacion de proyecto (variable segun convocatoria, no bono fijo).",
        "criterios": (
            "Empresa con un proyecto tecnico concreto de innovacion/I+D relacionado con IA "
            "(no adopcion generica) — evidencia de intencion real de desarrollo, no solo de "
            "modernizacion basica. Sin techo de tamaño, mejor encaje en empresas ya maduras "
            "tecnicamente que quieren dar un salto, no en las que parten de cero."
        ),
        "url": "",
        "vigente_hasta": "",
    },
    {
        "slug": "aragon_pyme_digitalizacion",
        "nombre": "Ayudas Aragón PYME Digitalización",
        "ambito": "aragon",
        "min_employees": None,
        "max_employees": 249,
        "sectores_excluidos": [],
        "importe_desc": "Hasta 70% (micro) / 50% (pyme) del presupuesto — hardware, software y consultoria (max 20%).",
        "criterios": (
            "Pyme con actividad en Zaragoza o Huesca que quiere invertir en digitalizacion "
            "(IA, ciberseguridad, cloud, IoT, ML...) — presupuesto regional limitado "
            "(695.000€ total), mejor encaje como alternativa/complemento a Kit Consulting "
            "cuando la empresa esta fuera de rango de empleados o quiere tambien financiar "
            "hardware/software, no solo consultoria."
        ),
        "url": "https://www.aragon.es/-/programa-ayudas-industria-pyme",
        "vigente_hasta": "",
    },
]


class GrantsRepository:
    """Lectura/escritura del catalogo de ayudas. Sin UI de gestion completa
    en esta primera entrega (a diferencia de sales_verticals, que si tiene
    CRUD desde el CRM) — las escrituras las hace GrantsDiscoveryService."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        db_path = Path(os.environ.get("NEXUS_PROSPECTING_DB_PATH") or (self._data_dir / "prospecting.sqlite3"))
        self._store = SQLiteStore(db_path)
        ensure_prospecting_schema(self._store)
        self._seed_defaults_if_empty()

    def _seed_defaults_if_empty(self) -> None:
        with self._store.transaction() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM grants_catalog").fetchone()
            if row["c"]:
                return
            now = _now_iso()
            for seed in _DEFAULT_SEED:
                conn.execute(
                    """
                    INSERT INTO grants_catalog(
                        slug, nombre, ambito, estado, min_employees, max_employees,
                        sectores_excluidos_json, importe_desc, criterios, url,
                        vigente_hasta, fuente, last_checked_at, created_at, updated_at
                    ) VALUES(?, ?, ?, 'activo', ?, ?, ?, ?, ?, ?, ?, 'semilla_inicial', ?, ?, ?)
                    """,
                    (
                        seed["slug"], seed["nombre"], seed["ambito"],
                        seed["min_employees"], seed["max_employees"],
                        json.dumps(seed["sectores_excluidos"], ensure_ascii=False),
                        seed["importe_desc"], seed["criterios"], seed["url"],
                        seed["vigente_hasta"], now, now, now,
                    ),
                )

    # ── Lectura ──────────────────────────────────────────────────────────────

    def list_all(self) -> list[Grant]:
        with self._store.connect() as conn:
            rows = conn.execute("SELECT * FROM grants_catalog ORDER BY ambito ASC, nombre ASC").fetchall()
        return [Grant.from_row(row) for row in rows]

    def list_active(self, *, ambito: str | list[str] | None = None) -> list[Grant]:
        """ambito=None devuelve todas las de estado='activo'; un slug o lista
        de slugs de ambito filtra (p.ej. ambito=["estatal", "aragon"] para la
        via IA, ambito="aragon" para la via OT — PAIP TDI-FEDER es solo
        regional). Nunca incluye pendiente_revision/expirado — esas no deben
        influir en la clasificacion de ningun lead."""
        active = [g for g in self.list_all() if g.estado == "activo"]
        if ambito is None:
            return active
        wanted = {ambito} if isinstance(ambito, str) else set(ambito)
        return [g for g in active if g.ambito in wanted]

    def list_pending_review(self) -> list[Grant]:
        """Ayudas descubiertas automaticamente esperando aprobacion humana."""
        return [g for g in self.list_all() if g.estado == "pendiente_revision"]

    def get(self, slug: str) -> Grant | None:
        slug = (slug or "").strip()
        if not slug:
            return None
        with self._store.connect() as conn:
            row = conn.execute("SELECT * FROM grants_catalog WHERE slug = ?", (slug,)).fetchone()
        return Grant.from_row(row) if row else None

    def find_by_name(self, nombre: str) -> Grant | None:
        """Match aproximado por nombre normalizado — usado por el
        descubrimiento para no duplicar una ayuda ya en catalogo bajo un
        nombre ligeramente distinto (ej. 'Kit Consulting' vs 'Programa Kit
        Consulting')."""
        from nexus.utils.text import normalize_text

        target = normalize_text(nombre)
        if not target:
            return None
        for grant in self.list_all():
            existing = normalize_text(grant.nombre)
            if existing == target or existing in target or target in existing:
                return grant
        return None

    # ── Escritura (usada por GrantsDiscoveryService) ────────────────────────

    def upsert_discovered(
        self,
        *,
        slug: str,
        nombre: str,
        ambito: str,
        min_employees: int | None = None,
        max_employees: int | None = None,
        importe_desc: str = "",
        criterios: str = "",
        url: str = "",
        vigente_hasta: str = "",
    ) -> Grant:
        """Inserta una ayuda nueva descubierta automaticamente — SIEMPRE en
        estado pendiente_revision, nunca activa directamente (misma logica
        que la cola de revision de leads: lo que descubre el sistema solo
        no se usa hasta que una persona lo confirma)."""
        now = _now_iso()
        with self._store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO grants_catalog(
                    slug, nombre, ambito, estado, min_employees, max_employees,
                    sectores_excluidos_json, importe_desc, criterios, url,
                    vigente_hasta, fuente, last_checked_at, created_at, updated_at
                ) VALUES(?, ?, ?, 'pendiente_revision', ?, ?, '[]', ?, ?, ?, ?, 'descubrimiento_automatico', ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    last_checked_at = excluded.last_checked_at,
                    updated_at = excluded.updated_at
                """,
                (
                    slug, nombre, ambito, min_employees, max_employees,
                    importe_desc, criterios, url, vigente_hasta, now, now, now,
                ),
            )
        return self.get(slug)  # type: ignore[return-value]

    def delete(self, slug: str) -> None:
        """Borra una ayuda pendiente_revision que el usuario ha rechazado —
        a diferencia de marcarla 'expirado' (que implica que fue real en
        algun momento), un rechazo de descubrimiento simplemente no existia."""
        with self._store.transaction() as conn:
            conn.execute("DELETE FROM grants_catalog WHERE slug = ?", (slug,))

    def set_estado(self, slug: str, estado: str) -> Grant | None:
        if estado not in ESTADOS:
            raise ValueError(f"estado invalido: {estado} (debe ser uno de {ESTADOS})")
        now = _now_iso()
        with self._store.transaction() as conn:
            conn.execute(
                "UPDATE grants_catalog SET estado = ?, updated_at = ? WHERE slug = ?",
                (estado, now, slug),
            )
        return self.get(slug)

    def mark_checked(self, slug: str, *, vigente_hasta: str | None = None) -> None:
        """Refresca last_checked_at tras verificar vigencia — se llama tanto
        si sigue activa como si se acaba de marcar expirada, para saber
        cuando fue la ultima comprobacion real."""
        now = _now_iso()
        with self._store.transaction() as conn:
            if vigente_hasta is not None:
                conn.execute(
                    "UPDATE grants_catalog SET last_checked_at = ?, vigente_hasta = ?, updated_at = ? WHERE slug = ?",
                    (now, vigente_hasta, now, slug),
                )
            else:
                conn.execute(
                    "UPDATE grants_catalog SET last_checked_at = ?, updated_at = ? WHERE slug = ?",
                    (now, now, slug),
                )
