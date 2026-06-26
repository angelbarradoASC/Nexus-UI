# Prompt Para Chat Normal

Quiero que actues como arquitecto principal de producto, IA agentica y software para `Nexus`, pero con una restriccion muy importante:

- cuando en esta conversacion se diga `Nexus`, significa **siempre** la aplicacion **desktop**, no la version navegador

Te adjunto un `.zip` con el codigo y la estructura real del proyecto para que lo analices. No quiero una respuesta generica sobre agentes. Quiero que inspecciones la estructura, detectes fortalezas, deuda tecnica, incoherencias de arquitectura, riesgos de producto y oportunidades modulares reales.

## Contexto de negocio

`Nexus` se quiere comercializar como una plataforma modular donde podamos vender modulos independientes o paquetes por dominio.

Los modulos actuales o previstos son:

- `Sales`: ya bastante afinado, orientado a prospeccion, outreach y flujo comercial
- `Operator`: sera el modulo para alarmas, operacion, acciones y automatizacion operativa
- `Shell`: superficie operativa y/o tecnica para acciones dirigidas
- mas adelante: hogar y oficina inteligente

La idea no es construir un chatbot loro, sino un sistema de agentes que haga cosas con criterio, trazabilidad y valor practico.

## Contexto tecnico real que debes asumir

1. La app canonica es la desktop.
2. Se ejecuta como aplicacion local nativa, no como frontend principal en Docker.
3. El arranque real desktop usa `pythonw -m desktop.main` y expone backend local en `127.0.0.1:11430`.
4. La arquitectura de ejecucion actual es monolitica en despliegue desktop, pero modular por archivos y dominios.
5. `Sales` no debe romperse ni redisenarse sin motivo. Se puede mejorar, pero no rehacer sin necesidad.
6. `Operator` y `Shell` son las superficies donde queremos construir nuestra IA agentica propia.
7. Los recursos de IA que queremos usar de forma principal estan en `192.168.1.150`.
8. La observabilidad fuerte vive en `192.168.1.150`:
   - Prometheus
   - Grafana
   - Alertmanager
   - Loki previsto en remoto
9. En local solo debe quedar lo minimo razonable. La version desktop no debe depender de un enjambre local de contenedores.

## Estado actual de IA y fallbacks

Quiero que tengas esto en cuenta al analizar el producto:

- El runtime desktop esta preparado para usar un proveedor remoto persistido localmente como override del primer nivel remoto.
- Existe un `LLMRouter` por niveles con estrategia de prioridad, fallback y retries.
- Historicamente se ha preparado soporte para:
  - local OpenAI-compatible / Ollama
  - OpenRouter Free
  - Groq Free
  - NVIDIA NIM / API Catalog como opcion OpenAI-compatible
- En `Sales` ya existen fallbacks y operativa de IA pensados para no depender de un solo proveedor caro.
- El servidor `192.168.1.150` es la referencia operativa actual para modelos y observabilidad.

## Lo que quiero que hagas

Quiero una respuesta estructurada en 5 bloques:

### 1. Lectura de arquitectura actual

Explica como entiendes la arquitectura real de `Nexus desktop` despues de revisar el zip:

- que es runtime local
- que es dominio reutilizable
- que es legado
- que esta bien planteado
- que esta mezclado o acoplado de mas

### 2. Diagnostico critico

Dime sin maquillaje:

- que problemas de arquitectura ves
- que deuda tecnica ves
- que incoherencias de producto/tecnologia ves
- que partes sobran
- que partes estan bien orientadas y conviene respetar

Prioriza por impacto real, no por purismo.

### 3. Diseno objetivo para `Operator`

Define como deberia ser `Operator` como modulo unico, vendible y util.

No lo quiero como un chat bonito. Lo quiero como un sistema agentico orientado a operacion:

- entender eventos, alarmas y contexto
- decidir que hacer
- pedir confirmacion cuando toque
- ejecutar acciones
- dejar explicacion y trazabilidad
- aprender patrones operativos utiles

Quiero que propongas:

- responsabilidades exactas del modulo
- tipos de agentes internos
- memoria que necesita
- herramientas o conectores que necesita
- capa de decisiones
- capa de explicabilidad
- capa de auditoria
- interfaz o superficies de uso

### 4. Relacion entre `Operator`, `Shell` y `Sales`

Quiero un modelo claro de convivencia:

- que comparte todo el sistema
- que pertenece solo a `Sales`
- que pertenece solo a `Operator`
- que papel juega `Shell`
- como evitar duplicidades
- como convertir esto en modulos comercializables

### 5. Roadmap pragmatico

Dame un roadmap por fases, priorizado y realista:

- que haria ya
- que haria en la siguiente fase
- que congelaria
- que eliminaria
- que modulo/refactor atacaria primero

## Restricciones importantes

- No propongas microservicios por defecto solo porque suena moderno.
- No propongas reescribir todo desde cero.
- No propongas mover `Nexus` a navegador como producto principal.
- No sacrifiques simplicidad operativa del desktop.
- No destruyas `Sales`.
- Prioriza trazabilidad, explicabilidad y accion real sobre UX vacia.

## Formato de respuesta deseado

- Quiero criterio de CTO/product architect.
- Quiero claridad y dureza honesta si algo esta mal.
- Quiero propuestas concretas, no discurso de consultoria.
- Si encuentras mejoras estructurales, proponlas con motivo.
- Si encuentras algo especialmente bien montado, dilo tambien.

Si algo no te cuadra en el zip, dilo explicitamente y separa hechos de inferencias.
