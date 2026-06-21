"""SQLite persistence for simulation results.

Stores simulated participant sessions, their responses, expression evaluations,
break findings, and path coverage — enabling cross-session interaction queries
(e.g. formr_api_* calls return data from earlier sessions).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from formr_mcp.utils import WORKSPACE_DIR


def _db_path() -> Path:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    return WORKSPACE_DIR / "simulations.db"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or _db_path()
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS simulations (
    id TEXT PRIMARY KEY,
    run_name TEXT NOT NULL,
    strategy TEXT NOT NULL DEFAULT 'explore',
    max_sessions INTEGER NOT NULL DEFAULT 50,
    loop_bounds_json TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    created_at TEXT NOT NULL,
    finished_at TEXT,
    sessions_completed INTEGER NOT NULL DEFAULT 0,
    breaks_count INTEGER NOT NULL DEFAULT 0,
    warnings_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    simulation_id TEXT NOT NULL REFERENCES simulations(id),
    sequence INTEGER NOT NULL,
    path_json TEXT NOT NULL,
    branch_decisions_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    loop_iterations_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    survey_name TEXT NOT NULL,
    item_name TEXT NOT NULL,
    iteration INTEGER NOT NULL DEFAULT 0,
    value_json TEXT NOT NULL,
    is_na INTEGER NOT NULL DEFAULT 0,
    sample_label TEXT
);

CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    survey_name TEXT,
    item_name TEXT,
    kind TEXT NOT NULL,
    expression TEXT NOT NULL,
    verdict TEXT NOT NULL,
    detail TEXT NOT NULL,
    inputs_json TEXT
);

CREATE TABLE IF NOT EXISTS breaks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT NOT NULL REFERENCES simulations(id),
    session_id TEXT,
    location TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL,
    inputs_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS path_coverage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT NOT NULL REFERENCES simulations(id),
    position INTEGER NOT NULL,
    reached INTEGER NOT NULL DEFAULT 0,
    branch_true INTEGER NOT NULL DEFAULT 0,
    branch_false INTEGER NOT NULL DEFAULT 0,
    branch_na INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sessions_sim ON sessions(simulation_id);
CREATE INDEX IF NOT EXISTS idx_responses_sim ON responses(simulation_id);
CREATE INDEX IF NOT EXISTS idx_responses_session ON responses(session_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_session ON evaluations(session_id);
CREATE INDEX IF NOT EXISTS idx_breaks_sim ON breaks(simulation_id);
CREATE INDEX IF NOT EXISTS idx_path_sim ON path_coverage(simulation_id);
"""


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    conn = _connect(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def create_simulation(
    run_name: str,
    strategy: str = "explore",
    max_sessions: int = 50,
    loop_bounds: dict[int, int] | None = None,
    db_path: Path | None = None,
) -> str:
    import uuid
    sim_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO simulations (id, run_name, strategy, max_sessions, loop_bounds_json, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'running', ?)",
            (sim_id, run_name, strategy, max_sessions,
             json.dumps(loop_bounds) if loop_bounds else None, now),
        )
        conn.commit()
    finally:
        conn.close()
    return sim_id


def finish_simulation(sim_id: str, sessions_completed: int, breaks: int, warnings: int,
                      db_path: Path | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE simulations SET status='completed', finished_at=?, "
            "sessions_completed=?, breaks_count=?, warnings_count=? WHERE id=?",
            (now, sessions_completed, breaks, warnings, sim_id),
        )
        conn.commit()
    finally:
        conn.close()


def insert_session(
    sim_id: str,
    session_id: str,
    sequence: int,
    path: list[int],
    branch_decisions: dict[int, str],
    status: str = "completed",
    loop_iterations: dict[int, int] | None = None,
    db_path: Path | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sessions (id, simulation_id, sequence, path_json, branch_decisions_json, "
            "status, loop_iterations_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, sim_id, sequence, json.dumps(path),
             json.dumps(branch_decisions), status,
             json.dumps(loop_iterations) if loop_iterations else None, now),
        )
        conn.commit()
    finally:
        conn.close()


def insert_response(
    simulation_id: str,
    session_id: str,
    survey_name: str,
    item_name: str,
    value: Any,
    is_na: bool = False,
    iteration: int = 0,
    sample_label: str | None = None,
    db_path: Path | None = None,
) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO responses (simulation_id, session_id, survey_name, item_name, iteration, value_json, is_na, sample_label) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (simulation_id, session_id, survey_name, item_name, iteration,
             json.dumps(value), int(is_na), sample_label),
        )
        conn.commit()
    finally:
        conn.close()


