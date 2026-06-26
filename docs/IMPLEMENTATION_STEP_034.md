# IMPLEMENTATION STEP 034

## Paso
Montaje inicial del router remoto LLM en `llmpro` y runtime CPU para modelos locales.

## Qué se ha montado

En el repo:

- [remote/router/litellm_config.yaml](C:/DEV/Nexus-UI/remote/router/litellm_config.yaml)
- [remote/router/litellm.env.example](C:/DEV/Nexus-UI/remote/router/litellm.env.example)
- [remote/router/systemd/open-nexus-litellm.service](C:/DEV/Nexus-UI/remote/router/systemd/open-nexus-litellm.service)
- [scripts/deploy_remote_router.py](C:/DEV/Nexus-UI/scripts/deploy_remote_router.py)
- [docs/REMOTE_ROUTER_CPU_SETUP.md](C:/DEV/Nexus-UI/docs/REMOTE_ROUTER_CPU_SETUP.md)
- [docs/REMOTE_INFRA_DIAGNOSTIC_20260529.md](C:/DEV/Nexus-UI/docs/REMOTE_INFRA_DIAGNOSTIC_20260529.md)

En el servidor `llmpro`:

- `Ollama` instalado en `/usr/local/bin/ollama`
- `ollama.service` habilitado y activo
- `LiteLLM` desplegado en:
  - `/opt/open-nexus-router/.venv`
  - `/opt/open-nexus-router/router/litellm_config.yaml`
  - `/opt/open-nexus-router/router/.env`
- `open-nexus-litellm.service` habilitado y activo

## Qué endpoints quedan vivos

- `Ollama`: `127.0.0.1:11434`
- `LiteLLM`: `0.0.0.0:4000`

## Validación real

Se ha verificado por SSH:

- `ollama.service` activo
- `open-nexus-litellm.service` activo
- `LiteLLM` expone aliases en `/v1/models`

Aliases activos en el router:

- `cpu-qwen-3b`
- `cpu-qwen-7b`

## Qué ha salido bien

- El servidor sí sirve como backend de routing
- `LiteLLM` quedó funcionando como capa única
- `Ollama` quedó instalado como runtime CPU local
- la máquina no necesita GPU para esta fase

## Qué ha salido regular

El `pull` del modelo bootstrap `qwen2.5:3b` no se ha completado aún de forma fiable.

Hallazgos:

- `Ollama` sí inicia la descarga
- hubo al menos un `unexpected EOF` en una de las partes del download
- por prudencia se ha parado el `pull` para no dejar un proceso colgando mientras no decidamos modelo final

## Conclusión operativa

La infraestructura ya está montada.

Lo único pendiente para tener inferencia CPU real es elegir el primer modelo y descargarlo bien.

Eso ya no es infraestructura.
Eso ya es decisión de modelo.

## Siguiente paso

- decidir modelo CPU bootstrap
- descargarlo con `ollama pull`
- validar `POST /v1/chat/completions` en `LiteLLM`
- y luego decidir cómo se mezcla con proveedores remotos y con Google más adelante
