"""
Búsqueda web gratuita via DuckDuckGo.
Sin API key, sin coste. Usa la librería duckduckgo-search.

Devuelve una lista de resultados con título, URL y snippet.
"""

import logging
from typing import List, Dict

from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

# Número de resultados por defecto
DEFAULT_MAX_RESULTS = 5


def search(query: str, max_results: int = DEFAULT_MAX_RESULTS, region: str = "es-es") -> List[Dict]:
    """
    Busca en DuckDuckGo y devuelve los resultados.

    Args:
        query: Consulta de búsqueda
        max_results: Número máximo de resultados
        region: Región para resultados localizados (es-es, wt-wt para global)

    Returns:
        Lista de dicts con: title, url, body (snippet)
    """
    try:
        logger.info(f"Buscando en DuckDuckGo: '{query}' (max={max_results})")
        with DDGS() as ddgs:
            results = list(ddgs.text(
                query,
                region=region,
                safesearch="moderate",
                max_results=max_results,
            ))
        logger.info(f"DuckDuckGo devolvió {len(results)} resultados")
        return results
    except Exception as e:
        logger.error(f"Error en búsqueda DuckDuckGo: {e}")
        return []


def search_news(query: str, max_results: int = 5) -> List[Dict]:
    """
    Busca noticias recientes en DuckDuckGo News.

    Returns:
        Lista de dicts con: title, url, body, date, source
    """
    try:
        logger.info(f"Buscando noticias: '{query}'")
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results))
        return results
    except Exception as e:
        logger.error(f"Error en búsqueda de noticias: {e}")
        return []
