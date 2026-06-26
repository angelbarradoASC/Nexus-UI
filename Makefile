# ─────────────────────────────────────────────
# NEXUS-UI — Comandos de desarrollo y testing
# ─────────────────────────────────────────────

.PHONY: test test-unit test-integration test-e2e test-smoke test-all lint typecheck clean install-dev test-audit-tanda1

# ── Tests ──────────────────────────────────────────────────────────────────────

## Todos los tests (excluye smoke)
test:
	cd app && python -m pytest ../tests/unit ../tests/integration ../tests/e2e \
		-v --tb=short -q

## Solo tests unitarios (rápidos, sin mocks complejos)
test-unit:
	cd app && python -m pytest ../tests/unit -v --tb=short

## Tests de integración (flujo completo con mocks)
test-integration:
	cd app && python -m pytest ../tests/integration -v --tb=short

## Tests e2e (API completa con TestClient)
test-e2e:
	cd app && python -m pytest ../tests/e2e -v --tb=short

## Smoke tests (sanidad rápida)
test-smoke:
	cd app && python -m pytest ../tests/smoke -v --tb=short

## Todos los tests con cobertura
test-coverage:
	cd app && python -m pytest ../tests/unit ../tests/integration ../tests/e2e \
		--cov=. --cov-report=term-missing --cov-report=html:../coverage \
		--cov-omit="*/migrations/*,*/static/*,*/templates/*" \
		-q

## Todos los tests incluyendo smoke
test-all:
	cd app && python -m pytest ../tests -v --tb=short

install-dev:
	python -m pip install -r requirements-dev.txt

test-audit-tanda1:
	python -m pytest -q tests/unit/test_desktop_backend_app.py tests/unit/test_desktop_runtime.py tests/unit/test_audit_tanda1_contract.py

# ── Calidad ────────────────────────────────────────────────────────────────────

## Lint con Ruff
lint:
	cd app && python -m ruff check . --fix

## Formatear con Ruff
format:
	cd app && python -m ruff format .

## Type check con mypy
typecheck:
	cd app && python -m mypy . --ignore-missing-imports --no-error-summary

# ── Aplicación ─────────────────────────────────────────────────────────────────

## Arrancar la app en modo desarrollo
dev:
	cd app && DEBUG=true python -m uvicorn main:app --reload --port 5010

## Arrancar el worker en modo desarrollo
dev-worker:
	cd app && DEBUG=true python ../worker/worker.py

# ── Limpieza ───────────────────────────────────────────────────────────────────

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf coverage/ 2>/dev/null || true
