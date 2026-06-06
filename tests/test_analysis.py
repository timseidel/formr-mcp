import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from formr_mcp.analysis import (
    _check_branch_flow,
    _check_common_mistakes,
    _check_item_consistency,
    _check_variable_references,
    _extract_r_expressions,
    _validate_r_syntax,
    analyze_run,
)


def _make_structure(units: list[dict], name: str = "test") -> dict:
    return {"name": name, "units": units}


def _make_survey(name: str, pos: int, items: list[dict]) -> dict:
    return {
        "type": "Survey",
        "position": pos,
        "description": name,
        "special": "",
        "survey_data": {
            "name": name,
            "items": items,
            "settings": {},
        },
    }


def _make_branch(condition: str, if_true: int, pos: int) -> dict:
    return {
        "type": "SkipForward",
        "position": pos,
        "condition": condition,
        "if_true": if_true,
        "automatically_jump": 1,
        "automatically_go_on": 1,
    }


class TestExtractRExpressions:
    def test_extracts_condition(self):
        structure = _make_structure([
            _make_branch("age >= 18", 30, 10),
        ])
        exprs = _extract_r_expressions(structure)
        assert len(exprs) == 1
        assert exprs[0]["expr"] == "age >= 18"
        assert exprs[0]["type"] == "condition"

    def test_extracts_showif(self):
        items = [
            {"type": "number", "name": "age", "showif": "consent == 1"},
        ]
        structure = _make_structure([_make_survey("demo", 10, items)])
        exprs = _extract_r_expressions(structure)
        assert len(exprs) == 1
        assert exprs[0]["expr"] == "consent == 1"
        assert "showif" in exprs[0]["type"]

    def test_extracts_calculate_value(self):
        items = [
            {"type": "calculate", "name": "score", "value": "mean(c(a, b, c))"},
        ]
        structure = _make_structure([_make_survey("survey", 10, items)])
        exprs = _extract_r_expressions(structure)
        assert len(exprs) == 1
        assert exprs[0]["expr"] == "mean(c(a, b, c))"
        assert exprs[0]["type"] == "value"

    def test_skips_sticky_value(self):
        items = [
            {"type": "text", "name": "name", "value": "sticky"},
        ]
        structure = _make_structure([_make_survey("survey", 10, items)])
        exprs = _extract_r_expressions(structure)
        assert len(exprs) == 0

    def test_extracts_js_only_showif(self):
        items = [
            {"type": "number", "name": "x", "showif": "//js_only\nnr_friends >= 1"},
        ]
        structure = _make_structure([_make_survey("survey", 10, items)])
        exprs = _extract_r_expressions(structure)
        assert len(exprs) == 1
        assert "js_only" in exprs[0]["type"]

    def test_extracts_pause_relative_to(self):
        structure = _make_structure([
            {"type": "Pause", "position": 20, "relative_to": "time_passed(minutes = 5)"},
        ])
        exprs = _extract_r_expressions(structure)
        assert len(exprs) == 1
        assert exprs[0]["type"] == "relative_to"


class TestValidateRSyntax:
    def test_valid_expression(self):
        results = _validate_r_syntax(["age >= 18"])
        if not results:
            pytest.skip("R not available")
        assert results["age >= 18"] is None

    def test_invalid_expression(self):
        results = _validate_r_syntax(["age >="])
        if not results:
            pytest.skip("R not available")
        assert results["age >="] is not None

    def test_complex_valid_expression(self):
        expr = "if (isTRUE(testerledigen1 == 0 | testerledigen1 == 1)) { 1 } else { 0 }"
        results = _validate_r_syntax([expr])
        if not results:
            pytest.skip("R not available")
        assert results[expr] is None


