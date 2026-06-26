# API-only LLM setup

## Objetivo

Dejar `Nexus` funcionando sin depender de modelos locales.

Eso significa:

- no usar `LM Studio`
- no usar `Ollama`
- no asumir GPU ni CPU suficiente en el equipo del usuario
- sacar toda la inferencia a proveedores cloud con API

## Proveedor recomendado ahora mismo

### 1. OpenRouter Free

Es la opcion que mejor encaja para arrancar ya:

- plan gratis oficial
- modelos gratis oficiales
- API OpenAI-compatible
- no hace falta montar infraestructura

Fuentes:

- [OpenRouter Pricing](https://openrouter.ai/pricing)
- [OpenRouter Free Models Router](https://openrouter.ai/docs/guides/guides/free-models-router-playground)
- [OpenRouter `:free` variants](https://openrouter.ai/docs/guides/routing/model-variants/free)

Modelo recomendado para empezar:

- `baidu/cobuddy:free`

### 2. Groq Free

Muy buena segunda opcion:

- gratis para build/test
- OpenAI-compatible
- rapido

Fuentes:

- [Groq Overview](https://console.groq.com/docs)
- [Groq Rate Limits](https://console.groq.com/docs/rate-limits)
- [Groq OpenAI Compatibility](https://console.groq.com/docs/openai)

Modelo recomendado para empezar:

- `openai/gpt-oss-20b`

## Plantilla preparada

- [`.env.api-only.example`](C:/DEV/Nexus-UI/.env.api-only.example)

## Configuracion recomendada

### OpenRouter Free

```env
LLM_PRIORITY=cost
LLM_L0_URL=
LLM_L0_KEY=
LLM_L0_MODEL=
LLM_L1_URL=https://openrouter.ai/api/v1
LLM_L1_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxx
LLM_L1_MODEL=openrouter/free
```

### Groq Free

```env
LLM_PRIORITY=cost
LLM_L0_URL=
LLM_L0_KEY=
LLM_L0_MODEL=
LLM_L1_URL=https://api.groq.com/openai/v1
LLM_L1_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxx
LLM_L1_MODEL=openai/gpt-oss-20b
```

## Script de prueba

- [`scripts/test_api_provider.py`](C:/DEV/Nexus-UI/scripts/test_api_provider.py)

Uso con OpenRouter:

```powershell
$env:TEST_LLM_BASE_URL="https://openrouter.ai/api/v1"
$env:TEST_LLM_API_KEY="sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxx"
$env:TEST_LLM_MODEL="baidu/cobuddy:free"
python scripts\test_api_provider.py
```

Uso con Groq:

```powershell
$env:TEST_LLM_BASE_URL="https://api.groq.com/openai/v1"
$env:TEST_LLM_API_KEY="gsk_xxxxxxxxxxxxxxxxxxxxxxxx"
$env:TEST_LLM_MODEL="openai/gpt-oss-20b"
python scripts\test_api_provider.py
```

## Lo importante para Nexus

No he cambiado la arquitectura del router porque no hacía falta.

El router ya sabe trabajar con endpoints OpenAI-compatible.

Por eso el camino bueno ahora es:

1. dejar `L0` vacío
2. poner el proveedor cloud en `L1`
3. validar con el script
4. usar ese proveedor como motor principal de desarrollo

## Recomendacion honesta

Si quieres **cero tarjeta** y **configurable ya**:

1. OpenRouter Free
2. Groq Free

Si luego quieres, metemos detrás:

3. Zhipu / GLM Flash
4. NVIDIA
