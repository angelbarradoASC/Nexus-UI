"""Prometheus metrics helpers for Nexus runtime and desktop surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest


CHAT_REQUESTS_TOTAL = Counter(
    "nexus_chat_requests_total",
    "Numero total de peticiones de chat procesadas por Nexus",
    ["surface", "mode", "status", "agent"],
)

CHAT_REQUEST_LATENCY_SECONDS = Histogram(
    "nexus_chat_request_latency_seconds",
    "Latencia de peticiones de chat procesadas por Nexus",
    ["surface", "mode", "agent"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)

COLLECTOR_STATUS = Gauge(
    "nexus_collector_status",
    "Estado de fuentes de recoleccion y visualizacion (1 up, 0.5 degraded, 0 down)",
    ["name", "kind", "endpoint"],
)

LLM_ROUTER_CALLS = Gauge(
    "nexus_llm_router_calls_total",
    "Numero acumulado de llamadas registradas por el router LLM",
    ["level"],
)

LLM_ROUTER_FAILURES = Gauge(
    "nexus_llm_router_failures_total",
    "Numero acumulado de fallos registrados por el router LLM",
    ["level"],
)

LLM_ROUTER_AVG_LATENCY_MS = Gauge(
    "nexus_llm_router_avg_latency_ms",
    "Latencia media observada por el router LLM en milisegundos",
    ["level"],
)

DESKTOP_ALERTS_TOTAL = Gauge(
    "nexus_desktop_alerts_total",
    "Numero de alertas locales ingeridas por el bridge desktop",
)

DESKTOP_METRIC_VALUE = Gauge(
    "nexus_desktop_metric_value",
    "Valores numericos exportados por el bridge desktop",
    ["metric"],
)

# ── Métricas de campañas outreach ─────────────────────────────────────────

CAMPAIGN_PROSPECTS_TOTAL = Gauge(
    "nexus_campaign_prospects_total",
    "Total de prospectos en la campaña",
    ["campaign_id", "campaign_name", "vertical"],
)

CAMPAIGN_PROSPECTS_WAITING = Gauge(
    "nexus_campaign_prospects_waiting",
    "Prospectos esperando siguiente envío (follow-up pendiente)",
    ["campaign_id", "campaign_name", "vertical"],
)

CAMPAIGN_PROSPECTS_DONE = Gauge(
    "nexus_campaign_prospects_done",
    "Prospectos que completaron todos los pasos de la secuencia",
    ["campaign_id", "campaign_name", "vertical"],
)

CAMPAIGN_SENDS_TOTAL = Gauge(
    "nexus_campaign_sends_total",
    "Emails enviados por campaña y paso (step=0 inicial, step>0 follow-up)",
    ["campaign_id", "campaign_name", "vertical", "step"],
)

CAMPAIGN_AGE_DAYS = Gauge(
    "nexus_campaign_age_days",
    "Dias desde la creacion de la campaña (detecta campañas estancadas)",
    ["campaign_id", "campaign_name", "vertical"],
)

CAMPAIGNS_ACTIVE = Gauge(
    "nexus_campaigns_active_total",
    "Numero de campañas con prospectos aun activos por vertical",
    ["vertical"],
)

CAMPAIGNS_TOTAL = Gauge(
    "nexus_campaigns_total",
    "Numero total de campañas por vertical",
    ["vertical"],
)


def _label(value: Any, fallback: str = "unknown") -> str:
    text = str(value or fallback).strip()
    return text or fallback


def _collector_status_value(status: str) -> float:
    if status == "up":
        return 1.0
    if status == "degraded":
        return 0.5
    return 0.0


def observe_chat_execution(
    *,
    surface: str,
    mode: str,
    status: str,
    agent: str,
    latency_seconds: float,
) -> None:
    CHAT_REQUESTS_TOTAL.labels(
        surface=_label(surface),
        mode=_label(mode),
        status=_label(status),
        agent=_label(agent),
    ).inc()
    CHAT_REQUEST_LATENCY_SECONDS.labels(
        surface=_label(surface),
        mode=_label(mode),
        agent=_label(agent),
    ).observe(max(latency_seconds, 0.0))


def update_collector_metrics(collectors_payload: Mapping[str, Any] | None) -> None:
    collectors = list((collectors_payload or {}).get("collectors", []) or [])
    for collector in collectors:
        COLLECTOR_STATUS.labels(
            name=_label(collector.get("name")),
            kind=_label(collector.get("kind")),
            endpoint=_label(collector.get("endpoint"), ""),
        ).set(_collector_status_value(_label(collector.get("status"))))


def update_llm_router_metrics(snapshot: Mapping[str, Any] | None) -> None:
    snapshot = snapshot or {}
    for level, count in (snapshot.get("calls") or {}).items():
        LLM_ROUTER_CALLS.labels(level=_label(level)).set(float(count or 0))
    for level, count in (snapshot.get("failures") or {}).items():
        LLM_ROUTER_FAILURES.labels(level=_label(level)).set(float(count or 0))
    for level, latency in (snapshot.get("avg_latency_ms") or {}).items():
        LLM_ROUTER_AVG_LATENCY_MS.labels(level=_label(level)).set(float(latency or 0))


def _flatten_numeric(prefix: str, payload: Mapping[str, Any]) -> dict[str, float]:
    flattened: dict[str, float] = {}
    for key, value in payload.items():
        metric_name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, bool):
            flattened[metric_name] = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            flattened[metric_name] = float(value)
        elif isinstance(value, Mapping):
            flattened.update(_flatten_numeric(metric_name, value))
    return flattened


def update_desktop_bridge_metrics(metrics_payload: Mapping[str, Any] | None, alerts_payload: list[Any] | None) -> None:
    DESKTOP_ALERTS_TOTAL.set(float(len(alerts_payload or [])))
    for metric_name, value in _flatten_numeric("", metrics_payload or {}).items():
        DESKTOP_METRIC_VALUE.labels(metric=_label(metric_name)).set(value)


def metrics_response_body() -> bytes:
    return generate_latest()


def metrics_response_content_type() -> str:
    return CONTENT_TYPE_LATEST


class MetricsTimer:
    """Small helper for timing blocks before exporting a histogram observation."""

    def __init__(self) -> None:
        self._start = perf_counter()

    @property
    def elapsed_seconds(self) -> float:
        return perf_counter() - self._start
