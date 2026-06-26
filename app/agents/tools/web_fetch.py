"""
Fetcher de páginas web.
Descarga el contenido HTML de una URL y extrae el texto legible.

Usa httpx (ya en el proyecto) + BeautifulSoup4 para parsear.
Elimina scripts, estilos, navs, footers y demás ruido para quedarse
solo con el texto relevante del artículo/página.
"""

import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Timeout agresivo — si una página tarda más, no merece la pena
FETCH_TIMEOUT = 15

# Máximo de caracteres del contenido extraído que se pasa al LLM
MAX_CONTENT_CHARS = 8_000

# Tags de los que extraemos texto
CONTENT_TAGS = ["article", "main", "section", "div", "p"]

# Tags que siempre eliminamos (ruido)
NOISE_TAGS = [
    "script", "style", "nav", "footer", "header",
    "aside", "form", "button", "iframe", "noscript",
    "figure", "figcaption", "meta", "link",
]

HEADERS = {
    "User-Agent": "Open-Nexus Fetcher/1.0 (+https://nexus.local)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


async def fetch_page(url: str) -> Optional[str]:
    """
    Descarga una URL y devuelve el texto limpio extraído.

    Returns:
        Texto limpio del contenido principal, o None si falla.
    """
    try:
        logger.info(f"Descargando: {url}")
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            headers=HEADERS,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                logger.warning(f"Tipo de contenido no soportado: {content_type}")
                return None

        html = response.text
        return _extraer_texto(html, url)

    except httpx.TimeoutException:
        logger.warning(f"Timeout descargando {url}")
        return None
    except httpx.HTTPStatusError as e:
        logger.warning(f"HTTP {e.response.status_code} en {url}")
        return None
    except Exception as e:
        logger.error(f"Error descargando {url}: {e}")
        return None


def _extraer_texto(html: str, url: str) -> Optional[str]:
    """Parsea el HTML y extrae texto limpio."""
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Eliminar ruido
        for tag in soup.find_all(NOISE_TAGS):
            tag.decompose()

        # Intentar primero el contenido principal
        texto = ""
        for selector in ["article", "main", '[role="main"]', ".content", "#content", "body"]:
            elemento = soup.select_one(selector)
            if elemento:
                texto = elemento.get_text(separator="\n", strip=True)
                break

        if not texto:
            texto = soup.get_text(separator="\n", strip=True)

        # Limpiar líneas vacías múltiples
        lineas = [l.strip() for l in texto.splitlines() if l.strip()]
        texto = "\n".join(lineas)

        # Truncar si es muy largo
        if len(texto) > MAX_CONTENT_CHARS:
            texto = texto[:MAX_CONTENT_CHARS] + f"\n\n[... contenido truncado a {MAX_CONTENT_CHARS} caracteres]"

        return texto if texto else None

    except Exception as e:
        logger.error(f"Error parseando HTML de {url}: {e}")
        return None
