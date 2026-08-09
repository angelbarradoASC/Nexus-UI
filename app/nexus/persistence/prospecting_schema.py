from __future__ import annotations

from nexus.persistence.sqlite_store import SQLiteStore


def ensure_prospecting_schema(store: SQLiteStore) -> None:
    with store.transaction() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prospecting_runs(
              run_id TEXT PRIMARY KEY,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS storage_migrations(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              migration_scope TEXT NOT NULL,
              source_path TEXT NOT NULL,
              source_hash TEXT NOT NULL,
              result TEXT NOT NULL,
              record_count INTEGER NOT NULL DEFAULT 0,
              migrated_at TEXT NOT NULL,
              details_json TEXT NOT NULL DEFAULT '{}',
              UNIQUE(migration_scope, source_path, source_hash, result)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prospecting_meta(
              key TEXT PRIMARY KEY,
              value_json TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sales_verticals(
              slug TEXT PRIMARY KEY,
              nombre TEXT NOT NULL,
              aliases_json TEXT NOT NULL DEFAULT '[]',
              activo INTEGER NOT NULL DEFAULT 1,
              is_fallback INTEGER NOT NULL DEFAULT 0,
              scoring_rules_json TEXT NOT NULL DEFAULT '{}',
              discovery_config_json TEXT NOT NULL DEFAULT '{}',
              crm_tags_json TEXT NOT NULL DEFAULT '[]',
              crm_sector TEXT NOT NULL DEFAULT 'otros',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
