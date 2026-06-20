import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from formr_mcp import utils
from formr_mcp.analysis import (
    _check_flow_semantics,
    _check_item_quality,
    analyze_run,
)
from formr_mcp.coverage import deep_analyze
from formr_mcp.depgraph import api_targets, classify, referenced_items, build_survey_items, iter_expressions
from formr_mcp.r_harness import Case, CaseResult, categorize_error, classify as classify_result, evaluate, r_available
from formr_mcp.value_domains import comparison_constants, item_domain, parse_number_constraints

R = pytest.mark.skipif(not r_available(), reason="R/Rscript not installed")


def _survey(name, pos, items):
    return {"type": "Survey", "position": pos,
            "survey_data": {"name": name, "items": items, "settings": {}}}


def _branch(cond, if_true, pos, utype="SkipForward"):
    return {"type": utype, "position": pos, "condition": cond, "if_true": if_true}


# ── value_domains ─────────────────────────────────────────────────────

class TestValueDomains:
    def test_na_always_present(self):
        d = item_domain({"type": "number", "name": "x"})
        assert any(s.is_na for s in d)

    def test_number_boundary_injection(self):
        item = {"type": "number", "name": "age", "type_options": "0,120"}
        d = item_domain(item, comparison_constants("age >= 18"))
        vals = {s.value for s in d if not s.is_na}
        assert {17, 18, 19}.issubset(vals)  # boundary values around 18
        assert 0 in vals and 120 in vals    # min/max from type_options

    def test_mc_codes(self):
        item = {"type": "mc", "name": "consent", "choices": {"1": "yes", "0": "no"}}
        vals = {s.value for s in item_domain(item) if not s.is_na}
        assert vals == {0, 1}

    def test_number_constraints_parsing(self):
        assert parse_number_constraints({"type_options": "0,100"}) == (0.0, 100.0)
        assert parse_number_constraints({"type_options": "min=5;max=9"}) == (5.0, 9.0)

    def test_comparison_constants(self):
        assert comparison_constants("x >= 18 & y == 5") == {18.0, 5.0}


# ── classification ─────────────────────────────────────────────────────

class TestClassification:
    def test_static_vs_dynamic(self):
        structure = {"units": [
            _survey("s", 10, [
                {"type": "number", "name": "age"},
                {"type": "text", "name": "comment"},
                {"type": "calculate", "name": "score", "value": "age * 2"},
            ]),
            _branch("s$age >= 18", 30, 20),
        ]}
        cls = classify(structure)
        items = cls.items["s"]
        assert items["age"]["dynamic"] is True      # referenced by branch + value
        assert items["score"]["dynamic"] is True     # computed
        assert items["comment"]["dynamic"] is False   # untouched

    def test_bare_name_reference_in_value(self):
        structure = {"units": [_survey("s", 10, [
            {"type": "number", "name": "a"},
            {"type": "calculate", "name": "b", "value": "a + 1"},
        ])]}
        surveys = build_survey_items(structure)
        refs = [r for r in iter_expressions(structure) if r.item == "b"][0]
        assert ("s", "a") in referenced_items(refs, surveys)

    def test_api_targets(self):
        assert api_targets('formr_api_fetch_results(survey_name = "other")') == ["other"]


# ── deep analysis (requires R) ─────────────────────────────────────────

