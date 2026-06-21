"""Tests for the simulation engine (formr_mcp.simulation) and DB (formr_mcp.simdb)."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from formr_mcp.simdb import (
    create_simulation,
    finish_simulation,
    init_db,
    insert_break,
    insert_evaluation,
    insert_response,
    insert_session,
    list_simulations,
    query_breaks,
    query_path_coverage,
    query_simulation,
    query_sessions,
    upsert_path_coverage,
)
from formr_mcp.simulation import (
    Agent,
    SimulationResult,
    _choose_item_values,
    _get_unit_at,
    _next_position,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_sim.db"


@pytest.fixture
def db(db_path):
    conn = init_db(db_path)
    conn.close()
    return db_path


def test_init_db_creates_tables(db):
    conn = init_db(db)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()]
    conn.close()
    assert "simulations" in tables
    assert "sessions" in tables
    assert "responses" in tables
    assert "evaluations" in tables
    assert "breaks" in tables
    assert "path_coverage" in tables


def test_create_and_query_simulation(db):
    sim_id = create_simulation("test-run", "explore", 50, db_path=db)
    sim = query_simulation(sim_id, db_path=db)
    assert sim is not None
    assert sim["run_name"] == "test-run"
    assert sim["strategy"] == "explore"
    assert sim["max_sessions"] == 50
    assert sim["status"] == "running"


def test_finish_simulation(db):
    sim_id = create_simulation("test-run", "explore", 50, db_path=db)
    finish_simulation(sim_id, 3, 1, 0, db_path=db)
    sim = query_simulation(sim_id, db_path=db)
    assert sim["status"] == "completed"
    assert sim["sessions_completed"] == 3
    assert sim["breaks_count"] == 1


def test_insert_and_query_session(db):
    sim_id = create_simulation("test-run", "explore", 10, db_path=db)
    insert_session(sim_id, "sess1", 0, [1, 5, 10], {5: "true"}, db_path=db)
    insert_session(sim_id, "sess2", 1, [1, 5, 20], {5: "false"}, db_path=db)
    sessions = query_sessions(sim_id, db_path=db)
    assert len(sessions) == 2
    assert json.loads(sessions[0]["path_json"]) == [1, 5, 10]
    assert json.loads(sessions[0]["branch_decisions_json"]) == {"5": "true"}


def test_insert_and_query_responses(db):
    sim_id = create_simulation("test-run", "explore", 10, db_path=db)
    insert_session(sim_id, "sess1", 0, [1], {}, db_path=db)
    insert_response(sim_id, "sess1", "survey1", "q1", 1, is_na=False, sample_label="choice code 1", db_path=db)
    insert_response(sim_id, "sess1", "survey1", "q2", None, is_na=True, sample_label="NA", db_path=db)
    from formr_mcp.simdb import query_responses_for_surveys
    responses = query_responses_for_surveys(sim_id, ["survey1"], db_path=db)
    assert len(responses) == 2


def test_insert_and_query_breaks(db):
    sim_id = create_simulation("test-run", "explore", 10, db_path=db)
    insert_break(sim_id, "Branch at position 5", "condition",
                 "condition returns NA", db_path=db)
    insert_break(sim_id, "Branch at position 10", "condition",
                 "condition returns NA", session_id="sess1", db_path=db)
    breaks = query_breaks(sim_id, db_path=db)
    assert len(breaks) == 2
    assert breaks[0]["location"] == "Branch at position 5"
    assert breaks[0]["kind"] == "condition"


def test_upsert_path_coverage(db):
    sim_id = create_simulation("test-run", "explore", 10, db_path=db)
    upsert_path_coverage(sim_id, 1, reached=True, branch_true=True, db_path=db)
    upsert_path_coverage(sim_id, 1, reached=True, branch_false=True, db_path=db)
    upsert_path_coverage(sim_id, 5, reached=True, db_path=db)
    cov = query_path_coverage(sim_id, db_path=db)
    assert len(cov) == 2
    pos1 = next(c for c in cov if c["position"] == 1)
    assert pos1["reached"] == 2
    assert pos1["branch_true"] == 1
    assert pos1["branch_false"] == 1


def test_list_simulations(db):
    create_simulation("run-a", "explore", 10, db_path=db)
    create_simulation("run-b", "explore", 20, db_path=db)
    create_simulation("run-a", "explore", 30, db_path=db)
    all_sims = list_simulations(db_path=db)
    assert len(all_sims) == 3
    a_sims = list_simulations(run_name="run-a", db_path=db)
    assert len(a_sims) == 2


def test_agent_defaults():
    agent = Agent(position=10)
    assert agent.position == 10
    assert agent.frames == {}
    assert agent.branch_decisions == {}
    assert agent.finished is False


def test_next_position():
    structure = {
        "units": [
            {"type": "Survey", "position": 10},
            {"type": "Branch", "position": 20},
            {"type": "Survey", "position": 30},
        ]
    }
    assert _next_position(structure, 10) == 20
    assert _next_position(structure, 20) == 30
    assert _next_position(structure, 30) is None
    assert _next_position(structure, 99) is None


def test_get_unit_at():
    structure = {
        "units": [
            {"type": "Survey", "position": 10, "survey_data": {"name": "s1"}},
            {"type": "Branch", "position": 20, "condition": "x==1", "if_true": 30},
        ]
    }
    unit = _get_unit_at(structure, 10)
    assert unit is not None
    assert unit["type"] == "Survey"
    assert _get_unit_at(structure, 99) is None


def test_simdb_init_idempotent(db):
    conn = init_db(db)
    conn.close()
    conn2 = init_db(db)
    conn2.close()
    sims = list_simulations(db_path=db)
    assert sims == []


def test_simulation_with_simple_structure(tmp_path, monkeypatch):
    workspace = tmp_path / ".formr"
    workspace.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("formr_mcp.utils.WORKSPACE_DIR", workspace)
    monkeypatch.setattr("formr_mcp.simdb.WORKSPACE_DIR", workspace)

    structure = {
        "name": "test-sim",
        "settings": {},
        "units": [
            {
                "type": "Survey",
                "position": 10,
                "survey_data": {
                    "name": "intro",
                    "items": [
                        {"name": "consent", "type": "mc", "choices": {"1": "Yes", "0": "No"}},
                    ],
                },
            },
            {
                "type": "SkipForward",
                "position": 20,
                "condition": "intro$consent == 0",
                "if_true": 40,
                "description": "skip if no consent",
            },
            {
                "type": "Survey",
                "position": 30,
                "survey_data": {
                    "name": "main",
                    "items": [
                        {"name": "age", "type": "number", "type_options": {"min": 18, "max": 99}},
                    ],
                },
            },
            {
                "type": "Endpage",
                "position": 40,
                "body": "Thank you!",
            },
            {
                "type": "Endpage",
                "position": 50,
                "body": "Goodbye!",
            },
        ],
    }
    (workspace / "test-sim.json").write_text(json.dumps(structure), encoding="utf-8")

    from formr_mcp import simdb as _simdb
    _simdb.init_db()

    from formr_mcp.simulation import simulate_run as _simulate_run

    with patch("formr_mcp.simulation._r_available", return_value=False):
        with patch("formr_mcp.analysis._r_available", return_value=False):
            result = _simulate_run("test-sim", max_sessions=5)

    assert result.sessions_completed > 0
    assert result.simulation_id