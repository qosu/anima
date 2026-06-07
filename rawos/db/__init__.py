"""
rawos database store — thin async wrapper over SQLite.
All public methods enforce user_id scoping by construction.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from rawos.models import (
    User, UserPublic, Project, Agent, AgentStatus,
    Intent, IntentStatus, Memory, Artifact, Tool, Event,
)

_DB_PATH: Path | None = None


def init(db_path: str | Path) -> None:
    global _DB_PATH
    _DB_PATH = Path(db_path)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _apply_schema()


def _apply_schema() -> None:
    # __file__ = rawos/db/__init__.py → go up 3 levels to project root
    schema_path = Path(__file__).parent.parent.parent / "migrations" / "001_initial.sql"
    schema_sql = schema_path.read_text()
    with _conn() as conn:
        conn.executescript(schema_sql)


@contextmanager
def _conn():
    assert _DB_PATH, "db.init() must be called before any db operation"
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def create_user(user: User) -> User:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO users
               (id, email, password_hash, tier, token_budget_daily,
                tokens_used_today, budget_reset_date, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (user.id, user.email, user.password_hash, user.tier.value,
             user.token_budget_daily, user.tokens_used_today,
             "", user.created_at, user.updated_at),
        )
    return user


def get_user_by_email(email: str) -> User | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower(),)
        ).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_id(user_id: str) -> User | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return _row_to_user(row) if row else None


def consume_tokens(user_id: str, tokens: int) -> None:
    """Atomically add tokens_used_today; caller must check budget before calling."""
    with _conn() as conn:
        conn.execute(
            "UPDATE users SET tokens_used_today = tokens_used_today + ?, updated_at = ? WHERE id = ?",
            (tokens, _now(), user_id),
        )


def reset_daily_budget(user_id: str) -> None:
    import datetime
    today = datetime.date.today().isoformat()
    with _conn() as conn:
        conn.execute(
            "UPDATE users SET tokens_used_today = 0, budget_reset_date = ?, updated_at = ? WHERE id = ?",
            (today, _now(), user_id),
        )


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"], email=row["email"], password_hash=row["password_hash"],
        tier=row["tier"], token_budget_daily=row["token_budget_daily"],
        tokens_used_today=row["tokens_used_today"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def create_project(project: Project) -> Project:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO projects (id, user_id, name, description, workdir, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (project.id, project.user_id, project.name, project.description,
             project.workdir, project.created_at, project.updated_at),
        )
    return project


def get_projects(user_id: str) -> list[Project]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM projects WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [_row_to_project(r) for r in rows]


def get_project(user_id: str, project_id: str) -> Project | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
    return _row_to_project(row) if row else None


def update_project(user_id: str, project_id: str, **fields: Any) -> Project | None:
    allowed = {"name", "description", "workdir"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_project(user_id, project_id)
    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with _conn() as conn:
        conn.execute(
            f"UPDATE projects SET {set_clause} WHERE id = ? AND user_id = ?",
            (*updates.values(), project_id, user_id),
        )
    return get_project(user_id, project_id)


def _row_to_project(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"], user_id=row["user_id"], name=row["name"],
        description=row["description"], workdir=row["workdir"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def create_agent(agent: Agent) -> Agent:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO agents
               (id, user_id, project_id, parent_id, status, goal, model, token_used, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (agent.id, agent.user_id, agent.project_id, agent.parent_id,
             agent.status.value, agent.goal, agent.model,
             agent.token_used, agent.created_at, agent.updated_at),
        )
    return agent


def update_agent_status(user_id: str, agent_id: str, status: AgentStatus) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE agents SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (status.value, _now(), agent_id, user_id),
        )


def add_agent_tokens(user_id: str, agent_id: str, tokens: int) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE agents SET token_used = token_used + ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (tokens, _now(), agent_id, user_id),
        )


def get_agent(user_id: str, agent_id: str) -> Agent | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE id = ? AND user_id = ?",
            (agent_id, user_id),
        ).fetchone()
    return _row_to_agent(row) if row else None


def _row_to_agent(row: sqlite3.Row) -> Agent:
    return Agent(
        id=row["id"], user_id=row["user_id"], project_id=row["project_id"],
        parent_id=row["parent_id"], status=AgentStatus(row["status"]),
        goal=row["goal"], model=row["model"], token_used=row["token_used"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# Intents
# ---------------------------------------------------------------------------

def create_intent(intent: Intent) -> Intent:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO intents
               (id, user_id, project_id, agent_id, raw_text, goal, status,
                result_artifact_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (intent.id, intent.user_id, intent.project_id, intent.agent_id,
             intent.raw_text, intent.goal, intent.status.value,
             intent.result_artifact_id, intent.created_at, intent.updated_at),
        )
    return intent


def update_intent(user_id: str, intent_id: str, **fields: Any) -> None:
    allowed = {"agent_id", "goal", "status", "result_artifact_id"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with _conn() as conn:
        conn.execute(
            f"UPDATE intents SET {set_clause} WHERE id = ? AND user_id = ?",
            (*updates.values(), intent_id, user_id),
        )


def get_project_history(user_id: str, project_id: str, limit: int = 60) -> list[Intent]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT * FROM intents WHERE project_id = ? AND user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (project_id, user_id, limit),
        ).fetchall()
    return [_row_to_intent(r) for r in reversed(rows)]


def _row_to_intent(row: sqlite3.Row) -> Intent:
    return Intent(
        id=row["id"], user_id=row["user_id"], project_id=row["project_id"],
        agent_id=row["agent_id"], raw_text=row["raw_text"], goal=row["goal"],
        status=IntentStatus(row["status"]),
        result_artifact_id=row["result_artifact_id"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# Memories
# ---------------------------------------------------------------------------

def save_memory(memory: Memory) -> Memory:
    content_json = json.dumps(memory.content, ensure_ascii=False)
    with _conn() as conn:
        conn.execute(
            """INSERT INTO memories
               (id, user_id, project_id, agent_id, tier, role, content,
                embedding, created_at, expires_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (memory.id, memory.user_id, memory.project_id, memory.agent_id,
             memory.tier.value, memory.role.value, content_json,
             memory.embedding, memory.created_at, memory.expires_at),
        )
    return memory


