# NVIDIA API Catalog y NIM hospedado

## Qué es exactamente

Hay dos cosas distintas:

1. **Endpoints hospedados por NVIDIA**
   - sirven modelos por API
   - son útiles para prototipado y desarrollo
   - usan la base URL `https://integrate.api.nvidia.com/v1`

2. **NIM autohospedado**
   - descargas un microservicio NIM y lo ejecutas en tu propia infraestructura con GPU
   - es útil para desarrollo, testing y despliegues más controlados

## Qué he verificado

Según la documentación oficial consultada el `2026-05-14`:

- NVIDIA ofrece acceso gratis a endpoints NIM hospedados para prototipado mediante el NVIDIA Developer Program.
- NVIDIA NIM para LLM expone una API compatible con OpenAI.
- La URL de integración hospedada usada por la propia documentación de NVIDIA es:
  - `https://integrate.api.nvidia.com/v1`

Fuentes:

- [NVIDIA NIM for Developers](https://developer.nvidia.com/nim?ncid=em-nurt-723851)
- [NVIDIA NIM LLM API Reference](https://docs.nvidia.com/nim/large-language-models/2.0.0/reference/api-reference.html)
- [NVIDIA API Catalog](https://build.nvidia.com/)
- [Access to NVIDIA NIM Now Available Free to Developer Program Members](https://developer.nvidia.com/blog/access-to-nvidia-nim-now-available-free-to-developer-program-members/)
- [OpenAI-compatible example with NVIDIA endpoint](https://docs.nvidia.com/nemo/curator/latest/curate-text/generate-data/connect-service/openai.html)

## Qué implica para Nexus

Nuestro router actual ya habla con endpoints OpenAI-compatible.

Eso significa que para `Nexus` no hace falta crear un cliente especial de cero.
Solo necesitamos:

- una API key de NVIDIA
- una base URL
- un modelo válido del catálogo

## Preparación ya hecha en el proyecto

### Config

Se ha añadido soporte para:

- `NVIDIA_API_KEY`
- `NVIDIA_API_BASE_URL`
- `NVIDIA_LLM_MODEL`
- `NVIDIA_USE_AS_L1`

Si activas `NVIDIA_USE_AS_L1=true`, el router puede usar NVIDIA como `L1` de desarrollo sin tocar más código.

### Fichero de ejemplo

- [`.env.nvidia.example`](C:/DEV/Nexus-UI/.env.nvidia.example)

### Script de validación

- [`scripts/test_nvidia_api.py`](C:/DEV/Nexus-UI/scripts/test_nvidia_api.py)

Este script:

1. llama a `GET /models`
2. lista modelos disponibles
3. hace una prueba real con `POST /chat/completions`

## Cómo activarlo

Añade al `.env` real:

```env
NVIDIA_USE_AS_L1=true
NVIDIA_API_KEY=nvapi-xxxxxxxxxxxxxxxxxxxxxxxx
NVIDIA_API_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_LLM_MODEL=meta/llama-3.1-8b-instruct
```

## Cómo comprobar conectividad

```powershell
$env:NVIDIA_API_KEY="nvapi-xxxxxxxxxxxxxxxxxxxxxxxx"
$env:NVIDIA_API_BASE_URL="https://integrate.api.nvidia.com/v1"
$env:NVIDIA_LLM_MODEL="meta/llama-3.1-8b-instruct"
python scripts\test_nvidia_api.py
```

## Nota importante sobre producción

La lectura razonable de la documentación oficial es esta:

- el acceso gratis está pensado para **desarrollo y prototipado**
- para producción lo serio sería:
  - o desplegar NIM en infraestructura propia
  - o pasar a una modalidad enterprise / endpoint dedicado

## Siguiente paso recomendable

1. conseguir la `NVIDIA_API_KEY`
2. ejecutar el script de prueba
3. fijar un modelo real del catálogo actual
4. decidir si NVIDIA será `L1` de desarrollo o respaldo cloud temporal
