"""
tests/test_llm_parser.py
--------------------------
Tests para LLMResponseParser y clean_llm_response.

Cubre: eliminación de XML tags, headers Markdown, patrones de texto,
formatos mixtos, edge cases y contrato del singleton get_parser().

NOTA DE IMPORTACIÓN:
    app/agents/utils/llm_parser.py solo depende de stdlib (re, logging).
    Importarlo vía `agents.utils.llm_parser` ejecuta `agents/__init__.py`,
    que a su vez importa OrchestrationAgent → WebAgent → duckduckgo_search.
    Si duckduckgo_search no está instalado, todos los tests del fixture
    `parser` fallan por error de setup.

    Solución: añadir `app/agents/utils` directamente al sys.path e importar
    `llm_parser` sin pasar por el paquete agents. Los tests son 100%
    independientes de la cadena de dependencias del paquete.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Importar el módulo directamente (sin agents/__init__.py) para no arrastrar
# la dependencia transitiva agents → web_agent → duckduckgo_search.
_UTILS_PATH = str(Path(__file__).parent.parent / "app" / "agents" / "utils")
if _UTILS_PATH not in sys.path:
    sys.path.insert(0, _UTILS_PATH)

from llm_parser import LLMResponseParser, clean_llm_response, get_parser  # noqa: E402


@pytest.fixture(scope="module")
def parser():
    return LLMResponseParser()


# ═══════════════════════════════════════════════════════════════════════════════
# Tags XML
# ═══════════════════════════════════════════════════════════════════════════════

class TestXmlTags:
    """<thinking>, <reflection>, <reasoning> y variantes deben eliminarse."""

    def test_thinking_tag_eliminado_del_output(self, parser):
        raw = "<thinking>El usuario saluda, debo responder en español.</thinking>\n\n¡Hola!"
        clean = parser.quick_parse(raw)
        assert "<thinking>" not in clean
        assert "</thinking>" not in clean

    def test_contenido_interno_del_thinking_eliminado(self, parser):
        raw = "<thinking>razonamiento interno secreto</thinking>\n\n¡Hola!"
        clean = parser.quick_parse(raw)
        assert "razonamiento interno secreto" not in clean

    def test_respuesta_despues_del_thinking_preservada(self, parser):
        raw = "<thinking>pensando</thinking>\n\nEsta es la respuesta visible."
        clean = parser.quick_parse(raw)
        assert "Esta es la respuesta visible." in clean

    def test_reflection_tag_eliminado(self, parser):
        raw = "<reflection>¿Debería pedir más detalles?</reflection>\n\nPara diagnosticar:"
        clean = parser.quick_parse(raw)
        assert "<reflection>" not in clean
        assert "¿Debería pedir más detalles?" not in clean
        assert "Para diagnosticar:" in clean

    def test_thinking_multilinea_eliminado(self, parser):
        raw = (
            "<thinking>\n"
            "Línea 1 del razonamiento.\n"
            "Línea 2 del razonamiento.\n"
            "Línea 3 del razonamiento.\n"
            "</thinking>\n\n"
            "Respuesta final."
        )
        clean = parser.quick_parse(raw)
        assert "Línea 1 del razonamiento" not in clean
        assert "Línea 2 del razonamiento" not in clean
        assert "Respuesta final." in clean

    def test_had_thinking_true_con_xml(self, parser):
        raw = "<thinking>algo</thinking>\nRespuesta."
        result = parser.parse(raw)
        assert result["had_thinking"] is True

    def test_had_thinking_false_sin_xml(self, parser):
        raw = "Respuesta directa sin ningún thinking."
        result = parser.parse(raw)
        assert result["had_thinking"] is False

    def test_thinking_process_en_debug_contiene_contenido_extraido(self, parser):
        raw = "<thinking>contenido del thinking aquí</thinking>\nRespuesta."
        result = parser.parse(raw, debug=True)
        assert "thinking_process" in result
        assert result["thinking_process"]  # No vacío
        assert "contenido del thinking aquí" in result["thinking_process"]

    def test_debug_false_no_incluye_thinking_process(self, parser):
        raw = "<thinking>algo</thinking>\nRespuesta."
        result = parser.parse(raw, debug=False)
        assert "thinking_process" not in result

    def test_sin_xml_respuesta_igual_al_original_tras_whitespace(self, parser):
        raw = "Respuesta limpia sin ningún markup especial."
        result = parser.parse(raw)
        assert result["clean_response"] == raw.strip()


# ═══════════════════════════════════════════════════════════════════════════════
# Headers Markdown
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarkdownHeaders:
    """### Thinking Process y variantes eliminan el bloque hasta el siguiente header."""

    def test_thinking_process_header_y_contenido_eliminados(self, parser):
        raw = (
            "### Thinking Process\n\n"
            "Análisis paso a paso.\n\n"
            "## Response\n\n"
            "Respuesta real al usuario."
        )
        clean = parser.quick_parse(raw)
        assert "Thinking Process" not in clean
        assert "Análisis paso a paso" not in clean

    def test_respuesta_tras_thinking_header_preservada(self, parser):
        raw = (
            "### Thinking Process\n\n"
            "Razonamiento.\n\n"
            "## Response\n\n"
            "Respuesta real al usuario."
        )
        clean = parser.quick_parse(raw)
        assert "Respuesta real al usuario." in clean

    def test_reasoning_header_eliminado(self, parser):
        """
        El bloque Reasoning se elimina hasta el siguiente header.
        Un salto de línea doble solo detiene la eliminación si la línea SIGUIENTE
        también está vacía (párrafo doble). Un header siguiente SÍ detiene siempre.
        """
        raw = (
            "### Reasoning\n\n"
            "Razonamiento interno.\n\n"
            "## Respuesta\n\n"     # Header no-thinking → detiene la eliminación
            "Resultado: OK."
        )
        clean = parser.quick_parse(raw)
        assert "Razonamiento interno" not in clean
        assert "Resultado: OK." in clean

    def test_header_normal_no_de_thinking_preservado(self, parser):
        """Headers que no son de thinking deben mantenerse intactos."""
        raw = "## Instalación\n\nPaso 1: instala dependencias.\nPaso 2: configura."
        clean = parser.quick_parse(raw)
        assert "Instalación" in clean
        assert "Paso 1" in clean

    def test_had_thinking_true_con_markdown_header(self, parser):
        raw = "### Thinking Process\n\nAnálisis.\n\nRespuesta."
        result = parser.parse(raw)
        assert result["had_thinking"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Patrones de texto plano
# ═══════════════════════════════════════════════════════════════════════════════

class TestTextPatterns:
    """'Let me think...', 'Thinking:', etc. eliminan el bloque hasta línea vacía."""

    def test_let_me_think_eliminado(self, parser):
        raw = (
            "Let me think about this carefully...\n"
            "Analizando el contexto del problema.\n\n"
            "Respuesta definitiva: sí."
        )
        clean = parser.quick_parse(raw)
        assert "Let me think" not in clean
        assert "Analizando el contexto" not in clean

    def test_respuesta_despues_de_let_me_think_preservada(self, parser):
        raw = (
            "Let me think about this carefully...\n"
            "Análisis.\n\n"
            "Respuesta definitiva: sí."
        )
        clean = parser.quick_parse(raw)
        assert "Respuesta definitiva: sí." in clean

    def test_thinking_colon_eliminado(self, parser):
        raw = "Thinking:\nContenido de razonamiento.\n\nRespuesta limpia."
        clean = parser.quick_parse(raw)
        # El bloque de thinking no debe estar en la respuesta
        assert "Contenido de razonamiento" not in clean
        assert "Respuesta limpia." in clean


# ═══════════════════════════════════════════════════════════════════════════════
# Formatos mixtos
# ═══════════════════════════════════════════════════════════════════════════════

class TestFormatosMixtos:
    """XML + Markdown juntos en el mismo texto."""

    def test_xml_y_reflection_ambos_eliminados(self, parser):
        raw = (
            "<thinking>\nAnálisis inicial.\n</thinking>\n\n"
            "<reflection>\nReflexión final.\n</reflection>\n\n"
            "Para diagnosticar el servidor, ejecuta `top`."
        )
        clean = parser.quick_parse(raw)
        assert "Análisis inicial" not in clean
        assert "Reflexión final" not in clean
        assert "Para diagnosticar el servidor" in clean

    def test_contenido_tecnico_de_respuesta_preservado(self, parser):
        """El contenido técnico (comandos, rutas, código) no debe alterarse."""
        payload = "Para diagnosticar PROD-01:\n\n- CPU: usa `top`\n- Disco: usa `df -h`"
        raw = f"<thinking>pensando</thinking>\n\n{payload}"
        clean = parser.quick_parse(raw)
        assert "PROD-01" in clean
        assert "`top`" in clean
        assert "`df -h`" in clean

    def test_had_thinking_true_en_formato_mixto(self, parser):
        raw = "<thinking>x</thinking>\n### Reasoning\n\ny\n\nRespuesta."
        result = parser.parse(raw)
        assert result["had_thinking"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_string_vacio_devuelve_vacio(self, parser):
        result = parser.parse("")
        assert result["clean_response"] == ""
        assert result["had_thinking"] is False

    def test_string_vacio_no_lanza(self, parser):
        # No debe lanzar ninguna excepción
        parser.quick_parse("")

    def test_solo_thinking_devuelve_string(self, parser):
        raw = "<thinking>todo es pensamiento, no hay respuesta visible</thinking>"
        clean = parser.quick_parse(raw)
        assert isinstance(clean, str)
        # El resultado puede ser vacío, pero no debe contener el tag
        assert "<thinking>" not in clean

    def test_multiples_saltos_de_linea_compactados(self, parser):
        """Tres o más saltos de línea consecutivos se reducen a dos."""
        raw = "Línea 1\n\n\n\n\nLínea 2"
        clean = parser.quick_parse(raw)
        assert "\n\n\n" not in clean

    def test_espacios_laterales_del_texto_eliminados(self, parser):
        raw = "   Respuesta con espacios al inicio y al final.   "
        clean = parser.quick_parse(raw)
        assert clean == clean.strip()

    def test_respuesta_larga_sin_thinking_preservada_completa(self, parser):
        """Texto largo sin thinking no pierde contenido."""
        raw = "\n".join(f"Línea de contenido número {i}." for i in range(50))
        clean = parser.quick_parse(raw)
        for i in (0, 24, 49):
            assert f"Línea de contenido número {i}." in clean


# ═══════════════════════════════════════════════════════════════════════════════
# Contrato de parse() y clean_llm_response()
# ═══════════════════════════════════════════════════════════════════════════════

class TestContrato:

    def test_parse_siempre_devuelve_dict_con_claves_obligatorias(self, parser):
        for raw in ["", "texto normal", "<thinking>x</thinking>", "### Thinking\n\nx\n\ny"]:
            result = parser.parse(raw)
            assert "clean_response" in result, f"Falta clean_response para: {raw!r}"
            assert "had_thinking" in result, f"Falta had_thinking para: {raw!r}"

    def test_clean_llm_response_devuelve_string(self):
        for raw in ["", "texto", "<thinking>x</thinking>\nRespuesta."]:
            result = clean_llm_response(raw)
            assert isinstance(result, str), f"No es string para: {raw!r}"

    def test_quick_parse_equivale_a_clean_llm_response(self, parser):
        raw = "<thinking>x</thinking>\n\nRespuesta de test."
        assert parser.quick_parse(raw) == clean_llm_response(raw)

    def test_get_parser_devuelve_singleton(self):
        p1 = get_parser()
        p2 = get_parser()
        assert p1 is p2

    def test_get_parser_devuelve_llmresponseparser(self):
        assert isinstance(get_parser(), LLMResponseParser)
