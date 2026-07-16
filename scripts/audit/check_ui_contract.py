from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path


PROTECTED_UI_ROOTS = (
    "app/templates",
    "app/static",
    "products/desktop/ui/templates",
    "products/desktop/ui/static",
    "products/web/ui/templates",
    "products/web/ui/static",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "docs" / "audit" / "ui_contract.sha256"
UPDATE_GUARD = "I_UNDERSTAND"


def _iter_ui_files() -> list[Path]:
    files: list[Path] = []
    for relative_root in PROTECTED_UI_ROOTS:
        root = REPO_ROOT / relative_root
        if not root.exists():
            continue
        files.extend(sorted(path for path in root.rglob("*") if path.is_file()))
    return sorted(files)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def compute_manifest() -> dict[str, str]:
    return {_relative(path): _sha256(path) for path in _iter_ui_files()}


def load_manifest() -> dict[str, str]:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"No existe el manifiesto UI: {MANIFEST_PATH}. "
            "Generalo con --update y NEXUS_ALLOW_UI_BASELINE_UPDATE."
        )

    manifest: dict[str, str] = {}
    for raw_line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            digest, relpath = line.split("  ", 1)
        except ValueError as exc:
            raise ValueError(f"Linea invalida en {MANIFEST_PATH}: {raw_line!r}") from exc
        manifest[relpath.strip()] = digest.strip().lower()
    return manifest


def write_manifest(manifest: dict[str, str]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# sha256  relative/path",
        *[f"{digest}  {relpath}" for relpath, digest in sorted(manifest.items())],
        "",
    ]
    MANIFEST_PATH.write_text("\n".join(lines), encoding="utf-8")


def compare(expected: dict[str, str], current: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    missing = sorted(path for path in expected if path not in current)
    unexpected = sorted(path for path in current if path not in expected)
    changed = sorted(path for path, digest in current.items() if expected.get(path) not in (None, digest))
    return missing, unexpected, changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Nexus protected UI file hashes.")
    parser.add_argument("--update", action="store_true", help="Refresh the UI hash manifest.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    current = compute_manifest()

    if args.update:
        if os.environ.get("NEXUS_ALLOW_UI_BASELINE_UPDATE") != UPDATE_GUARD:
            print(
                "Refusing to update UI baseline without "
                "NEXUS_ALLOW_UI_BASELINE_UPDATE=I_UNDERSTAND.",
                file=sys.stderr,
            )
            return 1
        write_manifest(current)
        print(f"UI baseline updated: {MANIFEST_PATH}")
        print(f"Protected files registered: {len(current)}")
        return 0

    try:
        expected = load_manifest()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    missing, unexpected, changed = compare(expected, current)
    if not missing and not unexpected and not changed:
        print(f"UI contract OK. Protected files verified: {len(current)}")
        return 0

    if missing:
        print("Missing protected UI files:")
        for path in missing:
            print(f"- {path}")
    if unexpected:
        print("Unexpected protected UI files:")
        for path in unexpected:
            print(f"- {path}")
    if changed:
        print("Modified protected UI files:")
        for path in changed:
            print(f"- {path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

