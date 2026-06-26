# REMOTE ROUTER + CPU LLM STACK

## Qué se monta

Este stack monta dos piezas:

### 1. `Ollama`

Servidor local de modelos por CPU en el host Ubuntu.

Responsabilidad:

- cargar modelos locales
- exponer endpoint local en `127.0.0.1:11434`

### 2. `LiteLLM`

Router/proxy OpenAI-compatible por encima de `Ollama`.

Responsabilidad:

- ofrecer una sola API a Nexus
- abstraer modelos locales y remotos
- permitir meter proveedores externos después

## Por qué esta combinación

- `Ollama` simplifica muchísimo servir modelos CPU
- `LiteLLM` nos da un punto único de entrada
- y más adelante nos deja mezclar:
  - CPU local
  - OpenRouter
  - Groq
  - Gemini
  - otros proveedores

sin reescribir el cliente de `Open-Nexus`

## Topología

- `Ollama`: local only
- `LiteLLM`: accesible en LAN

Puertos:

- `11434` -> `Ollama`
- `4000` -> `LiteLLM`

## Ficheros en repo

- [remote/router/litellm_config.yaml](C:/DEV/Nexus-UI/remote/router/litellm_config.yaml)
- [remote/router/litellm.env.example](C:/DEV/Nexus-UI/remote/router/litellm.env.example)
- [remote/router/systemd/open-nexus-litellm.service](C:/DEV/Nexus-UI/remote/router/systemd/open-nexus-litellm.service)
- [scripts/deploy_remote_router.py](C:/DEV/Nexus-UI/scripts/deploy_remote_router.py)

## Modelos propuestos para CPU

Sin decidir todavía el modelo final, los alias preparados son:

- `cpu-qwen-3b`
- `cpu-qwen-7b`

Motivo:

- Qwen suele responder bien
- aguanta mejor el castellano que varias alternativas pequeñas
- y nos da una escalera razonable entre algo ligero y algo más serio

## Cómo evoluciona luego

Después, cuando decidamos modelos remotos o Google GPU:

- `LiteLLM` seguirá siendo el router
- `Ollama` quedará como fallback local por CPU
- y añadiremos modelos remotos al mismo `config.yaml`

## Decisión operativa

Esta primera versión es deliberadamente simple:

- sin Kubernetes
- sin reverse proxy
- sin TLS
- sin base de datos extra

Primero:

- router funcionando
- runtime local CPU funcionando
- API única funcionando

Luego ya refinamos.
