# Plan: PEPO como asistente de tu bóveda de Obsidian

Fecha: 2026-10-23 · Rama: `feature/pepo-obsidian` (apilada sobre `feature/pepo-code-mode`)

## 1. Objetivo

Que le puedas pedir a PEPO, en el chat, cosas como:

- "apunta en Obsidian una nota sobre X" → la escribe con formato y con los enlaces que correspondan.
- "repasa mi bóveda" → te dice qué hay, qué está roto o suelto y cómo arreglarlo.
- "enlaza mis notas" / "dale formato a esta nota" / "ordena mi bóveda" → propone los cambios y, si apruebas, los aplica.

Sin gastar tokens de Claude: lo pesado lo hace código local y el texto lo escribe el LLM propio de PEPO (router o `qwen3:8b` del servidor).

## 2. Punto de partida (verificado el 2026-10-23)

- Bóveda: `C:\Users\angel\OneDrive - assetsconsultores.es\Boveda1` (abierta en Obsidian, ruta leída de `%APPDATA%\obsidian\obsidian.json`). Contiene solo 2 notas vacías: `cree un enlace.md` e `Indice de notas.md`. Está dentro de OneDrive.
- PEPO no tiene nada de Obsidian ni de notas.
- Piezas reutilizables: sandbox de carpetas (`desktop/code_agent/workspace.py`: rutas, junctions, lista negra de secretos, `redact`), ajustes de carpetas autorizadas (`desktop/storage/code_settings.py`), buscador BM25 (`code_agent/index.py`), flujo proponer/confirmar (`ConfirmableAgent`, igual que la respuesta de Outlook), catálogo de skills + `skill_router` + coordinador, embeddings `nomic-embed-text` en el servidor.

## 3. Principios (salen de lo medido en el modo código)

1. **El código hace lo determinista; el modelo solo tareas pequeñas.** Un 8B no sabe planificar un recorrido: se quedó explorando 10 minutos. Aquí el código lee la bóveda, detecta enlaces rotos, huérfanas y menciones sin enlazar; el modelo solo redacta el texto de una nota o un título/etiquetas.
2. **Todo lo que escribe pasa por vista previa y confirmación.** Crear, modificar o mover. Nunca borra.
3. **Antes de tocar una nota existente, copia de seguridad** en `.pepo/backups/<fecha>/` (carpeta oculta para Obsidian).
4. **Los enlaces los valida el código.** El modelo solo puede enlazar a notas que existen; un `[[enlace]]` inventado se rechaza o se convierte en texto plano.
5. **Repetible sin duplicar** (idempotente) y **sin reformatear lo que no se pidió**: el frontmatter se edita como texto, no se vuelca y recarga (así no se pierden claves ni comentarios).
6. **Seguridad:** solo la bóveda autorizada; `.obsidian/`, `.trash/` y `.pepo/` fuera de alcance; ficheros con nombre de credenciales no se envían al LLM; `redact()` antes de mandar texto al modelo.

## 4. Qué hará y cómo

| Petición | Cómo lo hace | LLM |
|---|---|---|
| Repasar la bóveda | Lee todas las notas, construye el grafo y entrega un informe: enlaces rotos, notas huérfanas, sin frontmatter, vacías, títulos duplicados, menciones de otra nota sin enlazar | No |
| Escribir una nota | Busca notas relacionadas, pasa al modelo su lista de títulos, el modelo redacta usando solo esos enlaces, el código valida, añade frontmatter y muestra vista previa | Sí (1 llamada) |
| Enlazar | Propone `[[enlaces]]` donde una nota menciona el título (o alias) de otra; opcionalmente por similitud | No / opcional |
| Dar formato | Normaliza frontmatter, encabezados y listas siguiendo las convenciones | No |
| Ordenar | Mantiene `Indice de notas.md` (zona entre marcadores) y propone mover/etiquetar; nunca mueve sin confirmar | Opcional (etiquetas) |

Convenciones por defecto (editables en una nota `_PEPO/Convenciones.md` de la bóveda): frontmatter con `created`, `tags` y `aliases`; nombre de fichero = título; enlaces `[[Título]]`; sin carpetas obligatorias.

## 5. Diseño

- `desktop/obsidian/vault.py` — `Vault` (sandbox sobre `Workspace` + carpetas vetadas), detección de la bóveda abierta en Obsidian.
- `desktop/obsidian/notes.py` — análisis de una nota: frontmatter (texto), título, `[[wikilinks]]` con alias/ancla, etiquetas, encabezados.
- `desktop/obsidian/graph.py` — índice de la bóveda: resolución de enlaces (como Obsidian: por nombre más corto), entrantes/salientes.
- `desktop/obsidian/audit.py` — informe determinista.
- `desktop/obsidian/writer.py` (fase 1) — propuestas de cambio con diff, copia de seguridad, escritura atómica.
- `desktop/obsidian/agent.py` (fase 1) — `ObsidianAgent(ConfirmableAgent)`.
- `desktop/storage/obsidian_settings.py` + rutas `/api/desktop/obsidian/*` + sección en Configuración (norma: toda config editable en la UI).
- Skill `notes.obsidian` en el catálogo, ruta en `skill_router` (nivel OPERATE para escritura, ASSIST para lectura) y manejador en el coordinador.

