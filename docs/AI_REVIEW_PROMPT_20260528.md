# AI Review Prompt 2026-05-28

Usa este prompt con otra IA para revisar el estado del proyecto:

---

Estoy compartiendo un paquete ZIP de un proyecto llamado `Nexus-UI`, que está pivotando desde una superficie web operativa hacia una aplicación de escritorio ejecutable llamada `Open-Nexus`, inspirada en Open Interpreter.

Quiero una revisión técnica y de producto, no solo de estilo.

Necesito que analices:

1. si la dirección arquitectónica tiene sentido
2. si el pivot desde web-first a desktop-first está bien planteado
3. si la separación entre runtime, shell, web puente y empaquetado es correcta
4. qué piezas están bien resueltas y cuáles huelen a parche temporal
5. qué riesgos ves en build, instalación, duplicidad de lógica y mantenibilidad
6. cómo cerrarías la transición de la web actual hacia `Open-Nexus`

Contexto importante:

- la web ya tiene chat, monitorización, correo Thunderbird, outreach, CRM interno y editor de prompts
- el objetivo final NO es una web, sino un ejecutable instalable de escritorio
- se ha descargado Open Interpreter en `vendor/open-interpreter` para usarlo como referencia de ingeniería inversa
- ya existe una primera base de `Open-Nexus` en `desktop/opennexus`
- ya existen scripts de build e instalación para Windows, pero todavía no se consideran definitivos

Quiero que centres la revisión en estos bloques:

- `desktop/opennexus`
- `desktop/application.py`
- `desktop/config.py`
- `desktop/tray.py`
- `desktop/runtime/*`
- `app/nexus/*`
- `app/main.py`
- `build/OpenNexus.spec`
- `scripts/build_open_nexus.ps1`
- `scripts/install_open_nexus_windows.ps1`
- `docs/OPEN_NEXUS_*`
- `docs/WEB_TO_OPEN_NEXUS_FEATURE_MAP.md`
- `docs/OPEN_NEXUS_MIGRATION_PLAN.md`

También revisa el uso de `vendor/open-interpreter` como referencia:

- si se está copiando lo que merece la pena
- o si hay decisiones importantes que aún no se han trasladado

Formato de respuesta que quiero:

1. evaluación general en 10-15 líneas
2. principales aciertos
3. principales errores o riesgos
4. qué harías en el siguiente sprint
5. si crees que la base actual sirve de verdad para construir un producto desktop serio o si convendría replantear algo

No quiero una review superficial ni obsesionada con estilo de código. Quiero criterio de arquitectura, producto y delivery.

---
