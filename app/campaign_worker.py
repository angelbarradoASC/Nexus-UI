"""app/campaign_worker.py
--------------------------------------------------------------------------
Runner headless de la Campaña — pensado para correr 24/7 en el servidor
self-hosted, sin depender de que la app de escritorio este abierta.

A diferencia de products/desktop/backend/app.py, construye SOLO lo que la
Campaña necesita (prospecting + outreach + CRM), sin el resto de
NexusCoordinator (Jira, Alertmanager, mouse_agent, remote_ops...) que no
aplica en un servidor sin esos conectores. Reutiliza tal cual el router
existente de app/nexus/api/routes/campaign.py (mismos endpoints que ya usa
la UI de escritorio) via dependency_overrides — sin duplicar logica.

Uso:
    python campaign_worker.py
(cwd=/app en Docker — mismo WORKDIR que main.py — o la raiz del repo en
local, para que data/campaigns, data/prospecting y data/credentials.enc se
resuelvan igual que en el resto de la app.)
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from fastapi import FastAPI  # noqa: E402
from loguru import logger  # noqa: E402

from agents.llm_router import get_router  # noqa: E402
from agents.tools.credential_store import CredentialStore  # noqa: E402
from config import cfg  # noqa: E402
from nexus.api.dependencies.auth import (  # noqa: E402
    get_campaign_agent,
    get_campaign_decomposer,
    get_prospecting_manager,
)
from nexus.api.routes import campaign as campaign_routes  # noqa: E402
from nexus.crm import CRMBridgeService  # noqa: E402
from nexus.outreach import OutreachManager  # noqa: E402
from nexus.prospecting import ProspectingAgentService  # noqa: E402
from nexus.prospecting.campaign_agent import CampaignAgent  # noqa: E402
from nexus.prospecting.campaign_decompose import CampaignDecomposer  # noqa: E402
from nexus.prospecting.embeddings import LocalEmbeddingsClient, LocalEmbeddingsSettings  # noqa: E402
from nexus.prospecting.llm import LocalLLMClient, LocalLLMSettings  # noqa: E402
from nexus.workers.scheduler import NexusScheduler  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("campaign_worker arrancando | version={}", cfg.app_version)

    llm_router = get_router()
    prospecting = ProspectingAgentService(cfg=cfg)
    outreach = OutreachManager(cfg=cfg, llm_router=llm_router, credential_store=CredentialStore())
    crm = CRMBridgeService(cfg=cfg)
    campaign = CampaignAgent(prospecting_svc=prospecting, outreach_mgr=outreach, crm_svc=crm)

    # Mismo patron que auth.py:build_runtime (campaign_decomposer), pero sin
    # construir el resto del NexusCoordinator — /campaign/decompose-verify
    # es el unico endpoint que lo necesita.
    campaign_local_llm = LocalLLMClient(
        settings=LocalLLMSettings(
            base_url=getattr(cfg, "local_llm_base_url", None),
            model=getattr(cfg, "local_llm_model", ""),
            provider=getattr(cfg, "local_llm_provider", "openai_compatible"),
            timeout=float(getattr(cfg, "local_llm_campaign_timeout", 300)),
            retries=1,
            enabled=bool(getattr(cfg, "local_llm_enabled", False)),
        ),
        api_key=getattr(cfg, "local_llm_api_key", "") or "not-needed",
    )
    campaign_decomposer = CampaignDecomposer(
        llm_router=llm_router,
        local_llm=campaign_local_llm,
        embeddings=LocalEmbeddingsClient(
            settings=LocalEmbeddingsSettings(
                base_url=getattr(cfg, "local_llm_base_url", None),
                model=getattr(cfg, "local_embeddings_model", "nomic-embed-text"),
                timeout=float(getattr(cfg, "local_embeddings_timeout", 120)),
                enabled=bool(getattr(cfg, "local_embeddings_enabled", False)),
            ),
        ),
        verticals=prospecting.verticals,
        regulations=prospecting.regulations,
    )

    # dependency_overrides en vez de app.state.nexus_runtime — las rutas de
    # campaign.py piden estos objetos via Depends(get_*), no hace falta
    # construir un NexusRuntime completo (que arrastraria Jira/Alertmanager/
    # mouse_agent, sin sentido en un servidor sin esos conectores).
    app.dependency_overrides[get_campaign_agent] = lambda: campaign
    app.dependency_overrides[get_prospecting_manager] = lambda: prospecting
    app.dependency_overrides[get_campaign_decomposer] = lambda: campaign_decomposer

    scheduler = NexusScheduler()
    scheduler.attach_campaign_agent(campaign)
    scheduler.start()
    app.state.nexus_scheduler = scheduler
    logger.info("campaign_worker | scheduler de campaña arrancado 24/7 | daily_prospecting 09:00 Europe/Madrid")

    yield

    logger.info("campaign_worker apagandose...")
    scheduler.stop()
    await llm_router.close()
    logger.info("campaign_worker detenido limpiamente")


app = FastAPI(title="Nexus Campaign Worker", lifespan=lifespan)
app.include_router(campaign_routes.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8100)