class TestVariableReferences:
    def test_valid_reference(self):
        items = [
            {"type": "mc", "name": "consent", "choices": {"1": "Yes"}},
            {"type": "number", "name": "age", "showif": "demo$consent == 1"},
        ]
        structure = _make_structure([_make_survey("demo", 10, items)])
        findings = _check_variable_references(structure)
        assert len(findings) == 0

    def test_missing_survey(self):
        items = [
            {"type": "number", "name": "x", "showif": "nonexistent$var == 1"},
        ]
        structure = _make_structure([_make_survey("survey", 10, items)])
        findings = _check_variable_references(structure)
        assert len(findings) == 1
        assert findings[0]["severity"] == "error"
        assert "nonexistent" in findings[0]["message"]

    def test_missing_item_in_existing_survey(self):
        items = [
            {"type": "mc", "name": "consent", "choices": {"1": "Yes"}},
            {"type": "number", "name": "age", "showif": "survey$missing_var == 1"},
        ]
        structure = _make_structure([_make_survey("survey", 10, items)])
        findings = _check_variable_references(structure)
        assert len(findings) == 1
        assert findings[0]["severity"] == "error"
        assert "missing_var" in findings[0]["message"]

    def test_builtin_table_not_flagged(self):
        items = [
            {"type": "number", "name": "x", "showif": "nrow(survey_unit_sessions) > 0"},
        ]
        structure = _make_structure([_make_survey("survey", 10, items)])
        findings = _check_variable_references(structure)
        assert len(findings) == 0


class TestBranchFlow:
    def test_valid_branch(self):
        structure = _make_structure([
            _make_survey("survey", 10, []),
            _make_branch("age >= 18", 30, 20),
            {"type": "Endpage", "position": 30, "body": "end"},
        ])
        findings = _check_branch_flow(structure)
        assert len(findings) == 0

    def test_invalid_if_true(self):
        structure = _make_structure([
            _make_survey("survey", 10, []),
            _make_branch("age >= 18", 999, 20),
        ])
        findings = _check_branch_flow(structure)
        assert any(f["severity"] == "error" and "999" in f["message"] for f in findings)

    def test_first_unit_is_endpage(self):
        structure = _make_structure([
            {"type": "Endpage", "position": 10, "body": "end"},
        ])
        findings = _check_branch_flow(structure)
        assert any(f["severity"] == "error" and "first unit" in f["message"].lower() for f in findings)


class TestItemConsistency:
    def test_empty_calculate_value(self):
        items = [
            {"type": "calculate", "name": "score", "value": ""},
        ]
        structure = _make_structure([_make_survey("survey", 10, items)])
        findings = _check_item_consistency(structure)
        assert any("empty value" in f["message"] for f in findings)

    def test_valid_choice_list_reference(self):
        items = [
            {"type": "mc_heading", "name": "likert5", "choices": {"1": "SD", "5": "SA"}},
            {"type": "mc", "name": "item1", "choice_list": "likert5"},
        ]
        structure = _make_structure([_make_survey("survey", 10, items)])
        findings = _check_item_consistency(structure)
        missing_ref = [f for f in findings if "choice_list" in f["message"]]
        assert len(missing_ref) == 0

    def test_missing_choice_list_reference(self):
        items = [
            {"type": "mc", "name": "item1", "choice_list": "nonexistent"},
        ]
        structure = _make_structure([_make_survey("survey", 10, items)])
        findings = _check_item_consistency(structure)
        assert any("nonexistent" in f["message"] for f in findings)


class TestCommonMistakes:
    def test_assignment_in_condition(self):
        structure = _make_structure([
            _make_branch("age = 18", 30, 10),
        ])
        findings = _check_common_mistakes(structure)
        assert any("assignment" in f["message"].lower() or "=)" in f["message"] for f in findings)

    def test_equality_comparison_not_flagged(self):
        structure = _make_structure([
            _make_branch("age == 18", 30, 10),
        ])
        findings = _check_common_mistakes(structure)
        assert not any("assignment" in f["message"].lower() for f in findings)


class TestAnalyzeRun:
    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="No local file"):
            analyze_run("nonexistent-run-xyz")

    def test_invalid_name(self):
        with pytest.raises(ValueError, match="Invalid run name"):
            analyze_run("../../etc/passwd")