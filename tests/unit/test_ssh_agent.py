"""
tests/unit/test_ssh_agent.py
------------------------------
Tests para SSHAgent — diagnóstico SSH con Paramiko.

Estrategia de mocking:
  - HostResolver mockeado para devolver host_info sin filesystem
  - CredentialStore mockeado para devolver creds sin almacén real
  - Paramiko SSHClient completamente mockeado (sin conexión real)
  - GenerationAgent mockeado para no necesitar LLM
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Datos de test ─────────────────────────────────────────────────────────────

_HOST_INFO = {
    "hostname": "web01",
    "ip":       "10.0.0.1",
    "tipo":     "linux",
    "puerto":   22,
    "usuario":  "admin",
    "descripcion": "Servidor web",
    "origen":   "known_hosts",
}

_CREDS_PASSWORD = {
    "user":      "admin",
    "password":  "secret",
    "auth_type": "password",
    "port":      22,
}

_CREDS_SSH_KEY = {
    "user":         "admin",
    "auth_type":    "ssh_key",
    "ssh_key_path": "/home/admin/.ssh/id_rsa",
    "port":         22,
}


# ── Fixture de SSHAgent con dependencias mockeadas ────────────────────────────

@pytest.fixture
def ssh_agent(mock_llm_router):
    """SSHAgent con HostResolver, CredentialStore y GenerationAgent mockeados."""
    with patch("agents.ssh_agent.HostResolver") as MockResolver, \
         patch("agents.ssh_agent.CredentialStore") as MockStore, \
         patch("agents.ssh_agent.GenerationAgent") as MockLLM:

        mock_resolver = MockResolver.return_value
        mock_store    = MockStore.return_value
        mock_llm_gen  = MockLLM.return_value

        mock_resolver.resolver = MagicMock(return_value=_HOST_INFO)
        mock_store.get         = MagicMock(return_value=_CREDS_PASSWORD)
        mock_llm_gen.generate_response = AsyncMock(return_value="Análisis: CPU al 45%")

        from agents.ssh_agent import SSHAgent
        agent = SSHAgent(router=mock_llm_router)
        # Inyectar mocks directamente para poder acceder después
        agent._resolver = mock_resolver
        agent._store    = mock_store
        agent._llm      = mock_llm_gen

        yield agent, mock_resolver, mock_store, mock_llm_gen


# ═══════════════════════════════════════════════════════════════════════════════
# Flujo sin hostname
# ═══════════════════════════════════════════════════════════════════════════════

class TestSSHAgentSinHostname:

    @pytest.mark.asyncio
    async def test_sin_hostname_en_entidades_pregunta_al_usuario(self, ssh_agent):
        agent, _, _, mock_llm = ssh_agent
        result = await agent.ejecutar("revisar servidor", {}, [])
        # Debe delegar al LLM para preguntar el hostname
        mock_llm.generate_response.assert_called_once()
        assert result.exito is True  # No es error — es una pregunta de seguimiento

    @pytest.mark.asyncio
    async def test_sin_hostname_respuesta_no_vacia(self, ssh_agent):
        agent, _, _, _ = ssh_agent
        result = await agent.ejecutar("revisar servidor", {}, [])
        assert result.respuesta

    @pytest.mark.asyncio
    async def test_hostname_en_entidades_pasa_adelante(self, ssh_agent):
        agent, mock_resolver, _, _ = ssh_agent
        await agent.ejecutar("revisar web01", {"servidor": "web01"}, [])
        mock_resolver.resolver.assert_called_once_with("web01")


# ═══════════════════════════════════════════════════════════════════════════════
# Resolución de host
# ═══════════════════════════════════════════════════════════════════════════════

class TestSSHAgentResolucionHost:

    @pytest.mark.asyncio
    async def test_host_no_resuelto_devuelve_fallo(self, ssh_agent):
        agent, mock_resolver, _, _ = ssh_agent
        mock_resolver.resolver.return_value = None
        result = await agent.ejecutar("diagnóstico", {"servidor": "desconocido"}, [])
        assert result.exito is False
        assert "desconocido" in result.respuesta

    @pytest.mark.asyncio
    async def test_host_no_resuelto_no_intenta_ssh(self, ssh_agent):
        agent, mock_resolver, _, _ = ssh_agent
        mock_resolver.resolver.return_value = None
        with patch("agents.ssh_agent.paramiko.SSHClient") as MockSSH:
            await agent.ejecutar("diagnóstico", {"servidor": "x"}, [])
            MockSSH.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Credenciales
# ═══════════════════════════════════════════════════════════════════════════════

class TestSSHAgentCredenciales:

    @pytest.mark.asyncio
    async def test_sin_credenciales_devuelve_fallo(self, ssh_agent):
        agent, _, mock_store, _ = ssh_agent
        mock_store.get.return_value = None
        result = await agent.ejecutar("diagnóstico", {"servidor": "web01"}, [])
        assert result.exito is False
        assert "credenciales" in result.respuesta.lower() or "web01" in result.respuesta

    @pytest.mark.asyncio
    async def test_busca_credenciales_por_hostname_y_por_ip(self, ssh_agent):
        agent, _, mock_store, _ = ssh_agent
        # Primer get (hostname) devuelve None; segundo get (IP) devuelve creds
        mock_store.get.side_effect = [None, _CREDS_PASSWORD]
        with patch.object(agent, "_ejecutar_diagnostico", return_value="output"):
            await agent.ejecutar("diagnóstico", {"servidor": "web01"}, [])
        assert mock_store.get.call_count == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Ejecución SSH correcta
# ═══════════════════════════════════════════════════════════════════════════════

class TestSSHAgentEjecucionCorrect:

    @pytest.mark.asyncio
    async def test_flujo_completo_devuelve_exito(self, ssh_agent):
        agent, _, _, _ = ssh_agent
        with patch.object(agent, "_ejecutar_diagnostico", return_value="uptime: 5 days"):
            result = await agent.ejecutar("diagnóstico", {"servidor": "web01"}, [])
        assert result.exito is True

    @pytest.mark.asyncio
    async def test_resultado_incluye_hostname_en_datos(self, ssh_agent):
        agent, _, _, _ = ssh_agent
        with patch.object(agent, "_ejecutar_diagnostico", return_value="output"):
            result = await agent.ejecutar("diagnóstico", {"servidor": "web01"}, [])
        assert result.datos.get("hostname") == "web01"

    @pytest.mark.asyncio
    async def test_llm_recibe_output_ssh(self, ssh_agent):
        agent, _, _, mock_llm = ssh_agent
        with patch.object(agent, "_ejecutar_diagnostico", return_value="CPU: 45%"):
            await agent.ejecutar("diagnóstico", {"servidor": "web01"}, [])
        call_prompt = mock_llm.generate_response.call_args.args[0]
        assert "CPU: 45%" in call_prompt

    @pytest.mark.asyncio
    async def test_consulta_del_usuario_en_prompt_llm(self, ssh_agent):
        agent, _, _, mock_llm = ssh_agent
        with patch.object(agent, "_ejecutar_diagnostico", return_value="output"):
            await agent.ejecutar("¿Hay problemas de disco?", {"servidor": "web01"}, [])
        call_prompt = mock_llm.generate_response.call_args.args[0]
        assert "¿Hay problemas de disco?" in call_prompt


# ═══════════════════════════════════════════════════════════════════════════════
# Manejo de errores SSH
# ═══════════════════════════════════════════════════════════════════════════════

class TestSSHAgentErroresSSH:

    @pytest.mark.asyncio
    async def test_auth_error_devuelve_fallo_amigable(self, ssh_agent):
        from agents.ssh_agent import _SSHAuthError
        agent, _, _, _ = ssh_agent
        with patch.object(agent, "_ejecutar_diagnostico", side_effect=_SSHAuthError("bad pass")):
            result = await agent.ejecutar("diagnóstico", {"servidor": "web01"}, [])
        assert result.exito is False
        assert "autenticación" in result.respuesta.lower() or "web01" in result.respuesta

    @pytest.mark.asyncio
    async def test_host_key_error_devuelve_fallo_amigable(self, ssh_agent):
        from agents.ssh_agent import _SSHHostKeyError
        agent, _, _, _ = ssh_agent
        with patch.object(agent, "_ejecutar_diagnostico", side_effect=_SSHHostKeyError("bad key")):
            result = await agent.ejecutar("diagnóstico", {"servidor": "web01"}, [])
        assert result.exito is False
        assert "known_hosts" in result.respuesta.lower() or "clave" in result.respuesta.lower()

    @pytest.mark.asyncio
    async def test_connect_error_devuelve_fallo_amigable(self, ssh_agent):
        from agents.ssh_agent import _SSHConnectError
        agent, _, _, _ = ssh_agent
        with patch.object(agent, "_ejecutar_diagnostico", side_effect=_SSHConnectError("timeout")):
            result = await agent.ejecutar("diagnóstico", {"servidor": "web01"}, [])
        assert result.exito is False

    @pytest.mark.asyncio
    async def test_excepcion_generica_devuelve_fallo(self, ssh_agent):
        agent, _, _, _ = ssh_agent
        with patch.object(agent, "_ejecutar_diagnostico", side_effect=RuntimeError("boom")):
            result = await agent.ejecutar("diagnóstico", {"servidor": "web01"}, [])
        assert result.exito is False


# ═══════════════════════════════════════════════════════════════════════════════
# _ejecutar_diagnostico (lógica síncrona)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEjecutarDiagnosticoSSH:
    """Tests para el método síncrono interno."""

    def _make_mock_client(self, output_per_cmd="ok output"):
        """Crea un SSHClient mock que devuelve output fijo por cada comando."""
        import io

        def _exec_command(cmd, timeout=None):
            stdout = MagicMock()
            stdout.read = MagicMock(return_value=output_per_cmd.encode())
            stderr = MagicMock()
            stderr.read = MagicMock(return_value=b"")
            return MagicMock(), stdout, stderr

        client = MagicMock()
        client.exec_command = MagicMock(side_effect=_exec_command)
        client.connect = MagicMock()
        client.close = MagicMock()
        client.load_host_keys = MagicMock()
        client.set_missing_host_key_policy = MagicMock()
        return client

    def test_devuelve_markdown_con_secciones(self, mock_llm_router):
        import paramiko
        mock_client = self._make_mock_client("   15:00:00 up 2 days")
        with patch("agents.ssh_agent.paramiko.SSHClient", return_value=mock_client):
            from agents.ssh_agent import SSHAgent
            agent = SSHAgent(router=mock_llm_router)
            output = agent._ejecutar_diagnostico(_HOST_INFO, _CREDS_PASSWORD)
        assert "###" in output  # Tiene secciones Markdown
        assert "15:00:00 up 2 days" in output

    def test_cierra_cliente_tras_ejecucion(self, mock_llm_router):
        mock_client = self._make_mock_client()
        with patch("agents.ssh_agent.paramiko.SSHClient", return_value=mock_client):
            from agents.ssh_agent import SSHAgent
            agent = SSHAgent(router=mock_llm_router)
            agent._ejecutar_diagnostico(_HOST_INFO, _CREDS_PASSWORD)
        mock_client.close.assert_called_once()

    def test_usa_ssh_key_si_auth_type_es_key(self, mock_llm_router):
        mock_client = self._make_mock_client()
        with patch("agents.ssh_agent.paramiko.SSHClient", return_value=mock_client):
            from agents.ssh_agent import SSHAgent
            agent = SSHAgent(router=mock_llm_router)
            agent._ejecutar_diagnostico(_HOST_INFO, _CREDS_SSH_KEY)
        connect_kwargs = mock_client.connect.call_args.kwargs
        assert "key_filename" in connect_kwargs
        assert "password" not in connect_kwargs

    def test_usa_password_si_auth_type_es_password(self, mock_llm_router):
        mock_client = self._make_mock_client()
        with patch("agents.ssh_agent.paramiko.SSHClient", return_value=mock_client):
            from agents.ssh_agent import SSHAgent
            agent = SSHAgent(router=mock_llm_router)
            agent._ejecutar_diagnostico(_HOST_INFO, _CREDS_PASSWORD)
        connect_kwargs = mock_client.connect.call_args.kwargs
        assert "password" in connect_kwargs

    def test_auth_exception_lanza_ssh_auth_error(self, mock_llm_router):
        import paramiko as pm
        mock_client = self._make_mock_client()
        mock_client.connect.side_effect = pm.AuthenticationException("bad")
        with patch("agents.ssh_agent.paramiko.SSHClient", return_value=mock_client):
            from agents.ssh_agent import SSHAgent, _SSHAuthError
            agent = SSHAgent(router=mock_llm_router)
            with pytest.raises(_SSHAuthError):
                agent._ejecutar_diagnostico(_HOST_INFO, _CREDS_PASSWORD)

    def test_bad_host_key_lanza_ssh_host_key_error(self, mock_llm_router):
        import paramiko as pm
        mock_client = self._make_mock_client()
        # BadHostKeyException.__str__ llama a got_key.get_base64() y
        # expected_key.get_base64() — con None ahi paramiko revienta con
        # AttributeError al formatear el mensaje, antes incluso de que
        # SSHAgent pueda capturar la excepcion.
        fake_key = MagicMock()
        fake_key.get_base64.return_value = "AAAAfakekeydata"
        mock_client.connect.side_effect = pm.BadHostKeyException("h", fake_key, fake_key)
        with patch("agents.ssh_agent.paramiko.SSHClient", return_value=mock_client):
            from agents.ssh_agent import SSHAgent, _SSHHostKeyError
            agent = SSHAgent(router=mock_llm_router)
            with pytest.raises(_SSHHostKeyError):
                agent._ejecutar_diagnostico(_HOST_INFO, _CREDS_PASSWORD)

    def test_os_error_lanza_ssh_connect_error(self, mock_llm_router):
        mock_client = self._make_mock_client()
        mock_client.connect.side_effect = OSError("connection refused")
        with patch("agents.ssh_agent.paramiko.SSHClient", return_value=mock_client):
            from agents.ssh_agent import SSHAgent, _SSHConnectError
            agent = SSHAgent(router=mock_llm_router)
            with pytest.raises(_SSHConnectError):
                agent._ejecutar_diagnostico(_HOST_INFO, _CREDS_PASSWORD)

    def test_comando_fallido_no_rompe_los_demas(self, mock_llm_router):
        """Si un comando SSH falla, los demás deben seguir ejecutándose."""
        call_count = [0]

        def _exec_command(cmd, timeout=None):
            call_count[0] += 1
            if call_count[0] == 2:  # El segundo comando falla
                raise Exception("exec error")
            stdout = MagicMock()
            stdout.read = MagicMock(return_value=b"output ok")
            stderr = MagicMock()
            stderr.read = MagicMock(return_value=b"")
            return MagicMock(), stdout, stderr

        mock_client = self._make_mock_client()
        mock_client.exec_command = MagicMock(side_effect=_exec_command)
        with patch("agents.ssh_agent.paramiko.SSHClient", return_value=mock_client):
            from agents.ssh_agent import SSHAgent, _DIAGNOSTIC_COMMANDS
            agent = SSHAgent(router=mock_llm_router)
            output = agent._ejecutar_diagnostico(_HOST_INFO, _CREDS_PASSWORD)
        # Debe tener output de más de un comando
        assert "output ok" in output
        assert "[error:" in output  # El comando fallido marcado

    def test_cierra_cliente_aunque_haya_error_en_comando(self, mock_llm_router):
        mock_client = self._make_mock_client()
        mock_client.exec_command.side_effect = Exception("fallo")
        with patch("agents.ssh_agent.paramiko.SSHClient", return_value=mock_client):
            from agents.ssh_agent import SSHAgent
            agent = SSHAgent(router=mock_llm_router)
            agent._ejecutar_diagnostico(_HOST_INFO, _CREDS_PASSWORD)
        mock_client.close.assert_called_once()
