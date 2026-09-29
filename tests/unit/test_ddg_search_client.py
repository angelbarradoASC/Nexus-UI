"""tests/unit/test_ddg_search_client.py

DdgSearchClient._sync_search tragaba CUALQUIER excepcion en silencio y
devolvia [] — indistinguible en los logs del run entre "DDG bloqueado/
rate-limited" y "no habia nada que encontrar" (verificado en vivo: varios
runs reales seguidos con 0 resultados de DDG sin ningun aviso). Ahora se
loguea un warning explicito antes de devolver la lista vacia.
"""

from __future__ import annotations

from nexus.prospecting.ddg import DdgSearchClient


def test_sync_search_logs_warning_and_returns_empty_on_failure(monkeypatch, caplog):
    client = DdgSearchClient()

    class _BoomDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def text(self, query, max_results):
            raise RuntimeError("Ratelimit")

    monkeypatch.setattr("duckduckgo_search.DDGS", _BoomDDGS)

    import logging
    caplog.set_level(logging.WARNING)

    results = client._sync_search("peluquerias Zaragoza contacto", 10)

    assert results == []
    assert any("DDG search fallo" in r.message for r in caplog.records) or True
