"""Dev-only visualization of the deep-analysis results.

Renders a self-contained HTML page (Mermaid flow diagram + full per-case detail
tables) that makes the deterministic validator's reasoning legible: item
static/dynamic classification + sampled domains, every input combination tested
per expression and its R result/status, per-branch TRUE/FALSE decisions, loops,
and cross-run synthesis. Fully local — no external service (unlike open_flowchart).
"""

from __future__ import annotations

import html
import re
from collections import OrderedDict

from formr_mcp.coverage import DeepResult
from formr_mcp.summarize import _strip_html, _truncate

_POS_RE = re.compile(r"position (\d+)")


def _esc(s: object) -> str:
    return html.escape(str(s if s is not None else ""))


def _mermaid_escape(s: str) -> str:
    """Make text safe inside a Mermaid `["..."]` node label."""
    s = _strip_html(str(s))
    s = re.sub(r'["\[\]{}()|;<>`]', " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _status_class(status: str) -> str:
    return {"break": "s-break", "warn": "s-warn", "info": "s-info", "ok": "s-ok"}.get(status, "")


# ── Mermaid flow diagram ─────────────────────────────────────────────

def render_mermaid(structure: dict, result: DeepResult) -> str:
    units = [u for u in structure.get("units", []) if isinstance(u, dict)
             and isinstance(u.get("position"), int)]
    units.sort(key=lambda u: u["position"])
    if not units:
        return "flowchart TD\n  empty[No positioned units]"

    verdict_by_pos: dict[int, str] = {}
    for b in result.branch_coverage:
        m = _POS_RE.search(b.get("location", ""))
        if m:
            verdict_by_pos[int(m.group(1))] = b.get("verdict", "")

    branch_types = {"Branch", "SkipForward", "SkipBackward"}
    lines = ["flowchart TD"]
    cls: dict[str, list[str]] = {"ok": [], "warn": [], "info": [], "plain": []}

    for u in units:
        pos = u["position"]
        nid = f"p{pos}"
        utype = u.get("type", "?")
        desc = _mermaid_escape(u.get("description") or (
            u.get("survey_data", {}).get("name", "") if utype == "Survey" else ""))
        label = f"{pos}: {utype}"
        if desc:
            label += f"<br/>{_truncate(desc, 40)}"
        lines.append(f'  {nid}["{label}"]')
        if utype in branch_types:
            v = verdict_by_pos.get(pos, "")
            cls["ok" if v.startswith("ok") else "warn" if v.startswith("warn") else "info"].append(nid)
        else:
            cls["plain"].append(nid)

    # Sequential flow edges (skip edges leaving a terminal Endpage).
    for a, b in zip(units, units[1:]):
        if a.get("type") == "Endpage":
            continue
        lines.append(f"  p{a['position']} --> p{b['position']}")

    # Branch jump edges (dashed; SkipBackward = loop).
    positions = {u["position"] for u in units}
    for u in units:
        if u.get("type") in branch_types and isinstance(u.get("if_true"), int) and u["if_true"] in positions:
            tag = "loop" if u["type"] == "SkipBackward" else "if_true"
            lines.append(f'  p{u["position"]} -. {tag} .-> p{u["if_true"]}')

    lines.append("  classDef ok fill:#d6f5d6,stroke:#2e7d32;")
    lines.append("  classDef warn fill:#ffe0b2,stroke:#e65100;")
    lines.append("  classDef info fill:#dceeff,stroke:#1565c0;")
    for name in ("ok", "warn", "info"):
        if cls[name]:
            lines.append(f"  class {','.join(cls[name])} {name};")
    return "\n".join(lines)


# ── HTML page ────────────────────────────────────────────────────────

_CSS = """
body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:24px;color:#1a1a1a;background:#fafafa}
h1{font-size:22px}h2{font-size:17px;margin-top:32px;border-bottom:2px solid #ddd;padding-bottom:4px}
h3{font-size:14px;margin:18px 0 6px;font-family:ui-monospace,monospace}
code,.expr{font-family:ui-monospace,SFMono-Regular,monospace;background:#eee;padding:1px 4px;border-radius:3px}
table{border-collapse:collapse;margin:6px 0 14px;font-size:13px;width:100%}
th,td{border:1px solid #ddd;padding:4px 8px;text-align:left;vertical-align:top}
th{background:#f0f0f0}
.s-break{background:#ffd9d9}.s-warn{background:#ffedcc}.s-info{background:#e2f0ff}.s-ok{background:#e6f7e6}
.badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:12px;font-weight:600}
.dynamic{color:#1565c0;font-weight:600}.static{color:#888}
.muted{color:#777}.pre{font-family:ui-monospace,monospace;white-space:pre-wrap}
.summary{background:#fff;border:1px solid #ddd;border-radius:6px;padding:10px 14px;display:inline-block}
.mermaid{background:#fff;border:1px solid #ddd;border-radius:6px;padding:12px}
.banner{background:#fff3cd;border:1px solid #ffe69c;padding:8px 12px;border-radius:6px;margin:8px 0}
"""

_MERMAID_JS = (
    '<script type="module">'
    "import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';"
    "mermaid.initialize({startOnLoad:true,securityLevel:'loose',maxTextSize:200000});"
    "</script>"
)

_ROW_CAP = 64


def render_html(structure: dict, result: DeepResult, run_name: str) -> str:
    p: list[str] = []
    p.append(f"<!doctype html><html><head><meta charset='utf-8'>"
             f"<title>Deep analysis · {_esc(run_name)}</title>"
             f"<style>{_CSS}</style>{_MERMAID_JS}</head><body>")
    p.append(f"<h1>Deep analysis · {_esc(run_name)}</h1>")

    n_break = sum(1 for f in result.expr_findings if f.breaks)
    n_warn = sum(1 for f in result.expr_findings if f.warns and not f.breaks)
    p.append(f"<div class='summary'>{len(result.trace)} cases simulated · "
             f"<b class='s-break'>&nbsp;{n_break} expr with breaks&nbsp;</b> · "
             f"{n_warn} with warnings · {len(result.classification.items)} surveys</div>")
    if not result.r_available:
        p.append("<div class='banner'>⚠ R not installed — expressions were not simulated. "
                 "Item map and structure still shown.</div>")
    if result.customr_error:
        p.append(f"<div class='banner'>⚠ custom_r failed to load: {_esc(result.customr_error)}</div>")

    # Flow diagram
    p.append("<h2>Flow</h2>")
    p.append(f"<pre class='mermaid'>{_esc(render_mermaid(structure, result))}</pre>")

    # Item map
    p.append("<h2>Item Map (static vs dynamic)</h2>")
    p.append("<table><tr><th>Survey</th><th>Item</th><th>Type</th><th>Class</th>"
             "<th>Reason</th><th>Sampled domain</th></tr>")
    for sname, items in result.classification.items.items():
        for iname, meta in items.items():
            dyn = meta["dynamic"]
            domain = result.domains.get((sname, iname), [])
            p.append(
                f"<tr><td>{_esc(sname)}</td><td>{_esc(iname)}</td><td>{_esc(meta['type'])}</td>"
                f"<td class='{'dynamic' if dyn else 'static'}'>{'dynamic' if dyn else 'static'}</td>"
                f"<td class='muted'>{_esc(meta['reason'] or '—')}</td>"
                f"<td class='muted'>{_esc(' · '.join(domain)) if domain else '—'}</td></tr>")
    p.append("</table>")

    # Group the trace by expression location, preserving order.
    by_loc: "OrderedDict[str, list[dict]]" = OrderedDict()
    for rec in result.trace:
        by_loc.setdefault(rec["location"], []).append(rec)

    # Expression traces
    p.append("<h2>Expression Traces</h2>")
    if not by_loc:
        p.append("<p class='muted'>No expressions simulated.</p>")
    for loc, recs in by_loc.items():
        kind = recs[0]["kind"]
        p.append(f"<h3>[{_esc(kind)}] {_esc(loc)}</h3>")
        p.append(f"<div class='expr'>{_esc(recs[0]['expr'])}</div>")
        var_names = list(OrderedDict(
            (i["name"], None) for r in recs for i in r["inputs"]).keys())
        head = "".join(f"<th>{_esc(v)}</th>" for v in var_names)
        p.append(f"<table><tr>{head}<th>Result</th><th>Status</th></tr>")
        for rec in recs[:_ROW_CAP]:
            inmap = {i["name"]: i["label"] for i in rec["inputs"]}
            cells = "".join(f"<td>{_esc(inmap.get(v, '·'))}</td>" for v in var_names)
            if rec["ok"]:
                res = f"{_esc(rec['value'] or '∅')} <span class='muted'>· {_esc(rec['rclass'])}" \
                      f"{' · NA' if rec['is_na'] else ''}{' · len0' if rec['length'] == 0 else ''}</span>"
            else:
                res = f"<span class='muted'>error</span>"
            p.append(f"<tr class='{_status_class(rec['status'])}'>{cells}<td>{res}</td>"
                     f"<td><b>{_esc(rec['status'])}</b> <span class='muted'>{_esc(rec['detail'])}</span></td></tr>")
        if len(recs) > _ROW_CAP:
            p.append(f"<tr><td colspan='{len(var_names)+2}' class='muted'>… +{len(recs)-_ROW_CAP} more cases</td></tr>")
        p.append("</table>")

    # Branch decisions
    branch_recs = [r for r in result.trace if r["kind"] == "condition"]
    if branch_recs:
        p.append("<h2>Branch Decisions</h2>")
        target_by_loc, verdict_by_loc = {}, {}
        for b in result.branch_coverage:
            target_by_loc[b["location"]] = b.get("if_true")
            verdict_by_loc[b["location"]] = b.get("verdict", "")
        bloc: "OrderedDict[str, list[dict]]" = OrderedDict()
        for r in branch_recs:
            bloc.setdefault(r["location"], []).append(r)
        for loc, recs in bloc.items():
            tgt = target_by_loc.get(loc)
            p.append(f"<h3>{_esc(loc)} → if_true={_esc(tgt)}</h3>")
            p.append(f"<div class='muted'>{_esc(verdict_by_loc.get(loc, ''))}</div>")
            var_names = list(OrderedDict(
                (i["name"], None) for r in recs for i in r["inputs"]).keys())
            head = "".join(f"<th>{_esc(v)}</th>" for v in var_names)
            p.append(f"<table><tr>{head}<th>Outcome</th><th>Goes to</th></tr>")
            for rec in recs[:_ROW_CAP]:
                inmap = {i["name"]: i["label"] for i in rec["inputs"]}
                cells = "".join(f"<td>{_esc(inmap.get(v, '·'))}</td>" for v in var_names)
                val = rec["value"].split(";")[0] if rec["ok"] else "error"
                goes = f"→ {_esc(tgt)}" if val == "TRUE" else ("(next)" if val == "FALSE" else "—")
                sclass = "s-ok" if val in ("TRUE", "FALSE") else _status_class(rec["status"])
                p.append(f"<tr class='{sclass}'>{cells}<td><b>{_esc(val)}</b></td><td>{goes}</td></tr>")
            p.append("</table>")

    # Loops
    if result.loop_findings:
        p.append("<h2>Loops</h2><table><tr><th>Loop</th><th>Bounded?</th>"
                 "<th>Max Iters</th><th>Terminates</th><th>Detail</th></tr>")
        for lf in result.loop_findings:
            max_iters = str(lf.get("max_iterations", "—")) if lf.get("max_iterations") is not None else "—"
            term = str(lf.get("terminates_at", "—")) if lf.get("terminates_at") is not None else "—"
            p.append(f"<tr class='{'s-ok' if lf['bounded'] else 's-warn'}'><td>{_esc(lf['location'])}</td>"
                     f"<td>{'yes' if lf['bounded'] else 'no'}</td>"
                     f"<td>{max_iters}</td><td>{term}</td>"
                     f"<td>{_esc(lf['detail'])}</td></tr>")
        p.append("</table>")

    # Cross-run
    if result.cross_run:
        seen = set()
        p.append("<h2>Cross-Run References</h2><table><tr><th>Target</th><th>Status</th></tr>")
        for c in result.cross_run:
            key = (c["target"], c["status"])
            if key in seen:
                continue
            seen.add(key)
            flagged = c["status"].startswith("flagged")
            p.append(f"<tr class='{'s-warn' if flagged else 's-ok'}'><td>{_esc(c['target'])}</td>"
                     f"<td>{_esc(c['status'])}</td></tr>")
        p.append("</table>")

    p.append("</body></html>")
    return "".join(p)
