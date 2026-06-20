import json
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server as server_mod
from formr_mcp import utils
from formr_mcp.coverage import deep_analyze
from formr_mcp.r_harness import r_available
from formr_mcp.visualize import render_html, render_mermaid

R = pytest.mark.skipif(not r_available(), reason="R/Rscript not installed")


def _survey(name, pos, items):
    return {"type": "Survey", "position": pos,
            "survey_data": {"name": name, "items": items, "settings": {}}}


def _branch(cond, if_true, pos, utype="SkipForward"):
    return {"type": utype, "position": pos, "condition": cond, "if_true": if_true}


_STRUCT = {"name": "viz", "units": [
    _survey("q", 10, [
        {"type": "number", "name": "age", "type_options": "0,120"},
        {"type": "calculate", "name": "risk", "value": "120 / age"},
    ]),
    _branch("tail(q$age, 1) >= 18", 30, 20),
    {"type": "Endpage", "position": 30},
]}


# ── trace ────────────────────────────────────────────────────────────

@R
def test_trace_populated():
    res = deep_analyze(_STRUCT)
    assert res.trace, "trace should not be empty"
    rec = res.trace[0]
    for key in ("location", "kind", "expr", "inputs", "status", "value", "rclass"):
        assert key in rec
    assert ("q", "age") in res.domains


# ── mermaid ──────────────────────────────────────────────────────────

def test_render_mermaid_structure():
    res = deep_analyze(_STRUCT)
    mm = render_mermaid(_STRUCT, res)
    assert mm.startswith("flowchart TD")
    assert "p10" in mm and "p20" in mm and "p30" in mm
    assert "classDef" in mm
    assert "-. if_true .->" in mm  # branch jump edge


def test_render_mermaid_loop_edge():
    s = {"name": "t", "units": [
        _survey("q", 10, [{"type": "number", "name": "x"}]),
        _branch("TRUE", 10, 20, utype="SkipBackward"),
    ]}
    mm = render_mermaid(s, deep_analyze(s))
    assert "-. loop .->" in mm


# ── html ─────────────────────────────────────────────────────────────

@R
def test_render_html_sections_and_break():
    res = deep_analyze(_STRUCT)
    htm = render_html(_STRUCT, res, "viz")
    for section in ("Flow", "Item Map", "Expression Traces", "Branch Decisions"):
        assert section in htm
    assert "mermaid" in htm
    # The risk=120/age value breaks on age=0 (Inf is ok) / age=NA (NA) → break shown.
    assert "always-invalid" in htm or "s-break" in htm
    # dynamic classification surfaced
    assert "dynamic" in htm


def test_render_html_handles_r_absent(monkeypatch):
    monkeypatch.setattr("formr_mcp.coverage.r_available", lambda: False)
    res = deep_analyze(_STRUCT)
    htm = render_html(_STRUCT, res, "viz")
    assert "R not installed" in htm
    assert "Item Map" in htm  # static sections still render


# ── tool ─────────────────────────────────────────────────────────────

def test_visualize_analysis_writes_and_opens(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "WORKSPACE_DIR", tmp_path)
    opened = {}
    monkeypatch.setattr(server_mod.webbrowser, "open", lambda url: opened.setdefault("url", url))
    (tmp_path / "viz.json").write_text(json.dumps(_STRUCT))

    out = server_mod.visualize_analysis("viz", ctx=MagicMock())

    html_path = tmp_path / "viz.analysis.html"
    assert html_path.exists()
    assert str(html_path) in out
    assert opened["url"].startswith("file://")
    assert "<html>" in html_path.read_text()
