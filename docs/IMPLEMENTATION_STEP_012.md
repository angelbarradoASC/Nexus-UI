# Implementation Step 012

## Paso

Activación real de `Nexus` en modo `API-only` con OpenRouter como proveedor principal.

## Que hago

- Configuro el `.env` real para no depender de ningún `L0` local.
- Pongo OpenRouter como `L1` principal.
- Fijo un modelo gratuito del ecosistema chino que responde de verdad:
  - `baidu/cobuddy:free`
- Ajusto el router para cabeceras recomendadas de OpenRouter.
- Hago al router tolerante a respuestas donde el texto llega en `reasoning` en vez de `content`.

## Que toco

- `.env`
- `.env.api-only.example`
- `app/agents/llm_router.py`
- `scripts/test_api_provider.py`
- `docs/API_ONLY_LLM_SETUP.md`
- `tests/unit/test_llm_router.py`

## Validación real

Se ha validado una llamada real contra OpenRouter:

- `GET /models` responde correctamente
- el modelo `baidu/cobuddy:free` responde

Matiz observado:

- este modelo puede devolver parte o toda la salida en el campo `reasoning`
- por eso se ha endurecido el router para aceptar:
  - `message.content`
  - o fallback a `message.reasoning`

## Test pasados

```text
python -m pytest tests\unit\test_llm_router.py -q
10 passed

python -m py_compile app\agents\llm_router.py scripts\test_api_provider.py
ok
```

## Resultado

`Nexus` ya queda orientado a:

- inferencia 100% API
- sin necesidad de modelo local
- con OpenRouter operativo como proveedor principal de desarrollo

## Siguiente paso natural

1. probar una llamada real desde el flujo de chat de `Nexus`
2. decidir si mantenemos `baidu/cobuddy:free` o cambiamos a otro free más obediente
3. meter un segundo proveedor de respaldo como `Groq`