@R
class TestDeepAnalysis:
    def test_na_in_condition_breaks(self):
        structure = {"name": "t", "units": [
            _survey("s", 10, [{"type": "number", "name": "age", "type_options": "0,120"}]),
            _branch("tail(s$age,1) >= 18", 30, 20),
        ]}
        res = deep_analyze(structure)
        cond = [f for f in res.expr_findings if f.kind == "condition"][0]
        assert any("NA" in b["detail"] for b in cond.breaks)

    def test_dynamic_value_na_breaks(self):
        structure = {"name": "t", "units": [_survey("s", 10, [
            {"type": "number", "name": "h"},
            {"type": "number", "name": "w"},
            {"type": "calculate", "name": "bmi", "value": "h / w"},
        ])]}
        res = deep_analyze(structure)
        val = [f for f in res.expr_findings if f.kind == "value"][0]
        assert val.breaks  # NA/0 inputs produce NA

    def test_clean_run_passes(self):
        structure = {"name": "t", "units": [
            _survey("s", 10, [{"type": "mc", "name": "g", "choices": {"1": "a", "2": "b"}}]),
            _branch("tail(s$g,1) == 1", 30, 20),
        ]}
        res = deep_analyze(structure)
        # condition can be NA when g is NA → that is a real break formr would hit
        cond = [f for f in res.expr_findings if f.kind == "condition"][0]
        non_na_breaks = [b for b in cond.breaks if "NA" not in b["detail"]]
        assert non_na_breaks == []

    def test_dead_branch_detection(self):
        # Contradiction: no value of age can satisfy both, so the branch is dead.
        structure = {"name": "t", "units": [
            _survey("s", 10, [{"type": "number", "name": "age", "type_options": "0,120"}]),
            _branch("tail(s$age,1) < 0 & tail(s$age,1) > 200", 30, 20),
        ]}
        res = deep_analyze(structure)
        cov = res.branch_coverage[0]
        assert "NEVER true" in cov["verdict"]

    def test_loop_bound_flagged(self):
        structure = {"name": "t", "units": [
            _survey("s", 10, [{"type": "number", "name": "x"}]),
            _branch("TRUE", 10, 20, utype="SkipBackward"),
        ]}
        res = deep_analyze(structure)
        assert res.loop_findings and not res.loop_findings[0]["bounded"]

    def test_cross_survey_reference_no_false_break(self):
        # A label in survey B referencing survey A's item must resolve (both
        # frames built) — not error with "object not found".
        structure = {"name": "t", "units": [
            _survey("a", 10, [{"type": "mc", "name": "grp", "choices": {"1": "x", "2": "y"}}]),
            _survey("b", 20, [
                {"type": "note", "name": "n", "label": "You are `r tail(a$grp,1)`"},
            ]),
        ]}
        res = deep_analyze(structure)
        knitr = [f for f in res.expr_findings if f.kind == "knitr"][0]
        assert not any("not found" in b["detail"] for b in knitr.breaks)

    def test_loop_bound_with_counter_ok(self):
        structure = {"name": "t", "units": [
            _survey("s", 10, [{"type": "number", "name": "x"}]),
            _branch("nrow(s) < 5", 10, 20, utype="SkipBackward"),
        ]}
        res = deep_analyze(structure)
        assert res.loop_findings[0]["bounded"] is True


# ── P2: error categorization ────────────────────────────────────────────

class TestErrorCategorization:
    def test_undefined_function(self):
        cat, detail = categorize_error('could not find function "frobnicate"')
        assert cat == "undefined_function" and "frobnicate" in detail

    def test_undefined_object(self):
        cat, detail = categorize_error("object 'foo' not found")
        assert cat == "undefined_object" and "foo" in detail

    def test_runtime_error(self):
        cat, detail = categorize_error("!is.null(date) is not TRUE")
        assert cat == "runtime" and "runtime" in detail.lower()


# ── P1: built-in run objects modeled (no false 'not found') ──────────────

@R
class TestBuiltinObjects:
    def _no_notfound(self, structure):
        res = deep_analyze(structure)
        for f in res.expr_findings:
            for b in f.breaks:
                assert "not found" not in b["detail"], b

    def test_survey_unit_sessions_and_shuffle(self):
        self._no_notfound({"name": "t", "units": [
            _survey("s", 10, [{"type": "number", "name": "x"}]),
            _branch("tail(survey_unit_sessions$position, 1) >= 10 & shuffle$group == 1", 30, 20),
        ]})

    def test_survey_system_columns(self):
        self._no_notfound({"name": "t", "units": [
            _survey("s", 10, [{"type": "number", "name": "x"}]),
            _branch("as.numeric(Sys.time() - tail(s$created, 1)) >= 0", 30, 20),
        ]})

    def test_undefined_function_still_breaks(self):
        res = deep_analyze({"name": "t", "units": [_survey("s", 10, [
            {"type": "calculate", "name": "c", "value": "frobnicate(1)"},
        ])]})
        val = [f for f in res.expr_findings if f.kind == "value"][0]
        assert any("not defined" in b["detail"] for b in val.breaks)


