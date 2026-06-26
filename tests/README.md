# NEXUS-UI — Batería de Tests

Guía de referencia para ingenieros: estructura, ejecución, cobertura y mejoras.

---

## A) Estructura de directorios

```
tests/
├── conftest.py                         ← Fixtures globales (auth, LLM mocks, app client)
├── test_llm_parser.py                  ← Parser de thinking / XML  (32 tests)
│
├── unit/                               ← Lógica pura, sin I/O real
│   ├── test_base_agent.py              ← AgentResult, BaseAgent (contrato)               (16)
│   ├── test_generation_agent.py        ← GenerationAgent (LLM general)                   (15)
│   ├── test_ssh_agent.py               ← SSHAgent + _ejecutar_diagnostico                (24)
│   ├── test_web_agent.py               ← WebAgent (DuckDuckGo + síntesis)                (14)
│   ├── test_host_resolver.py           ← HostResolver (known_hosts → DNS)                (21)
│   ├── test_mode_agents.py             ← AnalystAgent, CoderAgent, ResearcherAgent        (26)
│   ├── test_skills_registry.py         ← SkillsRegistry, SkillDefinition, validación     (33)
│   ├── test_intention_agent.py         ← IntentionAgent (clasificación de intenciones)   (14)
│   ├── test_llm_router.py              ← LLMRouter (niveles, reintentos, métricas)        (8)
│   ├── test_config.py                  ← AppConfig (parseo, validación, propiedades)     (19)
│   ├── test_session_auth.py            ← SessionAuth (bcrypt, TTL, sesiones)             (17)
│   └── test_credential_store.py        ← CredentialStore (Fernet, validación)            (19)
│                                                                               total: 226
│
├── integration/                        ← Tests con múltiples componentes reales
│   ├── test_orchestration.py           ← OrchestrationAgent (flujo process_query)         (8)
│   ├── test_orchestration_stream.py    ← process_query_stream(), agent_override           (26)
│   ├── test_conversation_repository.py ← ConversationRepository (CRUD MongoDB mock)      (47)
│   └── test_worker.py                  ← _procesar_tarea() (worker Redis mock)           (14)
│                                                                               total:  95
│
├── e2e/                                ← API completa (FastAPI TestClient)
│   ├── test_api.py                     ← Endpoints principales, auth, historial           (19)
│   └── test_api_crud.py                ← DELETE/PATCH/POST + SSE /chat/stream             (38)
│                                                                               total:  57
│
└── smoke/
    └── test_smoke_desktop.py           ← Endpoints desktop (/api/metrics, token auth)     (8)
```

**Total: 20 ficheros de test | 418 funciones `test_*`**

Conteo por capa: unit=226 · integration=95 · e2e=57 · smoke=8 · root=32

---

## B) Instrucciones de ejecución

### Instalación

```bash
cd C:\DEV\Nexus-UI
pip install -r app/requirements/dev.txt
```

Dependencias de test clave (en dev.txt):
```
pytest>=8.0
pytest-asyncio>=0.23
pytest-cov>=5.0
httpx>=0.27          # para TestClient async
duckduckgo-search    # requerido por WebAgent (aunque mockeado en tests)
```

> **Nota:** `duckduckgo-search` debe estar instalado para que pytest pueda
> importar los módulos de `agents/` sin errores de colección, aunque ningún
> test haga llamadas reales a DuckDuckGo.

### Variables de entorno

Las variables están definidas en `conftest.py` con valores seguros.
No se necesitan variables externas para ningún test de la batería.

```bash
# Opcional: ver logs del servidor en tests E2E
export DEBUG=true
```

### Ejecutar todos los tests

```bash
cd C:\DEV\Nexus-UI
pytest tests/ -v
```

### Por capa

```bash
# Solo unit tests (más rápidos, sin I/O)
pytest tests/unit/ -v

# Solo integration
pytest tests/integration/ -v

# Solo E2E
pytest tests/e2e/ -v

# Solo smoke
pytest tests/smoke/ -v

# Root (llm_parser)
pytest tests/test_llm_parser.py -v
```

