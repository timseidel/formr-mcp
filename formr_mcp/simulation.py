"""User-agent simulation engine for formr runs.

Walks through a run like an actual participant: accumulates state across surveys,
branches realistically, and stores results in SQLite. Complements the expression-level
deep analysis (coverage.py) by testing path-level reachability and inter-survey state
interactions that isolated evaluation cannot capture.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from formr_mcp import simdb
from formr_mcp.analysis import _r_available
from formr_mcp.coverage import _add_system_columns, _infer_loop_max, _DEFAULT_LOOP_MAX, _LOOP_COUNTER_RE, _find_loop_body
from formr_mcp.depgraph import (
    COMPUTED_TYPES,
    DISPLAY_TYPES,
    Classification,
    _knitr,
    build_survey_items,
    classify,
)
from formr_mcp.r_harness import Case, classify as classify_result, evaluate
from formr_mcp.utils import load_structure
from formr_mcp.value_domains import Sample, item_domain


@dataclass
class Agent:
    position: int
    frames: dict[str, dict[str, list]] = field(default_factory=dict)
    responses: list[dict] = field(default_factory=list)
    branch_decisions: dict[int, str] = field(default_factory=dict)
    loop_iterations: dict[int, int] = field(default_factory=dict)
    path: list[int] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    finished: bool = False


@dataclass
class SimulationResult:
    simulation_id: str
    sessions_completed: int = 0
    breaks: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    path_coverage: dict[int, dict] = field(default_factory=dict)
    r_available: bool = True


def _next_position(structure: dict, position: int) -> int | None:
    positions = sorted(
        u.get("position") for u in structure.get("units", [])
        if isinstance(u, dict) and isinstance(u.get("position"), int)
    )
    for p in positions:
        if p > position:
            return p
    return None


def _get_unit_at(structure: dict, position: int) -> dict | None:
    for unit in structure.get("units", []):
        if isinstance(unit, dict) and unit.get("position") == position:
            return unit
    return None


def _evaluate_condition(
    expr: str, agent: Agent, custom_r: str = "",
) -> tuple[str, str, str | None]:
    if not _r_available():
        return "info", "R not available", None
    cid = f"agent_{agent.session_id}_pos{agent.position}"
    case = Case(cid, expr, "condition", agent.frames, current_survey=None)
    results = evaluate([case], custom_r=custom_r)
    r = results.get(cid)
    if r is None:
        return "info", "evaluation returned no result", None
    status, detail = classify_result("condition", r)
    val = None
    if r.ok and "logical" in r.rclass and not r.is_na:
        val = r.value.split(";")[0]
    return status, detail, val


def _evaluate_expression(
    expr: str, kind: str, survey_name: str | None,
    agent: Agent, custom_r: str = "",
) -> tuple[str, str]:
    if not _r_available():
        return "info", "R not available"
    cid = f"agent_{agent.session_id}_expr"
    case = Case(cid, expr, kind, agent.frames, current_survey=survey_name)
    results = evaluate([case], custom_r=custom_r)
    r = results.get(cid)
    if r is None:
        return "info", "evaluation returned no result"
    return classify_result(kind, r)


def _choose_item_values(
    survey_name: str,
    items: dict[str, dict],
    cls: Classification,
) -> dict[str, tuple[object, str, bool]]:
    chosen: dict[str, tuple[object, str, bool]] = {}
    for iname, item in items.items():
        if item.get("type") in DISPLAY_TYPES or item.get("type") in COMPUTED_TYPES:
            continue
        domain = item_domain(item, cls.constants.get((survey_name, iname), set()))
        sample = domain[0]
        chosen[iname] = (sample.value, sample.label, sample.is_na)
    return chosen


def simulate_run(
    name: str,
    strategy: str = "explore",
    max_sessions: int = 50,
    loop_bounds: dict[int, int] | None = None,
) -> SimulationResult:
    structure = load_structure(name)
    surveys = build_survey_items(structure)
    cls = classify(structure)
    custom_r = (structure.get("settings") or {}).get("custom_r") or ""
    loop_bounds = loop_bounds or {}

    simdb.init_db()
    sim_id = simdb.create_simulation(name, strategy, max_sessions, loop_bounds)
    result = SimulationResult(simulation_id=sim_id, r_available=_r_available())

    positions = sorted(
        u.get("position") for u in structure.get("units", [])
        if isinstance(u, dict) and isinstance(u.get("position"), int)
    )
    if not positions:
        simdb.finish_simulation(sim_id, 0, 0, 0)
        return result

    queue: list[Agent] = [Agent(position=positions[0])]
    session_count = 0
    seen_states: set[tuple] = set()

    while queue and session_count < max_sessions:
        agent = queue.pop(0)
        if agent.finished:
            continue

        while not agent.finished and agent.position is not None and session_count < max_sessions:
            unit = _get_unit_at(structure, agent.position)
            if unit is None:
                agent.finished = True
                session_count += 1
                _finalize_session(agent, sim_id, session_count)
                break

            agent.path.append(agent.position)
            simdb.upsert_path_coverage(sim_id, agent.position, reached=True)

            utype = unit.get("type", "")

            if utype == "Survey":
                _step_survey(agent, unit, surveys, cls, custom_r, sim_id, result, structure)
            elif utype in ("Branch", "SkipForward"):
                fork = _step_branch(agent, unit, structure, surveys, cls, custom_r, sim_id, result, seen_states)
                if fork is not None:
                    queue.append(fork)
            elif utype == "SkipBackward":
                _step_skipbackward(agent, unit, structure, surveys, cls, custom_r, loop_bounds, sim_id, result)
            elif utype in ("Pause", "Wait"):
                _step_pause_wait(agent, unit, custom_r, sim_id, structure)
            elif utype in ("Page", "Endpage"):
                _step_endpage(agent, unit, custom_r, sim_id)
            elif utype == "External":
                agent.position = _next_position(structure, agent.position)
            elif utype == "Email":
                _step_email(agent, unit, custom_r, sim_id, structure)
            else:
                agent.position = _next_position(structure, agent.position)

            if agent.finished or agent.position is None:
                if not agent.finished:
                    agent.finished = True
                session_count += 1
                _finalize_session(agent, sim_id, session_count)
                break

    result.sessions_completed = session_count

    cov_rows = simdb.query_path_coverage(sim_id)
    for row in cov_rows:
        result.path_coverage[row["position"]] = {
            "reached": bool(row["reached"]),
            "branch_true": row["branch_true"],
            "branch_false": row["branch_false"],
            "branch_na": row["branch_na"],
        }

    result.breaks = simdb.query_breaks(sim_id)
    simdb.finish_simulation(sim_id, session_count, len(result.breaks), len(result.warnings))
    return result


def _step_survey(
    agent: Agent, unit: dict, surveys: dict, cls: Classification,
    custom_r: str, sim_id: str, result: SimulationResult, structure: dict,
) -> None:
    sd = unit.get("survey_data")
    if not isinstance(sd, dict):
        agent.position = _next_position(structure, agent.position)
        return
    sname = sd.get("name", "")
    if sname not in surveys:
        agent.position = _next_position(structure, agent.position)
        return

    items = surveys[sname]
    pos = unit.get("position", 0)
    chosen = _choose_item_values(sname, items, cls)

    for iname, (value, label, is_na) in chosen.items():
        item = items[iname]
        itype = item.get("type", "")

        if itype in DISPLAY_TYPES:
            continue

        showif = (item.get("showif") or "").strip()
        if showif.startswith("//js_only"):
            showif = showif[len("//js_only"):].strip()
        if showif:
            verdict, detail = _evaluate_expression(showif, "showif", sname, agent, custom_r)
            simdb.insert_evaluation(sim_id, agent.session_id, pos, "showif", showif, verdict, detail,
                                    survey_name=sname, item_name=iname)

        value_expr = (item.get("value") or "").strip()
        if value_expr and value_expr != "sticky" and itype in COMPUTED_TYPES:
            sv, sd_ = _evaluate_expression(value_expr, "value", sname, agent, custom_r)
            simdb.insert_evaluation(sim_id, agent.session_id, pos, "value", value_expr, sv, sd_,
                                    survey_name=sname, item_name=iname)

        if sname not in agent.frames:
            agent.frames[sname] = {}
        agent.frames[sname].setdefault(iname, []).append(None if is_na else value)

        simdb.insert_response(sim_id, agent.session_id, sname, iname, value,
                              is_na=is_na, sample_label=label)

    for sn, cols in agent.frames.items():
        n = max((len(v) for v in cols.values()), default=0)
        if n > 0 and "created" not in cols:
            _add_system_columns(cols, n)

    agent.position = _next_position(structure, agent.position)


def _step_branch(
    agent: Agent, unit: dict, structure: dict, surveys: dict,
    cls: Classification, custom_r: str, sim_id: str, result: SimulationResult,
    seen_states: set[tuple],
) -> Agent | None:
    """Process a Branch/SkipForward unit. Returns a forked Agent if both branches are reachable, else None."""
    cond = (unit.get("condition") or "").strip()
    if_true = unit.get("if_true")
    pos = unit.get("position", 0)

    if not cond:
        if isinstance(if_true, int):
            agent.position = if_true
        else:
            agent.position = _next_position(structure, agent.position)
        return None

    verdict, detail, raw_val = _evaluate_condition(cond, agent, custom_r)
    simdb.insert_evaluation(sim_id, agent.session_id, pos, "condition", cond, verdict, detail)

    took_branch = raw_val == "TRUE"
    fell_through = raw_val == "FALSE"

    if verdict == "break":
        result.breaks.append({"location": f"Branch at position {pos}", "detail": detail, "expression": cond})
        simdb.insert_break(sim_id, f"Branch at position {pos}", "condition", detail,
                          json_expr=cond, session_id=agent.session_id)
        fell_through = True

    simdb.upsert_path_coverage(sim_id, pos, branch_true=took_branch, branch_false=fell_through,
                                branch_na=(raw_val is None and verdict != "break"))
    agent.branch_decisions[pos] = "true" if took_branch else "false"

    next_fallthrough = _next_position(structure, agent.position)

    if took_branch and fell_through and isinstance(if_true, int):
        fork = Agent(
            position=next_fallthrough or pos,
            frames={sn: {k: list(v) for k, v in cols.items()} for sn, cols in agent.frames.items()},
            branch_decisions=dict(agent.branch_decisions),
            loop_iterations=dict(agent.loop_iterations),
            path=list(agent.path),
        )
        fork.branch_decisions[pos] = "false"
        state_key = (fork.position, frozenset(fork.branch_decisions.items()))
        if state_key not in seen_states:
            seen_states.add(state_key)
            return fork

    if took_branch and isinstance(if_true, int):
        agent.position = if_true
    else:
        agent.position = next_fallthrough

    return None


def _step_skipbackward(
    agent: Agent, unit: dict, structure: dict, surveys: dict,
    cls: Classification, custom_r: str, loop_bounds: dict[int, int],
    sim_id: str, result: SimulationResult,
) -> None:
    cond = (unit.get("condition") or "").strip()
    if_true = unit.get("if_true")
    pos = unit.get("position", 0)

    max_iter = loop_bounds.get(pos)
    if max_iter is None:
        _, body_surveys = _find_loop_body(structure, unit)
        if cond:
            max_iter = _infer_loop_max(cond, surveys, body_surveys)
        if max_iter is None:
            max_iter = 3 if (cond and _LOOP_COUNTER_RE.search(cond)) else _DEFAULT_LOOP_MAX

    current_iter = agent.loop_iterations.get(pos, 0)
    verdict, detail, raw_val = _evaluate_condition(cond, agent, custom_r)
    simdb.insert_evaluation(sim_id, agent.session_id, pos, "condition", cond, verdict, detail)

    took = raw_val == "TRUE"
    fell = raw_val == "FALSE"
    simdb.upsert_path_coverage(sim_id, pos, branch_true=took, branch_false=fell)

    if took and current_iter < max_iter:
        agent.loop_iterations[pos] = current_iter + 1
        agent.position = if_true if isinstance(if_true, int) else pos
    else:
        agent.position = _next_position(structure, agent.position)


def _step_pause_wait(
    agent: Agent, unit: dict, custom_r: str, sim_id: str, structure: dict,
) -> None:
    pos = unit.get("position", 0)
    rel = (unit.get("relative_to") or "").strip()
    if rel:
        verdict, detail = _evaluate_expression(rel, "relative_to", None, agent, custom_r)
        simdb.insert_evaluation(sim_id, agent.session_id, pos, "relative_to", rel, verdict, detail)

    body = unit.get("body")
    if isinstance(body, int):
        agent.position = body
    elif isinstance(body, str) and body.strip().isdigit():
        agent.position = int(body.strip())
    else:
        agent.position = _next_position(structure, agent.position)


def _step_endpage(
    agent: Agent, unit: dict, custom_r: str, sim_id: str,
) -> None:
    pos = unit.get("position", 0)
    body = (unit.get("body") or "").strip()
    if body:
        for ref in _knitr(body, f"Endpage body at position {pos}", pos):
            verdict, detail = _evaluate_expression(ref.expr, "knitr", ref.survey, agent, custom_r)
            simdb.insert_evaluation(sim_id, agent.session_id, pos, "knitr", ref.expr, verdict, detail)
    agent.finished = True


def _step_email(
    agent: Agent, unit: dict, custom_r: str, sim_id: str, structure: dict,
) -> None:
    pos = unit.get("position", 0)
    body = (unit.get("body") or "").strip()
    subject = (unit.get("subject") or "").strip()

    if body:
        for ref in _knitr(body, f"Email body at position {pos}", pos):
            verdict, detail = _evaluate_expression(ref.expr, "knitr", ref.survey, agent, custom_r)
            simdb.insert_evaluation(sim_id, agent.session_id, pos, "knitr", ref.expr, verdict, detail)

    from formr_mcp.depgraph import _INLINE_R_RE
    for m in _INLINE_R_RE.finditer(subject):
        verdict, detail = _evaluate_expression(m.group(1), "subject", None, agent, custom_r)
        simdb.insert_evaluation(sim_id, agent.session_id, pos, "subject", m.group(1), verdict, detail)

    agent.position = _next_position(structure, agent.position)


def _finalize_session(agent: Agent, sim_id: str, sequence: int) -> None:
    simdb.insert_session(
        sim_id, agent.session_id, sequence,
        agent.path, agent.branch_decisions,
        status="completed", loop_iterations=agent.loop_iterations,
    )


def render_simulation_report(result: SimulationResult) -> str:
    lines: list[str] = []
    lines.append(f"Simulation {result.simulation_id}")
    lines.append(f"  Strategy: explore (BFS)")
    lines.append(f"  Sessions completed: {result.sessions_completed}")
    lines.append(f"  R available: {result.r_available}")
    lines.append("")

    if result.breaks:
        lines.append("## Breaks Found")
        for b in result.breaks:
            lines.append(f"  ❌ {b['location']}: {b['detail']}")
        lines.append("")

    if result.warnings:
        lines.append("## Warnings")
        for w in result.warnings:
            lines.append(f"  ⚠ {w['location']}: {w['detail']}")
        lines.append("")

    if result.path_coverage:
        lines.append("## Path Coverage")
        for pos in sorted(result.path_coverage.keys()):
            cov = result.path_coverage[pos]
            status = "reached" if cov.get("reached") else "unreachable"
            bt = cov.get("branch_true", 0)
            bf = cov.get("branch_false", 0)
            lines.append(f"  Position {pos}: {status} (T={bt}, F={bf})")
        lines.append("")

    if not result.breaks and not result.warnings:
        lines.append("✅ No breaks or warnings found across all simulated paths.")

    return "\n".join(lines)