# ── P3: static quality + flow-semantic checks ────────────────────────────

class TestStaticChecks:
    def test_number_without_range_warns(self):
        s = {"units": [_survey("q", 10, [{"type": "number", "name": "age"}])]}
        assert any("min/max" in f["message"] for f in _check_item_quality(s))

    def test_number_with_range_ok(self):
        s = {"units": [_survey("q", 10, [
            {"type": "number", "name": "age", "type_options": "0,120"}])]}
        assert _check_item_quality(s) == []

    def test_shuffle_in_loop_intentional_not_flagged(self):
        # Per-iteration randomization: downstream reads tail(shuffle$group,1) — OK.
        s = {"units": [
            _survey("q", 10, [{"type": "number", "name": "x"}]),
            {"type": "Shuffle", "position": 30, "groups": 2},
            _branch("tail(shuffle$group, 1) == 1", 1000, 35),
            _branch("TRUE", 10, 40, utype="SkipBackward"),
        ]}
        assert not any("Shuffle" in f["message"] for f in _check_flow_semantics(s))

    def test_shuffle_in_loop_contradiction_warns(self):
        # Re-shuffles each iteration but reads the FIRST assignment — real bug.
        s = {"units": [
            _survey("q", 10, [{"type": "number", "name": "x"}]),
            {"type": "Shuffle", "position": 30, "groups": 2},
            _branch("first(shuffle$group) == 1", 1000, 35),
            _branch("TRUE", 10, 40, utype="SkipBackward"),
        ]}
        assert any("Shuffle" in f["message"] and "FIRST" in f["message"]
                   for f in _check_flow_semantics(s))

    def test_exclusion_not_enforced_fires_on_keyword(self):
        s = {"units": [
            _survey("q", 10, [
                {"type": "number", "name": "age"},
                {"type": "note", "name": "note_Ausschluss",
                 "label": "ausgeschlossen", "showif": "age < 16"},
            ]),
            {"type": "Endpage", "position": 9990},
        ]}
        msgs = [f["message"] for f in _check_flow_semantics(s)]
        assert any("not routed out" in m for m in msgs)

    def test_conditional_content_does_not_fire(self):
        # A plain conditional note (scenario variant) must NOT be flagged.
        s = {"units": [_survey("q", 10, [
            {"type": "mc", "name": "cond", "choices": {"1": "a", "2": "b"}},
            {"type": "note", "name": "note_variant_a", "label": "Scenario A",
             "showif": "cond == 1"},
        ])]}
        assert _check_flow_semantics(s) == []


# ── P4: severity calibration ─────────────────────────────────────────────

@R
class TestSeverityCalibration:
    def test_same_survey_showif_na_is_info(self):
        res = deep_analyze({"name": "t", "units": [_survey("s", 10, [
            {"type": "mc", "name": "a", "choices": {"1": "y", "2": "n"}},
            {"type": "text", "name": "b", "showif": "a == 1"},
        ])]})
        showif = [f for f in res.expr_findings if f.kind == "showif"][0]
        assert showif.infos and not showif.warns  # demoted, not a warning

    def test_cross_survey_showif_na_is_warn(self):
        res = deep_analyze({"name": "t", "units": [
            _survey("a", 10, [{"type": "mc", "name": "grp", "choices": {"1": "y", "2": "n"}}]),
            _survey("b", 20, [{"type": "text", "name": "q", "showif": "a$grp == 1"}]),
        ]})
        showif = [f for f in res.expr_findings if f.kind == "showif"][0]
        assert any("showif returns NA" in w["detail"] for w in showif.warns)

    def test_runtime_dependent_branch_is_info_not_warn(self):
        # shuffle$group reachability can't be judged offline → must not warn.
        res = deep_analyze({"name": "t", "units": [
            _survey("s", 10, [{"type": "number", "name": "x"}]),
            {"type": "Shuffle", "position": 15, "groups": 2},
            _branch("tail(shuffle$group, 1) == 2", 30, 20),
            {"type": "Endpage", "position": 30},
        ]})
        cov = [b for b in res.branch_coverage if "20" in b["location"]][0]
        assert cov["verdict"].startswith("info") and "runtime state" in cov["verdict"]

    def test_loop_exit_branch_downgrades(self):
        res = deep_analyze({"name": "t", "units": [
            _survey("s", 10, [{"type": "number", "name": "x"}]),
            _branch("as.numeric(Sys.time()) > 0", 40, 15),  # date exit inside body
            {"type": "Survey", "position": 20, "survey_data": {"name": "s2", "items": [
                {"type": "number", "name": "y"}], "settings": {}}},
            _branch("TRUE", 10, 30, utype="SkipBackward"),
            {"type": "Endpage", "position": 40},
        ]})
        loop = res.loop_findings[0]
        assert loop["bounded"] is True and "exit Branch" in loop["detail"]


