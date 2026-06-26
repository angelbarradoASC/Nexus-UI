# Scoring de prospectos

**Fichero:** `app/nexus/prospecting/scoring.py`  
**Clase:** `ProspectScorer`

---

## Cómo funciona

El scoring es **determinista y basado en reglas**. No interviene ningún modelo de lenguaje en la puntuación: el score final es la suma aritmética de criterios objetivos extraídos de cada candidato.

La IA solo participa en la fase de **extracción** previa (leer la web del candidato y obtener email, teléfono, web oficial, valoración…). Una vez extraídos los datos, el scorer los evalúa contra criterios fijos por vertical.

Rango final: 0–100. Se trunca si supera 100 o baja de 0.

---

## Prioridad según score

| Score | Prioridad |
|-------|-----------|
| ≥ 80  | Alta      |
| 50–79 | Media     |
| 20–49 | Baja      |
| < 20  | Descartar |

Un candidato se acepta si `score >= minimum_score` (configurable por run, por defecto 40).

---

## Criterios por vertical

### Asesoría / Gestoría (`asesoria`)

| Criterio | Puntos |
|----------|--------|
| Tiene web | +20 |
| DNS válido | +10 |
| MX válido (servidor de correo activo) | +15 |
| Email directo | +15 |
| Teléfono | +15 |
| Persona de contacto identificada | +5 |
| Valoración Google ≥ 4.0 | +10 |
| Valoración Google ≥ 3.5 | +5 |
| Señales de calidad (×5, máx. 10) | 0–10 |
| Solo formulario de contacto, sin email | −10 |
| Duplicado en CRM | −25 |
| **Máximo teórico** | **100** |

### Inmobiliaria (`inmobiliaria`)

| Criterio | Puntos |
|----------|--------|
| Tiene web | +20 |
| DNS válido | +10 |
| MX válido | +10 |
| Email directo o formulario de contacto | +15 |
| Teléfono | +15 |
| Valoración Google ≥ 4.0 | +10 |
| Valoración Google ≥ 3.5 | +5 |
| Redes sociales (×4, máx. 12) | 0–12 |
| Señales de calidad (×5, máx. 10) | 0–10 |
| Duplicado en CRM | −25 |
| **Máximo teórico** | **102** → truncado a 100 |

### Restaurante (`restaurants`)

| Criterio | Puntos |
|----------|--------|
| Tiene web | +15 |
| DNS válido | +10 |
| MX válido | +10 |
| Email directo o formulario | +15 |
| Teléfono | +10 |
| Formulario de contacto propio | +5 |
| Redes sociales (×4, máx. 12) | 0–12 |
| Señales de calidad (×6, máx. 24) | 0–24 |
| Premium (carta alta, terraza, grupos…) | +8 |
| Duplicado en CRM | −25 |
| **Máximo teórico** | **109** → truncado a 100 |

### Administración pública (`public_administration`)

| Criterio | Puntos |
|----------|--------|
| Tiene web | +20 |
| Web oficial | +10 |
| DNS válido | +10 |
| MX válido | +15 |
| Email directo | +15 |
| Teléfono | +10 |
| Rol TIC/Digital/Informática/Secretaría | +10 |
| Persona de contacto identificada | +5 |
| Señales de calidad (×5, máx. 15) | 0–15 |
| Solo formulario, sin email | −10 |
| Duplicado en CRM | −25 |
| **Máximo teórico** | **110** → truncado a 100 |

---

## Señales de calidad (`quality_signals`)

Campo libre que los extractores pueden rellenar con evidencias adicionales:
- Página de equipo o personal
- Blog o publicaciones activas
- Certificaciones o premios
- Membresía en asociaciones del sector
- Reseñas verificadas

Cada señal suma 5–6 puntos según la vertical, con techo de 10–24 puntos.

---

## Score breakdown en la UI

Desde la tabla de resultados, el botón **Info** muestra el desglose criterio a criterio:
- ✓ Criterios cumplidos con puntos sumados
- ○ Criterios no cumplidos con potencial perdido
- − Penalizaciones aplicadas

Esto permite identificar exactamente por qué un lead tiene un score bajo y qué habría que resolver para mejorarlo (p. ej.: conseguir el email directo en lugar de un formulario genérico).

---

## Cómo añadir un nuevo vertical

1. Añadir el valor al patrón de validación en `app/nexus/api/schemas/prospecting.py` (`ProspectingRunRequest.vertical`)
2. Crear el método `_score_<vertical>` en `ProspectScorer` siguiendo el patrón de los existentes (devuelve `_Criteria`)
3. Añadir el `elif vertical == "<vertical>"` en `ProspectScorer.score()`
4. Añadir la opción al `<select id="prospectingVertical">` en `app/templates/nexus_sales.html`

---

## Logs del run

Cada run escribe eventos estructurados en MongoDB (campo `logs` del documento del run) y en el fichero `logs/nexus.log`:

- Rotación: mensual (1 mes)
- Retención: 6 meses
- Formato: `YYYY-MM-DD HH:mm:ss | LEVEL | module | mensaje`

Los logs del run son consultables vía API:

```
GET /api/nexus/prospecting/runs/{run_id}/logs?level=info
```

Y se visualizan en la UI en el panel **Logs del run** tras cada ejecución.
