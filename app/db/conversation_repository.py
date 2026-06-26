"""
app/db/conversation_repository.py
-----------------------------------
Repositorio de conversaciones sobre MongoDB.

Encapsula TODAS las operaciones sobre la colección `conversations`.
Usa asyncio.to_thread() para no bloquear el event loop con PyMongo sync.

Upgrade path:
  - Phase 2: reemplazar PyMongo + asyncio.to_thread() por Motor (asyncio nativo).
  - La interfaz pública de esta clase NO cambiará al hacer ese upgrade.

Uso:
    repo = ConversationRepository(collection)
    await repo.guardar(username, query, response, thinking, audit)
    historial = await repo.listar(username, limit=10)
    conv = await repo.obtener(conversation_id)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from loguru import logger


class ConversationRepository:
    """
    Repositorio de conversaciones.
    Acepta None como colección — devuelve resultados vacíos si MongoDB no está disponible.
    """

    def __init__(self, collection: Any | None) -> None:
        self._col = collection

    @property
    def disponible(self) -> bool:
        return self._col is not None

    # ── Escritura ─────────────────────────────────────────────────────────────

    async def guardar(
        self,
        username: str,
        query: str,
        response: str,
        thinking: str = "",
        audit: dict[str, Any] | None = None,
        intencion: str = "general",
        agente: str = "",
    ) -> str | None:
        """
        Guarda una conversación. Devuelve el ID insertado, o None si MongoDB no disponible.
        Nunca lanza excepciones — loguea y continúa.
        """
        if not self.disponible:
            return None

        doc = {
            "username":   username,
            "query":      query,
            "response":   response,
            "thinking":   thinking,
            "audit":      audit or {},
            "intencion":  intencion,
            "agente":     agente,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }

        try:
            result = await asyncio.to_thread(self._col.insert_one, doc)
            inserted_id = str(result.inserted_id)
            logger.debug(
                "ConversationRepository: guardada | usuario={} | id={}",
                username, inserted_id,
            )
            return inserted_id
        except Exception as e:
            logger.error(
                "ConversationRepository: error guardando | usuario={} | {}",
                username, e,
            )
            return None

    # ── Lectura ───────────────────────────────────────────────────────────────

    async def listar(
        self,
        username: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Devuelve las últimas `limit` conversaciones de un usuario.
        Devuelve lista vacía si MongoDB no está disponible o hay error.
        """
        if not self.disponible:
            return []

        try:
            docs = await asyncio.to_thread(
                lambda: list(
                    self._col.find({"username": username})
                    .sort("timestamp", -1)
                    .limit(limit)
                )
            )
            return [self._serializar(doc) for doc in docs]

        except Exception as e:
            logger.error(
                "ConversationRepository: error listando | usuario={} | {}",
                username, e,
            )
            return []

    async def obtener(self, conversation_id: str) -> dict[str, Any] | None:
        """
        Devuelve una conversación por ID, o None si no existe o hay error.
        """
        if not self.disponible:
            return None

        try:
            oid = ObjectId(conversation_id)
        except Exception:
            logger.warning(
                "ConversationRepository: ObjectId inválido | id={}",
                conversation_id,
            )
            return None

        try:
            doc = await asyncio.to_thread(self._col.find_one, {"_id": oid})
            return self._serializar(doc) if doc else None
        except Exception as e:
            logger.error(
                "ConversationRepository: error obteniendo | id={} | {}",
                conversation_id, e,
            )
            return None

    # ── Mutaciones ────────────────────────────────────────────────────────────

    async def eliminar(self, conversation_id: str) -> bool:
        """
        Elimina una conversación por ID.
        Devuelve True si se eliminó, False si no existía o hay error.
        """
        if not self.disponible:
            return False

        try:
            oid = ObjectId(conversation_id)
        except Exception:
            logger.warning("ConversationRepository: ObjectId inválido | id={}", conversation_id)
            return False

        try:
            result = await asyncio.to_thread(self._col.delete_one, {"_id": oid})
            deleted = result.deleted_count > 0
            logger.debug("ConversationRepository: eliminar | id={} | deleted={}", conversation_id, deleted)
            return deleted
        except Exception as e:
            logger.error("ConversationRepository: error eliminando | id={} | {}", conversation_id, e)
            return False

    async def actualizar_carpeta(self, conversation_id: str, folder: str) -> bool:
        """Asigna una carpeta a una conversación. Devuelve True si actualizó."""
        if not self.disponible:
            return False

        try:
            oid = ObjectId(conversation_id)
        except Exception:
            logger.warning("ConversationRepository: ObjectId inválido | id={}", conversation_id)
            return False

        try:
            result = await asyncio.to_thread(
                self._col.update_one,
                {"_id": oid},
                {"$set": {"folder": folder}},
            )
            return result.matched_count > 0
        except Exception as e:
            logger.error("ConversationRepository: error actualizando carpeta | id={} | {}", conversation_id, e)
            return False

    async def guardar_canvas(
        self,
        conversation_id: str,
        content: str,
        canvas_type: str = "code",
    ) -> bool:
        """Persiste el contenido del Canvas en la conversación. Devuelve True si actualizó."""
        if not self.disponible:
            return False

        try:
            oid = ObjectId(conversation_id)
        except Exception:
            logger.warning("ConversationRepository: ObjectId inválido | id={}", conversation_id)
            return False

        try:
            result = await asyncio.to_thread(
                self._col.update_one,
                {"_id": oid},
                {"$set": {"canvas_content": content, "canvas_type": canvas_type}},
            )
            return result.matched_count > 0
        except Exception as e:
            logger.error("ConversationRepository: error guardando canvas | id={} | {}", conversation_id, e)
            return False

    async def toggle_favorito(self, conversation_id: str) -> bool | None:
        """
        Alterna el campo `favorite` de una conversación.
        Devuelve el nuevo valor (True/False), o None si no existe o hay error.
        """
        if not self.disponible:
            return None

        try:
            oid = ObjectId(conversation_id)
        except Exception:
            logger.warning("ConversationRepository: ObjectId inválido | id={}", conversation_id)
            return None

        try:
            doc = await asyncio.to_thread(self._col.find_one, {"_id": oid}, {"favorite": 1})
            if not doc:
                return None
            nuevo_valor = not bool(doc.get("favorite", False))
            await asyncio.to_thread(
                self._col.update_one,
                {"_id": oid},
                {"$set": {"favorite": nuevo_valor}},
            )
            return nuevo_valor
        except Exception as e:
            logger.error("ConversationRepository: error toggling favorito | id={} | {}", conversation_id, e)
            return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _serializar(doc: dict[str, Any]) -> dict[str, Any]:
        """Convierte ObjectId a str para que sea JSON-serializable."""
        doc = dict(doc)
        doc["_id"] = str(doc["_id"])
        return doc

    @staticmethod
    def _preview(texto: str, max_len: int = 100) -> str:
        return texto[:max_len - 3] + "..." if len(texto) > max_len else texto

    def formatear_para_api(self, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Transforma documentos crudos al formato que espera /api/history.
        Separado de listar() para que sea testeable independientemente.
        """
        resultado = []
        for doc in docs:
            ts = doc.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
                display_time = dt.strftime("%d/%m/%Y %H:%M") if dt else "Sin fecha"
            except Exception:
                display_time = "Sin fecha"

            resultado.append({
                "id":           doc.get("_id", ""),
                "query":        doc.get("query", ""),
                "response":     doc.get("response", ""),
                "timestamp":    ts,
                "intencion":    doc.get("intencion", "general"),
                "agente":       doc.get("agente", ""),
                "thinking":     doc.get("thinking", ""),
                "preview":      self._preview(doc.get("query", "")),
                "display_time": display_time,
            })
        return resultado
