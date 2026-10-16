"""
desktop/local_agents/outlook_watcher_agent.py
------------------------------------------------
OutlookWatcherAgent — loop autonomo que vigila la bandeja de Outlook y
avisa por iniciativa propia cuando hay algo importante, en vez de esperar
a que el usuario pregunte. Mismo molde que MonitoringAgent: bucle en hilo
daemon, habla con el propio servidor local por HTTP (nunca importa
nexus.* directamente — OutlookMailManager vive dentro del ciclo de vida
de FastAPI, no es reconstruible barato desde este proceso).

Tipo de agente: AUTONOMO (no necesita input del usuario).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Callable

import httpx

logger = logging.getLogger("nexus.outlook_watcher")

_MAX_NOTIFIED_IDS = 500


def _default_notified_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Open-Nexus" / "config"
    root.mkdir(parents=True, exist_ok=True)
    return root / "outlook_notified.json"


class OutlookWatcherAgent:
    """Vigila /api/nexus/outlook/priority cada `interval_seconds` y avisa
    (notificacion de Windows + conversacion de PEPO ya escrita) de los
    correos importantes que no se hayan avisado ya."""

    def __init__(
        self,
        *,
        interval_seconds: int = 300,
        local_url: str = "http://127.0.0.1:11430",
        internal_token: str = "",
        importance_threshold: str = "high",
        notify_fn: Callable[[str, str], None] | None = None,
        notified_path: Path | None = None,
    ) -> None:
        self.interval = interval_seconds
        self.local_url = local_url
        self.internal_token = internal_token
        self.importance_threshold = importance_threshold
        self._notify_fn = notify_fn
        self._notified_path = notified_path or _default_notified_path()
        self.running = False
        self._notified_ids = self._load_notified_ids()

    # ── Ciclo de vida ────────────────────────────────────────────────────────

    def run_sync(self) -> None:
        """Ejecuta el loop de vigilancia de forma sincrona. Disenado para
        correr en un hilo daemon via threading.Thread."""
        logger.info(f"OutlookWatcherAgent arrancado (intervalo: {self.interval}s)")
        self.running = True
        while self.running:
            try:
                self._tick()
            except Exception as e:
                logger.error(f"Error en ciclo de OutlookWatcherAgent: {e}", exc_info=True)
            time.sleep(self.interval)
        logger.info("OutlookWatcherAgent detenido")

    def stop(self) -> None:
        self.running = False

    # ── Internos ─────────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        headers = {}
        if self.internal_token:
            headers["Authorization"] = f"Bearer {self.internal_token}"
        return headers

    def _tick(self) -> None:
        try:
            response = httpx.get(
                f"{self.local_url}/api/nexus/outlook/priority",
                headers=self._headers(),
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            # Outlook puede no estar conectado todavia, o el servidor local
            # puede no estar listo — fallo silencioso, se reintenta en el
            # siguiente ciclo (igual que MonitoringAgent._push_metrics).
            logger.debug(f"OutlookWatcherAgent: no se pudo consultar Outlook: {e}")
            return

        if payload.get("status") != "success":
            return

        # Un aviso por conversacion, no por correo: un hilo con varias
        # respuestas nuevas (visto en vivo: 5 "Re: FinOps Engineer position"
        # a la vez) abria 5 conversaciones de PEPO y 5 notificaciones.
        groups: dict[str, list[dict]] = {}
        for message in payload.get("messages", []):
            message_id = message.get("message_id")
            if not message_id or message_id in self._notified_ids:
                continue
            if not self._is_important_enough(message):
                continue
            key = message.get("conversation_id") or message_id
            groups.setdefault(key, []).append(message)

        for group in groups.values():
            self._notify_group(group)

    def _notify_group(self, group: list[dict]) -> None:
        # Representante: el mas reciente del hilo; el motivo, el del de mayor puntuacion.
        latest = max(group, key=lambda m: m.get("received_at") or "")
        best = max(group, key=lambda m: m.get("priority_score") or 0)

        sender = latest.get("sender_name") or latest.get("sender_email") or "alguien"
        subject = latest.get("subject") or "(sin asunto)"
        reason = best.get("reason") or ""

        if len(group) == 1:
            pepo_message = (
                f"Te ha llegado un correo de {sender} sobre \"{subject}\" que parece importante"
                + (f": {reason}" if reason else ".")
                + " ¿Quieres que le eche un vistazo o te ayude a responder?"
            )
            toast = f"{sender}: {subject}"
        else:
            pepo_message = (
                f"Tienes {len(group)} correos nuevos en la conversación \"{subject}\" "
                f"(el último de {sender}) que parecen importantes"
                + (f": {reason}" if reason else ".")
                + " ¿Quieres que los revise y te resuma en qué punto está?"
            )
            toast = f"{len(group)} correos nuevos — {subject}"

        self._create_proactive_conversation(pepo_message)
        if self._notify_fn is not None:
            try:
                self._notify_fn(toast, "PEPO")
            except Exception as e:
                logger.error(f"OutlookWatcherAgent: fallo mostrando notificacion: {e}")

        for message in group:
            self._mark_notified(message["message_id"])

    def _is_important_enough(self, message: dict) -> bool:
        order = {"low": 0, "medium": 1, "high": 2}
        threshold = order.get(self.importance_threshold, 2)
        actual = order.get(message.get("importance", "low"), 0)
        return actual >= threshold

    def _create_proactive_conversation(self, message: str) -> None:
        try:
            response = httpx.post(
                f"{self.local_url}/api/desktop/pepo/conversations/proactive",
                json={"first_message": message},
                headers=self._headers(),
                timeout=10.0,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"OutlookWatcherAgent: fallo creando conversacion proactiva: {e}")

    # ── Deduplicacion persistente ────────────────────────────────────────────

    def _load_notified_ids(self) -> set[str]:
        try:
            if self._notified_path.exists():
                return set(json.loads(self._notified_path.read_text(encoding="utf-8")))
        except Exception:
            pass
        return set()

    def _mark_notified(self, message_id: str) -> None:
        self._notified_ids.add(message_id)
        # Tope simple — nunca crece sin limite. No importa el orden exacto
        # de lo que se descarta, solo que no se acumule para siempre.
        if len(self._notified_ids) > _MAX_NOTIFIED_IDS:
            self._notified_ids = set(list(self._notified_ids)[-_MAX_NOTIFIED_IDS:])
        try:
            tmp_path = self._notified_path.with_suffix(f".tmp-{uuid.uuid4().hex[:8]}")
            tmp_path.write_text(json.dumps(sorted(self._notified_ids)), encoding="utf-8")
            tmp_path.replace(self._notified_path)
        except Exception as e:
            logger.error(f"OutlookWatcherAgent: fallo guardando dedup: {e}")
