# Mapa del repositorio

Este documento resume, en una sola página, qué hay realmente en `Nexus-UI` y por dónde conviene empezar a poner orden.

## Qué es este repo

`Nexus-UI` es una aplicación web FastAPI con una UI tipo chat llamada `JAINA`, un worker asíncrono basado en Redis y persistencia en MongoDB. Además incluye observabilidad con Grafana, Prometheus, Loki y Tempo, y una capa de agentes para clasificar y resolver peticiones.

## Documento canónico

La referencia principal para entender el producto y sus nombres es [docs/ARQUITECTURA_CANONICA.md](C:/DEV/Nexus-UI/docs/ARQUITECTURA_CANONICA.md).
Ese documento define el reparto actual entre `NEXUS`, `JAINA`, `Hive Mind`, el módulo de incidencias y los MCPs.

Para el diseño operativo de `Nexus v1` y la ruta de migración:

- [docs/NEXUS_V1.md](C:/DEV/Nexus-UI/docs/NEXUS_V1.md)
- [docs/ORQUESTACION_AGENTES.md](C:/DEV/Nexus-UI/docs/ORQUESTACION_AGENTES.md)
- [docs/ESTRUCTURA_OBJETIVO.md](C:/DEV/Nexus-UI/docs/ESTRUCTURA_OBJETIVO.md)
- [docs/ROADMAP_PRODUCCION.md](C:/DEV/Nexus-UI/docs/ROADMAP_PRODUCCION.md)

## Camino principal

1. El usuario entra por `app/main.py`.
2. La UI vive en `app/templates/chat.html` y `app/static/js/app.js`.
3. El backend encola tareas en Redis.
4. `worker/worker.py` consume la cola.
5. `app/agents/orchestration_agent.py` decide qué agente ejecutar.
6. La respuesta vuelve al frontend y se persiste en MongoDB si está disponible.

## Piezas activas

- Backend web: [app/main.py](C:/DEV/Nexus-UI/app/main.py)
- Orquestación: [app/agents/orchestration_agent.py](C:/DEV/Nexus-UI/app/agents/orchestration_agent.py)
- Monitorización y Alertmanager: [app/main.py](C:/DEV/Nexus-UI/app/main.py), [app/static/js/modules/alerts.js](C:/DEV/Nexus-UI/app/static/js/modules/alerts.js)
- Ruta objetivo escalable: [app/nexus/README.md](C:/DEV/Nexus-UI/app/nexus/README.md)
- Worker: [worker/worker.py](C:/DEV/Nexus-UI/worker/worker.py)
- Skills registry: [app/skills/skills_registry.py](C:/DEV/Nexus-UI/app/skills/skills_registry.py)
- Frontend principal: [app/templates/chat.html](C:/DEV/Nexus-UI/app/templates/chat.html) y [app/static/js/app.js](C:/DEV/Nexus-UI/app/static/js/app.js)
- Infra local: [docker-compose.yml](C:/DEV/Nexus-UI/docker-compose.yml)

## Qué parece soporte, no producto núcleo

- `grafana/`, `prometheus/`, `loki/`, `tempo-data/`, `monitoring/`: observabilidad y soporte.
- `docs/`: mezcla de documentación útil y visión de futuro.
- `OLD/`: archivo histórico, no fuente de verdad.
- `tests/`: batería amplia, buena base para refactorizar con seguridad.

## Orden recomendado

1. Trabajar solo sobre lo que esté en la ruta activa.
2. Si algo no entra en el camino principal, archivarlo en `OLD/`.
3. Mantener como referencia viva solo la arquitectura canónica y el mapa de repositorio.
4. Recién después tocar funcionalidad nueva o refactors grandes.

## Lectura rápida

Si alguien nuevo entra aquí, el proyecto no es "solo una UI". Es una plataforma de agentes con backend, cola, persistencia, observabilidad y control operativo. La mejor forma de no perderse es tratar `app/main.py`, `worker/worker.py` y `app/agents/orchestration_agent.py` como el núcleo, y todo lo demás como soporte o extensión hasta demostrar lo contrario.
