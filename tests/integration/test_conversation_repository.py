"""
tests/integration/test_conversation_repository.py
----------------------------------------------------
Tests de integración para ConversationRepository.

Estrategia:
  - MongoDB mockeado con MagicMock + asyncio.to_thread interceptado
  - Cada método de PyMongo (_col.insert_one, find, etc.) es un MagicMock
  - Se prueba el comportamiento del repositorio, no MongoDB en sí
  - Los tests cubren: flujo feliz, MongoDB=None (disponible=False),
    ObjectId inválido, excepciones de red y edge cases
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId


# ── Helpers ───────────────────────────────────────────────────────────────────

_OID_STR  = "507f1f77bcf86cd799439011"
_OID      = ObjectId(_OID_STR)

def _make_doc(**kwargs):
    """Crea un documento MongoDB mock (con _id como ObjectId)."""
    base = {
        "_id":       _OID,
        "username":  "testuser",
        "query":     "Consulta de prueba",
        "response":  "Respuesta de prueba",
        "thinking":  "",
        "audit":     {},
        "intencion": "general",
        "agente":    "GenerationAgent",
        "timestamp": "2026-04-07T10:00:00+00:00",
    }
    base.update(kwargs)
    return base


@pytest.fixture
def repo():
    """ConversationRepository con colección mockeada."""
    col = MagicMock()
    # Simular inserted_id para insert_one
    inserted = MagicMock()
    inserted.inserted_id = _OID
    col.insert_one = MagicMock(return_value=inserted)

    # find().sort().limit() — chain de mocks
    cursor = MagicMock()
    cursor.__iter__ = MagicMock(return_value=iter([_make_doc()]))
    col.find = MagicMock(return_value=cursor)
    cursor.sort = MagicMock(return_value=cursor)
    cursor.limit = MagicMock(return_value=cursor)

    col.find_one   = MagicMock(return_value=_make_doc())
    col.delete_one = MagicMock(return_value=MagicMock(deleted_count=1))
    col.update_one = MagicMock(return_value=MagicMock(matched_count=1))

    from db.conversation_repository import ConversationRepository
    return ConversationRepository(col), col


@pytest.fixture
def repo_sin_mongo():
    from db.conversation_repository import ConversationRepository
    return ConversationRepository(None)


# ═══════════════════════════════════════════════════════════════════════════════
# disponible
# ═══════════════════════════════════════════════════════════════════════════════

class TestDisponible:
    def test_con_coleccion_es_disponible(self, repo):
        r, _ = repo
        assert r.disponible is True

    def test_sin_coleccion_no_disponible(self, repo_sin_mongo):
        assert repo_sin_mongo.disponible is False


# ═══════════════════════════════════════════════════════════════════════════════
# guardar
# ═══════════════════════════════════════════════════════════════════════════════

class TestGuardar:

    @pytest.mark.asyncio
    async def test_guardar_devuelve_id_string(self, repo):
        r, _ = repo
        id_ = await r.guardar("user", "query", "response")
        assert isinstance(id_, str)
        assert id_ == _OID_STR

    @pytest.mark.asyncio
    async def test_guardar_sin_mongo_devuelve_none(self, repo_sin_mongo):
        id_ = await repo_sin_mongo.guardar("user", "query", "response")
        assert id_ is None

    @pytest.mark.asyncio
    async def test_guardar_llama_insert_one(self, repo):
        r, col = repo
        await r.guardar("user", "query", "resp")
        col.insert_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_guardar_doc_contiene_campos_obligatorios(self, repo):
        r, col = repo
        await r.guardar("testuser", "mi query", "mi respuesta", thinking="pens")
        doc = col.insert_one.call_args.args[0]
        assert doc["username"]  == "testuser"
        assert doc["query"]     == "mi query"
        assert doc["response"]  == "mi respuesta"
        assert doc["thinking"]  == "pens"
        assert "timestamp" in doc

    @pytest.mark.asyncio
    async def test_guardar_con_audit(self, repo):
        r, col = repo
        audit = {"agent": "SSHAgent", "success": True}
        await r.guardar("user", "q", "r", audit=audit)
        doc = col.insert_one.call_args.args[0]
        assert doc["audit"] == audit

    @pytest.mark.asyncio
    async def test_guardar_excepcion_devuelve_none(self, repo):
        r, col = repo
        col.insert_one.side_effect = Exception("DB error")
        id_ = await r.guardar("user", "query", "response")
        assert id_ is None  # Nunca lanza


# ═══════════════════════════════════════════════════════════════════════════════
# listar
# ═══════════════════════════════════════════════════════════════════════════════

class TestListar:

    @pytest.mark.asyncio
    async def test_listar_devuelve_lista(self, repo):
        r, _ = repo
        docs = await r.listar("testuser")
        assert isinstance(docs, list)
        assert len(docs) == 1

    @pytest.mark.asyncio
    async def test_listar_sin_mongo_devuelve_lista_vacia(self, repo_sin_mongo):
        docs = await repo_sin_mongo.listar("user")
        assert docs == []

    @pytest.mark.asyncio
    async def test_listar_ids_son_strings(self, repo):
        r, _ = repo
        docs = await r.listar("testuser")
        for doc in docs:
            assert isinstance(doc["_id"], str)

    @pytest.mark.asyncio
    async def test_listar_con_limit(self, repo):
        r, col = repo
        cursor = col.find.return_value
        await r.listar("user", limit=5)
        cursor.limit.assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_listar_orden_descendente(self, repo):
        r, col = repo
        cursor = col.find.return_value
        await r.listar("user")
        cursor.sort.assert_called_once_with("timestamp", -1)

    @pytest.mark.asyncio
    async def test_listar_excepcion_devuelve_lista_vacia(self, repo):
        r, col = repo
        col.find.side_effect = Exception("network error")
        docs = await r.listar("user")
        assert docs == []


# ═══════════════════════════════════════════════════════════════════════════════
# obtener
# ═══════════════════════════════════════════════════════════════════════════════

class TestObtener:

    @pytest.mark.asyncio
    async def test_obtener_existente_devuelve_doc(self, repo):
        r, _ = repo
        doc = await r.obtener(_OID_STR)
        assert doc is not None
        assert doc["_id"] == _OID_STR

    @pytest.mark.asyncio
    async def test_obtener_no_existente_devuelve_none(self, repo):
        r, col = repo
        col.find_one.return_value = None
        doc = await r.obtener(_OID_STR)
        assert doc is None

    @pytest.mark.asyncio
    async def test_obtener_sin_mongo_devuelve_none(self, repo_sin_mongo):
        doc = await repo_sin_mongo.obtener(_OID_STR)
        assert doc is None

    @pytest.mark.asyncio
    async def test_obtener_oid_invalido_devuelve_none(self, repo):
        r, col = repo
        doc = await r.obtener("no-es-un-objectid")
        assert doc is None
        col.find_one.assert_not_called()  # No debe intentar la query con OID inválido

    @pytest.mark.asyncio
    async def test_obtener_excepcion_devuelve_none(self, repo):
        r, col = repo
        col.find_one.side_effect = Exception("timeout")
        doc = await r.obtener(_OID_STR)
        assert doc is None


# ═══════════════════════════════════════════════════════════════════════════════
# eliminar
# ═══════════════════════════════════════════════════════════════════════════════

class TestEliminar:

    @pytest.mark.asyncio
    async def test_eliminar_existente_devuelve_true(self, repo):
        r, _ = repo
        ok = await r.eliminar(_OID_STR)
        assert ok is True

    @pytest.mark.asyncio
    async def test_eliminar_no_existente_devuelve_false(self, repo):
        r, col = repo
        col.delete_one.return_value = MagicMock(deleted_count=0)
        ok = await r.eliminar(_OID_STR)
        assert ok is False

    @pytest.mark.asyncio
    async def test_eliminar_sin_mongo_devuelve_false(self, repo_sin_mongo):
        ok = await repo_sin_mongo.eliminar(_OID_STR)
        assert ok is False

    @pytest.mark.asyncio
    async def test_eliminar_oid_invalido_devuelve_false(self, repo):
        r, col = repo
        ok = await r.eliminar("id-invalido")
        assert ok is False
        col.delete_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_eliminar_excepcion_devuelve_false(self, repo):
        r, col = repo
        col.delete_one.side_effect = Exception("timeout")
        ok = await r.eliminar(_OID_STR)
        assert ok is False


# ═══════════════════════════════════════════════════════════════════════════════
# actualizar_carpeta
# ═══════════════════════════════════════════════════════════════════════════════

class TestActualizarCarpeta:

    @pytest.mark.asyncio
    async def test_actualiza_carpeta_devuelve_true(self, repo):
        r, _ = repo
        ok = await r.actualizar_carpeta(_OID_STR, "Proyectos")
        assert ok is True

    @pytest.mark.asyncio
    async def test_no_encontrado_devuelve_false(self, repo):
        r, col = repo
        col.update_one.return_value = MagicMock(matched_count=0)
        ok = await r.actualizar_carpeta(_OID_STR, "Carpeta")
        assert ok is False

    @pytest.mark.asyncio
    async def test_sin_mongo_devuelve_false(self, repo_sin_mongo):
        ok = await repo_sin_mongo.actualizar_carpeta(_OID_STR, "X")
        assert ok is False

    @pytest.mark.asyncio
    async def test_oid_invalido_devuelve_false(self, repo):
        r, col = repo
        ok = await r.actualizar_carpeta("bad-id", "Carpeta")
        assert ok is False
        col.update_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_one_llama_con_campo_folder(self, repo):
        r, col = repo
        await r.actualizar_carpeta(_OID_STR, "MI_CARPETA")
        call_args = col.update_one.call_args
        update_op = call_args.args[1]
        assert update_op["$set"]["folder"] == "MI_CARPETA"


# ═══════════════════════════════════════════════════════════════════════════════
# guardar_canvas
# ═══════════════════════════════════════════════════════════════════════════════

class TestGuardarCanvas:

    @pytest.mark.asyncio
    async def test_guardar_canvas_devuelve_true(self, repo):
        r, _ = repo
        ok = await r.guardar_canvas(_OID_STR, "print('hello')", "code")
        assert ok is True

    @pytest.mark.asyncio
    async def test_sin_mongo_devuelve_false(self, repo_sin_mongo):
        ok = await repo_sin_mongo.guardar_canvas(_OID_STR, "content", "text")
        assert ok is False

    @pytest.mark.asyncio
    async def test_update_incluye_content_y_type(self, repo):
        r, col = repo
        await r.guardar_canvas(_OID_STR, "SELECT * FROM x", "code")
        update_op = col.update_one.call_args.args[1]
        assert update_op["$set"]["canvas_content"] == "SELECT * FROM x"
        assert update_op["$set"]["canvas_type"] == "code"

    @pytest.mark.asyncio
    async def test_tipo_default_es_code(self, repo):
        r, col = repo
        await r.guardar_canvas(_OID_STR, "content")
        update_op = col.update_one.call_args.args[1]
        assert update_op["$set"]["canvas_type"] == "code"

    @pytest.mark.asyncio
    async def test_oid_invalido_devuelve_false(self, repo):
        r, col = repo
        ok = await r.guardar_canvas("bad-oid", "content")
        assert ok is False
        col.update_one.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# toggle_favorito
# ═══════════════════════════════════════════════════════════════════════════════

class TestToggleFavorito:

    def _setup_find_one_favorito(self, col, favorite_value):
        col.find_one.return_value = {"_id": _OID, "favorite": favorite_value}

    @pytest.mark.asyncio
    async def test_toggle_de_false_a_true(self, repo):
        r, col = repo
        self._setup_find_one_favorito(col, False)
        nuevo = await r.toggle_favorito(_OID_STR)
        assert nuevo is True

    @pytest.mark.asyncio
    async def test_toggle_de_true_a_false(self, repo):
        r, col = repo
        self._setup_find_one_favorito(col, True)
        nuevo = await r.toggle_favorito(_OID_STR)
        assert nuevo is False

    @pytest.mark.asyncio
    async def test_toggle_sin_campo_favorite_trata_como_false(self, repo):
        r, col = repo
        col.find_one.return_value = {"_id": _OID}  # Sin campo favorite
        nuevo = await r.toggle_favorito(_OID_STR)
        assert nuevo is True  # False → True

    @pytest.mark.asyncio
    async def test_toggle_doc_no_encontrado_devuelve_none(self, repo):
        r, col = repo
        col.find_one.return_value = None
        nuevo = await r.toggle_favorito(_OID_STR)
        assert nuevo is None

    @pytest.mark.asyncio
    async def test_toggle_sin_mongo_devuelve_none(self, repo_sin_mongo):
        nuevo = await repo_sin_mongo.toggle_favorito(_OID_STR)
        assert nuevo is None

    @pytest.mark.asyncio
    async def test_toggle_oid_invalido_devuelve_none(self, repo):
        r, col = repo
        nuevo = await r.toggle_favorito("bad-oid")
        assert nuevo is None
        col.find_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_toggle_excepcion_devuelve_none(self, repo):
        r, col = repo
        col.find_one.side_effect = Exception("timeout")
        nuevo = await r.toggle_favorito(_OID_STR)
        assert nuevo is None


# ═══════════════════════════════════════════════════════════════════════════════
# _serializar y formatear_para_api
# ═══════════════════════════════════════════════════════════════════════════════

class TestSerializarYFormatear:

    def test_serializar_convierte_objectid_a_str(self):
        from db.conversation_repository import ConversationRepository
        doc = {"_id": _OID, "username": "u", "query": "q"}
        serializado = ConversationRepository._serializar(doc)
        assert isinstance(serializado["_id"], str)
        assert serializado["_id"] == _OID_STR

    def test_serializar_preserva_otros_campos(self):
        from db.conversation_repository import ConversationRepository
        doc = {"_id": _OID, "username": "user1", "response": "resp"}
        s = ConversationRepository._serializar(doc)
        assert s["username"] == "user1"
        assert s["response"] == "resp"

    def test_preview_trunca_texto_largo(self):
        from db.conversation_repository import ConversationRepository
        largo = "A" * 200
        prev = ConversationRepository._preview(largo, max_len=100)
        assert len(prev) == 100
        assert prev.endswith("...")

    def test_preview_texto_corto_sin_truncar(self):
        from db.conversation_repository import ConversationRepository
        corto = "texto corto"
        assert ConversationRepository._preview(corto) == corto

    def test_formatear_para_api_campos_correctos(self):
        from db.conversation_repository import ConversationRepository
        repo = ConversationRepository(None)
        docs = [_make_doc()]
        # Necesita _id como string
        docs[0]["_id"] = _OID_STR
        resultado = repo.formatear_para_api(docs)
        assert len(resultado) == 1
        item = resultado[0]
        assert "id" in item
        assert "query" in item
        assert "response" in item
        assert "preview" in item
        assert "display_time" in item

    def test_formatear_timestamp_invalido_devuelve_sin_fecha(self):
        from db.conversation_repository import ConversationRepository
        repo = ConversationRepository(None)
        docs = [_make_doc()]
        docs[0]["_id"] = _OID_STR
        docs[0]["timestamp"] = "fecha-invalida"
        resultado = repo.formatear_para_api(docs)
        assert resultado[0]["display_time"] == "Sin fecha"
