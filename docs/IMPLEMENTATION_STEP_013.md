# Implementation Step 013

## Paso

Validación real del `LLMRouter` de `Nexus` contra OpenRouter en modo `API-only`.

## Que hago

- Corrijo el `.env` para que la aplicación pueda arrancar sin bloquearse por claves inseguras.
- Mantengo `OpenRouter` como `L1` único.
- Verifico una llamada real del router, no solo del script auxiliar.

## Que toco

- `.env`
  - `SECRET_KEY`
  - `CREDENTIAL_STORE_KEY`

## Prueba real ejecutada

Se ha ejecutado una llamada directa del propio `LLMRouter` con:

- `min_level=1`
- `preferred_level=1`
- modelo:
  - `baidu/cobuddy:free`

Resultado:

```text
error= None
level= 1
model= baidu/cobuddy:free
content= Nexus listo.
```

## Qué demuestra

No solo vale la API key.

También queda validado que:

- `AppConfig` carga con el `.env` actual
- `LLMRouter` inicializa niveles correctamente
- `Nexus` puede usar OpenRouter como motor principal
- el modelo configurado responde por el flujo real del router

## Nota

El nombre interno del nivel sigue apareciendo como `L1-Groq` en logs por herencia del código antiguo del router.

No afecta al funcionamiento, pero conviene renombrarlo más adelante a algo neutro como:

- `L1-Cloud`
- o `L1-OpenRouter`

## Siguiente paso natural

1. probar el flujo de chat completo de la aplicación con worker o ruta directa
2. meter un segundo proveedor de respaldo
3. renombrar el nivel `L1` para que no confunda en logs y auditoría
