"""Catalogo de lo que ofrece Assets Consultores (servicios, productos) y que
senales indican encaje, persistido en SQLite.

Mismo patron que regulations.py/grants.py/sales_verticals.py (BBDD curada,
CRUD manual, sin descubrimiento automatico, mismo prospecting.sqlite3).

Nace de un hueco real detectado por el usuario: el analisis de la campaña solo
sabia proponer mejoras de web para pymes (UX, SEO, chatbot...) y no sabia nada
de que vende Assets, asi que no podia buscar ENCAJE entre una empresa analizada
y lo que la consultora ofrece. Este catalogo es lo que el analisis consulta
para citar encajes reales — nunca inventa servicios.

Semilla extraida de https://assetsconsultores.es el 2026-10-16. Cada entrada
lleva `cautelas`: afirmaciones de la web que NO estan respaldadas (cifras sin
cliente nombrado, resultados "potenciales", funcionalidades en roadmap). El
analisis y el redactor de correos no deben presentarlas como hechos ni como
referencias — la web misma no nombra ni un solo cliente.
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

SOURCE_URL = "https://assetsconsultores.es"
SOURCE_DATE = "2026-10-16"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Offering:
    slug: str
    nombre: str
    tipo: str = "servicio"  # servicio | producto | perfil
    descripcion: str = ""
    senales: list[str] = field(default_factory=list)
    normativas: list[str] = field(default_factory=list)
    sectores: list[str] = field(default_factory=list)
    cautelas: str = ""
    url: str = ""
    activo: bool = True
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "nombre": self.nombre,
            "tipo": self.tipo,
            "descripcion": self.descripcion,
            "senales": list(self.senales),
            "normativas": list(self.normativas),
            "sectores": list(self.sectores),
            "cautelas": self.cautelas,
            "url": self.url,
            "activo": self.activo,
        }

    @staticmethod
    def from_row(row: Any) -> "Offering":
        return Offering(
            slug=row["slug"],
            nombre=row["nombre"],
            tipo=row["tipo"],
            descripcion=row["descripcion"],
            senales=json.loads(row["senales_json"] or "[]"),
            normativas=json.loads(row["normativas_json"] or "[]"),
            sectores=json.loads(row["sectores_json"] or "[]"),
            cautelas=row["cautelas"],
            url=row["url"],
            activo=bool(row["activo"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# ── Semilla extraida de la web (2026-10-16) — no inventada ──────────────────
_DEFAULT_SEED: list[dict[str, Any]] = [
    {
        "slug": "assets_perfil",
        "nombre": "Assets Consultores — quienes somos",
        "tipo": "perfil",
        "descripcion": (
            "Consultora tecnologica fundada en 2017 con sede en Madrid y hubs en Costa Rica "
            "(San Jose) y Panama. Especializada en cloud, FinOps, observabilidad e inteligencia "
            "artificial; trabaja con empresas europeas e iberoamericanas. Multicloud (AWS, Azure, "
            "GCP, Vultr) y transferencia de conocimiento al equipo del cliente. La primera "
            "sesion es sin coste."
        ),
        "senales": [],
        "normativas": [],
        "sectores": ["retail", "telecomunicaciones", "energia", "legal", "educacion", "logistica", "gobierno"],
        "cautelas": (
            "La web no nombra ningun cliente, no declara certificaciones ni alianzas formales y "
            "no indica el tamaño del equipo. No inventar referencias, clientes ni certificaciones."
        ),
        "url": f"{SOURCE_URL}/conocenos/",
    },
    {
        "slug": "seguridad_nis2",
        "nombre": "Seguridad y cumplimiento NIS2",
        "tipo": "servicio",
        "descripcion": (
            "Gap analysis NIS2, implementacion de controles tecnicos y documentacion para "
            "auditoria; auditoria de seguridad cloud (CIS Benchmarks, IAM), arquitectura Zero "
            "Trust (MFA, PAM) y respuesta a incidentes 24/7 con analisis forense. Entregables: "
            "informe ejecutivo, roadmap de remediacion y evidencias para auditoria. Marcos "
            "citados: NIS2, GDPR, ISO 27001, SOC 2, CIS, NIST."
        ),
        "senales": [
            "sector incluido en el Anexo I o II de NIS2 (energia, transporte, salud, aguas, digital, telecomunicaciones...)",
            "mediana o gran empresa dentro del alcance de NIS2",
            "no hay CISO ni responsable de ciberseguridad publicado",
            "infraestructura cloud (AWS, Azure, GCP) sin evidencia de auditoria de seguridad",
            "correo con DMARC en p=none o sin politica",
            "recientemente nombrada como entidad esencial o importante",
        ],
        "normativas": ["nis2", "gdpr", "iso27001", "soc2"],
        "sectores": [],
        "cautelas": (
            "El panel de 'monitorizacion en vivo' de la web (72 intentos de acceso, 97% de politicas "
            "IAM...) no indica si son datos de clientes reales: NO citarlo. La web no menciona ENS ni DORA en seguridad."
        ),
        "url": f"{SOURCE_URL}/seguridad/",
    },
    {
        "slug": "aegis",
        "nombre": "AEGIS Platform (control continuo de cumplimiento)",
        "tipo": "producto",
        "descripcion": (
            "Producto propio de control continuo de cumplimiento normativo basado en evidencias. "
            "Cuatro modulos: back-office normativo (norma -> grafo de requisitos), motor de "
            "evaluacion (scoring continuo por evidencia, requisito y norma), gestion de evidencias "
            "con LLM supervisado y federacion de proveedores (cadena de suministro como red de "
            "dependencias). Oferta de validacion piloto con diagnostico inicial, sin compromiso."
        ),
        "senales": [
            "organizacion dentro del ambito de NIS2 que debe demostrar cumplimiento con evidencias",
            "cadena de suministro con proveedores criticos que afectan al cumplimiento",
            "necesita informes para auditoria o para la direccion (responsabilidad directa de la direccion en NIS2)",
            "responsable de cumplimiento o de proveedores identificable",
        ],
        "normativas": ["nis2"],
        "sectores": [],
        "cautelas": (
            "Solo NIS2 figura 'en vigor'; GDPR, DORA, ENS, ISO 27001 e ISO 22301 estan en 'roadmap' sin fechas — "
            "NO ofrecerlos como disponibles. La web indica que esta 'pendiente de patente': no decir 'patentado'. "
            "No hay metricas, resultados ni clientes publicados."
        ),
        "url": f"{SOURCE_URL}/productos/aegis/",
    },
    {
        "slug": "energia_ot_it",
        "nombre": "Datos, observabilidad y seguridad para energia",
        "tipo": "servicio",
        "descripcion": (
            "Plataformas de datos y cloud para utilities: data lakes para telemetria IoT, modelos "
            "predictivos de consumo, observabilidad de infraestructura critica (SCADA, redes de "
            "distribucion), seguridad de entornos OT/IT convergentes (segmentacion y deteccion de "
            "intrusiones) y reporting regulatorio automatizado para la CNMC."
        ),
        "senales": [
            "generacion renovable distribuida (eolica, solar) con telemetria a gran escala",
            "redes de distribucion electrica propias o contadores inteligentes",
            "obligaciones de reporting ante la CNMC",
            "comercializadora con prevision de demanda y desvios en el mercado mayorista",
            "entorno OT/IT convergente (SCADA, monitorizacion de plantas)",
        ],
        "normativas": ["nis2", "cnmc"],
        "sectores": ["energia"],
        "cautelas": (
            "Los resultados de la web (desvio de prediccion <3%, deteccion de fallos de 8 h a <15 min, informes CNMC "
            "automaticos) son casos sin cliente nombrado: NO presentarlos como referencias."
        ),
        "url": f"{SOURCE_URL}/energia/",
    },
    {
        "slug": "observabilidad_nexus",
        "nombre": "Observabilidad y Nexus",
        "tipo": "servicio",
        "descripcion": (
            "Metricas, logs, trazas y monitorizacion sintetica unificados. Compatible con Prometheus, "
            "Grafana, Datadog, New Relic, Elastic, Dynatrace, OpenTelemetry y Jaeger. Producto propio "
            "Nexus: panel unico, multi-tenant, retencion de hasta 13 meses, precio por hosts y no por "
            "volumen de datos, sin vendor lock-in."
        ),
        "senales": [
            "equipo de operaciones o SRE que opera muchos sistemas",
            "operacion reactiva, diagnostico lento de incidentes, sin SLO/SLA medibles",
            "requisitos de trazabilidad de logs para auditoria o cumplimiento",
            "infraestructura critica que no tolera puntos ciegos",
        ],
        "normativas": [],
        "sectores": [],
        "cautelas": (
            "SLA 99.9% y MTTD <5 min son cifras de la web sin clientes que las respalden. "
            "La web no define perfil de cliente para Nexus."
        ),
        "url": f"{SOURCE_URL}/observabilidad/",
    },
    {
        "slug": "consultoria_cloud",
        "nombre": "Consultoria cloud (arquitectura, migracion, datos, formacion)",
        "tipo": "servicio",
        "descripcion": (
            "Arquitectura cloud (Well-Architected, serverless, microservicios), migracion on-premise a "
            "nube con estrategia 6R e infraestructura como codigo, data & analytics (data lakes, "
            "pipelines ETL/ELT, dashboards) y formacion cloud. AWS, Azure, GCP y Vultr. Metodologia en "
            "cuatro fases: analisis, diseño, implementacion, optimizacion."
        ),
        "senales": [
            "aplicaciones monoliticas o infraestructura on-premise a migrar",
            "necesita una plataforma de datos o analitica",
            "equipo que necesita formacion cloud o preparacion de certificaciones",
        ],
        "normativas": [],
        "sectores": [],
        "cautelas": "Solo se respalda con cifras '+50 proyectos cloud'. 'Cero disrupciones' y '100% garantizado' son lemas sin datos.",
        "url": f"{SOURCE_URL}/consultoria-cloud/",
    },
    {
        "slug": "finops_cloudledger",
        "nombre": "FinOps (CloudLedger y SmartScale)",
        "tipo": "servicio",
        "descripcion": (
            "Optimizacion del gasto cloud: informar, optimizar y operar (rightsizing, reservas, spot, "
            "gobierno financiero) con marco FinOps Foundation. Productos propios: CloudLedger (auditoria "
            "continua del gasto, alertas de anomalias) y SmartScale (optimizacion dinamica de recursos)."
        ),
        "senales": [
            "gasto cloud relevante sin visibilidad por servicio, equipo o entorno",
            "crecimiento rapido de infraestructura cloud",
        ],
        "normativas": [],
        "sectores": [],
        "cautelas": "El ahorro 12-22% es un promedio de la industria, NO un resultado verificado de clientes propios.",
        "url": f"{SOURCE_URL}/finops/",
    },
    {
        "slug": "ia_braingel",
        "nombre": "Inteligencia artificial y Braingel",
        "tipo": "servicio",
        "descripcion": (
            "IA generativa desplegada en el entorno del cliente (LLM con RAG sobre documentos internos), "
            "machine learning, agentes autonomos y data engineering. Producto propio Braingel: asistente con "
            "memoria contextual desplegado en la infraestructura del cliente. Metodologia: diagnostico, "
            "prototipo en 48 horas, validacion y escala. Diagnostico gratuito."
        ),
        "senales": [
            "gran volumen de documentacion o conocimiento interno poco aprovechado",
            "procesos manuales repetitivos que un agente podria asumir",
            "restricciones de privacidad que exigen que los datos no salgan del perimetro",
        ],
        "normativas": ["gdpr"],
        "sectores": [],
        "cautelas": "'60% de reduccion de tareas manuales' es un potencial declarado, no un resultado medido.",
        "url": f"{SOURCE_URL}/inteligencia-artificial/",
    },
    {
        "slug": "automatizacion_barman_motu",
        "nombre": "Automatizacion (Barman y Motu)",
        "tipo": "servicio",
        "descripcion": (
            "RPA, orquestacion de workflows, agentes IA e integracion de sistemas (REST, SOAP, GraphQL, EDI; "
            "conectores SAP y Salesforce). Productos propios: Barman (orquestador de workflows con diseñador "
            "visual) y Motu (automatizacion local para pymes: facturacion, cobros, stock y avisos por WhatsApp, "
            "pago unico)."
        ),
        "senales": [
            "procesos de finanzas, RRHH o IT con trabajo manual en sistemas legacy sin API",
            "integracion entre varios sistemas (SAP, Salesforce) hecha a mano",
            "pyme que quiere facturacion y cobros automaticos sin suscripcion (Motu)",
        ],
        "normativas": [],
        "sectores": [],
        "cautelas": "Todos los resultados (80% menos tareas manuales, ROI en 3-6 meses...) son 'potenciales'. La web no describe Motu en detalle.",
        "url": f"{SOURCE_URL}/automatizacion/",
    },
    {
        "slug": "telecomunicaciones",
        "nombre": "Telecomunicaciones (cloud telco, automatizacion de red, seguridad)",
        "tipo": "servicio",
        "descripcion": (
            "Cloud telco (VNF/CNF sobre Kubernetes), automatizacion de red (zero-touch, GitOps), "
            "observabilidad telco (QoE, trazabilidad de señalizacion) y seguridad telco (SS7/Diameter, "
            "anti-fraude VoIP/SIP, cumplimiento NIS2 y ENS)."
        ),
        "senales": [
            "operadora o empresa con red de telecomunicaciones propia (fibra, movil)",
            "sistemas OSS/BSS legacy a modernizar",
            "presion regulatoria de NIS2 por ser proveedor de infraestructura digital",
        ],
        "normativas": ["nis2", "ens"],
        "sectores": ["telecomunicaciones"],
        "cautelas": "'+10 operadoras como cliente' y 'presencia en 4 paises' son cifras declaradas sin clientes nombrados.",
        "url": f"{SOURCE_URL}/telecomunicaciones/",
    },
    {
        "slug": "outsourcing_monitorizacion",
        "nombre": "Outsourcing: monitorizacion y escalado 24x7",
        "tipo": "servicio",
        "descripcion": (
            "Equipo externo que vigila la infraestructura todo el año y decide el escalado, con SLA de tiempos "
            "de respuesta contractuales y cobertura continua con redundancia."
        ),
        "senales": [
            "infraestructura critica que necesita vigilancia continua sin querer mantener turnos propios",
            "equipo de TI pequeño para el tamaño de la operacion",
        ],
        "normativas": [],
        "sectores": [],
        "cautelas": "Es el unico servicio de outsourcing descrito; la web anuncia mas 'proximamente'. No prometer perfiles ni modelos no descritos.",
        "url": f"{SOURCE_URL}/outsourcing/",
    },
]


class OfferingsRepository:
    """Lectura/escritura del catalogo de ofertas de Assets. Tabla curada a
    mano (sin descubrimiento automatico) — ver modulo."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        db_path = Path(os.environ.get("NEXUS_PROSPECTING_DB_PATH") or (self._data_dir / "prospecting.sqlite3"))
        self._store = SQLiteStore(db_path)
        ensure_prospecting_schema(self._store)
        self._seed_defaults_if_empty()

    def _seed_defaults_if_empty(self) -> None:
        with self._store.transaction() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM company_offerings").fetchone()
            if row["c"]:
                return
            now = _now_iso()
            for seed in _DEFAULT_SEED:
                conn.execute(
                    """
                    INSERT INTO company_offerings(
                        slug, nombre, tipo, descripcion, senales_json, normativas_json,
                        sectores_json, cautelas, url, activo, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        seed["slug"], seed["nombre"], seed["tipo"], seed["descripcion"],
                        json.dumps(seed["senales"], ensure_ascii=False),
                        json.dumps(seed["normativas"], ensure_ascii=False),
                        json.dumps(seed["sectores"], ensure_ascii=False),
                        seed["cautelas"], seed["url"], now, now,
                    ),
                )

    # ── Lectura ──────────────────────────────────────────────────────────────

    def list_all(self) -> list[Offering]:
        with self._store.connect() as conn:
            rows = conn.execute("SELECT * FROM company_offerings ORDER BY tipo DESC, nombre ASC").fetchall()
        return [Offering.from_row(row) for row in rows]

    def list_active(self) -> list[Offering]:
        return [o for o in self.list_all() if o.activo]

    def get(self, slug: str) -> Offering | None:
        slug = (slug or "").strip()
        if not slug:
            return None
        with self._store.connect() as conn:
            row = conn.execute("SELECT * FROM company_offerings WHERE slug = ?", (slug,)).fetchone()
        return Offering.from_row(row) if row else None

    # ── Escritura (CRUD manual) ──────────────────────────────────────────────

    def upsert(
        self,
        *,
        slug: str,
        nombre: str,
        tipo: str = "servicio",
        descripcion: str = "",
        senales: list[str] | None = None,
        normativas: list[str] | None = None,
        sectores: list[str] | None = None,
        cautelas: str = "",
        url: str = "",
        activo: bool = True,
    ) -> Offering:
        now = _now_iso()
        with self._store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO company_offerings(
                    slug, nombre, tipo, descripcion, senales_json, normativas_json,
                    sectores_json, cautelas, url, activo, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    nombre = excluded.nombre,
                    tipo = excluded.tipo,
                    descripcion = excluded.descripcion,
                    senales_json = excluded.senales_json,
                    normativas_json = excluded.normativas_json,
                    sectores_json = excluded.sectores_json,
                    cautelas = excluded.cautelas,
                    url = excluded.url,
                    activo = excluded.activo,
                    updated_at = excluded.updated_at
                """,
                (
                    slug, nombre, tipo, descripcion,
                    json.dumps(list(senales or []), ensure_ascii=False),
                    json.dumps(list(normativas or []), ensure_ascii=False),
                    json.dumps(list(sectores or []), ensure_ascii=False),
                    cautelas, url, int(activo), now, now,
                ),
            )
        return self.get(slug)  # type: ignore[return-value]

    def set_activo(self, slug: str, activo: bool) -> Offering | None:
        now = _now_iso()
        with self._store.transaction() as conn:
            conn.execute(
                "UPDATE company_offerings SET activo = ?, updated_at = ? WHERE slug = ?",
                (int(activo), now, slug),
            )
        return self.get(slug)

    def delete(self, slug: str) -> None:
        with self._store.transaction() as conn:
            conn.execute("DELETE FROM company_offerings WHERE slug = ?", (slug,))


def build_offerings_block(offerings: list[Offering]) -> str:
    """Bloque de texto con las ofertas reales activas, sus señales de encaje y
    sus cautelas — mismo patron que build_regulations_block/_classify_grant_fit
    — inyectado en el prompt de analisis de encaje para que el LLM nunca
    invente un servicio ni cite una cifra que la web no respalda."""
    items = [o for o in offerings if o.tipo != "perfil"]
    if not items:
        return "(sin ofertas en el catalogo)"
    lines = []
    for o in items:
        senales = "; ".join(o.senales) or "(sin señales definidas)"
        lines.append(
            f"- slug={o.slug} | {o.nombre}\n"
            f"  que es: {o.descripcion}\n"
            f"  encaja cuando: {senales}\n"
            f"  NO afirmar: {o.cautelas or '(sin cautelas)'}"
        )
    return "\n".join(lines)
