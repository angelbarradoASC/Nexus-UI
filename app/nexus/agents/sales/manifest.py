"""Manifest for the sales agent."""

from nexus.agents.shared.result import AgentCapability, AgentManifest

SALES_MANIFEST = AgentManifest(
    agent_id="sales",
    name="Nexus Sales",
    role="sales",
    description="Gestiona prospeccion, CRM y outreach con una tuberia autonoma comercial separada del operador.",
    accepted_modes=["sales", "prospecting", "crm", "outreach"],
    capabilities=[
        AgentCapability(
            capability_id="brief.guard",
            name="Brief Guardian",
            description="Protege la intencion comercial y aplica guardrails al briefing.",
        ),
        AgentCapability(
            capability_id="brief.refine",
            name="Brief Refiner",
            description="Refina criterios de prospeccion sin tocar vertical, geografia o marca.",
        ),
        AgentCapability(
            capability_id="sources.strategy",
            name="Source Strategist",
            description="Decide el orden de fuentes y el fallback discovery.",
        ),
        AgentCapability(
            capability_id="brief.verify",
            name="Brief Verifier",
            description="Comprueba de ida y vuelta que el brief representa fielmente el texto original, via LLM local.",
        ),
        AgentCapability(
            capability_id="queries.plan",
            name="Query Architect",
            description="Genera queries de bajo ruido y cobertura controlada.",
        ),
        AgentCapability(
            capability_id="discovery.execute",
            name="Search Executor",
            description="Ejecuta Brave y Google Places segun el plan activo.",
        ),
        AgentCapability(
            capability_id="candidates.qualify",
            name="Candidate Qualifier",
            description="Extrae, valida, deduplica y puntua cada candidato.",
        ),
        AgentCapability(
            capability_id="crm.package",
            name="CRM Packager",
            description="Prepara el handoff al CRM con readiness y tags comerciales.",
        ),
    ],
    skill_ids=[
        "prospecting.guardrails",
        "prospecting.refine",
        "prospecting.verify",
        "prospecting.plan_sources",
        "prospecting.plan_queries",
        "prospecting.search",
        "prospecting.score",
        "crm.push_result",
        "outreach.launch_campaign",
    ],
    connector_ids=["assets-crm", "odoo", "smtp", "imap"],
    tags=["always-on", "commercial", "modular"],
)