def insert_evaluation(
    simulation_id: str,
    session_id: str,
    position: int,
    kind: str,
    expression: str,
    verdict: str,
    detail: str,
    inputs_json: str | None = None,
    survey_name: str | None = None,
    item_name: str | None = None,
    db_path: Path | None = None,
) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO evaluations (simulation_id, session_id, position, survey_name, item_name, kind, expression, "
            "verdict, detail, inputs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (simulation_id, session_id, position, survey_name, item_name, kind, expression,
             verdict, detail, inputs_json),
        )
        conn.commit()
    finally:
        conn.close()


def insert_break(
    sim_id: str,
    location: str,
    kind: str,
    detail: str,
    inputs_json: str | None = None,
    session_id: str | None = None,
    db_path: Path | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect(db_path)
    try:
        if session_id:
            conn.execute(
                "INSERT INTO breaks (simulation_id, session_id, location, kind, detail, inputs_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sim_id, session_id, location, kind, detail, inputs_json, now),
            )
        else:
            conn.execute(
                "INSERT INTO breaks (simulation_id, location, kind, detail, inputs_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sim_id, location, kind, detail, inputs_json, now),
            )
        conn.commit()
    finally:
        conn.close()


def upsert_path_coverage(
    sim_id: str,
    position: int,
    reached: bool = False,
    branch_true: bool = False,
    branch_false: bool = False,
    branch_na: bool = False,
    db_path: Path | None = None,
) -> None:
    conn = _connect(db_path)
    try:
        existing = conn.execute(
            "SELECT id FROM path_coverage WHERE simulation_id=? AND position=?",
            (sim_id, position),
        ).fetchone()
        if existing:
            sets = []
            params: list = []
            if reached:
                sets.append("reached = reached + 1")
            if branch_true:
                sets.append("branch_true = branch_true + 1")
            if branch_false:
                sets.append("branch_false = branch_false + 1")
            if branch_na:
                sets.append("branch_na = branch_na + 1")
            if sets:
                conn.execute(
                    f"UPDATE path_coverage SET {', '.join(sets)} WHERE simulation_id=? AND position=?",
                    (sim_id, position),
                )
        else:
            conn.execute(
                "INSERT INTO path_coverage (simulation_id, position, reached, branch_true, branch_false, branch_na) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sim_id, position, int(reached), int(branch_true), int(branch_false), int(branch_na)),
            )
        conn.commit()
    finally:
        conn.close()


def query_simulation(sim_id: str, db_path: Path | None = None) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM simulations WHERE id=?", (sim_id,)).fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


def query_breaks(sim_id: str, db_path: Path | None = None) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM breaks WHERE simulation_id=? ORDER BY created_at", (sim_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_path_coverage(sim_id: str, db_path: Path | None = None) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM path_coverage WHERE simulation_id=? ORDER BY position", (sim_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_sessions(sim_id: str, db_path: Path | None = None) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE simulation_id=? ORDER BY sequence", (sim_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_responses_for_surveys(simulation_id: str, survey_names: list[str], db_path: Path | None = None) -> list[dict]:
    if not survey_names:
        return []
    placeholders = ",".join("?" * len(survey_names))
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM responses WHERE simulation_id=? AND survey_name IN ({placeholders})",
            [simulation_id] + survey_names,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_prior_session_frames(
    simulation_id: str,
    survey_names: list[str],
    max_sessions: int = 5,
    db_path: Path | None = None,
) -> dict[str, dict[str, list]]:
    """Build cross-session frames from prior simulated responses.

    Returns {survey_name: {item_name: [values from prior sessions...]}}
    where each value is one session's latest answer for that item.
    """
    if not survey_names:
        return {}
    responses = query_responses_for_surveys(simulation_id, survey_names, db_path)
    if not responses:
        return {}

    from collections import defaultdict
    session_items: dict[str, dict[str, Any]] = defaultdict(dict)
    for r in responses:
        session_items[r["session_id"]][(r["survey_name"], r["item_name"])] = (
            json.loads(r["value_json"]) if r["value_json"] else None,
            bool(r["is_na"]),
        )

    sessions = list(session_items.keys())[:max_sessions]
    frames: dict[str, dict[str, list]] = {}
    for sname in survey_names:
        cols: dict[str, list] = {}
        for sid in sessions:
            for (sv, si), (val, is_na) in session_items[sid].items():
                if sv != sname:
                    continue
                cols.setdefault(si, []).append(None if is_na else val)
        if cols:
            frames[sname] = cols
    return frames


def list_simulations(run_name: str | None = None, db_path: Path | None = None) -> list[dict]:
    conn = _connect(db_path)
    try:
        if run_name:
            rows = conn.execute(
                "SELECT * FROM simulations WHERE run_name=? ORDER BY created_at DESC", (run_name,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM simulations ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()