def get_project_memories(user_id: str, project_id: str, tier: str, limit: int = 100) -> list[Memory]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT * FROM memories
               WHERE project_id = ? AND user_id = ? AND tier = ?
               AND (expires_at IS NULL OR expires_at > ?)
               ORDER BY created_at ASC LIMIT ?""",
            (project_id, user_id, tier, _now(), limit),
        ).fetchall()
    return [_row_to_memory(r) for r in rows]


def purge_expired_memories() -> int:
    with _conn() as conn:
        cursor = conn.execute(
            "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (_now(),),
        )
        return cursor.rowcount


def _row_to_memory(row: sqlite3.Row) -> Memory:
    from rawos.models import MemoryTier, MessageRole
    content = json.loads(row["content"])
    return Memory(
        id=row["id"], user_id=row["user_id"], project_id=row["project_id"],
        agent_id=row["agent_id"], tier=MemoryTier(row["tier"]),
        role=MessageRole(row["role"]), content=content,
        embedding=row["embedding"], created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


# ---------------------------------------------------------------------------
# Events (append-only audit log)
# ---------------------------------------------------------------------------

def log_event(event: Event) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO events (id, user_id, project_id, agent_id, type, payload, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (event.id, event.user_id, event.project_id, event.agent_id,
             event.type.value, json.dumps(event.payload, ensure_ascii=False),
             event.created_at),
        )


# ---------------------------------------------------------------------------
# Refresh tokens
# ---------------------------------------------------------------------------

def save_refresh_token(token_id: str, user_id: str, token_hash: str, expires_at: int) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, created_at)
               VALUES (?,?,?,?,?)""",
            (token_id, user_id, token_hash, expires_at, _now()),
        )


def get_refresh_token(token_hash: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM refresh_tokens WHERE token_hash = ? AND expires_at > ?",
            (token_hash, _now()),
        ).fetchone()
    return dict(row) if row else None


def revoke_refresh_token(token_hash: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM refresh_tokens WHERE token_hash = ?", (token_hash,))
