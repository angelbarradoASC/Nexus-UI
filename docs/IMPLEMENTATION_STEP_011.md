# Implementation Step 011

## Paso

Preparación de `Nexus` para funcionar en modo `API-only`, sin dependencia de modelos locales.

## Que hago

- Defino una plantilla de entorno pensada para cloud-only.
- Dejo `OpenRouter Free` como opción principal para arrancar.
- Dejo `Groq Free` como segunda opción inmediata.
- Añado un script genérico para validar cualquier proveedor OpenAI-compatible.

## Que toco

- `.env.api-only.example`
- `scripts/test_api_provider.py`
- `docs/API_ONLY_LLM_SETUP.md`

## Qué queda listo

Ahora ya hay un camino explícito para:

- no usar L0 local
- configurar un proveedor API como motor principal
- validar el proveedor antes de conectarlo al producto

## Proveedores priorizados

1. `OpenRouter Free`
2. `Groq Free`

## Test pasados

```text
python -m py_compile scripts\test_api_provider.py
ok
```

## Siguiente paso natural

1. copiar `.env.api-only.example` a `.env`
2. meter la API key elegida
3. ejecutar `python scripts\test_api_provider.py`
4. abrir Nexus ya contra proveedor cloud puro
