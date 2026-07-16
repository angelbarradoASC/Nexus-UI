# Comandos Tanda 1

```bash
python -m pip install -r requirements-dev.txt
make test-audit-tanda1
pytest -q
```

## Resultado esperado

- `python -m pip install -r requirements-dev.txt` instala dependencias de app, worker, desktop y test sin errores de resolucion.
- `make test-audit-tanda1` deja verde la base de seguridad de esta tanda.
- `pytest -q` debe recoger tests sin fallar por modulos ausentes.

## Como distinguir fallos

- Fallo de dependencia:
  - aparece durante import o coleccion con mensajes como `ModuleNotFoundError`.
  - indica que el entorno no esta completo.
- Fallo funcional:
  - la coleccion termina y fallan asserts o respuestas HTTP.
  - indica regresion de comportamiento o seguridad.
