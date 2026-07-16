# Tanda 1 - Contrato Congelado

## Interfaz congelada

Las siguientes rutas quedan congeladas y no deben modificarse en esta tanda:

- `products/desktop/ui/templates/**`
- `products/desktop/ui/static/css/**`
- `products/desktop/ui/static/js/**`
- `products/web/ui/templates/**`
- `products/web/ui/static/css/**`
- `products/web/ui/static/js/**`
- `app/templates/**`
- `app/static/**`

## Flujos que deben mantenerse

- Arranque del backend desktop.
- Login con credenciales configuradas.
- Lectura de configuracion local LLM.
- Guardado y lectura de historial local de shell.
- Preview de prospeccion/CRM sin correos ni integraciones externas.

## Rutas de API que se verifican

Las rutas siguientes salen del codigo real de `products/desktop/backend/app.py` y son las que cubren los tests de esta tanda:

- `GET /health`
- `POST /login`
- `GET /api/desktop/providers`
- `PUT /api/desktop/providers`

## Contrato de compatibilidad

- No cambian las claves JSON expuestas por las rutas cubiertas.
- No cambian los nombres de endpoint ya existentes.
- La configuracion de proveedor sigue devolviendo `provider`, `configured` y `applied`.
- La persistencia local conserva los nombres de archivo y el formato JSON/JSONL actual.