# ── cross-run resolution ────────────────────────────────────────────────

@R
class TestCrossRun:
    def test_resolves_local_run_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(utils, "WORKSPACE_DIR", tmp_path)
        other = {"name": "otherrun", "units": [_survey("otherrun", 10, [
            {"type": "mc", "name": "grp", "choices": {"1": "a", "2": "b"}},
        ])]}
        (tmp_path / "otherrun.json").write_text(json.dumps(other))
        structure = {"name": "t", "units": [
            _survey("s", 10, [{"type": "number", "name": "x"}]),
            _branch('nrow(formr_api_fetch_results(run_name = "otherrun")) > 0', 30, 20),
        ]}
        res = deep_analyze(structure)
        assert any("resolved" in c["status"] for c in res.cross_run)

    def test_flags_unobtainable_run(self, tmp_path, monkeypatch):
        monkeypatch.setattr(utils, "WORKSPACE_DIR", tmp_path)
        structure = {"name": "t", "units": [
            _survey("s", 10, [{"type": "number", "name": "x"}]),
            _branch('nrow(formr_api_fetch_results(run_name = "missingrun")) > 0', 30, 20),
        ]}
        res = deep_analyze(structure)
        assert any(c["status"].startswith("flagged") for c in res.cross_run)


# ── analyze_run integration ─────────────────────────────────────────────

class TestAnalyzeRunIntegration:
    def _write(self, tmp_path, monkeypatch, structure):
        monkeypatch.setattr(utils, "WORKSPACE_DIR", tmp_path)
        (tmp_path / f"{structure['name']}.json").write_text(json.dumps(structure))

    def test_non_deep_unchanged_clean(self, tmp_path, monkeypatch):
        structure = {"name": "clean", "units": [
            _survey("s", 10, [{"type": "text", "name": "comment"}]),
        ]}
        self._write(tmp_path, monkeypatch, structure)
        out = analyze_run("clean", deep=False)
        assert out == "✅ Run 'clean': no issues found (0 errors, 0 warnings)."

    @R
    def test_deep_reports_break(self, tmp_path, monkeypatch):
        structure = {"name": "broken", "units": [
            _survey("s", 10, [{"type": "number", "name": "age", "type_options": "0,120"}]),
            _branch("tail(s$age,1) >= 18", 30, 20),
        ]}
        self._write(tmp_path, monkeypatch, structure)
        out = analyze_run("broken", deep=True)
        assert "Deterministic Evaluation" in out
        assert "Item Map" in out
        assert "simulation break" in out

    def test_deep_without_r_degrades(self, tmp_path, monkeypatch):
        # Force the harness to report R as unavailable.
        monkeypatch.setattr("formr_mcp.coverage.r_available", lambda: False)
        structure = {"name": "nor", "units": [
            _survey("s", 10, [{"type": "number", "name": "age"}]),
            _branch("tail(s$age,1) >= 18", 30, 20),
        ]}
        self._write(tmp_path, monkeypatch, structure)
        out = analyze_run("nor", deep=True)
        # Still produces a report (item map) and does not crash.
        assert "Item Map" in out
