"""
tests/e2e/test_api_crud.py
----------------------------
Tests E2E para:
  - DELETE /api/conversation/{id}
  - PATCH  /api/conversation/{id}/folder
  - POST   /api/conversation/{id}/favorite
  - POST   /api/canvas/save
  - GET    /chat/stream/{task_id}  (SSE)

NOTAS DE IMPLEMENTACIÓN:
- raise_server_exceptions=True en todos los clientes: las excepciones no controladas
  se propagan al test (error real, no 500 silencioso).
  Las HTTPException de FastAPI NO se ven afectadas — devuelven su código correcto.
- Los tests de "sin auth" usan el fixture autenticado y limpian las cookies,
  evitando el anti-patrón `next(generator)` que no limpia context managers.
- Los tests que necesitan variar el comportamiento del repo (403, 500...)
  mutan el mock_repo DENTRO del fixture, no crean un cliente nuevo.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Constantes de test ────────────────────────────────────────────────────────

_FAKE_OID = "507f1f77bcf86cd799439011"
_FAKE_CONV = {
    "_id":      _FAKE_OID,
    "username": "testuser",
    "query":    "Consulta de test",
    "response": "Respuesta de test",
    "thinking": "",
    "favorite": False,
    "folder":   "",
}


# ── Fixture base ──────────────────────────────────────────────────────────────

def _build_client(test_config, mock_llm_router, conv_doc):
    """
    Genera un TestClient con ConversationRepository mockeado.
    conv_doc: documento que devuelve repo.obtener() (None = no encontrado).

    Se usa SÓLO a través de fixtures con 'yield from' para garantizar
    que los context managers se limpian correctamente.
    """
    mock_redis = AsyncMock()
    mock_redis.ping      = AsyncMock(return_value=True)
    mock_redis.lpush     = AsyncMock(return_value=1)
    mock_redis.rpop      = AsyncMock(return_value=None)
    mock_redis.aclose    = AsyncMock()

    mock_repo = MagicMock()
    mock_repo.disponible          = True
    mock_repo.obtener             = AsyncMock(return_value=conv_doc)
    mock_repo.eliminar            = AsyncMock(return_value=True)
    mock_repo.actualizar_carpeta  = AsyncMock(return_value=True)
    mock_repo.toggle_favorito     = AsyncMock(return_value=True)
    mock_repo.guardar_canvas      = AsyncMock(return_value=True)
    mock_repo.listar              = AsyncMock(return_value=[])
    mock_repo.formatear_para_api  = MagicMock(return_value=[])

    with patch("main._redis", mock_redis), \
         patch("main.cfg", test_config), \
         patch("agents.llm_router._router", mock_llm_router):

        import main as app_module
        from utils.session_auth import SessionAuth
        app_module._session_auth = SessionAuth(test_config)
        app_module._redis        = mock_redis
        app_module.app.state.repo = mock_repo

        with TestClient(app_module.app, raise_server_exceptions=True) as client:
            client.post(
                "/login",
                data={"username": "testuser", "password": "testpass"},
                follow_redirects=False,
            )
            yield client, mock_repo


@pytest.fixture
def authed_client_with_conv(test_config, mock_llm_router):
    """Cliente autenticado con conversación existente."""
    yield from _build_client(test_config, mock_llm_router, _FAKE_CONV)


@pytest.fixture
def authed_client_no_conv(test_config, mock_llm_router):
    """Cliente autenticado pero sin conversación (obtener → None)."""
    yield from _build_client(test_config, mock_llm_router, conv_doc=None)


# ═══════════════════════════════════════════════════════════════════════════════
# DELETE /api/conversation/{id}
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeleteConversation:

    def test_delete_existente_devuelve_200(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        resp = client.delete(f"/api/conversation/{_FAKE_OID}")
        assert resp.status_code == 200

    def test_delete_existente_body_correcto(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        resp = client.delete(f"/api/conversation/{_FAKE_OID}")
        body = resp.json()
        assert body["status"] == "success"
        assert body["deleted"] == _FAKE_OID

    def test_delete_llama_a_repo_eliminar(self, authed_client_with_conv):
        client, mock_repo = authed_client_with_conv
        client.delete(f"/api/conversation/{_FAKE_OID}")
        mock_repo.eliminar.assert_called_once_with(_FAKE_OID)

    def test_delete_no_encontrado_devuelve_404(self, authed_client_no_conv):
        client, _ = authed_client_no_conv
        resp = client.delete(f"/api/conversation/{_FAKE_OID}")
        assert resp.status_code == 404

    def test_delete_sin_auth_devuelve_401(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        client.cookies.clear()
        resp = client.delete(f"/api/conversation/{_FAKE_OID}")
        assert resp.status_code == 401

    def test_delete_otro_usuario_devuelve_403(self, authed_client_with_conv):
        client, mock_repo = authed_client_with_conv
        mock_repo.obtener = AsyncMock(
            return_value={**_FAKE_CONV, "username": "otro_usuario"}
        )
        resp = client.delete(f"/api/conversation/{_FAKE_OID}")
        assert resp.status_code == 403

    def test_delete_cuando_repo_falla_devuelve_500(self, authed_client_with_conv):
        client, mock_repo = authed_client_with_conv
        mock_repo.eliminar = AsyncMock(return_value=False)
        resp = client.delete(f"/api/conversation/{_FAKE_OID}")
        assert resp.status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# PATCH /api/conversation/{id}/folder
# ═══════════════════════════════════════════════════════════════════════════════

class TestUpdateConversationFolder:

    def test_patch_folder_devuelve_200(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        resp = client.patch(
            f"/api/conversation/{_FAKE_OID}/folder",
            json={"folder": "Proyectos"},
        )
        assert resp.status_code == 200

    def test_patch_folder_body_correcto(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        resp = client.patch(
            f"/api/conversation/{_FAKE_OID}/folder",
            json={"folder": "Trabajo"},
        )
        body = resp.json()
        assert body["status"] == "success"
        assert body["folder"] == "Trabajo"
        assert body["conversation_id"] == _FAKE_OID

    def test_patch_folder_llama_a_repo_con_valor_correcto(self, authed_client_with_conv):
        client, mock_repo = authed_client_with_conv
        client.patch(
            f"/api/conversation/{_FAKE_OID}/folder",
            json={"folder": "MiCarpeta"},
        )
        mock_repo.actualizar_carpeta.assert_called_once_with(_FAKE_OID, "MiCarpeta")

    def test_patch_folder_no_encontrado_devuelve_404(self, authed_client_no_conv):
        client, _ = authed_client_no_conv
        resp = client.patch(
            f"/api/conversation/{_FAKE_OID}/folder",
            json={"folder": "X"},
        )
        assert resp.status_code == 404

    def test_patch_folder_sin_auth_devuelve_401(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        client.cookies.clear()
        resp = client.patch(
            f"/api/conversation/{_FAKE_OID}/folder",
            json={"folder": "X"},
        )
        assert resp.status_code == 401

    def test_patch_folder_sin_body_devuelve_422(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        resp = client.patch(f"/api/conversation/{_FAKE_OID}/folder")
        assert resp.status_code == 422

    def test_patch_folder_otro_usuario_devuelve_403(self, authed_client_with_conv):
        client, mock_repo = authed_client_with_conv
        mock_repo.obtener = AsyncMock(
            return_value={**_FAKE_CONV, "username": "otro_usuario"}
        )
        resp = client.patch(
            f"/api/conversation/{_FAKE_OID}/folder",
            json={"folder": "X"},
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/conversation/{id}/favorite
# ═══════════════════════════════════════════════════════════════════════════════

class TestToggleConversationFavorite:

    def test_toggle_favorite_devuelve_200(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        resp = client.post(f"/api/conversation/{_FAKE_OID}/favorite")
        assert resp.status_code == 200

    def test_toggle_favorite_body_tiene_campo_favorite(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        resp = client.post(f"/api/conversation/{_FAKE_OID}/favorite")
        body = resp.json()
        assert body["status"] == "success"
        assert "favorite" in body
        assert body["conversation_id"] == _FAKE_OID

    def test_toggle_favorite_valor_es_booleano(self, authed_client_with_conv):
        client, mock_repo = authed_client_with_conv
        mock_repo.toggle_favorito = AsyncMock(return_value=True)
        resp = client.post(f"/api/conversation/{_FAKE_OID}/favorite")
        assert resp.json()["favorite"] is True

    def test_toggle_favorite_llama_a_repo(self, authed_client_with_conv):
        client, mock_repo = authed_client_with_conv
        client.post(f"/api/conversation/{_FAKE_OID}/favorite")
        mock_repo.toggle_favorito.assert_called_once_with(_FAKE_OID)

    def test_toggle_favorite_no_encontrado_devuelve_404(self, authed_client_no_conv):
        client, _ = authed_client_no_conv
        resp = client.post(f"/api/conversation/{_FAKE_OID}/favorite")
        assert resp.status_code == 404

    def test_toggle_favorite_sin_auth_devuelve_401(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        client.cookies.clear()
        resp = client.post(f"/api/conversation/{_FAKE_OID}/favorite")
        assert resp.status_code == 401

    def test_toggle_favorite_repo_devuelve_none_da_500(self, authed_client_with_conv):
        client, mock_repo = authed_client_with_conv
        mock_repo.toggle_favorito = AsyncMock(return_value=None)
        resp = client.post(f"/api/conversation/{_FAKE_OID}/favorite")
        assert resp.status_code == 500

    def test_toggle_favorite_otro_usuario_devuelve_403(self, authed_client_with_conv):
        client, mock_repo = authed_client_with_conv
        mock_repo.obtener = AsyncMock(
            return_value={**_FAKE_CONV, "username": "otro_usuario"}
        )
        resp = client.post(f"/api/conversation/{_FAKE_OID}/favorite")
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/canvas/save
# ═══════════════════════════════════════════════════════════════════════════════

class TestSaveCanvas:

    def _payload(self, conv_id=_FAKE_OID, content="print('hello')", canvas_type="code"):
        return {"conversation_id": conv_id, "content": content, "type": canvas_type}

    def test_canvas_save_devuelve_200(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        resp = client.post("/api/canvas/save", json=self._payload())
        assert resp.status_code == 200

    def test_canvas_save_body_correcto(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        resp = client.post("/api/canvas/save", json=self._payload())
        assert resp.json()["status"] == "success"

    def test_canvas_save_llama_repo_con_args_correctos(self, authed_client_with_conv):
        client, mock_repo = authed_client_with_conv
        client.post("/api/canvas/save", json=self._payload(
            content="SELECT * FROM users", canvas_type="code"
        ))
        mock_repo.guardar_canvas.assert_called_once_with(
            _FAKE_OID, "SELECT * FROM users", "code"
        )

    def test_canvas_save_sin_conversation_id_devuelve_400(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        resp = client.post("/api/canvas/save", json={"content": "algo", "type": "code"})
        assert resp.status_code == 400

    def test_canvas_save_conversacion_no_encontrada_devuelve_404(self, authed_client_no_conv):
        client, _ = authed_client_no_conv
        resp = client.post("/api/canvas/save", json=self._payload())
        assert resp.status_code == 404

    def test_canvas_save_sin_auth_devuelve_401(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        client.cookies.clear()
        resp = client.post("/api/canvas/save", json=self._payload())
        assert resp.status_code == 401

    def test_canvas_save_tipo_text_aceptado(self, authed_client_with_conv):
        client, mock_repo = authed_client_with_conv
        resp = client.post("/api/canvas/save", json=self._payload(
            content="Texto libre", canvas_type="text"
        ))
        assert resp.status_code == 200
        mock_repo.guardar_canvas.assert_called_once_with(_FAKE_OID, "Texto libre", "text")


# ═══════════════════════════════════════════════════════════════════════════════
# GET /chat/stream/{task_id}  — SSE endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatStreamEndpoint:
    """
    El SSE endpoint no puede testearse en streaming real con TestClient síncrono
    (TestClient consume la respuesta completa). Se verifica:
    - Autenticación
    - Content-Type: text/event-stream
    - Headers anti-caché
    - Formato SSE de los datos emitidos
    - Terminación correcta con evento done/error
    """

    def _make_done_pubsub(self, data: dict):
        """Pubsub mock que emite un único mensaje y luego None."""
        message = {
            "type":    "message",
            "data":    json.dumps(data),
            "channel": "nexus_stream:test",
        }
        calls = [0]

        def _get_message(ignore_subscribe_messages=True):
            if calls[0] == 0:
                calls[0] += 1
                return message
            return None

        pubsub = AsyncMock()
        pubsub.subscribe   = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose      = AsyncMock()
        pubsub.get_message = MagicMock(side_effect=_get_message)
        return pubsub

    def test_stream_sin_auth_devuelve_401(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        client.cookies.clear()
        resp = client.get("/chat/stream/fake-task-id")
        assert resp.status_code == 401

    def test_stream_content_type_es_event_stream(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        import main as app_module
        # app_module._redis es None cuando no hay Redis real disponible en el
        # entorno (el lifespan de main.py lo deja en None si el ping falla al
        # arrancar) — se sustituye el objeto entero, no solo .pubsub, para que
        # el test sea autonomo y no dependa de tener Redis corriendo.
        app_module._redis = AsyncMock()
        app_module._redis.pubsub = MagicMock(
            return_value=self._make_done_pubsub({"type": "done"})
        )
        resp = client.get("/chat/stream/test-task")
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_stream_header_no_cache(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        import main as app_module
        # app_module._redis es None cuando no hay Redis real disponible en el
        # entorno (el lifespan de main.py lo deja en None si el ping falla al
        # arrancar) — se sustituye el objeto entero, no solo .pubsub, para que
        # el test sea autonomo y no dependa de tener Redis corriendo.
        app_module._redis = AsyncMock()
        app_module._redis.pubsub = MagicMock(
            return_value=self._make_done_pubsub({"type": "done"})
        )
        resp = client.get("/chat/stream/test-task")
        assert resp.headers.get("cache-control") == "no-cache"

    def test_stream_emite_formato_sse_correcto(self, authed_client_with_conv):
        """Cada evento SSE debe estar en formato 'data: {...}\\n\\n'."""
        client, _ = authed_client_with_conv
        import main as app_module
        # Dos mensajes: un chunk y luego done
        messages_data = [
            {"type": "chunk", "content": "Hola"},
            {"type": "done"},
        ]
        call_n = [0]
        def _get_message(ignore_subscribe_messages=True):
            if call_n[0] < len(messages_data):
                msg = {
                    "type": "message",
                    "data": json.dumps(messages_data[call_n[0]]),
                    "channel": "nexus_stream:t",
                }
                call_n[0] += 1
                return msg
            return None
        pubsub = AsyncMock()
        pubsub.subscribe   = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose      = AsyncMock()
        pubsub.get_message = MagicMock(side_effect=_get_message)
        app_module._redis = AsyncMock()
        app_module._redis.pubsub = MagicMock(return_value=pubsub)

        resp = client.get("/chat/stream/test-task")
        # El cuerpo debe contener líneas con "data:"
        assert "data:" in resp.text
        assert "Hola" in resp.text

    def test_stream_evento_error_termina_stream(self, authed_client_with_conv):
        client, _ = authed_client_with_conv
        import main as app_module
        app_module._redis = AsyncMock()
        app_module._redis.pubsub = MagicMock(
            return_value=self._make_done_pubsub({"type": "error", "content": "Fallo"})
        )
        resp = client.get("/chat/stream/test-task")
        assert "error" in resp.text


# ═══════════════════════════════════════════════════════════════════════════════
# MongoDB no disponible → 503 en todos los endpoints CRUD
# ═══════════════════════════════════════════════════════════════════════════════

class TestCrudEndpointsSinMongo:
    """Cuando MongoDB no está disponible, todos los CRUD devuelven 503."""

    @pytest.fixture
    def client_sin_mongo(self, test_config, mock_llm_router):
        mock_redis = AsyncMock()
        mock_redis.ping   = AsyncMock(return_value=True)
        mock_redis.lpush  = AsyncMock(return_value=1)
        mock_redis.rpop   = AsyncMock(return_value=None)
        mock_redis.aclose = AsyncMock()

        mock_repo = MagicMock()
        mock_repo.disponible = False  # MongoDB no disponible

        with patch("main._redis", mock_redis), \
             patch("main.cfg", test_config), \
             patch("agents.llm_router._router", mock_llm_router):

            import main as app_module
            from utils.session_auth import SessionAuth
            app_module._session_auth = SessionAuth(test_config)
            app_module._redis        = mock_redis
            app_module.app.state.repo = mock_repo

            with TestClient(app_module.app, raise_server_exceptions=True) as client:
                client.post(
                    "/login",
                    data={"username": "testuser", "password": "testpass"},
                    follow_redirects=False,
                )
                yield client

    def test_delete_sin_mongo_devuelve_503(self, client_sin_mongo):
        resp = client_sin_mongo.delete(f"/api/conversation/{_FAKE_OID}")
        assert resp.status_code == 503

    def test_patch_folder_sin_mongo_devuelve_503(self, client_sin_mongo):
        resp = client_sin_mongo.patch(
            f"/api/conversation/{_FAKE_OID}/folder",
            json={"folder": "Test"},
        )
        assert resp.status_code == 503

    def test_toggle_favorite_sin_mongo_devuelve_503(self, client_sin_mongo):
        resp = client_sin_mongo.post(f"/api/conversation/{_FAKE_OID}/favorite")
        assert resp.status_code == 503

    def test_canvas_save_sin_mongo_devuelve_503(self, client_sin_mongo):
        resp = client_sin_mongo.post("/api/canvas/save", json={
            "conversation_id": _FAKE_OID,
            "content": "code",
            "type": "code",
        })
        assert resp.status_code == 503
