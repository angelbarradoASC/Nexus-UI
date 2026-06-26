from __future__ import annotations

import pytest

from desktop.storage.atomic_io import atomic_write_text


def test_atomic_write_text_escribe_contenido_correcto(tmp_path):
    target = tmp_path / "state.json"

    atomic_write_text(target, '{"ok": true}\n')

    assert target.read_text(encoding="utf-8") == '{"ok": true}\n'


def test_atomic_write_text_preserva_archivo_previo_si_falla_replace(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    target.write_text("contenido-previo", encoding="utf-8")

    def _boom(_src, _dst):
        raise OSError("replace failed")

    monkeypatch.setattr("desktop.storage.atomic_io.os.replace", _boom)

    with pytest.raises(OSError, match="replace failed"):
        atomic_write_text(target, "nuevo-contenido")

    assert target.read_text(encoding="utf-8") == "contenido-previo"
    assert list(tmp_path.glob("*.tmp")) == []