### Con cobertura

```bash
pytest tests/ \
  --cov=app \
  --cov-report=term-missing \
  --cov-report=html:coverage_html \
  -v
```

El reporte HTML se genera en `coverage_html/index.html`.

### Tests específicos

```bash
# Un fichero
pytest tests/unit/test_ssh_agent.py -v

# Una clase
pytest tests/unit/test_ssh_agent.py::TestEjecutarDiagnosticoSSH -v

# Un test concreto
pytest "tests/unit/test_ssh_agent.py::TestEjecutarDiagnosticoSSH::test_cierra_cliente_tras_ejecucion" -v

# Por keyword
pytest tests/ -k "stream" -v
pytest tests/ -k "error or fallo" -v
pytest tests/ -k "persistencia" -v
```

### Configuración pytest (pytest.ini)

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
filterwarnings =
    ignore::DeprecationWarning
    ignore::PendingDeprecationWarning
```

### CI/CD (GitHub Actions)

```yaml
- name: Install dependencies
  run: pip install -r app/requirements/dev.txt

- name: Run tests
  run: |
    pytest tests/ \
      --cov=app \
      --cov-report=xml \
      --junitxml=test-results.xml \
      -v --tb=short
  env:
    DEBUG: "true"
    APP_USERS: "testuser:testpass"
    SECRET_KEY: "ci-test-secret-key-32chars-min!!"
    CREDENTIAL_STORE_KEY: "ci-encryption-key-32chars-min!!"
    LLM_API_BASE_URL: "http://localhost:1234/v1"
    REDIS_HOST: "localhost"
    MONGO_URI: ""

- name: Upload coverage
  uses: codecov/codecov-action@v4
  with:
    file: coverage.xml
