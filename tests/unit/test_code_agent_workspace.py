"""tests/unit/test_code_agent_workspace.py

Sandbox del modo codigo de PEPO (docs/PLAN_PEPO_MODO_CODIGO.md, D4). Estos tests
son BLOQUEANTES: el contenido de los ficheros viaja a un LLM en la nube y el agente
nunca debe leer ni escribir fuera de la carpeta de trabajo ni tocar credenciales.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from desktop.code_agent.workspace import (
    Workspace,
    WorkspaceError,
    is_denied_name,
    redact,
    validate_workspace_root,
)


@pytest.fixture
def ws(tmp_path) -> Workspace:
    root = tmp_path / "proyecto"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('hola')\n", encoding="utf-8")
    (tmp_path / "fuera.txt").write_text("secreto fuera del proyecto", encoding="utf-8")
    return Workspace(root)


# ── Escapes de ruta ──────────────────────────────────────────────────────────

def test_relative_path_inside_is_resolved(ws):
    assert ws.resolve("src/app.py") == (ws.root / "src" / "app.py").resolve()
    assert ws.resolve(".") == ws.root
    assert ws.resolve(None) == ws.root
    assert ws.resolve("") == ws.root


def test_a_file_that_does_not_exist_yet_can_still_be_resolved(ws):
    assert ws.resolve("src/nuevo.py") == (ws.root / "src" / "nuevo.py").resolve()


@pytest.mark.parametrize("raw", [
    "../fuera.txt",
    "src/../../fuera.txt",
    "src/../../../Windows/win.ini",
])
def test_parent_directory_escape_is_rejected(ws, raw):
    with pytest.raises(WorkspaceError):
        ws.resolve(raw)


def test_absolute_path_outside_the_workspace_is_rejected(ws, tmp_path):
    with pytest.raises(WorkspaceError):
        ws.resolve(str(tmp_path / "fuera.txt"))


def test_absolute_path_inside_the_workspace_is_accepted(ws):
    assert ws.resolve(str(ws.root / "src" / "app.py")) == (ws.root / "src" / "app.py").resolve()


def test_a_sibling_folder_sharing_the_prefix_is_not_inside(tmp_path):
    root = tmp_path / "proyecto"
    root.mkdir()
    sibling = tmp_path / "proyecto-secreto"
    sibling.mkdir()
    (sibling / "x.txt").write_text("x", encoding="utf-8")

    with pytest.raises(WorkspaceError):
        Workspace(root).resolve(str(sibling / "x.txt"))


@pytest.mark.parametrize("raw", [
    "\\\\servidor\\share\\x.txt",
    "//servidor/share/x.txt",
])
def test_unc_paths_are_rejected(ws, raw):
    with pytest.raises(WorkspaceError):
        ws.resolve(raw)


@pytest.mark.parametrize("raw", [
    "src/app.py:secreto",          # flujo alterno de datos de NTFS
    "C:fuera.txt",                 # ruta relativa a unidad
    "src/app.py::$DATA",
])
def test_ntfs_alternate_streams_and_drive_relative_paths_are_rejected(ws, raw):
    with pytest.raises(WorkspaceError):
        ws.resolve(raw)


@pytest.mark.parametrize("raw", ["nul", "CON", "src/aux.txt", "com1.log", "LPT3"])
def test_windows_reserved_device_names_are_rejected(ws, raw):
    with pytest.raises(WorkspaceError):
        ws.resolve(raw)


def test_null_bytes_are_rejected(ws):
    with pytest.raises(WorkspaceError):
        ws.resolve("src/app.py\x00.txt")


def test_symlink_escaping_the_workspace_is_rejected(ws, tmp_path):
    link = ws.root / "enlace"
    try:
        link.symlink_to(tmp_path / "fuera.txt")
    except (OSError, NotImplementedError):
        pytest.skip("crear symlinks requiere privilegios en este equipo")

    with pytest.raises(WorkspaceError):
        ws.resolve("enlace")


@pytest.mark.skipif(sys.platform != "win32", reason="junctions solo existen en Windows")
def test_junction_escaping_the_workspace_is_rejected(ws, tmp_path):
    outside = tmp_path / "carpeta_fuera"
    outside.mkdir()
    (outside / "secreto.txt").write_text("no debe verse", encoding="utf-8")
    junction = ws.root / "atajo"
    completed = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True, text=True)
    if completed.returncode != 0:
        pytest.skip(f"no se pudo crear la junction: {completed.stderr or completed.stdout}")

    with pytest.raises(WorkspaceError):
        ws.resolve("atajo/secreto.txt")


# ── Lista negra de ficheros sensibles ────────────────────────────────────────

@pytest.mark.parametrize("name", [
    ".env", ".env.local", ".env.production", "prod.env", "clave.pem", "server.key", "id_rsa", "id_rsa.pub",
    "id_ed25519", "credentials.enc", "credentials.json", "secrets.yaml", ".netrc", "token.json", "vault.kdbx",
    "SERVER.KEY", ".ENV",
])
def test_sensitive_file_names_are_denied(name):
    assert is_denied_name(name) is True


@pytest.mark.parametrize("name", ["app.py", "README.md", "environment.py", "keyboard.py", "secrets_helper.py", "main.go"])
def test_normal_file_names_are_not_denied(name):
    assert is_denied_name(name) is False


def test_resolve_readable_blocks_env_and_git_internals(ws):
    (ws.root / ".env").write_text("API_KEY=abcdef123456789\n", encoding="utf-8")
    (ws.root / ".git").mkdir()
    (ws.root / ".git" / "config").write_text("[core]\n", encoding="utf-8")

    with pytest.raises(WorkspaceError):
        ws.resolve_readable(".env")
    with pytest.raises(WorkspaceError):
        ws.resolve_readable(".git/config")
    with pytest.raises(WorkspaceError):
        ws.resolve_readable(".git")


def test_a_denied_file_inside_a_subfolder_is_blocked_too(ws):
    (ws.root / "src" / ".env").write_text("X=1\n", encoding="utf-8")

    with pytest.raises(WorkspaceError):
        ws.resolve_readable("src/.env")


def test_iter_files_skips_noise_and_denied_files(ws):
    (ws.root / ".env").write_text("X=1\n", encoding="utf-8")
    (ws.root / "node_modules" / "paquete").mkdir(parents=True)
    (ws.root / "node_modules" / "paquete" / "index.js").write_text("x", encoding="utf-8")
    (ws.root / ".git").mkdir()
    (ws.root / ".git" / "HEAD").write_text("ref", encoding="utf-8")

    names = {ws.rel(p) for p in ws.iter_files()}

    assert names == {"src/app.py"}


# ── Redaccion de secretos ────────────────────────────────────────────────────

@pytest.mark.parametrize("text, leaked", [
    ("api_key = 'abcdef1234567890xyz'", "abcdef1234567890xyz"),
    ("password: hunter2hunter2", "hunter2hunter2"),
    ('"token": "ZZZZ1111aaaa2222bbbb"', "ZZZZ1111aaaa2222bbbb"),
    ("GROQ=gsk_abcdefghijklmnopqrstuvwxyz0123", "gsk_abcdefghijklmnopqrstuvwxyz0123"),
    ("clave sk-proj-AbCdEfGhIjKlMnOpQrStUv", "sk-proj-AbCdEfGhIjKlMnOpQrStUv"),
    ("Authorization: Bearer abcdefghijklmnop1234", "abcdefghijklmnop1234"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----", "MIIEow"),
    ("AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP"),
])
def test_redact_hides_secrets(text, leaked):
    redacted = redact(text)

    assert leaked not in redacted
    assert "REDACTAD" in redacted


def test_redact_leaves_normal_code_alone():
    code = "def token_count(text):\n    return len(text.split())\n\nMAX_TOKENS = 4096\n"

    assert redact(code) == code


# ── Validacion de la carpeta de trabajo ──────────────────────────────────────

def test_validate_accepts_a_real_project_folder(tmp_path):
    assert validate_workspace_root(str(tmp_path)) == tmp_path.resolve()


@pytest.mark.parametrize("raw", ["", "   ", "relativa/carpeta", "."])
def test_validate_rejects_empty_or_relative(raw):
    with pytest.raises(WorkspaceError):
        validate_workspace_root(raw)


def test_validate_rejects_missing_folder_and_files(tmp_path):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")

    with pytest.raises(WorkspaceError):
        validate_workspace_root(str(tmp_path / "no_existe"))
    with pytest.raises(WorkspaceError):
        validate_workspace_root(str(tmp_path / "f.txt"))


def test_validate_rejects_drive_root_and_user_profile():
    anchor = Path(Path.home().anchor or "/")
    with pytest.raises(WorkspaceError):
        validate_workspace_root(str(anchor))
    with pytest.raises(WorkspaceError):
        validate_workspace_root(str(Path.home()))
    with pytest.raises(WorkspaceError):
        validate_workspace_root(str(Path.home().parent))


@pytest.mark.skipif(sys.platform != "win32", reason="rutas de Windows")
def test_validate_rejects_the_windows_folder():
    with pytest.raises(WorkspaceError):
        validate_workspace_root(os.environ.get("SystemRoot", r"C:\Windows"))
