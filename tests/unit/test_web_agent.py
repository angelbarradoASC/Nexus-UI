"""
tests/unit/test_web_agent.py
------------------------------
Tests para WebAgent — DuckDuckGo + síntesis LLM.

Estrategia de mocking:
  - web_search.search / search_news: mockeados con listas de resultados
  - web_fetch.fetch_page: mockeado para devolver contenido HTML
  - GenerationAgent: mockeado para no necesitar LLM real
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Datos de test ─────────────────────────────────────────────────────────────

_RESULTS_OK = [
    {"title": "Artículo 1", "href": "https://example.com/1", "body": "Snippet 1"},
    {"title": "Artículo 2", "href": "https://example.com/2", "body": "Snippet 2"},
    {"title": "Artículo 3", "href": "https://example.com/3", "body": "Snippet 3"},
]

_RESULTS_NEWS = [
    {"title": "Noticia reciente", "url": "https://news.com/1", "body": "Snippet noticia"},
]


# ── Fixture de WebAgent con dependencias mockeadas ────────────────────────────

@pytest.fixture
def web_agent(mock_llm_router):
    """WebAgent con search, fetch y LLM mockeados."""
    with patch("agents.web_agent.search",       return_value=_RESULTS_OK), \
         patch("agents.web_agent.search_news",  return_value=_RESULTS_NEWS), \
         patch("agents.web_agent.fetch_page",   new_callable=AsyncMock, return_value="Contenido de la página"), \
         patch("agents.web_agent.GenerationAgent") as MockLLM:

        mock_llm_gen = MockLLM.return_value
        mock_llm_gen.generate_response = AsyncMock(return_value="Respuesta sintetizada del LLM")

        from agents.web_agent import WebAgent
        agent = WebAgent(router=mock_llm_router)
        agent._llm = mock_llm_gen

        yield agent, mock_llm_gen


# ═══════════════════════════════════════════════════════════════════════════════
# Flujo básico
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebAgentBasic:

    @pytest.mark.asyncio
    async def test_devuelve_resultado_exitoso(self, web_agent):
        agent, _ = web_agent
        result = await agent.ejecutar("Python async programming", {}, [])
        assert result.exito is True

    @pytest.mark.asyncio
    async def test_respuesta_incluye_texto_llm(self, web_agent):
        agent, _ = web_agent
        result = await agent.ejecutar("Python async", {}, [])
        assert "Respuesta sintetizada del LLM" in result.respuesta

    @pytest.mark.asyncio
    async def test_respuesta_incluye_fuentes(self, web_agent):
        agent, _ = web_agent
        result = await agent.ejecutar("Python async", {}, [])
        assert "Fuentes" in result.respuesta or "Artículo 1" in result.respuesta

    @pytest.mark.asyncio
    async def test_datos_incluyen_estadisticas(self, web_agent):
        agent, _ = web_agent
        result = await agent.ejecutar("Python async", {}, [])
        assert "results_found" in result.datos
        assert "pages_fetched" in result.datos
        assert "urls" in result.datos

    @pytest.mark.asyncio
    async def test_agente_en_resultado(self, web_agent):
        agent, _ = web_agent
        result = await agent.ejecutar("Python", {}, [])
        assert result.agente == "WebAgent"

    @pytest.mark.asyncio
    async def test_llm_recibe_contexto_web(self, web_agent):
        agent, mock_llm = web_agent
        await agent.ejecutar("Python async", {}, [])
        call_prompt = mock_llm.generate_response.call_args.args[0]
        assert "Python async" in call_prompt
        assert "Snippet 1" in call_prompt  # fragmento de búsqueda incluido


# ═══════════════════════════════════════════════════════════════════════════════
# Detección de noticias
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebAgentNewsDetection:

    @pytest.mark.parametrize("consulta,es_noticia", [
        ("últimas noticias de Python",         True),
        ("hoy en tecnología",                  True),
        ("precio del Bitcoin ahora",           True),
        ("actualmente cuánto cuesta",          True),
        ("latest news on AI",                  True),
        ("breaking developments in space",     True),
        ("cómo funciona el algoritmo RSA",     False),
        ("explícame qué es recursividad",      False),
        ("historia de Linux",                  False),
    ])
    @pytest.mark.asyncio
    async def test_deteccion_keywords_noticias(self, consulta, es_noticia, mock_llm_router):
        with patch("agents.web_agent.search",      return_value=_RESULTS_OK) as mock_search, \
             patch("agents.web_agent.search_news", return_value=_RESULTS_NEWS) as mock_news, \
             patch("agents.web_agent.fetch_page",  new_callable=AsyncMock, return_value=None), \
             patch("agents.web_agent.GenerationAgent") as MockLLM:

            MockLLM.return_value.generate_response = AsyncMock(return_value="ok")
            from agents.web_agent import WebAgent
            agent = WebAgent(router=mock_llm_router)
            agent._llm = MockLLM.return_value

            await agent.ejecutar(consulta, {}, [])

            if es_noticia:
                mock_news.assert_called_once()
                mock_search.assert_not_called()
            else:
                mock_search.assert_called_once()
                mock_news.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_query_de_entidades_tiene_prioridad(self, mock_llm_router):
        """Si entidades tiene search_query, se usa en lugar de la consulta completa."""
        with patch("agents.web_agent.search", return_value=_RESULTS_OK) as mock_search, \
             patch("agents.web_agent.search_news", return_value=[]), \
             patch("agents.web_agent.fetch_page", new_callable=AsyncMock, return_value=None), \
             patch("agents.web_agent.GenerationAgent") as MockLLM:

            MockLLM.return_value.generate_response = AsyncMock(return_value="ok")
            from agents.web_agent import WebAgent
            agent = WebAgent(router=mock_llm_router)
            agent._llm = MockLLM.return_value

            await agent.ejecutar("busca esto", {"search_query": "query exacta"}, [])
            mock_search.assert_called_once_with("query exacta", max_results=5)


# ═══════════════════════════════════════════════════════════════════════════════
# Sin resultados
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebAgentSinResultados:

    @pytest.mark.asyncio
    async def test_sin_resultados_devuelve_fallo(self, mock_llm_router):
        with patch("agents.web_agent.search",      return_value=[]), \
             patch("agents.web_agent.search_news", return_value=[]), \
             patch("agents.web_agent.GenerationAgent") as MockLLM:

            MockLLM.return_value.generate_response = AsyncMock(return_value="ok")
            from agents.web_agent import WebAgent
            agent = WebAgent(router=mock_llm_router)
            result = await agent.ejecutar("consulta sin resultados", {}, [])

        assert result.exito is False
        assert result.error == "no_results"

    @pytest.mark.asyncio
    async def test_sin_resultados_respuesta_amigable(self, mock_llm_router):
        with patch("agents.web_agent.search",      return_value=[]), \
             patch("agents.web_agent.search_news", return_value=[]), \
             patch("agents.web_agent.GenerationAgent") as MockLLM:

            MockLLM.return_value.generate_response = AsyncMock(return_value="ok")
            from agents.web_agent import WebAgent
            agent = WebAgent(router=mock_llm_router)
            result = await agent.ejecutar("x", {}, [])

        assert "No encontré" in result.respuesta or "reformula" in result.respuesta.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Descarga de páginas
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebAgentFetchPages:

    @pytest.mark.asyncio
    async def test_fetch_se_llama_en_paralelo_para_top_3(self, mock_llm_router):
        """Debe descargar hasta _MAX_PAGES=3 páginas en paralelo."""
        fetch_calls: list[str] = []

        async def _fake_fetch(url):
            fetch_calls.append(url)
            return f"Contenido de {url}"

        with patch("agents.web_agent.search",      return_value=_RESULTS_OK), \
             patch("agents.web_agent.search_news", return_value=[]), \
             patch("agents.web_agent.fetch_page",  side_effect=_fake_fetch), \
             patch("agents.web_agent.GenerationAgent") as MockLLM:

            MockLLM.return_value.generate_response = AsyncMock(return_value="ok")
            from agents.web_agent import WebAgent
            agent = WebAgent(router=mock_llm_router)
            agent._llm = MockLLM.return_value

            await agent.ejecutar("consulta", {}, [])

        assert len(fetch_calls) <= 3

    @pytest.mark.asyncio
    async def test_fetch_fallido_no_rompe_el_flujo(self, mock_llm_router):
        """Si fetch_page devuelve None (fallo silencioso), el agente sigue."""
        with patch("agents.web_agent.search",      return_value=_RESULTS_OK), \
             patch("agents.web_agent.search_news", return_value=[]), \
             patch("agents.web_agent.fetch_page",  new_callable=AsyncMock, return_value=None), \
             patch("agents.web_agent.GenerationAgent") as MockLLM:

            MockLLM.return_value.generate_response = AsyncMock(return_value="ok")
            from agents.web_agent import WebAgent
            agent = WebAgent(router=mock_llm_router)
            agent._llm = MockLLM.return_value

            result = await agent.ejecutar("Python", {}, [])

        assert result.exito is True
        assert result.datos["pages_fetched"] == 0

    @pytest.mark.asyncio
    async def test_contenido_descargado_incluido_en_prompt(self, mock_llm_router):
        """El contenido descargado debe aparecer en el prompt al LLM."""
        with patch("agents.web_agent.search",      return_value=_RESULTS_OK[:1]), \
             patch("agents.web_agent.search_news", return_value=[]), \
             patch("agents.web_agent.fetch_page",  new_callable=AsyncMock, return_value="CONTENIDO_UNICO_XYZ"), \
             patch("agents.web_agent.GenerationAgent") as MockLLM:

            mock_llm = MagicMock()
            mock_llm.generate_response = AsyncMock(return_value="ok")
            MockLLM.return_value = mock_llm

            from agents.web_agent import WebAgent
            agent = WebAgent(router=mock_llm_router)
            agent._llm = mock_llm

            await agent.ejecutar("Python", {}, [])

        call_prompt = mock_llm.generate_response.call_args.args[0]
        assert "CONTENIDO_UNICO_XYZ" in call_prompt


# ═══════════════════════════════════════════════════════════════════════════════
# Historial
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebAgentHistorial:

    @pytest.mark.asyncio
    async def test_historial_se_pasa_al_llm(self, mock_llm_router):
        historial = [{"role": "user", "content": "contexto anterior"}]
        with patch("agents.web_agent.search",      return_value=_RESULTS_OK), \
             patch("agents.web_agent.search_news", return_value=[]), \
             patch("agents.web_agent.fetch_page",  new_callable=AsyncMock, return_value=None), \
             patch("agents.web_agent.GenerationAgent") as MockLLM:

            mock_llm = MagicMock()
            mock_llm.generate_response = AsyncMock(return_value="ok")
            MockLLM.return_value = mock_llm

            from agents.web_agent import WebAgent
            agent = WebAgent(router=mock_llm_router)
            agent._llm = mock_llm

            await agent.ejecutar("Python", {}, historial)

        # generate_response recibe (prompt, username, historial)
        call_args = mock_llm.generate_response.call_args.args
        assert len(call_args) >= 3
