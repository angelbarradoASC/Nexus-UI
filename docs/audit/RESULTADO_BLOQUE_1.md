# Resultado Bloque 1

## Objetivo

Establecer una baseline funcional verificable y un contrato de UI por hashes sin tocar la interfaz ni sus rutas.

## Archivos tocados

- `.gitignore`
- `docs/audit/BASELINE_FUNCIONAL.md`
- `docs/audit/ui_contract.sha256`
- `scripts/audit/check_ui_contract.py`

## Validaciones ejecutadas

- `python scripts/audit/check_ui_contract.py`
  - Resultado: `OK`
  - Ficheros UI protegidos verificados: `125`
- `python -m pytest -q`
  - Resultado: no finalizó dentro de `300s`
  - Evidencia parcial guardada en `.pytest-block1.log`
  - El log parcial confirma que la colección arranca y que siguen existiendo fallos heredados en suites ajenas a esta tarea, por ejemplo:
    - `tests/e2e/test_api_crud.py::TestChatStreamEndpoint::test_stream_evento_error_termina_stream`
    - varios tests de `tests/integration/test_worker.py`
- `git diff --check`
  - Sin errores de formato; solo avisos CRLF en dos ficheros UI ya modificados en el worktree antes de esta tarea.

## Hashes UI Antes/Despues

- Baseline inicial creada desde el árbol actual en `docs/audit/ui_contract.sha256`
- Verificación inmediatamente posterior: `OK`
- Interpretación operativa:
  - no se alteró ningún hash durante la ejecución de esta tarea;
  - el contrato queda listo para detectar cambios futuros en UI protegida.

## Riesgos abiertos

- El repositorio sigue en estado Git no consolidado, con gran parte del árbol apareciendo como `??`.
- El worktree ya contenía modificaciones en UI protegida antes de esta tarea:
  - `products/desktop/ui/static/css/open_nexus.css`
  - `products/desktop/ui/templates/open_nexus.html`
- La baseline refleja el estado actual del árbol, no un árbol limpio histórico.
- La suite global de `pytest -q` sigue teniendo fallos heredados fuera del alcance de este bloque.

## Rollback Exacto

Si hay que revertir solo esta tarea:

1. Borrar:
   - `docs/audit/BASELINE_FUNCIONAL.md`
   - `docs/audit/ui_contract.sha256`
   - `docs/audit/RESULTADO_BLOQUE_1.md`
   - `scripts/audit/check_ui_contract.py`
2. Restaurar manualmente los cambios de `.gitignore` de este bloque.
3. Volver a ejecutar:

```powershell
python -m pytest -q
```

## Commit SHA

- Base usada: `2d8e085fcac8803974ee82181c54fe77009f1e8f`
- Commit nuevo de esta tarea: no creado todavía
