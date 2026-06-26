# IMPLEMENTATION STEP 017

## Paso
Corregir el comportamiento del chat para que funcione como una consola usable: el scroll tiene que vivir dentro del timeline del chat y no hacer crecer toda la pagina.

## Que hago
- Restauro la hoja de estilos activa de `Nexus v1`, que no estaba en disco.
- Fijo la altura del `workspace` a la ventana visible.
- Convierto el layout principal en una rejilla con `minmax(0, 1fr)` para que los paneles puedan contraerse.
- Hago que el `chat-shell` y el `ops-rail` tengan altura util fija.
- Muevo el scroll vertical al `chat-timeline` y al `feed-list`.
- Mantengo `overflow: hidden` en escritorio para que no crezca el documento entero.
- Dejo fallback responsive para que en pantallas pequenas vuelva a permitirse scroll de pagina.
- Roto la version del CSS/JS en la plantilla para romper cache.

## Que toco
- `app/static/css/nexus_v1.css`
- `app/templates/nexus_v1.html`

## Resultado esperado
- El chat deja de empujar la pagina hacia abajo.
- Los mensajes nuevos siguen entrando y el scroll se queda dentro del panel de conversacion.
- La actividad lateral tambien hace scroll interno.

## Tests pasados
- `python -m pytest tests\e2e\test_nexus_v1_api.py -q`
  - `6 passed`

## Validacion adicional
- `GET http://127.0.0.1:5010/nexus-v1`
  - devuelve la plantilla con `nexus_v1.css?v=20260515a`
