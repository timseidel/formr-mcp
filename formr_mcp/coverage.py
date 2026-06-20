"""Test-case generation and orchestration for deterministic run validation.

Ties the pieces together: classify items (depgraph), model their value domains
(value_domains), generate a bounded but representative set of input combinations,
evaluate them locally (r_harness), and summarize which expressions/branches are
safe and which break — and on what input.

Input-space control (full brute force is V^N — infeasible):
  - per expression, only the items that expression *reads* are varied
  - each item contributes its equivalence classes (incl. boundary values + NA)
  - the full cross-product is used when small; otherwise a bounded
    one-variable-at-a-time + all-NA strategy (single-variable breaks — the NA
    case especially — are always covered)
  - cross-run / aggregate frames (formr_api_*) vary a row-count partition {0,1,3}
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field

from formr_mcp.analysis import _extract_dollar_refs
from formr_mcp.depgraph import (
    DISPLAY_TYPES,
    Classification,
    ExprRef,
    api_targets,
    build_survey_items,
    classify,
    referenced_items,
)
from formr_mcp.r_harness import Case, classify as classify_result, evaluate, r_available
from formr_mcp.utils import load_structure
from formr_mcp.value_domains import RRaw, Sample, item_domain

# Date/count signals that indicate a loop's real exit lives in a date/count
# branch (the common ESM idiom: SkipBackward(TRUE) + an exit Branch on time/count).
_EXIT_SIGNAL_RE = re.compile(
    r"\bnext_day\b|\bSys\.time\b|\bSys\.Date\b|\bexpired\b|\bcreated\b|\bended\b|"
    r"\bnrow\b|\bdiff\w*\b|\bdays?\b|\bin_time_window\b|\bfinished\b|\bn\(\)|\bcount\b"
)
# A branch whose truth depends on randomization / time / cron / aggregate state
# cannot have its reachability determined offline (our stubs are fixed values),
# so dead-branch / always-true verdicts on these would be false positives.
_RUNTIME_DEP_RE = re.compile(
    r"\bshuffle\b|\bsurvey_unit_sessions\b|\bsurvey_run_sessions\b|\bsurvey_users\b|"
    r"\bexternals\b|\bSys\.time\b|\bSys\.Date\b|\bnext_day\b|\bin_time_window\b|"
    r"\btime_passed\b|\bexpired\b|\bended\b|\bformr_api\w*\b|\bformr_aggregate\b|"
    r"\.formr\b|\bcreated\b|\bmodified\b"
)

MAX_CASES_PER_EXPR = 60
ROW_COUNTS = [0, 1, 3]  # aggregate dimension for cross-run frames
_EVALUABLE = {"condition", "showif", "value", "relative_to", "knitr", "address"}
_LOOP_COUNTER_RE = re.compile(r"\bnrow\b|\bn\(\)|\blength\b|\biteration\b|\bsum\b|\bcount\b")


@dataclass
class ExprFinding:
    location: str
    kind: str
    expr: str
    cases: int = 0
    passed: int = 0
    breaks: list[dict] = field(default_factory=list)  # {detail, inputs}
    warns: list[dict] = field(default_factory=list)
    infos: list[dict] = field(default_factory=list)   # expected/benign (not counted)


@dataclass
class DeepResult:
    classification: Classification
    expr_findings: list[ExprFinding] = field(default_factory=list)
    branch_coverage: list[dict] = field(default_factory=list)
    loop_findings: list[dict] = field(default_factory=list)
    cross_run: list[dict] = field(default_factory=list)
    r_available: bool = True
    customr_error: str | None = None
    # Per-case trace for visualization/debugging: one record per evaluated case.
    trace: list[dict] = field(default_factory=list)
    # (survey, item) -> equivalence-class labels sampled for that dynamic item.
    domains: dict[tuple[str, str], list[str]] = field(default_factory=dict)


def _add_system_columns(cols: dict[str, list], n_rows: int) -> None:
    """Every formr survey results frame carries these system timestamp columns —
    add them so refs like `survey$created` resolve as POSIXct (not 'not found')."""
    now = [RRaw("Sys.time()")] * n_rows
    na_time = [RRaw('as.POSIXct(NA, origin="1970-01-01")')] * n_rows
    cols.setdefault("created", list(now))
    cols.setdefault("modified", list(now))
    cols.setdefault("ended", list(na_time))
    cols.setdefault("expired", list(na_time))


# ── cross-run resolution (JSON only, recursive, bounded) ─────────────

def _resolve_survey_items(
    name: str,
    local_surveys: dict[str, dict[str, dict]],
    cross_run: list[dict],
    depth: int = 0,
    seen: set | None = None,
) -> dict[str, dict] | None:
    """Find the item definitions for a survey/run name referenced by formr_api_*.

    Looks in the current run first, then other runs' JSON in the local workspace.
    Returns {item_name: item_dict} or None if unobtainable (→ flagged)."""
    seen = seen or set()
    if name in seen or depth > 10:
        return None
    seen.add(name)

    if name in local_surveys:
        cross_run.append({"target": name, "status": "resolved (same run survey)"})
        return local_surveys[name]
    try:
        other = load_structure(name)
    except (FileNotFoundError, ValueError):
        cross_run.append({"target": name, "status": "flagged — JSON not available locally"})
        return None
    other_surveys = build_survey_items(other)
    # Prefer a survey named like the run, else the first survey.
    items = other_surveys.get(name) or (next(iter(other_surveys.values()), None))
    if items is None:
        cross_run.append({"target": name, "status": "flagged — no surveys in referenced run"})
        return None
    cross_run.append({"target": name, "status": f"resolved (run '{name}' JSON)"})
    return items


def _synth_frame(items: dict[str, dict], n_rows: int) -> dict[str, list]:
    """Synthesize a data frame for a cross-run survey: one representative
    non-NA value per item, repeated n_rows times."""
    frame: dict[str, list] = {}
    for iname, item in items.items():
        if item.get("type") in DISPLAY_TYPES:
            continue
        frame[iname] = [_representative(item)] * n_rows
    _add_system_columns(frame, n_rows)
    return frame


def _representative(item: dict):
    for s in item_domain(item):
        if not s.is_na:
            return s.value
    return None


# ── input combination generation ─────────────────────────────────────

def _assignments(dims: list[tuple], cap: int):
    """Yield combinations over dims = [(key, [samples]), ...].

    Full cross-product when small; otherwise base + one-variable-at-a-time +
    all-NA (keeps single-variable breaks, esp. NA, always covered)."""
    sizes = [len(s) for _, s in dims]
    total = 1
    for n in sizes:
        total *= n
    if total <= cap:
        for combo in itertools.product(*[s for _, s in dims]):
            yield list(zip((k for k, _ in dims), combo))
        return

    def base_sample(samples):
        for s in samples:
            if not getattr(s, "is_na", False):
                return s
        return samples[0]

    base = {k: base_sample(s) for k, s in dims}
    yield list(base.items())
    for k, samples in dims:
        for s in samples:
            if s is base[k]:
                continue
            combo = dict(base)
            combo[k] = s
            yield list(combo.items())
    # all-NA combo to surface NA interactions
    na = {}
    for k, samples in dims:
        na[k] = next((s for s in samples if getattr(s, "is_na", False)), base[k])
    yield list(na.items())


# ── main entry ────────────────────────────────────────────────────────

def deep_analyze(structure: dict) -> DeepResult:
    cls = classify(structure)
    surveys = build_survey_items(structure)
    result = DeepResult(classification=cls, r_available=r_available())

    cases: list[Case] = []
    case_meta: dict[str, dict] = {}
    findings_by_loc: dict[str, ExprFinding] = {}

    for ei, ref in enumerate(cls.expressions):
        if ref.kind not in _EVALUABLE:
            continue
        finding = ExprFinding(location=ref.location, kind=ref.kind, expr=ref.expr)
        findings_by_loc[ref.location] = finding
        result.expr_findings.append(finding)

        # Items this expression reads, grouped by survey, each with its domain.
        refs = referenced_items(ref, surveys)
        dims: list[tuple] = []
        for (sname, iname) in sorted(refs):
            item = surveys[sname][iname]
            consts = cls.constants.get((sname, iname), set())
            domain = item_domain(item, consts)
            dims.append(((sname, iname), domain))
            result.domains.setdefault((sname, iname), [s.label for s in domain])

        # Every survey named in the expression needs a frame with ALL its
        # (non-display) items as columns — formr's getRunData builds a column per
        # item — so dollar refs to non-varied items and nrow()/aggregates resolve.
        ref_surveys = {s for (s, _) in refs}
        for s, _ in _extract_dollar_refs(ref.expr):
            if s in surveys:
                ref_surveys.add(s)
        if ref.survey and ref.survey in surveys:
            ref_surveys.add(ref.survey)

        # Cross-run frames (synthesized) + a row-count dimension if present.
        cross_items: dict[str, dict[str, dict]] = {}
        for target in api_targets(ref.expr):
            items = _resolve_survey_items(target, surveys, result.cross_run)
            if items is not None:
                cross_items[target] = items
        row_dim = [("__rows__", [Sample(n, f"{n} prior rows") for n in ROW_COUNTS])] if cross_items else []

        for ci, assignment in enumerate(_assignments(dims + row_dim, MAX_CASES_PER_EXPR)):
            assign_map = {k: s for k, s in assignment if k != "__rows__"}
            labels: list[str] = []
            inputs_struct: list[dict] = []
            n_rows = 1
            for key, sample in assignment:
                if key == "__rows__":
                    n_rows = sample.value
                    labels.append(sample.label)
                    inputs_struct.append({"name": "rows", "label": sample.label, "value": sample.value})
                else:
                    labels.append(f"{key[1]}={sample.label}")
                    inputs_struct.append({"name": key[1], "label": sample.label, "value": sample.value})
            # Build a 1-row frame per referenced survey: varied items take the
            # assigned sample, the rest take a representative value.
            frames: dict[str, dict[str, list]] = {}
            for s in ref_surveys:
                cols: dict[str, list] = {}
                for iname, item in surveys[s].items():
                    if item.get("type") in DISPLAY_TYPES:
                        continue
                    sample = assign_map.get((s, iname))
                    cols[iname] = [sample.value if sample else _representative(item)]
                _add_system_columns(cols, 1)
                frames[s] = cols
            for target, items in cross_items.items():
                frames[target] = _synth_frame(items, n_rows)

            cid = f"e{ei}c{ci}"
            current = ref.survey if ref.kind in ("showif", "value") or (ref.kind == "knitr" and ref.survey) else None
            cases.append(Case(cid, ref.expr, ref.kind, frames, current))
            case_meta[cid] = {
                "location": ref.location, "kind": ref.kind,
                "inputs": ", ".join(labels) or "(no dynamic inputs)",
                "inputs_struct": inputs_struct,
                "expr": ref.expr, "survey": ref.survey, "item": ref.item,
                "position": ref.position,
                # A same-survey showif on a not-yet-answered item is expected
                # (formr re-evaluates it client-side) → demote NA to info.
                "cross_survey": any(s != ref.survey for (s, _) in refs),
            }

    custom_r = (structure.get("settings") or {}).get("custom_r") or ""
    results = evaluate(cases, custom_r=custom_r) if r_available() else {}
    if "__customr_error__" in results:
        result.customr_error = results["__customr_error__"].error

    # Per-branch boolean outcomes for path coverage.
    branch_truth: dict[str, dict[str, bool]] = {}

    for cid, meta in case_meta.items():
        finding = findings_by_loc[meta["location"]]
        finding.cases += 1
        r = results.get(cid)
        if r is None:
            continue
        status, detail = classify_result(meta["kind"], r)
        entry = {"detail": detail, "inputs": meta["inputs"]}
        if status == "break":
            finding.breaks.append(entry)
        elif status == "warn":
            # Same-survey showif returning NA is expected (re-evaluated client-side).
            if meta["kind"] == "showif" and "showif returns NA" in detail and not meta["cross_survey"]:
                status = "info"
                finding.infos.append(entry)
            else:
                finding.warns.append(entry)
        else:
            finding.passed += 1

        result.trace.append({
            "location": meta["location"], "kind": meta["kind"], "expr": meta["expr"],
            "survey": meta["survey"], "item": meta["item"], "position": meta["position"],
            "inputs": meta["inputs_struct"], "status": status, "detail": detail,
            "ok": r.ok, "value": r.value, "rclass": r.rclass,
            "is_na": r.is_na, "length": r.length,
        })
        if meta["kind"] == "condition" and r.ok and "logical" in r.rclass and not r.is_na:
            truth = branch_truth.setdefault(meta["location"], {})
            val = r.value.split(";")[0]
            if val == "TRUE":
                truth["true"] = True
            elif val == "FALSE":
                truth["false"] = True

    _branch_and_loop_coverage(structure, branch_truth, result)
    return result


def _branch_and_loop_coverage(structure: dict, branch_truth: dict, result: DeepResult) -> None:
    for unit in structure.get("units", []):
        if not isinstance(unit, dict):
            continue
        utype = unit.get("type", "")
        if utype not in ("Branch", "SkipForward", "SkipBackward"):
            continue
        pos = unit.get("position", "?")
        loc = f"{utype} condition at position {pos}"
        truth = branch_truth.get(loc, {})
        took = truth.get("true", False)
        fell = truth.get("false", False)
        cond_text = unit.get("condition") or ""
        if utype == "SkipBackward":
            # Loop back-edge — an always-true condition is normal; termination is
            # assessed in the Loops section, so don't double-warn here.
            verdict = "info — loop back-edge (termination assessed under Loops)"
        elif _RUNTIME_DEP_RE.search(cond_text):
            verdict = ("info — reachability depends on runtime state "
                       "(randomization/time/cron/aggregate); not determinable offline")
        elif took and fell:
            verdict = "ok — both branches reachable"
        elif took and not fell:
            verdict = "warn — condition ALWAYS true under tested inputs; fall-through path may be dead"
        elif fell and not took:
            verdict = "warn — condition NEVER true under tested inputs; jump target may be unreachable"
        else:
            verdict = "info — no boolean outcome observed (R missing or aggregate/external logic)"
        result.branch_coverage.append({
            "location": loc, "if_true": unit.get("if_true"),
            "taken": took, "fallthrough": fell, "verdict": verdict,
        })

        if utype == "SkipBackward":
            cond = unit.get("condition") or ""
            bounded = bool(_LOOP_COUNTER_RE.search(cond))
            if bounded:
                detail = "loop bound references a counter (nrow/length/iteration/...) — verify it converges"
            elif _loop_has_exit_branch(structure, unit):
                bounded = True
                detail = ("condition is always-true, but the loop body contains a date/count "
                          "exit Branch (ESM idiom) — verify that exit can fire")
            else:
                detail = ("loop bound NOT statically determinable — ensure the condition can "
                          "become FALSE or an exit branch leaves the loop, or it may loop forever")
            result.loop_findings.append({"location": loc, "bounded": bounded, "detail": detail})


def _loop_has_exit_branch(structure: dict, skipback: dict) -> bool:
    """True if the loop body (positions between the SkipBackward's jump-back target
    and itself) contains a Branch/SkipForward whose condition tests time/count —
    i.e. the real termination lives in an exit branch, not the SkipBackward."""
    target = skipback.get("if_true")
    back_pos = skipback.get("position")
    if not isinstance(target, int) or not isinstance(back_pos, int):
        return False
    lo, hi = min(target, back_pos), max(target, back_pos)
    for u in structure.get("units", []):
        if not isinstance(u, dict) or u is skipback:
            continue
        if u.get("type") not in ("Branch", "SkipForward"):
            continue
        pos = u.get("position")
        if isinstance(pos, int) and lo <= pos <= hi and _EXIT_SIGNAL_RE.search(u.get("condition") or ""):
            return True
    return False


# ── report rendering ──────────────────────────────────────────────────

def render_report(result: DeepResult) -> tuple[list[str], int, int]:
    """Render the deep-analysis sections. Returns (lines, errors, warnings)."""
    lines: list[str] = []
    errors = warnings = 0

    # Item map
    lines.append("## Item Map (static vs dynamic)")
    if not result.classification.items:
        lines.append("  No survey items found.")
    for sname, items in result.classification.items.items():
        dyn = [n for n, m in items.items() if m["dynamic"]]
        stat = [n for n, m in items.items() if not m["dynamic"]]
        lines.append(f"  Survey '{sname}': {len(dyn)} dynamic, {len(stat)} static")
        for n in dyn:
            lines.append(f"    ● {n} — dynamic ({items[n]['reason']})")
        if stat:
            lines.append(f"    ○ static: {', '.join(stat)}")
    lines.append("")

    # Deterministic evaluation
    lines.append("## Deterministic Evaluation")
    if not result.r_available:
        lines.append("  ⚠ R not installed — expressions could not be simulated. "
                     "Install R to enable deterministic input testing.")
    elif not result.expr_findings:
        lines.append("  No dynamic expressions to evaluate.")
    else:
        if result.customr_error:
            warnings += 1
            lines.append(f"  ⚠ custom_r failed to load: {result.customr_error}")
            lines.append("     (functions/packages it defines were unavailable during simulation "
                         "— some findings below may be due to this)")
        total_cases = sum(f.cases for f in result.expr_findings)
        info_total = sum(len(f.infos) for f in result.expr_findings)
        lines.append(f"  Simulated {total_cases} input combination(s) across "
                     f"{len(result.expr_findings)} expression(s).")
        for f in result.expr_findings:
            if f.breaks:
                errors += 1
                lines.append(f"  ❌ {f.location}")
                lines.append(f"     [{f.kind}] {_truncate(f.expr)}")
                lines.append(f"     {f.passed}/{f.cases} inputs OK; {len(f.breaks)} breaking:")
                for b in _dedup(f.breaks)[:4]:
                    lines.append(f"       • {b['detail']}  ⟵  {b['inputs']}")
            elif f.warns:
                warnings += 1
                lines.append(f"  ⚠ {f.location}")
                lines.append(f"     [{f.kind}] {_truncate(f.expr)}")
                for w in _dedup(f.warns)[:3]:
                    lines.append(f"       • {w['detail']}  ⟵  {w['inputs']}")
        if not any(f.breaks or f.warns for f in result.expr_findings):
            lines.append("  ✅ All simulated inputs evaluated without breaking.")
        if info_total:
            lines.append(f"  ℹ {info_total} expected/benign note(s) suppressed "
                         f"(e.g. same-survey showif NA — formr re-evaluates these client-side).")
    lines.append("")

    # Branch-path coverage
    if result.branch_coverage:
        lines.append("## Branch-Path Coverage")
        for b in result.branch_coverage:
            icon = "✅" if b["verdict"].startswith("ok") else ("⚠" if b["verdict"].startswith("warn") else "ℹ")
            if b["verdict"].startswith("warn"):
                warnings += 1
            lines.append(f"  {icon} {b['location']} → if_true={b['if_true']}: {b['verdict']}")
        lines.append("")

    # Loops
    if result.loop_findings:
        lines.append("## Loops")
        for lf in result.loop_findings:
            icon = "✅" if lf["bounded"] else "⚠"
            if not lf["bounded"]:
                warnings += 1
            lines.append(f"  {icon} {lf['location']}: {lf['detail']}")
        lines.append("")

    # Cross-run references
    if result.cross_run:
        lines.append("## Cross-Run References")
        for c in _dedup_cross(result.cross_run):
            flagged = c["status"].startswith("flagged")
            if flagged:
                warnings += 1
            lines.append(f"  {'⚠' if flagged else '✅'} {c['target']}: {c['status']}")
        lines.append("")

    return lines, errors, warnings


def _truncate(s: str, n: int = 80) -> str:
    s = " ".join(s.split())
    return s[:n] + ("…" if len(s) > n else "")


def _dedup(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        key = (it["detail"], it["inputs"])
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def _dedup_cross(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        key = (it["target"], it["status"])
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out
