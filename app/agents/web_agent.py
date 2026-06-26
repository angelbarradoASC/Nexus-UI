"""
app/agents/web_agent.py
------------------------
Agente de búsqueda web — DuckDuckGo gratuito + síntesis LLM.

Flujo:
  1. Busca en DuckDuckGo (sin API key)
  2. Descarga contenido de los top N resultados en paralelo
  3. Pasa todo al LLM para sintetizar una respuesta con fuentes
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from .base_agent import AgentResult, BaseAgent
from .generation_agent import GenerationAgent
from .tools.web_fetch import fetch_page
from .tools.web_search import search, search_news

_MAX_PAGES = 3

_NEWS_KEYWORDS: tuple[str, ...] = (
    "noticia", "noticias", "hoy", "ahora", "última hora", "reciente",
    "news", "today", "latest", "breaking", "actual", "actualmente",
)


class WebAgent(BaseAgent):
    """
    Busca en la web y sintetiza la respuesta con el LLM.
    Devuelve siempre AgentResult — nunca lanza al orquestador.
    """

    def __init__(self, router: Any) -> None:
        super().__init__(router)
        self._llm = GenerationAgent(router)

    async def ejecutar(
        self,
        consulta: str,
        entidades: dict[str, Any],
        historial: list[dict[str, str]],
    ) -> AgentResult:
        search_query = entidades.get("search_query") or consulta
        es_noticia = any(kw in consulta.lower() for kw in _NEWS_KEYWORDS)

        self.logger.info(
            "WebAgent buscando | query={!r} | noticias={}",
            search_query, es_noticia,
        )

        # 1. Buscar
        results = (
            search_news(search_query, max_results=_MAX_PAGES + 2)
            if es_noticia
            else search(search_query, max_results=_MAX_PAGES + 2)
        )

        if not results:
            return AgentResult(
                respuesta=(
                    "No encontré resultados en la web para esa consulta. "
                    "Prueba a reformularla."
                ),
                exito=False,
                agente=self._nombre(),
                error="no_results",
            )

        # 2. Descargar contenido de las top páginas en paralelo
        urls: list[str] = [
            r.get("href") or r.get("url", "")
            for r in results
            if r.get("href") or r.get("url")
        ][:_MAX_PAGES]

        contenidos: list[str | None] = await asyncio.gather(
            *[fetch_page(url) for url in urls]
        )

        # 3. Construir contexto para el LLM
        fragmentos: list[str] = []
        for i, r in enumerate(results):
            titulo = r.get("title", "Sin título")
            url = r.get("href") or r.get("url", "")
            snippet = r.get("body", "")
            fragmentos.append(f"[Fuente {i + 1}] {titulo}\nURL: {url}\n{snippet}")

        paginas_ok: list[str] = []
        for i, (url, contenido) in enumerate(zip(urls, contenidos)):
            if contenido:
                fragmentos.append(
                    f"\n--- Contenido completo Fuente {i + 1} ({url}) ---\n{contenido}\n---"
                )
                paginas_ok.append(url)

        contexto_web = "\n\n".join(fragmentos)

        # 4. Sintetizar con LLM
        prompt = (
            f"Tienes acceso a los siguientes resultados de búsqueda web.\n\n"
            f"PREGUNTA DEL USUARIO: {consulta}\n\n"
            f"RESULTADOS:\n{contexto_web}\n\n"
            f"Responde de forma clara y concisa. "
            f"Cita las fuentes cuando sea relevante. "
            f"Si la información es contradictoria entre fuentes, indícalo."
        )

        respuesta = await self._llm.generate_response(
            prompt, "system", self._construir_historial_ventana(historial)
        )

        fuentes = "\n".join(
            f"- {r.get('title', '')}: {r.get('href') or r.get('url', '')}"
            for r in results[:_MAX_PAGES]
        )
        respuesta_final = f"{respuesta}\n\n**Fuentes consultadas:**\n{fuentes}"

        self.logger.info(
            "WebAgent OK | resultados={} | páginas_descargadas={}",
            len(results), len(paginas_ok),
        )

        return AgentResult(
            respuesta=respuesta_final,
            exito=True,
            agente=self._nombre(),
            datos={
                "search_query": search_query,
                "results_found": len(results),
                "pages_fetched": len(paginas_ok),
                "urls": urls,
            },
        )
