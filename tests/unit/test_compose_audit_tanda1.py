from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_prod_no_tiene_reload_ni_mounts_de_codigo():
    prod = _read("docker-compose.prod.yml")

    assert "--reload" not in prod
    assert "./app:/app" not in prod
    assert "./products:/app/products" not in prod
    assert "./desktop:/app/desktop" not in prod
    assert "./worker:/app" not in prod


def test_prod_no_usa_promtail_latest():
    prod = _read("docker-compose.prod.yml")
    base = _read("docker-compose.yml")

    assert "promtail:latest" not in prod
    assert "promtail:latest" not in base


def test_dev_conserva_reload_y_mounts_de_desarrollo():
    dev = _read("docker-compose.dev.yml")

    assert "--reload" in dev
    assert "./app:/app" in dev
    assert "./products:/app/products" in dev
    assert "./desktop:/app/desktop" in dev
    assert "./worker:/app" in dev
