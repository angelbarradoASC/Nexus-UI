from __future__ import annotations

import subprocess
import sys
from pathlib import Path


FROZEN_UI_PREFIXES = (
    "products/desktop/ui/templates/",
    "products/desktop/ui/static/css/",
    "products/desktop/ui/static/js/",
    "products/web/ui/templates/",
    "products/web/ui/static/css/",
    "products/web/ui/static/js/",
    "app/templates/",
    "app/static/",
)


def main() -> int:
    base_ref = sys.argv[1] if len(sys.argv) > 1 else "HEAD~1"
    repo_root = Path(__file__).resolve().parents[1]
    verify_base = subprocess.run(
        ["git", "rev-parse", "--verify", base_ref],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    diff_command = (
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"]
        if verify_base.returncode == 0
        else ["git", "diff", "--name-only", "HEAD"]
    )
    if verify_base.returncode != 0:
        sys.stderr.write(
            f"Referencia base no disponible ({base_ref}); se compara el worktree actual contra HEAD.\n"
        )

    result = subprocess.run(
        diff_command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return result.returncode

    changed_files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    forbidden = [
        path for path in changed_files
        if path.startswith(FROZEN_UI_PREFIXES)
    ]

    if forbidden:
        print("UI congelada modificada:")
        for path in forbidden:
            print(f"- {path}")
        return 2

    print("Sin cambios en la UI congelada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
