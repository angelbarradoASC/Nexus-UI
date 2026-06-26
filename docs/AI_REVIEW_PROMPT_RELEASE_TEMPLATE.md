# Prompt Revision Template

Usa este prompt con otra IA para revisar un ZIP de release de Nexus u Open-Nexus:

---

Te voy a pasar un ZIP de un proyecto llamado `Nexus-UI`.

Quiero que:

1. lo extraigas
2. leas la documentación y el código
3. entiendas la arquitectura real y la dirección de producto
4. determines qué pruebas faltan o qué pruebas habría que generar
5. propongas y, si tu entorno lo permite, ejecutes los tests necesarios por consola
6. anotes las correcciones o cambios recomendados en un nuevo archivo Markdown aparte
7. me des una evaluación honesta de si la base es sólida o si hay decisiones peligrosas

Contexto:

- el proyecto está pivotando desde una superficie web hacia una aplicación de escritorio instalable llamada `Open-Nexus`
- hay integraciones de correo, CRM, prompts y runtime desktop
- también se ha incluido una copia de `open-interpreter` para referencia de ingeniería inversa

Quiero que revises especialmente:

- arquitectura
- separación de responsabilidades
- mantenibilidad
- build e instalación
- deuda técnica
- duplicidad entre web y desktop
- cobertura de tests

Instrucciones concretas:

- si ves que faltan tests, propón exactamente cuáles
- si puedes ejecutarlos, hazlo
- si detectas fallos de diseño, dilo sin adornos
- no te centres en minucias de estilo
- prioriza riesgos reales, aciertos y siguiente plan de acción

Formato de salida:

1. resumen ejecutivo
2. aciertos principales
3. errores o riesgos principales
4. tests que faltan o habría que reforzar
5. correcciones recomendadas
6. siguiente sprint recomendado

Además:

- crea un Markdown nuevo llamado `revision_resultado.md`
- ahí resume los cambios, hallazgos y correcciones propuestas

---
