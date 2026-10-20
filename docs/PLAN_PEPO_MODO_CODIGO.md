# Plan — PEPO "modo código" (agente local tipo Cursor)

Estado: **Fases 0 y 1 hechas (2026-10-19); bloqueado por la cuota del proveedor de IA** (ver sección 8) · Rama de trabajo: `feature/pepo-code-mode` (desde `master`)

## 1. Objetivo

Que PEPO pueda trabajar sobre un proyecto real del PC del usuario como lo hace Cursor:
entender el código, proponer cambios como diffs, aplicarlos con aprobación, ejecutar
tests y corregir hasta que pasen. Todo local, con permisos explícitos y deshacible.

No-objetivos de este plan: editor embebido, autocompletado en línea, indexado semántico
(embeddings), unificar los otros agentes de PEPO (SystemTaskAgent, RemoteOps…).

## 2. Punto de partida (verificado leyendo el código, 2026-10-19)

| Pieza | Estado real |
|---|---|
| Bucle con tool calling | `SystemTaskAgent` (12 pasos): `lookup_cmdb`, `run_diagnostic`, `list_directory`, `read_file`, `ask_user`, `run_script`, `finish`. `ConfirmableAgent` (base de RemoteOps/SelfConfig/MCP): 6 pasos. |
| Confirmación | Texto "sí/no" en el chat o `POST /agents/pending/{id}/confirm`. Pendientes persistidos en SQLite. |
| Lectura de ficheros | `read_file` sin rangos (primeros 100.000 caracteres) y **sin restricción de ruta**. Sin `grep`/`glob`. |
| Edición | No existe. Solo vía `run_script` (PowerShell). Sin diff ni deshacer. |
| Modo explícito | `ChatRequest.mode` existe (por defecto `general`); la UI lo envía fijo. Hoy el clasificador de intención decide el agente. |
| UI del chat | Texto escapado (`escHtml`): sin markdown, sin diffs, sin streaming. |

**Limitaciones de `ConfirmableAgent` que bloquean el caso Cursor** (hay que levantarlas):

1. Tras confirmar una propuesta, `execute()` **termina**: el resultado no vuelve al LLM, así que no puede encadenar editar → probar → corregir.
2. Solo procesa la **primera** tool call de cada turno (las demás se ignoran). Cursor lee varios ficheros en paralelo.
3. `max_loop_steps = 6` y `max_tokens = 1400` fijos; nivel de modelo fijo (`preferred_level=2`).

## 3. Decisiones de diseño

**D1 — Entrada explícita, sin clasificador.** Un interruptor "Código" en la UI de PEPO envía `mode="code"` + carpeta de trabajo. El coordinador, si `mode == "code"` y hay `CodeAgent`, salta el router de skills (la causa de errores como "Cisco → ratón"). Los pendientes del `CodeAgent` se comprueban primero, como los demás.

**D2 — Nuevo `CodeAgent(ConfirmableAgent)`, con extensiones retrocompatibles a la base**, activadas por atributos de clase (por defecto, comportamiento actual):
`resume_after_execute` (el resultado de `execute()` vuelve como mensaje `tool` y el bucle sigue), `batch_readonly_calls` (ejecuta todas las lecturas del turno hasta la primera propuesta), `preferred_level`, `max_loop_steps`, `max_tokens`. Los tres agentes existentes y sus tests no cambian.

**D3 — Herramientas.**

| Tool | Efecto | Permiso |
|---|---|---|
| `read_file(path, start_line?, end_line?)` | Lectura con números de línea, máx. ~400 líneas por llamada | automático |
| `grep(pattern, path?, glob?)` | Busca en el workspace (ripgrep si existe; si no, Python), máx. 100 coincidencias | automático |
| `glob(pattern)` · `list_directory(path)` | Lista ficheros | automático |
| `git_status` · `git_diff` | Solo lectura | automático |
| `edit_file(path, old_string, new_string)` | Reemplazo exacto y único (como el Edit de Claude Code); **propone un diff**, no escribe | aprobación |
| `write_file(path, content)` | Solo ficheros nuevos | aprobación |
| `run_command(command, timeout?)` | Ejecuta en el workspace | aprobación (salvo lista "permitir siempre" del usuario) |
| `update_plan(items)` | Lista de tareas visible en la UI, sin efectos | automático |
| `ask_user`, `finish` | Ya existen en la base | — |

