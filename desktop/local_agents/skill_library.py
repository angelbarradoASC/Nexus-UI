"""
desktop/local_agents/skill_library.py
--------------------------------------
SkillLibrary — memoria de scripts que PEPO ha generado, probado y validado.

La idea: la primera vez que se pide una tarea de sistema scriptable, el LLM
escribe un script de PowerShell para resolverla. Si el usuario confirma su
ejecucion y el propio script verifica que funciono, se guarda como skill
"draft". La siguiente vez que se pida algo parecido, se reutiliza el script
guardado en vez de volver a generarlo — y tras un segundo exito pasa a
"validado" (se ejecuta directo, sin pasar por el LLM en absoluto).

Mismo patron de almacenamiento que DesktopMonitoringIntegrationStore
(SQLite en config_dir), para no meter una dependencia nueva.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    skill_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    script_body TEXT NOT NULL,
    verify_command TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);
"""

_PROMOTE_AFTER_SUCCESSES = 2


@dataclass(slots=True)
class Skill:
    skill_id: str
    description: str
    script_body: str
    verify_command: str
    status: str
    success_count: int
    failure_count: int
    created_at: str
    last_used_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Skill":
        return cls(
            skill_id=str(row["skill_id"]),
            description=str(row["description"]),
            script_body=str(row["script_body"]),
            verify_command=str(row["verify_command"]),
            status=str(row["status"]),
            success_count=int(row["success_count"]),
            failure_count=int(row["failure_count"]),
            created_at=str(row["created_at"]),
            last_used_at=row["last_used_at"],
        )


class SkillLibrary:
    """Guarda y recupera scripts validados para tareas de sistema repetidas."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def list_skills(self) -> list[Skill]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM skills ORDER BY created_at DESC").fetchall()
        return [Skill.from_row(row) for row in rows]

    def get_skill(self, skill_id: str) -> Skill | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM skills WHERE skill_id = ?", (skill_id,)).fetchone()
        return Skill.from_row(row) if row is not None else None

    async def find_match(self, task: str, llm_router) -> Skill | None:
        """Pregunta al LLM si alguna skill guardada resuelve ya esta tarea."""
        skills = self.list_skills()
        if not skills or llm_router is None:
            return None

        from nexus.prompts import resolve_prompt_sync
        from nexus.utils.llm_json import parse_llm_json

        catalogue = "\n".join(f"- {s.skill_id}: {s.description}" for s in skills)
        messages = [
            {"role": "system", "content": resolve_prompt_sync("pepo.skill_library_match")},
            {"role": "user", "content": f"Skills guardadas:\n{catalogue}\n\nTarea pedida:\n{task}"},
        ]
        try:
            response = await llm_router.call(
                messages=messages,
                preferred_level=2,  # L1 sigue caido — ver nota en skill_router.resolve_llm
                temperature=0.0,
                # L2 es un modelo "reasoning" — necesita margen para pensar antes
                # de escribir el JSON (ver nota igual en skill_router.resolve_llm).
                max_tokens=900,
                timeout=14.0,
            )
        except Exception:
            return None
        if getattr(response, "error", None):
            return None

        parsed = parse_llm_json(response.content or "") or {}
        skill_id = parsed.get("skill_id")
        confidence = float(parsed.get("confidence", 0))
        if not skill_id or confidence < 0.75:
            return None
        return self.get_skill(skill_id)

    def save_skill(self, *, description: str, script_body: str, verify_command: str) -> Skill:
        skill = Skill(
            skill_id=f"skill-{uuid.uuid4().hex[:12]}",
            description=description,
            script_body=script_body,
            verify_command=verify_command,
            status="draft",
            success_count=1,
            failure_count=0,
            created_at=datetime.now(timezone.utc).isoformat(),
            last_used_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO skills (
                    skill_id, description, script_body, verify_command,
                    status, success_count, failure_count, created_at, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    skill.skill_id, skill.description, skill.script_body, skill.verify_command,
                    skill.status, skill.success_count, skill.failure_count,
                    skill.created_at, skill.last_used_at,
                ),
            )
            conn.commit()
        return skill

    def record_success(self, skill_id: str) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT success_count, status FROM skills WHERE skill_id = ?", (skill_id,)).fetchone()
            if row is None:
                return
            new_count = int(row["success_count"]) + 1
            new_status = "validado" if new_count >= _PROMOTE_AFTER_SUCCESSES else row["status"]
            conn.execute(
                "UPDATE skills SET success_count = ?, status = ?, last_used_at = ? WHERE skill_id = ?",
                (new_count, new_status, datetime.now(timezone.utc).isoformat(), skill_id),
            )
            conn.commit()

    def record_failure(self, skill_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE skills SET failure_count = failure_count + 1, last_used_at = ? WHERE skill_id = ?",
                (datetime.now(timezone.utc).isoformat(), skill_id),
            )
            conn.commit()
