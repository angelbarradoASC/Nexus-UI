# Nexus Analysis Bundle

Este bundle esta pensado para subirlo a otro modelo para revision tecnica y de producto.

Incluye:

- codigo fuente principal
- runtime desktop
- modulos UI
- rutas y backend
- scripts
- tests
- documentacion tecnica
- configuracion de observabilidad y runtime remoto

No incluye por defecto:

- `.git`
- caches
- logs
- artefactos binarios o de build prescindibles
- datasets pesados y salidas operativas que no aportan al analisis de arquitectura

El objetivo es que el modelo pueda analizar:

- estructura
- modularidad
- acoplamientos
- organizacion del runtime desktop
- integracion de Sales, Operator y Shell
- uso de proveedores LLM y fallbacks
- deuda tecnica y mejoras posibles
