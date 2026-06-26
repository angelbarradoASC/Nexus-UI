# IMPLEMENTATION STEP 035

## Paso
Análisis del estado real del servidor y saneamiento del stack remoto LLM.

## Qué había realmente instalado

En `llmpro` ya existían estas piezas útiles:

- `LiteLLM` activo en `0.0.0.0:4000`
- `n8n` activo en `5678`
- `Ollama` ya disponible en `11434`
- varios modelos ya descargados

Modelos detectados:

- `qwen2.5:1.5b`
- `qwen2.5-coder:1.5b`
- `llama3.2:3b`
- `nomic-embed-text:latest`

## Qué estaba mal

Había dos inconsistencias:

### 1. Router LiteLLM apuntando a modelos inexistentes

El fichero remoto seguía anunciando:

- `cpu-qwen-3b`
- `cpu-qwen-7b`

pero esos modelos no estaban instalados en `Ollama`.

### 2. Doble Ollama

Había un `ollama serve` real corriendo desde un contenedor `moby/containerd`, y además un `ollama.service` local que entraba en conflicto con ese puerto.

Resultado:

- el servicio `systemd` de Ollama fallaba
- pero el puerto `11434` seguía respondiendo porque el contenedor ya lo estaba sirviendo

## Qué he hecho

- Actualizado [remote/router/litellm_config.yaml](C:/DEV/Nexus-UI/remote/router/litellm_config.yaml) para publicar aliases reales:
  - `cpu-fast` -> `qwen2.5:1.5b`
  - `cpu-general` -> `llama3.2:3b`
  - `cpu-coder` -> `qwen2.5-coder:1.5b`
- Aplicada esa config al servidor remoto
- Reiniciado `open-nexus-litellm`
- Deshabilitado el `ollama.service` duplicado para no pelearse con el `Ollama` ya existente en contenedor

## Estado final bueno

- `open-nexus-litellm.service` activo
- `Ollama` operativo en `11434`
- `LiteLLM` operativo en `4000`
- aliases publicados correctos en `/v1/models`
- chat validado contra el router con respuesta real

## Validación real

Se ha validado:

- `GET /v1/models`
- `POST /v1/chat/completions`

El router respondió correctamente usando:

- `cpu-fast`
- `cpu-general`
- `cpu-coder`

## Conclusión

No hacía falta instalar desde cero.
Hacía falta detectar lo ya existente y ordenarlo.

Ahora el stack está coherente:

- un único router `LiteLLM`
- un único `Ollama` efectivo
- aliases que corresponden a modelos reales

## Siguiente paso

- decidir qué modelo dejamos como principal por calidad
- decidir si `cpu-fast` será el default o si metemos proveedor remoto como primario
- empezar a cablear `Open-Nexus` contra `http://192.168.1.150:4000`