## 6. Fases

| Fase | Contenido | Criterio de aceptación |
|---|---|---|
| 0 | Ajustes + bóveda autorizada + análisis + grafo + auditoría, solo lectura. "Repasa mi bóveda" en el chat. | Informe correcto sobre una bóveda de prueba con casos conocidos; no escribe nada; tests |
| 1 | Escribir notas con vista previa y confirmación; validación de enlaces; copia de seguridad | Una nota nueva queda con formato y enlaces solo a notas existentes; sin confirmar no se escribe |
| 2 | Enlazar y dar formato a notas existentes con diff; mantener `Indice de notas.md` | Cambios por lote con aprobación; deshacer desde la copia |
| 3 | Orden: propuesta de carpetas/etiquetas, detección de duplicados, UI de revisión | A decidir con el uso real |

## 7. Riesgos

- **OneDrive:** escrituras atómicas y espaciadas; si OneDrive duplica un fichero ("conflicto"), la auditoría lo detecta como título duplicado.
- **Enlaces ambiguos:** Obsidian resuelve `[[Nota]]` por nombre; con dos notas homónimas en carpetas distintas hay que usar ruta. La auditoría lo marca.
- **Bóvedas grandes:** el grafo se construye en memoria y de forma incremental (por fecha de modificación).
- **El modelo inventa enlaces o contenido:** validación en código; la vista previa muestra todo antes de escribir.
- **Notas con secretos:** nombres tipo `credentials*` no se leen; `redact()` sobre todo texto que va al modelo.

## 8. Decisiones tomadas por defecto (cámbialas si quieres)

- Bóveda = la abierta en Obsidian (`Boveda1`); se confirma en Configuración.
- Escritura siempre con confirmación; nunca borrado.
- Texto de las notas: LLM propio de PEPO (router o modelo del servidor), nunca Claude.

## 9. Registro de avance

- 2026-10-23: plan escrito; bóveda inspeccionada (2 notas vacías).
- 2026-10-23: **Fase 0 hecha** (`08d05f9`): análisis de notas, bóveda con sandbox, grafo de enlaces, auditoría, ajustes, rutas `/api/desktop/obsidian/*`, skill `notes.obsidian` y manejador en el coordinador. 1169 tests en verde. Verificado en la app real: "repasa mi bóveda de Obsidian" por `/api/nexus/chat` → `obsidian-assistant`, informe correcto sobre `Boveda1` (2 notas vacías, sin enlaces). Sin LLM ni tokens. **No verificado:** que la sección de Configuración exista (no se ha hecho UI todavía: los ajustes se gestionan solo por API).
- Siguiente: fase 1 (escribir notas con vista previa y confirmación, `ObsidianAgent(ConfirmableAgent)`, validación de enlaces en código, copia de seguridad) y sección en Configuración (norma: toda config editable en la UI).
- 2026-10-23: **Fase 1 hecha** (`c66a1a9`): escribir notas con vista previa y confirmación. Reparto: el LLM redacta el cuerpo y contrasta con las 3 notas más parecidas; el código busca relacionadas (TF-IDF, umbral 1,0 con ≥2 términos), quita enlaces inventados, enlaza las menciones reales (primera mención, nombres ≥4 letras y no ambiguos), normaliza etiquetas, da formato y escribe. Nunca sobrescribe ni borra: título existente → se añade al final con copia en `.pepo/backups`; se aborta si la nota cambió; conserva CRLF; las notas generadas se marcan «sin verificar»; sí/no desde el chat o el gestor de agentes; las pendientes sobreviven a un reinicio. 1214 tests en verde. Verificado en la app real con el LLM de PEPO: «apunta en Obsidian una nota sobre las landing zones de Azure» → propuesta en 2,9 s; cancelada, bóveda intacta.
- Aprendido: umbral de relacionadas calibrado con una bóveda de 3 notas (puntuaciones 0,7–4); con una bóveda grande habrá que reajustarlo midiendo. Alias de 3 letras no se enlazan solos (falsos positivos).
- Pendiente: fase 2 (enlazar/dar formato a notas EXISTENTES con diff, mantener `Indice de notas.md`), fase 3 (orden), contraste contra internet para notas generadas, sección en Configuración.
