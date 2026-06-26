# Implementation Step 010

## Paso

Preparación de `Nexus` para usar endpoints hospedados de NVIDIA API Catalog / NIM como proveedor LLM de desarrollo.

## Que hago

- Investigo la oferta oficial de NVIDIA para acceso gratuito de desarrollo.
- Verifico que los endpoints hospedados usan una API compatible con OpenAI.
- Preparo el proyecto para usar NVIDIA como `L1` sin reescribir el router.
- Añado un script real para validar conectividad y modelos disponibles.

## Qué he verificado

Consulta hecha el `2026-05-14`, usando fuentes oficiales de NVIDIA:

- acceso gratis para prototipado y desarrollo mediante el NVIDIA Developer Program
- URL hospedada de integración:
  - `https://integrate.api.nvidia.com/v1`
- compatibilidad OpenAI-style para chat completions y listado de modelos

Fuentes:

- [NVIDIA NIM for Developers](https://developer.nvidia.com/nim?ncid=em-nurt-723851)
- [NVIDIA NIM LLM API Reference](https://docs.nvidia.com/nim/large-language-models/2.0.0/reference/api-reference.html)
- [NVIDIA API Catalog](https://build.nvidia.com/)
- [NVIDIA Technical Blog sobre acceso gratis a NIM](https://developer.nvidia.com/blog/access-to-nvidia-nim-now-available-free-to-developer-program-members/)
- [Ejemplo OpenAI-compatible con endpoint NVIDIA](https://docs.nvidia.com/nemo/curator/latest/curate-text/generate-data/connect-service/openai.html)

## Qué toco

### Configuración

- `app/config.py`
  - añade:
    - `nvidia_api_key`
    - `nvidia_api_base_url`
    - `nvidia_llm_model`
    - `nvidia_use_as_l1`
  - añade properties:
    - `l1_url`
    - `l1_key`
    - `l1_model`

### Router LLM

- `app/agents/llm_router.py`
  - usa `cfg.l1_url`, `cfg.l1_key` y `cfg.l1_model`
  - eso permite que NVIDIA entre como `L1` sin tocar el resto del flujo

### Soporte operativo

- `.env.nvidia.example`
- `scripts/test_nvidia_api.py`
- `docs/NVIDIA_NIM_SETUP.md`

### Tests

- `tests/unit/test_config.py`
- `tests/unit/test_llm_router.py`

## Qué queda listo

Ahora `Nexus` puede usar NVIDIA como proveedor `L1` de desarrollo si se configuran:

```env
NVIDIA_USE_AS_L1=true
NVIDIA_API_KEY=...
NVIDIA_API_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_LLM_MODEL=meta/llama-3.1-8b-instruct
```

## Test pasados

```text
python -m pytest tests\unit\test_config.py -q
23 passed

python -m pytest tests\unit\test_llm_router.py -q
8 passed

python -m py_compile app\config.py app\agents\llm_router.py scripts\test_nvidia_api.py
ok
```

## Limitación actual

No se ha podido ejecutar la prueba real contra NVIDIA porque en este entorno no tengo una `NVIDIA_API_KEY` válida cargada.

## Siguiente paso natural

1. obtener la `NVIDIA_API_KEY`
2. ejecutar `python scripts\test_nvidia_api.py`
3. fijar el modelo real a usar según `/v1/models`
4. decidir si NVIDIA será respaldo cloud temporal o proveedor principal de desarrollo
