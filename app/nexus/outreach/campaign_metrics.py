"""
app/nexus/outreach/campaign_metrics.py
-----------------------------------------
Lee el estado de todas las campañas outreach y actualiza los gauges
Prometheus correspondientes.  Se llama desde el endpoint /metrics de
la app desktop — NO desde el scheduler.

Diseño: snapshot completo en cada scrape.  Los gauges sobrescriben el
valor anterior, por lo que siempre reflejan el estado actual.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from loguru import logger

import metrics as m


# Etiqueta segura para Prometheus (caracteres permitidos: a-z, 0-9, _)
_RE_UNSAFE = re.compile(r"[^a-zA-Z0-9_]")


def _safe(value: Any, fallback: str = "unknown") -> str:
    raw = str(value or fallback).strip()
    return raw[:64] or fallback


def _vertical_from_campaign(campaign: dict[str, Any]) -> str:
    """Intenta inferir el vertical desde el nombre de campaña o la audiencia."""
    name = (campaign.get("campaign_name") or "").lower()
    hint = (campaign.get("audience_hint") or "").lower()
    for kw in ("inmobiliaria", "restaurant", "public_administration", "retail", "logistica"):
        if kw in name or kw in hint:
            return kw
    return "custom"


def _age_days(created_at: str | None) -> float:
    if not created_at:
        return 0.0
    try:
        dt = datetime.fromisoformat(created_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return max(0.0, delta.total_seconds() / 86400)
    except Exception:
        return 0.0


async def update_campaign_metrics(outreach_repository) -> None:
    """
    Lee el estado de todas las campañas outreach y actualiza los gauges Prometheus.
    Nunca lanza excepciones — falla silenciosamente para no interrumpir /metrics.
    """
    try:
        campaigns = await outreach_repository.load_campaigns()
        _update_campaign_gauges(campaigns)
    except Exception as exc:
        logger.warning("update_campaign_metrics: error no crítico | {}", exc)


def _update_campaign_gauges(campaigns: list[dict[str, Any]]) -> None:
    # Contadores por vertical
    totals_per_vertical: dict[str, int] = {}
    active_per_vertical: dict[str, int] = {}

    for campaign in campaigns:
        cid   = _safe(campaign.get("campaign_id"), "unknown")
        cname = _safe(campaign.get("campaign_name"), cid)[:40]
        vert  = _vertical_from_campaign(campaign)

        prospects = campaign.get("prospects") or []
        total     = len(prospects)
        waiting   = sum(1 for p in prospects if p.get("status") == "waiting_followup")
        done      = sum(1 for p in prospects if p.get("status") == "completed")
        is_active = any(
            p.get("status") in ("pending", "waiting_followup")
            for p in prospects
        )

        # Envíos por paso
        step_counts: dict[str, int] = {}
        for prospect in prospects:
            for event in prospect.get("history") or []:
                if event.get("event_type") == "email_sent":
                    step = str(int(event.get("step_index", 0)))
                    step_counts[step] = step_counts.get(step, 0) + 1

        labels = dict(campaign_id=cid, campaign_name=cname, vertical=vert)

        m.CAMPAIGN_PROSPECTS_TOTAL.labels(**labels).set(total)
        m.CAMPAIGN_PROSPECTS_WAITING.labels(**labels).set(waiting)
        m.CAMPAIGN_PROSPECTS_DONE.labels(**labels).set(done)
        m.CAMPAIGN_AGE_DAYS.labels(**labels).set(_age_days(campaign.get("created_at")))

        for step, count in step_counts.items():
            m.CAMPAIGN_SENDS_TOTAL.labels(**labels, step=step).set(count)

        # Asegurar que haya un valor aunque no se haya enviado nada
        if not step_counts:
            m.CAMPAIGN_SENDS_TOTAL.labels(**labels, step="0").set(0)

        totals_per_vertical[vert] = totals_per_vertical.get(vert, 0) + 1
        if is_active:
            active_per_vertical[vert] = active_per_vertical.get(vert, 0) + 1

    for vert, total in totals_per_vertical.items():
        m.CAMPAIGNS_TOTAL.labels(vertical=vert).set(total)
    for vert, active in active_per_vertical.items():
        m.CAMPAIGNS_ACTIVE.labels(vertical=vert).set(active)


