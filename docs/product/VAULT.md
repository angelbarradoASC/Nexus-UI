# Pestana Vault

## Objetivo

`Vault` es la superficie de custodia local de credenciales y de inventario de dispositivos accesibles desde Nexus.
Su razon de existir es separar credenciales reales del modelo y de la configuracion general.

## Ruta y archivos

- ruta UI: `/nexus/vault`
- template: [nexus_vault.html](C:\DEV\Nexus-UI\products\desktop\ui\templates\nexus_vault.html)
- cliente JS: [nexus_vault.js](C:\DEV\Nexus-UI\products\desktop\ui\static\js\nexus_vault.js)
- estilos: [nexus_vault.css](C:\DEV\Nexus-UI\products\desktop\ui\static\css\nexus_vault.css)

## Pantallas internas

### Estado bloqueado

Muestra:

- vault bloqueado o no inicializado
- formulario de setup o unlock

### Estado desbloqueado

Muestra:

- badge de estado
- inventario de dispositivos
- modales de alta/edicion
- modales de credenciales

## Endpoints usados

- `/api/nexus/vault/status`
- `/api/nexus/vault/setup`
- `/api/nexus/vault/unlock`
- `/api/nexus/vault/lock`
- `/api/nexus/vault/credentials`
- `/api/nexus/vault/credentials/{device_id}`
- `/api/nexus/vault/test/{device_id}`
- `/api/nexus/cmdb/devices`
- `/api/nexus/cmdb/devices/{device_id}`

## Datos que maneja

- dispositivos del CMDB local
- metadatos de acceso
- usuario
- password
- claves SSH
- tokens API

## Reglas de seguridad

- la password maestra no debe documentarse en markdown
- las credenciales no deben pasar al modelo en claro
- `Vault` y `CMDB` deben verse como dos capas complementarias

## Rol dentro del producto

`Vault` prepara el terreno para:

- accesos SSH
- accesos WinRM
- accesos RDP asistidos
- conectores operativos a infraestructura real
