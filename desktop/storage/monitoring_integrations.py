"""SQLite-backed monitoring integrations for Nexus Desktop."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitoring_integrations (
    integration_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    is_default INTEGER NOT NULL DEFAULT 0,
    auth_type TEXT NOT NULL DEFAULT 'none',
    username TEXT NOT NULL DEFAULT '',
    secret_ref TEXT NOT NULL DEFAULT '',
    header_name TEXT NOT NULL DEFAULT '',
    verify_tls INTEGER NOT NULL DEFAULT 1,
    timeout_seconds INTEGER,
    source TEXT NOT NULL DEFAULT 'manual',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_monitoring_integrations_kind
    ON monitoring_integrations(kind);
"""

_SUPPORTED_KINDS = ("prometheus", "grafana", "alertmanager")


@dataclass(slots=True)
class DesktopMonitoringIntegration:
    integration_id: str
    kind: str
    name: str
    base_url: str
    enabled: bool = True
    is_default: bool = False
    auth_type: str = "none"
    username: str = ""
    secret_ref: str = ""
    header_name: str = ""
    verify_tls: bool = True
    timeout_seconds: int | None = None
    source: str = "manual"
    updated_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        kind: str,
        name: str,
        base_url: str,
        enabled: bool = True,
        is_default: bool = False,
        auth_type: str = "none",
        username: str = "",
        secret_ref: str = "",
        header_name: str = "",
        verify_tls: bool = True,
        timeout_seconds: int | None = None,
        source: str = "manual",
        integration_id: str | None = None,
    ) -> "DesktopMonitoringIntegration":
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind not in _SUPPORTED_KINDS:
            raise ValueError(f"Unsupported monitoring integration kind: {kind}")
        return cls(
            integration_id=integration_id or f"mi-{uuid.uuid4().hex[:12]}",
            kind=normalized_kind,
            name=str(name or "").strip() or normalized_kind.title(),
            base_url=str(base_url or "").strip().rstrip("/"),
            enabled=bool(enabled),
            is_default=bool(is_default),
            auth_type=str(auth_type or "none").strip().lower() or "none",
            username=str(username or "").strip(),
            secret_ref=str(secret_ref or "").strip(),
            header_name=str(header_name or "").strip(),
            verify_tls=bool(verify_tls),
            timeout_seconds=timeout_seconds,
            source=str(source or "manual").strip() or "manual",
        ).touched()

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "DesktopMonitoringIntegration":
        return cls(
            integration_id=str(row["integration_id"]),
            kind=str(row["kind"]),
            name=str(row["name"]),
            base_url=str(row["base_url"]),
            enabled=bool(row["enabled"]),
            is_default=bool(row["is_default"]),
            auth_type=str(row["auth_type"]),
            username=str(row["username"]),
            secret_ref=str(row["secret_ref"]),
            header_name=str(row["header_name"]),
            verify_tls=bool(row["verify_tls"]),
            timeout_seconds=row["timeout_seconds"],
            source=str(row["source"]),
            updated_at=str(row["updated_at"]),
        )

    def touched(self) -> "DesktopMonitoringIntegration":
        return DesktopMonitoringIntegration(
            integration_id=self.integration_id,
            kind=self.kind,
            name=self.name,
            base_url=self.base_url.rstrip("/"),
            enabled=self.enabled,
            is_default=self.is_default,
            auth_type=self.auth_type,
            username=self.username,
            secret_ref=self.secret_ref,
            header_name=self.header_name,
            verify_tls=self.verify_tls,
            timeout_seconds=self.timeout_seconds,
            source=self.source,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DesktopMonitoringIntegrationStore:
    """Persists operator monitoring endpoints for the desktop product."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            placeholders = ", ".join("?" for _ in _SUPPORTED_KINDS)
            conn.execute(
                f"DELETE FROM monitoring_integrations WHERE kind NOT IN ({placeholders})",
                _SUPPORTED_KINDS,
            )
            conn.commit()

    def list_integrations(self, *, kind: str | None = None) -> list[DesktopMonitoringIntegration]:
        query = """
            SELECT * FROM monitoring_integrations
        """
        params: tuple[object, ...] = ()
        if kind:
            query += " WHERE kind = ?"
            params = (kind.strip().lower(),)
        query += " ORDER BY kind ASC, is_default DESC, name COLLATE NOCASE ASC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [DesktopMonitoringIntegration.from_row(row) for row in rows]

    def get_integration(self, integration_id: str) -> DesktopMonitoringIntegration | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM monitoring_integrations WHERE integration_id = ?",
                (integration_id,),
            ).fetchone()
        if row is None:
            return None
        return DesktopMonitoringIntegration.from_row(row)

    def get_default(self, kind: str) -> DesktopMonitoringIntegration | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM monitoring_integrations
                WHERE kind = ? AND enabled = 1 AND is_default = 1
                LIMIT 1
                """,
                (kind.strip().lower(),),
            ).fetchone()
        if row is None:
            return None
        return DesktopMonitoringIntegration.from_row(row)

    def save_integration(self, integration: DesktopMonitoringIntegration) -> DesktopMonitoringIntegration:
        integration = integration.touched()
        with self._connect() as conn:
            if integration.is_default:
                conn.execute(
                    """
                    UPDATE monitoring_integrations
                    SET is_default = 0
                    WHERE kind = ? AND integration_id <> ?
                    """,
                    (integration.kind, integration.integration_id),
                )
            conn.execute(
                """
                INSERT INTO monitoring_integrations (
                    integration_id, kind, name, base_url, enabled, is_default,
                    auth_type, username, secret_ref, header_name, verify_tls,
                    timeout_seconds, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(integration_id) DO UPDATE SET
                    kind = excluded.kind,
                    name = excluded.name,
                    base_url = excluded.base_url,
                    enabled = excluded.enabled,
                    is_default = excluded.is_default,
                    auth_type = excluded.auth_type,
                    username = excluded.username,
                    secret_ref = excluded.secret_ref,
                    header_name = excluded.header_name,
                    verify_tls = excluded.verify_tls,
                    timeout_seconds = excluded.timeout_seconds,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    integration.integration_id,
                    integration.kind,
                    integration.name,
                    integration.base_url,
                    int(integration.enabled),
                    int(integration.is_default),
                    integration.auth_type,
                    integration.username,
                    integration.secret_ref,
                    integration.header_name,
                    int(integration.verify_tls),
                    integration.timeout_seconds,
                    integration.source,
                    integration.updated_at,
                ),
            )
            conn.commit()
        return integration

    def delete_integration(self, integration_id: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                "DELETE FROM monitoring_integrations WHERE integration_id = ?",
                (integration_id,),
            )
            conn.commit()
        return result.rowcount > 0

    def delete_integrations_by_kind(self, kind: str) -> int:
        with self._connect() as conn:
            result = conn.execute(
                "DELETE FROM monitoring_integrations WHERE kind = ?",
                (kind.strip().lower(),),
            )
            conn.commit()
        return result.rowcount

    def migrate_from_cfg(self, cfg) -> list[DesktopMonitoringIntegration]:
        migrated: list[DesktopMonitoringIntegration] = []
        defaults = {
            "prometheus": getattr(cfg, "prometheus_url", ""),
            "grafana": getattr(cfg, "grafana_url", ""),
            "alertmanager": getattr(cfg, "alertmanager_url", ""),
        }
        for kind, base_url in defaults.items():
            normalized_url = str(base_url or "").strip().rstrip("/")
            if not normalized_url:
                continue
            if self.get_default(kind) is not None:
                continue
            integration = DesktopMonitoringIntegration.create(
                kind=kind,
                name=f"{kind.title()} principal",
                base_url=normalized_url,
                enabled=True,
                is_default=True,
                source="cfg_migration",
            )
            migrated.append(self.save_integration(integration))
        return migrated


def resolve_monitoring_base_urls(cfg, store: DesktopMonitoringIntegrationStore | None) -> dict[str, str]:
    """Return effective base URLs with desktop-local overrides when available."""

    resolved = {
        "prometheus": getattr(cfg, "prometheus_url", ""),
        "grafana": getattr(cfg, "grafana_url", ""),
        "alertmanager": getattr(cfg, "alertmanager_url", ""),
    }
    if store is None:
        return resolved

    store.migrate_from_cfg(cfg)
    for kind in resolved:
        default_integration = store.get_default(kind)
        if default_integration and default_integration.base_url:
            resolved[kind] = default_integration.base_url
    return resolved
