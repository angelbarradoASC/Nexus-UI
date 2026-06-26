"""Deploy the first remote LLM stack to llmpro.

Installs:
- Ollama (CPU runtime)
- LiteLLM proxy/router
- systemd service for LiteLLM

This is intentionally simple and LAN-first.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

import paramiko


REPO_ROOT = Path(__file__).resolve().parents[1]
REMOTE_BASE = "/opt/open-nexus-router"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def upload_file(sftp: paramiko.SFTPClient, content: str, remote_path: str) -> None:
    with sftp.file(remote_path, "w") as fh:
        fh.write(content)


def run(ssh: paramiko.SSHClient, command: str) -> tuple[int, str, str]:
    stdin, stdout, stderr = ssh.exec_command(command, get_pty=True)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    return stdout.channel.recv_exit_status(), out, err


def emit(text: str) -> None:
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))


def sudo_wrap(password: str, command: str) -> str:
    return f"echo {password!r} | sudo -S -p '' bash -lc {command!r}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--pull-bootstrap-model", action="store_true")
    parser.add_argument("--bootstrap-model", default="qwen2.5:3b")
    args = parser.parse_args()

    litellm_cfg = read_text(REPO_ROOT / "remote" / "router" / "litellm_config.yaml")
    systemd_unit = read_text(REPO_ROOT / "remote" / "router" / "systemd" / "open-nexus-litellm.service")
    master_key = secrets.token_urlsafe(24)
    env_content = f"LITELLM_MASTER_KEY={master_key}\n"

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        args.host,
        username=args.username,
        password=args.password,
        timeout=20,
        banner_timeout=20,
        auth_timeout=20,
    )

    try:
        code, out, err = run(
            ssh,
            sudo_wrap(
                args.password,
                (
                    "set -euo pipefail; "
                    "apt-get update; "
                    "apt-get install -y python3-venv curl; "
                    f"mkdir -p {REMOTE_BASE}/router; "
                    f"chown -R {args.username}:{args.username} {REMOTE_BASE}"
                ),
            ),
        )
        emit(out)
        emit(err)
        if code != 0:
            return code

        code, out, err = run(
            ssh,
            (
                "command -v ollama >/dev/null 2>&1 || "
                "(curl -fsSL https://ollama.com/install.sh -o /tmp/ollama_install.sh && "
                + sudo_wrap(args.password, "bash /tmp/ollama_install.sh")
                + ")"
            ),
        )
        emit(out)
        emit(err)
        if code != 0:
            return code

        sftp = ssh.open_sftp()
        try:
            upload_file(sftp, litellm_cfg, f"{REMOTE_BASE}/router/litellm_config.yaml")
            upload_file(sftp, env_content, f"{REMOTE_BASE}/router/.env")
            upload_file(sftp, systemd_unit, "/tmp/open-nexus-litellm.service")
        finally:
            sftp.close()

        code, out, err = run(
            ssh,
            sudo_wrap(
                args.password,
                (
                    "set -euo pipefail; "
                    f"python3 -m venv {REMOTE_BASE}/.venv; "
                    f"{REMOTE_BASE}/.venv/bin/pip install --upgrade pip setuptools wheel; "
                    f"{REMOTE_BASE}/.venv/bin/pip install 'litellm[proxy]'; "
                    "cp /tmp/open-nexus-litellm.service /etc/systemd/system/open-nexus-litellm.service; "
                    "systemctl daemon-reload; "
                    "systemctl enable --now ollama; "
                    "systemctl enable --now open-nexus-litellm"
                ),
            ),
        )
        emit(out)
        emit(err)
        if code != 0:
            return code

        if args.pull_bootstrap_model:
            code, out, err = run(
                ssh,
                f"ollama pull {args.bootstrap_model}",
            )
            emit(out)
            emit(err)
            if code != 0:
                return code

        code, out, err = run(
            ssh,
            "curl -s http://127.0.0.1:4000/health || true; echo; systemctl status open-nexus-litellm --no-pager -n 10 || true; echo; systemctl status ollama --no-pager -n 10 || true",
        )
        emit(out)
        emit(err)

        print("\n===DEPLOYMENT_SUMMARY===")
        print(f"Router URL: http://{args.host}:4000")
        print("Master key stored on remote host at /opt/open-nexus-router/router/.env")
        if args.pull_bootstrap_model:
            print(f"Bootstrap model pulled: {args.bootstrap_model}")
        else:
            print("No bootstrap model pulled yet.")
        return 0
    finally:
        ssh.close()


if __name__ == "__main__":
    raise SystemExit(main())
