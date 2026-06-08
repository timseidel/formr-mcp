"""Tests for editing.py — add_run_unit, remove_run_unit, duplicate_run_units,
shift_run_positions, generate_survey_items."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from formr_mcp.editing import (
    add_run_unit,
    duplicate_run_units,
    generate_survey_items,
    remove_run_unit,
    shift_run_positions,
    WORKSPACE_DIR,
)


@pytest.fixture
def run_file(tmp_path, monkeypatch):
    """Create a temporary .formr/ directory and a test run file."""
    workspace = tmp_path / ".formr"
    workspace.mkdir()
    monkeypatch.setattr("formr_mcp.editing.WORKSPACE_DIR", workspace)
    return workspace


def _write_run(workspace, units, name="test-run"):
    """Write a run structure to the workspace."""
    structure = {"name": name, "units": units, "settings": {}, "files": []}
    path = workspace / f"{name}.json"
    with open(path, "w") as f:
        json.dump(structure, f, indent=2)
    return path


def _read_run(workspace, name="test-run"):
    """Read a run structure from the workspace."""
    path = workspace / f"{name}.json"
    with open(path) as f:
        return json.load(f)


class TestAddRunUnit:
    def test_add_survey(self, run_file):
        _write_run(run_file, [])
        add_run_unit("test-run", "Survey", 10, description="baseline survey")
        structure = _read_run(run_file)
        assert len(structure["units"]) == 1
        assert structure["units"][0]["type"] == "Survey"
        assert structure["units"][0]["position"] == 10

    def test_add_skip_forward(self, run_file):
        _write_run(run_file, [])
        add_run_unit("test-run", "SkipForward", 20, description="eligibility check",
                     condition="screening$eligible==1", if_true=40)
        structure = _read_run(run_file)
        unit = structure["units"][0]
        assert unit["type"] == "SkipForward"
        assert unit["condition"] == "screening$eligible==1"
        assert unit["if_true"] == 40
        assert unit["automatically_jump"] == 1  # default for SkipForward

    def test_add_email(self, run_file):
        _write_run(run_file, [])
        add_run_unit("test-run", "Email", 30, description="welcome email",
                     subject="Welcome!", body="Hello {{login_link}}", account_id=1,
                     cron_only=1)
        structure = _read_run(run_file)
        unit = structure["units"][0]
        assert unit["type"] == "Email"
        assert unit["subject"] == "Welcome!"
        assert unit["account_id"] == 1
        assert unit["cron_only"] == 1

    def test_add_endpage(self, run_file):
        _write_run(run_file, [])
        add_run_unit("test-run", "Endpage", 50, body="Thank you!")
        structure = _read_run(run_file)
        unit = structure["units"][0]
        assert unit["type"] == "Endpage"
        assert unit["body"] == "Thank you!"

    def test_shift_mode(self, run_file):
        _write_run(run_file, [
            {"type": "Survey", "position": 10, "description": "first"},
        ])
        add_run_unit("test-run", "Survey", 10, description="inserted", insert_mode="shift")
        structure = _read_run(run_file)
        assert len(structure["units"]) == 2
        positions = sorted(u["position"] for u in structure["units"])
        assert positions == [10, 20]  # original 10 shifted to 20

    def test_overwrite_mode(self, run_file):
        _write_run(run_file, [
            {"type": "Survey", "position": 10, "description": "original"},
        ])
        add_run_unit("test-run", "Survey", 10, description="replacement", insert_mode="overwrite")
        structure = _read_run(run_file)
        assert len(structure["units"]) == 1
        assert structure["units"][0]["description"] == "replacement"

    def test_add_with_pause(self, run_file):
        _write_run(run_file, [])
        add_run_unit("test-run", "Pause", 20, description="wait until 9AM",
                     wait_minutes=600, relative_to="library(lubridate)\nhour(now()) >= 9",
                     body="Please wait")
        structure = _read_run(run_file)
        unit = structure["units"][0]
        assert unit["type"] == "Pause"
        assert unit["wait_minutes"] == 600

    def test_unknown_unit_type_raises(self, run_file):
        _write_run(run_file, [])
        with pytest.raises(ValueError, match="Unknown unit type"):
            add_run_unit("test-run", "InvalidType", 10)

    def test_missing_branch_condition_raises(self, run_file):
        _write_run(run_file, [])
        with pytest.raises(ValueError, match="condition"):
            add_run_unit("test-run", "SkipForward", 10, if_true=30)

    def test_invalid_run_name_raises(self, run_file):
        with pytest.raises(ValueError, match="Invalid run name"):
            add_run_unit("../../etc", "Survey", 10)

    def test_file_not_found_raises(self, run_file):
        with pytest.raises(FileNotFoundError, match="No local file"):
            add_run_unit("nonexistent-run", "Survey", 10)


class TestRemoveRunUnit:
    def test_remove_unit(self, run_file):
        _write_run(run_file, [
            {"type": "Survey", "position": 10, "description": "first"},
            {"type": "Endpage", "position": 20, "body": "end"},
        ])
        result = remove_run_unit("test-run", 20)
        assert "Removed Endpage" in result
        structure = _read_run(run_file)
        assert len(structure["units"]) == 1
        assert structure["units"][0]["position"] == 10

    def test_remove_with_compact(self, run_file):
        _write_run(run_file, [
            {"type": "Survey", "position": 10, "description": "first"},
            {"type": "Survey", "position": 20, "description": "second"},
            {"type": "Endpage", "position": 30, "body": "end"},
        ])
        remove_run_unit("test-run", 20, compact=True)
        structure = _read_run(run_file)
        assert len(structure["units"]) == 2
        positions = sorted(u["position"] for u in structure["units"])
        # 10 stays, 30 compacted to 29
        assert positions == [10, 29]

    def test_remove_nonexistent_position_raises(self, run_file):
        _write_run(run_file, [{"type": "Survey", "position": 10, "description": "first"}])
        with pytest.raises(ValueError, match="No unit found at position 99"):
            remove_run_unit("test-run", 99)


class TestDuplicateRunUnits:
    def test_duplicate_single_unit(self, run_file):
        _write_run(run_file, [
            {"type": "Survey", "position": 10, "description": "baseline"},
        ])
        result = duplicate_run_units("test-run", [10], 100)
        assert "Duplicated 1 unit" in result
        structure = _read_run(run_file)
        assert len(structure["units"]) == 2
        assert structure["units"][1]["position"] == 100
        assert "copy" in structure["units"][1]["description"]

    def test_duplicate_multiple_units(self, run_file):
        _write_run(run_file, [
            {"type": "Pause", "position": 30, "description": "wait", "wait_minutes": 90},
            {"type": "Email", "position": 40, "description": "reminder", "cron_only": 1},
            {"type": "Survey", "position": 45, "description": "esm"},
        ])
        duplicate_run_units("test-run", [30, 40, 45], 100)
        structure = _read_run(run_file)
        assert len(structure["units"]) == 6
        new_positions = sorted(u["position"] for u in structure["units"] if u["position"] >= 100)
        assert new_positions == [100, 110, 120]

    def test_shift_existing(self, run_file):
        _write_run(run_file, [
            {"type": "Survey", "position": 10, "description": "baseline"},
            {"type": "Endpage", "position": 100, "body": "end"},
        ])
        # Duplicate baseline at position 10, targeting pos 100
        # This should shift the Endpage at 100 up to make room
        duplicate_run_units("test-run", [10], 100, shift_existing=True)
        structure = _read_run(run_file)
        # Original at 10, copy at 100, original Endpage shifted up by 10
        positions = sorted(u["position"] for u in structure["units"])
        assert len(structure["units"]) == 3

    def test_no_shift_no_conflict_raises(self, run_file):
        _write_run(run_file, [
            {"type": "Survey", "position": 10, "description": "baseline"},
            {"type": "Endpage", "position": 20, "body": "end"},
        ])
        with pytest.raises(ValueError, match="already occupied"):
            duplicate_run_units("test-run", [10], 20, shift_existing=False)

    def test_empty_from_positions_raises(self, run_file):
        _write_run(run_file, [])
        with pytest.raises(ValueError, match="from_positions is empty"):
            duplicate_run_units("test-run", [], 100)

    def test_missing_source_position_raises(self, run_file):
        _write_run(run_file, [{"type": "Survey", "position": 10, "description": "s"}])
        with pytest.raises(ValueError, match="No unit found at position 99"):
            duplicate_run_units("test-run", [99], 100)


class TestShiftRunPositions:
    def test_shift_up(self, run_file):
        _write_run(run_file, [
            {"type": "Survey", "position": 10, "description": "first"},
            {"type": "Survey", "position": 20, "description": "second"},
            {"type": "Endpage", "position": 30, "body": "end"},
        ])
        result = shift_run_positions("test-run", 20, 10)
        assert "Shifted 2 unit(s)" in result
        structure = _read_run(run_file)
        positions = {u["position"] for u in structure["units"]}
        assert positions == {10, 30, 40}

    def test_shift_down(self, run_file):
        _write_run(run_file, [
            {"type": "Survey", "position": 10, "description": "first"},
            {"type": "Survey", "position": 20, "description": "second"},
            {"type": "Endpage", "position": 30, "body": "end"},
        ])
        result = shift_run_positions("test-run", 20, -5)
        assert "Shifted 2 unit(s)" in result
        structure = _read_run(run_file)
        positions = {u["position"] for u in structure["units"]}
        assert positions == {10, 15, 25}

    def test_zero_delta(self, run_file):
        _write_run(run_file, [{"type": "Survey", "position": 10, "description": "s"}])
        result = shift_run_positions("test-run", 10, 0)
        assert "No change" in result


class TestGenerateSurveyItems:
    def test_returns_json(self):
        result = generate_survey_items("Screening questionnaire")
        parsed = json.loads(result)
        assert "template" in parsed
        assert parsed["description"] == "Screening questionnaire"
        assert parsed["language"] == "en"

    def test_custom_language(self):
        result = generate_survey_items("BFI-15", language="de")
        parsed = json.loads(result)
        assert parsed["language"] == "de"