```

---

## C) Cobertura por módulo

| Módulo | Fichero de test | Tests | Cobertura estimada |
|--------|----------------|-------|--------------------|
| `base_agent.py` | test_base_agent.py | 16 | Alta |
| `generation_agent.py` | test_generation_agent.py | 15 | Alta |
| `ssh_agent.py` | test_ssh_agent.py | 24 | Alta |
| `web_agent.py` | test_web_agent.py | 14 | Media-Alta |
| `analyst_agent.py` | test_mode_agents.py | 7 | Media-Alta |
| `coder_agent.py` | test_mode_agents.py | 6 | Media-Alta |
| `researcher_agent.py` | test_mode_agents.py | 9 | Media-Alta |
| `intention_agent.py` | test_intention_agent.py | 14 | Alta |
| `orchestration_agent.py` | test_orchestration*.py | 34 | Alta |
| `llm_router.py` | test_llm_router.py | 8 | Media |
| `host_resolver.py` | test_host_resolver.py | 21 | Alta |
| `credential_store.py` | test_credential_store.py | 19 | Alta |
| `skills_registry.py` | test_skills_registry.py | 33 | Alta |
| `conversation_repository.py` | test_conversation_repository.py | 47 | Alta |
| `worker.py` | test_worker.py | 14 | Media-Alta |
| `config.py` | test_config.py | 19 | Alta |
| `session_auth.py` | test_session_auth.py | 17 | Alta |
| `main.py` | test_api*.py | 57 | Media-Alta |
| `llm_parser.py` | test_llm_parser.py | 32 | Alta |

**Módulos sin tests directos** (cobertura indirecta vía agentes):
- `tools/jira_client.py` — cubierto indirectamente por JiraAgent
- `tools/web_fetch.py` — mockeado en test_web_agent.py
- `tools/web_search.py` — mockeado en test_web_agent.py
- `exceptions.py` — clases simples, cobertura en E2E
- `metrics.py` — cubierto en smoke tests

---

## D) Tests aún frágiles y por qué

### 1. `tests/smoke/test_smoke_desktop.py` — `raise_server_exceptions=False`

El cliente sigue usando `raise_server_exceptions=False`. Las excepciones no controladas
se convierten en 500 silenciosos. Cambiar a `True` requiere validar que el endpoint
`/api/metrics` no lanza en el contexto `nexus_context=desktop_app`.

**Riesgo:** bugs en desktop no se propagan al test.

### 2. `tests/integration/test_orchestration_stream.py` — SSE con TestClient

`TestClient` de Starlette consume el stream completo de una vez. No testea latencia,
backpressure ni reconexión. Para SSE real se necesita `httpx.AsyncClient` en streaming.

**Impacto:** comportamiento de reconexión del frontend no está cubierto.

### 3. `tests/unit/test_ssh_agent.py` — known_hosts via filesystem real

`SSHAgent._KNOWN_HOSTS_FILE` es una constante global. Los tests monkeypatchen
`HostResolver.resolver()` pero no la política de host keys de Paramiko. Si se activa
una conexión real (sin mock), podría leer `~/.ssh/known_hosts`.

**Riesgo bajo** porque `paramiko.SSHClient` está mockeado completo.

### 4. `tests/integration/test_conversation_repository.py` — cursor MongoDB encadenado

Los métodos `find().sort().limit()` se mockean con cadenas de MagicMock. Si la
implementación cambia el orden de las llamadas (ej. `limit().sort()`), los tests
no lo detectarían — el mock devuelve el iterable sin importar el orden.

### 5. `tests/e2e/test_api_crud.py` — fixture `authed_client_with_conv` compartida

Varios tests mutan `mock_repo` después de obtener el cliente del fixture. Si pytest
cambia el orden de ejecución dentro de la clase, un test que muta `mock_repo` puede
afectar al siguiente. Mitigación: cada test debería restaurar `mock_repo` en teardown.

---

## E) Partes sin validar

1. **`jira_client.py`** — `create_issue()`, `get_issue()`, `add_comment()`, `search_issues()`
   no tienen tests directos. Solo se ejercitan indirectamente si JiraAgent los llama.

2. **`worker.main()`** — el loop infinito con SIGINT/SIGTERM no está testeado.
   Solo `_procesar_tarea()` tiene cobertura directa.

3. **SSE reconexión** — el endpoint `/chat/stream/{task_id}` se testea con
   `TestClient` que consume el stream completo. No cubre: timeout Redis, cliente
   que desconecta, reconexión automática del EventSource del navegador.

4. **ResearcherAgent + WebAgent en serie** — el flujo completo
   "búsqueda web → enriquecimiento → síntesis LLM" no está cubierto end-to-end.
   Los tests mockean WebAgent o LLM por separado, no ambos juntos.

5. **Cifrado Fernet con rotación de clave** — `CredentialStore` no testea el
   comportamiento al rotar `CREDENTIAL_STORE_KEY` en producción (datos cifrados
   con clave antigua, nueva instancia con clave nueva).

---

## F) Fixtures compartidas (conftest.py)

| Fixture | Scope | Descripción |
|---------|-------|-------------|
| `test_config` | session | AppConfig con valores seguros de test |
| `session_auth` | function | SessionAuth inicializado |
| `mock_llm_router` | function | LLMRouter con call() mockeado (éxito) |
| `mock_llm_router_error` | function | LLMRouter que siempre devuelve error |
| `mock_llm_router_stream` | function | LLMRouter con call_stream() como async generator |
| `credential_store` | function | CredentialStore en tmp_path |
| `app_client` | function | FastAPI TestClient con Redis/MongoDB mockeados |

### Convenciones de naming

```
TestNombreClase          ← Clase de test para una clase del sistema
TestFlujoEspecifico      ← Grupo de tests para un flujo o escenario
test_accion_condicion    ← test_devuelve_none_si_objectid_invalido
test_accion_resultado    ← test_toggle_de_false_a_true
```
