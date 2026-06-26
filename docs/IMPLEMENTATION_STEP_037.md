# IMPLEMENTATION STEP 037

## Paso
Exposicion de metricas Prometheus reales en Nexus y alta del scrape job remoto en el Prometheus de `.150`.

## Qué hice
- Añadi un endpoint `/metrics` compatible con `prometheus_client`.
- Instrumente el chat web para exportar:
  - total de peticiones
  - latencia por superficie/modo/agente
- Exporte gauges para:
  - estado de recolectores
  - metricas agregadas del router LLM
  - metricas y alertas ingeridas desde el bridge desktop
- Hice que el lanzador web pueda escuchar en LAN y deje de estar pensado solo para `127.0.0.1`.
- Verifique desde el servidor `192.168.1.150` que la ruta `http://192.168.1.36:5010/metrics` responde.
- Añadi el job `nexus` al Prometheus remoto en `/home/angel/monitoring/prometheus/prometheus.yml`.
- Reinicie el contenedor `prometheus` y verifique que el target `nexus` aparece en estado `up`.

## Qué toqué
- `app/metrics.py`
- `app/nexus/api/routes/chat.py`
- `app/main.py`
- `tests/smoke/test_smoke_desktop.py`
- `scripts/run_nexus_web.py`

## Validación
- `GET /metrics` devuelve series Prometheus
- `curl` desde `.150` contra `http://192.168.1.36:5010/metrics` responde
- Prometheus remoto reporta:
  - `job: nexus`
  - `scrapeUrl: http://192.168.1.36:5010/metrics`
  - `health: up`

## Tests
```powershell
python -m pytest tests\smoke\test_smoke_desktop.py::TestDesktopToken::test_prometheus_metrics_endpoint_expone_series -q
python -m pytest tests\smoke\test_smoke_desktop.py tests\e2e\test_nexus_v1_api.py tests\unit\test_nexus_coordinator.py -q
```

Resultados:
- `1 passed`
- `38 passed`

## Siguiente paso natural
- levantar `Alertmanager` en `.150`
- añadir reglas basicas para:
  - `NexusDown`
  - `NexusLLMFailures`
  - `NexusCollectorDegraded`
