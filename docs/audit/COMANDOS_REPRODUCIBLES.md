# Comandos Reproducibles

## Runtime canonico

- Plataforma objetivo: Windows Desktop
- Runtime Python canonico para desarrollo local: `Python 3.11`
- Comando recomendado:

```powershell
.\scripts\bootstrap_dev.ps1
```

## Bootstrap

```powershell
.\scripts\bootstrap_dev.ps1
```

Este comando:

- crea o reutiliza `.venv`
- instala `requirements-dev.txt`
- verifica imports minimos: `fastapi`, `pytest`, `bson`, `paramiko`
- no arranca Docker
- no toca configuracion personal del usuario

## Verificacion de contrato

```powershell
.\scripts\test_contract.ps1
```

Este comando ejecuta:

```powershell
python scripts/audit/check_ui_contract.py
pytest -q
```

## Notas operativas

- Si `pytest -q` falla, el fallo debe tratarse como regresion o fallo heredado reproducible; no se maquilla en este bloque.
- El contrato de UI debe permanecer verde antes de aceptar cualquier cambio de backend o runtime.
- `.\scripts\test_contract.ps1` guarda la salida completa de `pytest` en `runtime/logs/pytest-contract.log` antes de propagar el exit code.
