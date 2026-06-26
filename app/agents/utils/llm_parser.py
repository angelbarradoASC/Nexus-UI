# app/agents/utils/llm_parser.py
import re
import logging

logger = logging.getLogger(__name__)

class LLMResponseParser:
    """
    Parser que limpia las respuestas de LLMs de razonamiento profundo (DeepSeek, QwQ, o1, etc.)
    eliminando todo el proceso de "thinking" y dejando solo la respuesta final limpia.
    
    Soporta múltiples formatos:
    - Tags XML: <thinking>, <reasoning>, <thought>, <reflection>
    - Bloques Markdown: ### Thinking, ## Reasoning, etc.
    - Patrones texto plano: "Let me think...", "Reasoning:", etc.
    """
    
    # Tags XML que pueden contener thinking (con variaciones)
    XML_TAGS = [
        'thinking', 'reasoning', 'thought', 'reflection', 
        'analysis', 'internal', 'process', 'scratchpad'
    ]
    
    # Headers markdown que indican thinking
    MARKDOWN_HEADERS = [
        'thinking', 'reasoning', 'thought process', 
        'let me think', 'internal reasoning', 'reflection',
        'analysis process', 'internal analysis'  # "analysis" solo es muy genérico
    ]
    
    # Patrones de texto plano al inicio de línea
    TEXT_PATTERNS = [
        r'^let me think',
        r'^thinking:',
        r'^reasoning:',
        r'^thought process:',
        r'^internal analysis:',
        r'^reflection:',
        r'^\*\*thinking\*\*',
        r'^\*\*reasoning\*\*'
    ]
    
    def __init__(self):
        # Compilar patrones regex para eficiencia
        self._compile_patterns()
        logger.info("LLMResponseParser inicializado")
    
    def _compile_patterns(self):
        """Precompila todos los patrones regex para mejor performance"""
        
        # Pattern para tags XML (con contenido multi-línea, no-greedy)
        xml_patterns = []
        for tag in self.XML_TAGS:
            # Detecta <tag>...</tag> con cualquier contenido dentro
            pattern = f'<{tag}>(.*?)</{tag}>'
            xml_patterns.append(pattern)
        
        # Combina todos en un solo pattern con alternativas
        self.xml_pattern = re.compile(
            '|'.join(xml_patterns),
            re.DOTALL | re.IGNORECASE
        )
        
        # Pattern para headers markdown (## Thinking, ### Reasoning, etc.)
        # Captura el header más todo el contenido hasta:
        # - Doble salto de línea (párrafo vacío), O
        # - Otro header (línea que empieza con #), O
        # - Fin del texto
        markdown_patterns = []
        for header in self.MARKDOWN_HEADERS:
            # Captura header + opcional espacio + contenido hasta condición de parada
            pattern = rf'^#+\s*{re.escape(header)}\s*$\n(.*?)(?=\n\n|^#|\Z)'
            markdown_patterns.append(pattern)
        
        self.markdown_pattern = re.compile(
            '|'.join(markdown_patterns),
            re.MULTILINE | re.DOTALL | re.IGNORECASE
        )
        
        # Pattern para bloques de texto plano
        self.text_pattern = re.compile(
            '|'.join(self.TEXT_PATTERNS),
            re.MULTILINE | re.IGNORECASE
        )
    
    def parse(self, raw_response: str, debug: bool = False) -> dict:
        """
        Procesa la respuesta del LLM y extrae la respuesta limpia.
        
        Args:
            raw_response: Respuesta completa del LLM (con o sin thinking)
            debug: Si True, retorna también el thinking extraído
        
        Returns:
            dict con:
                - 'clean_response': Respuesta limpia sin thinking
                - 'thinking_process': El thinking extraído (solo si debug=True)
                - 'had_thinking': Boolean indicando si se encontró thinking
        """
        if not raw_response or not isinstance(raw_response, str):
            logger.warning("Respuesta vacía o no es string")
            return {
                'clean_response': '',
                'thinking_process': '' if debug else None,
                'had_thinking': False
            }
        
        original_length = len(raw_response)
        thinking_extracted = []
        
        # Paso 1: Remover tags XML
        cleaned, xml_thinking = self._remove_xml_tags(raw_response)
        if xml_thinking:
            thinking_extracted.extend(xml_thinking)
        
        # Paso 2: Remover headers markdown
        cleaned, md_thinking = self._remove_markdown_headers(cleaned)
        if md_thinking:
            thinking_extracted.extend(md_thinking)
        
        # Paso 3: Remover bloques de texto plano
        cleaned, text_thinking = self._remove_text_blocks(cleaned)
        if text_thinking:
            thinking_extracted.extend(text_thinking)
        
        # Paso 4: Limpieza final
        cleaned = self._final_cleanup(cleaned)
        
        # Logging y resultado
        had_thinking = len(thinking_extracted) > 0
        if had_thinking:
            removed_chars = original_length - len(cleaned)
            logger.info(f"Thinking detectado y removido: {removed_chars} caracteres ({len(thinking_extracted)} bloques)")
        
        result = {
            'clean_response': cleaned,
            'had_thinking': had_thinking
        }
        
        if debug:
            result['thinking_process'] = '\n\n---\n\n'.join(thinking_extracted) if thinking_extracted else ''
        
        return result
    
    def _remove_xml_tags(self, text: str) -> tuple:
        """
        Remueve todos los tags XML de thinking.
        Retorna: (texto_limpio, lista_de_thinking_extraido)
        """
        thinking_blocks = []
        
        # Encuentra todos los matches
        for match in self.xml_pattern.finditer(text):
            # El contenido está en alguno de los grupos (cada tag es un grupo)
            content = match.group(0)  # El match completo
            thinking_blocks.append(content)
        
        # Remueve todos los matches
        cleaned = self.xml_pattern.sub('', text)
        
        return cleaned, thinking_blocks
    
    def _remove_markdown_headers(self, text: str) -> tuple:
        """
        Remueve secciones markdown que indican thinking.
        Usa un enfoque línea por línea más robusto.
        Retorna: (texto_limpio, lista_de_thinking_extraido)
        """
        thinking_blocks = []
        lines = text.split('\n')
        result_lines = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Detecta si la línea es un header markdown con keyword de thinking
            if line.strip().startswith('#'):
                header_text = line.strip().lstrip('#').strip().lower()
                
                # Verifica si el header contiene algún keyword de thinking
                is_thinking_header = any(
                    keyword in header_text 
                    for keyword in self.MARKDOWN_HEADERS
                )
                
                if is_thinking_header:
                    # Captura este header y todo hasta el próximo header o párrafo vacío
                    block = [line]
                    i += 1
                    
                    while i < len(lines):
                        next_line = lines[i]
                        
                        # Para si encuentra otro header
                        if next_line.strip().startswith('#'):
                            break
                        
                        # Para si encuentra línea vacía Y la siguiente también (párrafo vacío)
                        if not next_line.strip():
                            if i + 1 < len(lines) and not lines[i + 1].strip():
                                block.append(next_line)
                                i += 1
                                break
                        
                        block.append(next_line)
                        i += 1
                    
                    # Guarda el bloque como thinking
                    thinking_blocks.append('\n'.join(block))
                    continue
            
            # Si no es thinking header, guarda la línea
            result_lines.append(line)
            i += 1
        
        cleaned = '\n'.join(result_lines)
        return cleaned, thinking_blocks
    
    def _remove_text_blocks(self, text: str) -> tuple:
        """
        Remueve bloques de texto plano que parecen thinking.
        Estos suelen estar al inicio y van hasta un salto de línea doble.
        """
        thinking_blocks = []
        lines = text.split('\n')
        cleaned_lines = []
        skip_mode = False
        
        for line in lines:
            # Si la línea matchea un pattern de inicio de thinking
            if self.text_pattern.match(line.strip().lower()):
                skip_mode = True
                thinking_blocks.append(line)
                continue
            
            # Si estamos en modo skip, continuamos hasta línea vacía
            if skip_mode:
                if line.strip() == '':
                    skip_mode = False  # Fin del bloque de thinking
                else:
                    thinking_blocks.append(line)
                continue
            
            # Si no estamos skipeando, guardamos la línea
            cleaned_lines.append(line)
        
        cleaned = '\n'.join(cleaned_lines)
        thinking_text = '\n'.join(thinking_blocks) if thinking_blocks else None
        
        return cleaned, [thinking_text] if thinking_text else []
    
    def _final_cleanup(self, text: str) -> str:
        """
        Limpieza final: remueve espacios extras, líneas vacías múltiples, etc.
        """
        # Remueve múltiples saltos de línea
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Remueve espacios al inicio y final de cada línea
        lines = [line.rstrip() for line in text.split('\n')]
        text = '\n'.join(lines)
        
        # Remueve espacios al inicio y final del texto completo
        text = text.strip()
        
        return text
    
    def quick_parse(self, raw_response: str) -> str:
        """
        Método rápido que solo retorna la respuesta limpia (sin metadata).
        Útil para cuando solo necesitas el texto limpio.
        """
        result = self.parse(raw_response, debug=False)
        return result['clean_response']


# Instancia global para reutilizar (evita recompilar patterns)
_parser_instance = None

def get_parser() -> LLMResponseParser:
    """
    Retorna una instancia singleton del parser.
    Esto evita recompilar los regex en cada llamada.
    """
    global _parser_instance
    if _parser_instance is None:
        _parser_instance = LLMResponseParser()
    return _parser_instance


# Función helper para uso directo
def clean_llm_response(raw_response: str, debug: bool = False) -> str:
    """
    Función helper que limpia una respuesta del LLM de forma simple.
    
    Args:
        raw_response: La respuesta completa del LLM
        debug: Si True, loggea información sobre el thinking detectado
    
    Returns:
        str: La respuesta limpia sin thinking
    """
    parser = get_parser()
    result = parser.parse(raw_response, debug=debug)
    
    if debug and result['had_thinking']:
        logger.debug(f"Thinking removido, respuesta limpia: {len(result['clean_response'])} chars")
    
    return result['clean_response']
