# IMPLEMENTATION STEP 019

## Paso
Preparar `Nexus` para trabajar con cuatro familias de infraestructura objetivo:

- servidores Linux
- servidores Windows
- firewalls Fortinet
- switches Cisco

## Que hago
- Creo una taxonomia tecnica formal para estas cuatro familias.
- Defino por cada una:
  - clave canonica
  - metodo de acceso previsto
  - modos de autenticacion
  - capacidades de observacion
  - capacidades de accion futuras
- Añado un clasificador heuristico de tecnologia para que `Nexus` pueda decidir de que tipo de activo estamos hablando antes de investigar.
- Registro capacidades visibles en el runtime desktop para que el sistema ya exponga que estas familias existen como superficies operativas.

## Que toco
- `app/nexus/targets/__init__.py`
- `app/nexus/targets/models.py`
- `app/nexus/targets/catalogue.py`
- `app/nexus/targets/classifier.py`
- `desktop/runtime/capabilities.py`
- `tests/unit/test_technology_classifier.py`
- `tests/unit/test_desktop_runtime.py`

## Familias preparadas

### compute.linux
- acceso: `ssh`
- observacion:
  - `host.run_command`
  - `host.read_logs`
  - `service.status`
  - `filesystem.usage`
  - `process.list`

### compute.windows
- acceso: `winrm`
- observacion:
  - `host.run_powershell`
  - `service.status`
  - `eventlog.read`
  - `process.list`
  - `filesystem.usage`

### network.firewall.fortinet
- acceso: `fortios-api`
- observacion:
  - `firewall.system_status`
  - `firewall.interface_status`
  - `firewall.route_table`
  - `firewall.session_overview`
  - `firewall.event_logs`

### network.switch.cisco
- acceso: `network-cli`
- observacion:
  - `switch.show_interfaces`
  - `switch.show_mac_table`
  - `switch.show_spanning_tree`
  - `switch.show_cpu`
  - `switch.show_logs`

## Resultado
`Nexus` ya tiene una base comun para no pensar solo en Docker. Ahora puede clasificar y describir de forma estructurada esas cuatro familias objetivo antes de enchufar adaptadores reales.

## Tests pasados
- `python -m pytest tests\unit\test_technology_classifier.py -q`
  - `5 passed`
- `python -m pytest tests\unit\test_desktop_runtime.py -q`
  - `7 passed`
- `python -m pytest tests\unit\test_nexus_coordinator.py -q`
  - `15 passed`

## Observaciones
- Esto no conecta todavia a Linux, Windows, Fortinet o Cisco reales.
- Lo que deja listo es el contrato correcto para hacerlo sin rehacer la arquitectura cuando enchufemos cada adaptador.
