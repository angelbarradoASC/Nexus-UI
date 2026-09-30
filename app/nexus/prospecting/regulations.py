"""Catalogo de normativas/obligaciones de cumplimiento -> sectores reales
que cubren, persistido en SQLite.

Mismo patron que grants.py/sales_verticals.py (BBDD, no if/elif por
normativa) — reutiliza el mismo SQLiteStore/prospecting.sqlite3.

Nace de un hueco real detectado por el usuario: pedir prospeccion por un
criterio indirecto (ej. "empresas afectadas por la normativa NIS2") hacia
que target_description saliera como el nombre literal de la ley — una
frase que ninguna empresa usa para describirse online, asi que la
busqueda no encontraba nada util. Este catalogo da al LLM de extraccion
los sectores REALES a los que aplica cada normativa, para construir un
target_description que si es una consulta de busqueda real — ver
_regulations_block() en app/nexus/api/routes/prospecting.py.

A diferencia de GrantsRepository, sin lifecycle activo/pendiente_revision/
expirado ni descubrimiento automatico: una directiva no caduca como un
programa de ayudas, y el riesgo de que un LLM "descubra" mal el alcance
legal de una normativa es mayor que el beneficio — tabla curada a mano,
editable por CRUD igual que sales_verticals, ampliable con mas normativas
(RGPD, ENS, DORA...) cuando haga falta, sin tocar codigo.

Datos sembrados verificados (Directiva UE 2022/2555 — NIS2, Anexos I y II,
2026-09-30) — no inventados.
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Regulation:
    slug: str
    nombre: str
    activo: bool = True
    sectores: list[str] = field(default_factory=list)
    criterios: str = ""
    url: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "nombre": self.nombre,
            "activo": self.activo,
            "sectores": list(self.sectores),
            "criterios": self.criterios,
            "url": self.url,
        }

    @staticmethod
    def from_row(row: Any) -> "Regulation":
        return Regulation(
            slug=row["slug"],
            nombre=row["nombre"],
            activo=bool(row["activo"]),
            sectores=json.loads(row["sectores_json"] or "[]"),
            criterios=row["criterios"],
            url=row["url"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# ── Semilla verificada (Directiva UE 2022/2555 — NIS2, Anexos I y II) ───────
_DEFAULT_SEED: list[dict[str, Any]] = [
    {
        "slug": "nis2",
        "nombre": "NIS2 (Directiva UE 2022/2555 de ciberseguridad)",
        "sectores": [
            "operadores de energía eléctrica, gas u otros suministros energéticos",
            "empresas de transporte aéreo, ferroviario, marítimo o por carretera",
            "entidades bancarias",
            "infraestructuras de mercados financieros",
            "hospitales y proveedores de asistencia sanitaria",
            "empresas de suministro y distribución de agua potable",
            "empresas de tratamiento de aguas residuales",
            "proveedores de infraestructura digital (centros de datos, DNS, servicios cloud, redes de telecomunicaciones)",
            "proveedores de servicios gestionados de TI y ciberseguridad",
            "administraciones públicas",
            "empresas del sector espacial",
            "empresas de servicios postales y mensajería",
            "empresas de gestión de residuos",
            "fabricantes y distribuidores de productos químicos",
            "empresas de producción y distribución de alimentos",
            "fabricantes de dispositivos médicos, electrónica, maquinaria o vehículos",
            "plataformas digitales (marketplaces, buscadores, redes sociales)",
            "centros de investigación",
        ],
        "criterios": (
            "Directiva UE 2022/2555 (NIS2) sobre ciberseguridad — aplica a entidades "
            "esenciales e importantes de los sectores listados. Generalmente mediana o "
            "gran empresa (50+ empleados o >10M€ de facturacion/balance anual) — "
            "microempresas y pequeñas empresas quedan fuera salvo excepciones sectoriales "
            "especificas (ej. proveedores de confianza digital, registros de dominio). "
            "Transpuesta en España via el Proyecto de Ley de Coordinacion y Gobernanza "
            "de la Ciberseguridad."
        ),
        "url": "https://eur-lex.europa.eu/eli/dir/2022/2555/oj",
    },
]


class RegulationsRepository:
    """Lectura/escritura del catalogo de normativas -> sectores reales.
    Tabla curada a mano (sin descubrimiento automatico) — ver modulo."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        db_path = Path(os.environ.get("NEXUS_PROSPECTING_DB_PATH") or (self._data_dir / "prospecting.sqlite3"))
        self._store = SQLiteStore(db_path)
        ensure_prospecting_schema(self._store)
        self._seed_defaults_if_empty()

    def _seed_defaults_if_empty(self) -> None:
        with self._store.transaction() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM compliance_regulations").fetchone()
            if row["c"]:
                return
            now = _now_iso()
            for seed in _DEFAULT_SEED:
                conn.execute(
                    """
                    INSERT INTO compliance_regulations(
                        slug, nombre, activo, sectores_json, criterios, url, created_at, updated_at
                    ) VALUES(?, ?, 1, ?, ?, ?, ?, ?)
                    """,
                    (
                        seed["slug"], seed["nombre"],
                        json.dumps(seed["sectores"], ensure_ascii=False),
                        seed["criterios"], seed["url"], now, now,
                    ),
                )

    # ── Lectura ──────────────────────────────────────────────────────────────

    def list_all(self) -> list[Regulation]:
        with self._store.connect() as conn:
            rows = conn.execute("SELECT * FROM compliance_regulations ORDER BY nombre ASC").fetchall()
        return [Regulation.from_row(row) for row in rows]

    def list_active(self) -> list[Regulation]:
        return [r for r in self.list_all() if r.activo]

    def get(self, slug: str) -> Regulation | None:
        slug = (slug or "").strip()
        if not slug:
            return None
        with self._store.connect() as conn:
            row = conn.execute("SELECT * FROM compliance_regulations WHERE slug = ?", (slug,)).fetchone()
        return Regulation.from_row(row) if row else None

    # ── Escritura (CRUD manual, mismo patron que sales_verticals) ───────────

    def upsert(
        self,
        *,
        slug: str,
        nombre: str,
        sectores: list[str],
        criterios: str = "",
        url: str = "",
        activo: bool = True,
    ) -> Regulation:
        now = _now_iso()
        with self._store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO compliance_regulations(
                    slug, nombre, activo, sectores_json, criterios, url, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    nombre = excluded.nombre,
                    activo = excluded.activo,
                    sectores_json = excluded.sectores_json,
                    criterios = excluded.criterios,
                    url = excluded.url,
                    updated_at = excluded.updated_at
                """,
                (
                    slug, nombre, int(activo),
                    json.dumps(list(sectores), ensure_ascii=False),
                    criterios, url, now, now,
                ),
            )
        return self.get(slug)  # type: ignore[return-value]

    def set_activo(self, slug: str, activo: bool) -> Regulation | None:
        now = _now_iso()
        with self._store.transaction() as conn:
            conn.execute(
                "UPDATE compliance_regulations SET activo = ?, updated_at = ? WHERE slug = ?",
                (int(activo), now, slug),
            )
        return self.get(slug)

    def delete(self, slug: str) -> None:
        with self._store.transaction() as conn:
            conn.execute("DELETE FROM compliance_regulations WHERE slug = ?", (slug,))

    def find_by_query(self, query: str) -> Regulation | None:
        """Match aproximado por nombre/slug — usado por el tool de busqueda
        del bucle conversacional (lookup_regulation_sectors) para resolver
        lo que el usuario nombro ("la NIS2", "normativa de ciberseguridad
        NIS2"...) contra el catalogo real, sin exigir coincidencia exacta."""
        from nexus.utils.text import normalize_text

        target = normalize_text(query)
        if not target:
            return None
        for reg in self.list_active():
            if not reg.activo:
                continue
            candidates = [reg.slug, reg.nombre]
            for candidate in candidates:
                normalized = normalize_text(candidate)
                if normalized and (normalized in target or target in normalized):
                    return reg
        return None


def build_regulations_block(regulations: list[Regulation]) -> str:
    """Bloque de texto con las normativas reales activas y sus sectores —
    mismo patron que el catalog_block de _classify_grant_fit (service.py) —
    inyectado en el prompt de extraccion para que el LLM nunca tenga que
    inventar a que sectores aplica una normativa."""
    if not regulations:
        return "(sin normativas en el catalogo)"
    lines = []
    for reg in regulations:
        sectores = "; ".join(reg.sectores)
        lines.append(f"- slug={reg.slug} | {reg.nombre} | sectores reales: {sectores}")
    return "\n".join(lines)