**D4 — Seguridad (innegociable).**
- **Sandbox de rutas:** todo path se resuelve (`realpath`) y debe quedar dentro del workspace; se rechazan `..`, rutas absolutas de otra unidad, UNC y symlinks que escapen.
- **Lista negra de lectura/escritura:** `.env*`, `*.pem`, `*.key`, `credentials*`, `.git/` (escritura), almacenes de credenciales. El contenido de los ficheros **viaja a un LLM en la nube** (Groq), por eso se bloquea por defecto y se redacta con patrones de claves/tokens en las salidas.
- **Escrituras atómicas con comprobación de hash:** el diff se propone con el hash del fichero; si cambió antes de aprobar, se rechaza y se vuelve a proponer.
- **Deshacer:** antes de la primera edición de una tarea se guarda copia de cada fichero (en `%LOCALAPPDATA%\Open-Nexus\code_checkpoints\<tarea>\`); comando "deshacer" restaura.
- **Comandos:** el shell no se puede sandboxear de verdad, así que `run_command` siempre muestra el comando exacto y pide aprobación; solo se auto-aprueba lo que el usuario añada a una lista de patrones exactos (p. ej. `pytest tests/unit`). Entorno del subproceso sin claves de API.
- **Workspace permitido:** lista de carpetas autorizadas, editable en `/nexus/settings` (norma del proyecto: toda config nueva también en la UI de configuración, no solo `.env`).
- **Auditoría:** cada propuesta, aprobación y ejecución al repositorio de auditoría existente.
- **Permiso de skill:** `OPERATE`; activable/desactivable desde el gestor de agentes (`agent_settings`).

**D5 — Prompt `pepo.code_loop`** (en `app/nexus/prompts/catalogue.py`): explorar antes de editar, cambios mínimos, ejecutar tests tras editar, citar `ruta:línea`, no inventar rutas, preguntar solo lo imprescindible. Si el workspace tiene `PEPO.md` o `CLAUDE.md`, se inyecta (tope 8 KB) como reglas del proyecto.

**D6 — Modelo.** Un bucle de agente necesita buen tool calling: nivel configurable (`code_agent_level`), por defecto L2 (Groq qwen3.8-27b), con L3 para tareas difíciles. L1 (`qwen2.5:3b` en 192.168.68.150) no sirve para esto. Límites duros por tarea (pasos y tokens) y mensaje honesto si Groq da 429, porque un bucle agéntico gasta cuota mucho más rápido que el chat.

**D7 — Contexto.** Salidas de tools truncadas con aviso, y los resultados antiguos del bucle se sustituyen por un resumen de una línea cuando se supera un presupuesto de tokens.

**D8 — UI.**
- Fase 1: interruptor "Código" + selector de carpeta en `nexus_pepo.html`; propuestas con botones **Aprobar / Rechazar** (usan `/agents/pending/{id}/confirm|cancel`, ya existentes) en lugar de teclear "sí".
- Renderizador de diff (líneas `+`/`-` coloreadas) en `nexus_pepo.js`, sin añadir dependencias.
- Fase 4: trazas de progreso ("Leyendo X…", "Ejecutando tests…") y después streaming.

## 4. Fases y criterio de aceptación

Cada fase termina verificada **en la app de escritorio real** (no en navegador) y con la suite completa en verde. Las estimaciones son orientativas.

| Fase | Contenido | Aceptación | Esfuerzo |
|---|---|---|---|
| **0. Base** | Extensiones a `ConfirmableAgent` tras atributos de clase + tests | Los tests de RemoteOps/SelfConfig/MCP pasan sin cambios; tests nuevos del bucle con router falso (reanudar tras execute, lecturas en lote) | ½ día |
| **1. Solo lectura** | `CodeAgent` con `read_file`/`grep`/`glob`/`list_directory`/`git_*`, sandbox, lista negra, `mode="code"` en coordinador, prompt, interruptor en UI | "Explica cómo funciona X" sobre este repo responde con `ruta:línea` correctos; intentos de salir del workspace o leer `.env` son rechazados (tests) | 1 día |
| **2. Edición** | `edit_file`/`write_file` con diff, hash, botones Aprobar/Rechazar, checkpoints y "deshacer" | En un repo de pruebas, PEPO cambia una función, el diff se aprueba y se aplica; deshacer restaura; fichero modificado a mano → se rechaza | 1–2 días |
| **3. Ejecutar y corregir** | `run_command`, lista "permitir siempre", salida truncada, bucle que continúa tras ejecutar | Con un test roto en el repo de pruebas, PEPO edita, ejecuta `pytest`, lee el fallo y corrige hasta verde, con aprobación visible en cada paso | 1–2 días |
| **4. Experiencia** | Progreso/streaming, renderizador de diff pulido, `update_plan` visible | La UI muestra qué está haciendo mientras trabaja | 2 días |
| **5. Contexto y reglas** | `PEPO.md`/`CLAUDE.md`, compactación de contexto, `code_agent_level` en configuración | Tarea de >20 pasos sin desbordar contexto | 1 día |

## 5. Pruebas

- **Seguridad (bloqueantes):** `..`, ruta absoluta de otra unidad, UNC, symlink de escape, `.env`/claves, escritura en `.git/`, hash obsoleto, comando sin aprobación, inyección de prompt desde un fichero leído que intente ordenar ejecutar algo (el contenido de ficheros es dato, nunca instrucción).
- **Bucle:** router falso con tool calls en lote, propuesta, aprobación, reanudación, límite de pasos, error del LLM.
- **Vivo:** repositorio de pruebas fuera de `C:\DEV\Nexus-UI` con un test roto; después, el propio Nexus-UI en modo solo lectura.

## 6. Riesgos

| Riesgo | Mitigación |
|---|---|
| Código y secretos salen a un LLM en la nube | Lista negra + redacción + workspace autorizado + aviso en la UI; opción de forzar un modelo local |
| Cuota de Groq (429) en bucles largos | Límites por tarea, nivel configurable, mensaje claro, reintento manual |
| Modelos pequeños fallan en tool calling | Nivel mínimo L2; validar JSON de argumentos y devolver el error al modelo |
| Aprobaciones de comandos que cansan | Lista "permitir siempre" con patrones exactos |
| Cambios en `ConfirmableAgent` rompen agentes existentes | Atributos de clase con valores actuales por defecto; sus tests deben pasar sin tocarlos |

## 7. Decisiones que necesito del usuario

1. **Modelo y privacidad:** ¿aceptas que el código del proyecto se envíe a Groq (L2/L3) con la lista negra de secretos, o prefieres limitarlo a un modelo local (el servidor 192.168.68.150) aunque sea más débil?
2. **Comandos:** ¿aprobación en cada `run_command` (recomendado al principio) o desde ya con lista de permitidos (p. ej. `pytest`, `git diff`)?
3. **Dónde vive:** interruptor dentro del chat de PEPO (recomendado) o página aparte.
4. **Primer workspace:** `C:\DEV\Nexus-UI` (pruebas sobre sí mismo, empezando en solo lectura) o un repositorio de pruebas.

## 8. Registro de avance (2026-10-19)

**Hecho y verificado**
- **Fase 0** (`77b3ca1`): `ConfirmableAgent` con lecturas en lote, reanudar tras ejecutar, `reject()` y parámetros de LLM configurables, apagados por defecto. 804 tests en verde, los de RemoteOps/SelfConfig/MCP sin tocar.
- **Fase 1** (`e35b720`, `8b86dbd`): sandbox (`workspace.py`; probado con una junction real de Windows), herramientas de solo lectura, `CodeAgent`, carpetas autorizadas (`code_settings.json`, API `/api/desktop/code/*`, panel en Configuración), interruptor en el chat de PEPO, cableado `mode="code"` sin clasificador. 953 tests en verde.
- Verificado en la app real por API: carpeta no autorizada rechazada sin gastar LLM; pregunta "lista las carpetas de primer nivel y para qué sirve cada una" respondida correctamente con citas de ruta (124 s).

**Lo que NO está verificado:** el aspecto del interruptor y del panel en la ventana nativa. Se pidió control de pantalla y el permiso del proceso `Python 3.11` (dueño de la ventana al arrancar desde fuente) figura denegado; solo se comprobó por HTTP que el servidor sirve la interfaz nueva.

**Hallazgo bloqueante: la cuota del proveedor.** La cuenta de Groq medida tiene **8.000 tokens/minuto** (cabecera `x-ratelimit-limit-tokens`). Un agente reenvía todo el contexto en cada paso: 1,5 k tokens fijos (prompt + herramientas) más los resultados de lectura. En vivo:
- Sin control, el bucle recibía HTTP 429 en el segundo paso.
- Con el limitador (`pacer.py`) cada paso espera ~1 minuto: una pregunta de 3 pasos tarda ~2 min, y una de 5+ pasos agota el límite de 4 min y se rinde con un mensaje claro (visto con "¿dónde se decide si el historial pasa al clasificador?", 183 s sin respuesta).
- `qwen3:8b` en 192.168.68.150 hace bien el tool calling pero tarda ~72 s por paso (sin GPU útil): tampoco sirve para un bucle interactivo.

**Consecuencia:** el diseño es correcto, pero con 8.000 tokens/min el agente no es interactivo. Antes de seguir con edición/ejecución (fases 2 y 3, que añaden más pasos por tarea) hay que resolver la cuota. Opciones: (a) plan de pago de Groq con más tokens/min (después, subir el valor en Configuración › Modo código; el contexto y el ritmo se ajustan solos); (b) otro proveedor para el nivel del agente; (c) un modelo local con GPU real. Sin esto, las fases 2–3 funcionarían pero a ~1 paso por minuto.

**Mejoras pendientes sin depender de la cuota:** al agotar el tiempo, devolver lo averiguado hasta ese momento en vez de solo el aviso; progreso visible en la UI (fase 4).


### Refuerzo del arnés con modelos propios (2026-10-20)

Objetivo del usuario: preguntas simples sobre código resueltas con los modelos que ya tiene (`qwen3:8b` think=false y `qwen2.5-coder:3b` en 192.168.68.150), mejorando el arnés y no el modelo.

**Medido** (conjunto `tests/eval/code_questions_fresh.json`, 12 preguntas no vistas al afinar; corrector estricto, que infravalora respuestas alternativas válidas):

| Configuración (qwen3:8b) | Aciertos |
|---|---|
| Pre-carga de candidatos (A) | 5/12 |
| Pre-carga + verificador de citas (B) | 4/12 |
| **Sin pre-carga, `find_code` como herramienta** | **9/12** (7,8 pasos, 199 s de media) |
| Sin `find_code` (4 preguntas) | 0/4 (se rinde pronto) |

- Hipótesis refutada: empujar candidatos al contexto empeora (el modelo se ancla en ellos). Queda apagada (`prefetch_hits = 0`).
- Lo que sí ayuda: `find_code` que el modelo llama él mismo (BM25 + sinónimos ES→EN + AST), y que `grep` sin resultados adjunte candidatos de `find_code` (un resultado de herramienta se lee; una regla del prompt no se obedece de forma fiable).
- Recuperación léxica pura: recall@8 = 0,58 en el conjunto fresco.
- Guardas añadidas tras trazas en vivo: ventana mínima de lectura (60 líneas), rangos invertidos tolerados, y la 3ª llamada idéntica en una tarea no se ejecuta (qwen3:8b repitió la misma lectura 9 veces hasta agotar los 10 min). `vendor/` y `third_party/` fuera del índice.
- Velocidad: ~150–200 s por pregunta con qwen3:8b (60 % CPU / 40 % GPU en el servidor). `qwen3:4b` (2,5 GB) cabría entero en GPU; no descargado, pendiente de OK.
- Verificador de citas: efecto no medible con este conjunto (ruido mayor que la señal).
