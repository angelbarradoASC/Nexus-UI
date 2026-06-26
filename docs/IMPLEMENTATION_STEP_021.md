# IMPLEMENTATION STEP 021

## Paso
Extender el sistema para que no solo conozca las familias Linux, Windows, Fortinet y Cisco, sino que ya pueda:

- resolver skills específicas por familia
- construir una línea de investigación inicial
- responder por chat con un prediagnóstico guiado por dominio tecnológico

## Que hago
- Añado skills nuevas:
  - `linux.prediagnostico`
  - `windows.prediagnostico`
  - `fortinet.prediagnostico`
  - `cisco.switch.prediagnostico`
- Amplío el `DesktopSkillRouter` para detectar esas familias por texto y asignar capabilities concretas.
- Creo un `TechnologyInvestigationPlanner` que genera:
  - resumen
  - método de acceso
  - capacidades de observación
  - pasos iniciales
  - postura de riesgo
- Integro ese planificador en el `NexusCoordinator` para que el chat ya pueda producir un prediagnóstico inicial por dominio, aunque todavía no exista el conector real.
- Endurezco el prompt para que el LLM no empiece pidiendo más información, sino que formule hipótesis y siguiente paso.

## Que toco
- `app/skills/catalogue/linux_prediagnostico.json`
- `app/skills/catalogue/windows_prediagnostico.json`
- `app/skills/catalogue/fortinet_prediagnostico.json`
- `app/skills/catalogue/cisco_switch_prediagnostico.json`
- `desktop/runtime/skill_router.py`
- `app/nexus/investigation/__init__.py`
- `app/nexus/investigation/technology_plan.py`
- `app/nexus/orchestration/coordinator.py`
- `tests/unit/test_desktop_runtime.py`
- `tests/unit/test_technology_investigation_plan.py`
- `tests/unit/test_nexus_coordinator.py`

## Resultado
`Nexus` ya puede empezar a responder de forma distinta cuando detecta:

- una alarma Linux
- una alarma Windows
- una alarma Fortinet
- una alarma sobre switching Cisco

Sin conectores reales todavía, pero con:

- clasificación
- capacidad asociada
- método de acceso previsto
- y plan inicial de investigación

## Tests pasados
- `python -m pytest tests\unit\test_desktop_runtime.py -q`
  - `9 passed`
- `python -m pytest tests\unit\test_technology_classifier.py -q`
  - `5 passed`
- `python -m pytest tests\unit\test_technology_investigation_plan.py -q`
  - `2 passed`
- `python -m pytest tests\unit\test_nexus_coordinator.py -q`
  - `16 passed`

## Observaciones
- Esta iteración mueve a `Nexus` desde “sé que existen estas tecnologías” a “ya sé cómo debería empezar a investigarlas”.
- El siguiente paso natural es enchufar adaptadores reales empezando por:
  - Linux por SSH
  - Windows por WinRM
  - Cisco por CLI
  - Fortinet por API
