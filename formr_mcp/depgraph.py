"""Dependency graph + static/dynamic item classification.

An item is **static** when nothing in the run reads or computes it — it is pure
data capture, so there is nothing to simulate. An item is **dynamic** when it is
referenced by R (a branch condition, another item's showif/value/label, a
page/email body) or is itself computed (calculate/get/random/value). Only dynamic
items need to be varied during deterministic evaluation, which collapses the
input space dramatically.

This module provides a *structured* expression walker (richer than
analysis._extract_r_expressions: it also reports the containing survey/item) and
the classification, including the comparison constants that reference each item
(for boundary-value sampling) and the cross-run targets of formr_api_* calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from formr_mcp.analysis import _INLINE_R_RE, _R_CHUNK_RE, _extract_dollar_refs
from formr_mcp.value_domains import comparison_constants

_IDENT_RE = re.compile(r"[A-Za-z.][A-Za-z0-9_.]*")
# formr_api_fetch_results(survey_name = "x") / run_name = "y" — capture the target.
_API_CALL_RE = re.compile(r"formr_api_\w+\s*\(([^)]*)\)")
_API_ARG_RE = re.compile(r"(?:survey_name|run_name|survey|run)\s*=\s*['\"]([^'\"]+)['\"]")

# Item types whose value is produced (computed), not entered by the participant.
COMPUTED_TYPES = {"calculate", "get", "random", "server", "browser", "ip", "referrer"}
# Display-only types that never hold a value.
DISPLAY_TYPES = {"note", "note_iframe", "block", "mc_heading", "submit", "blank",
                 "image", "audio", "video"}


@dataclass(frozen=True)
class ExprRef:
    expr: str
    kind: str            # condition | relative_to | address | showif | value | knitr | subject
    location: str
    position: object = None
    survey: str | None = None  # containing survey (for item-level exprs)
    item: str | None = None    # containing item


def iter_expressions(structure: dict) -> list[ExprRef]:
    """Walk the structure and yield every R expression with its structural context."""
    out: list[ExprRef] = []
    for unit in structure.get("units", []):
        if not isinstance(unit, dict):
            continue
        pos = unit.get("position", "?")
        utype = unit.get("type", "?")

        if utype in ("Branch", "SkipForward", "SkipBackward"):
            cond = (unit.get("condition") or "").strip()
            if cond:
                out.append(ExprRef(cond, "condition", f"{utype} condition at position {pos}", pos))
        elif utype in ("Pause", "Wait"):
            rel = (unit.get("relative_to") or "").strip()
            if rel:
                out.append(ExprRef(rel, "relative_to", f"{utype} relative_to at position {pos}", pos))
            out += _knitr(unit.get("body") or "", f"{utype} body at position {pos}", pos)
        elif utype == "External":
            addr = (unit.get("address") or "").strip()
            if addr and not addr.startswith("http"):
                out.append(ExprRef(addr, "address", f"External address at position {pos}", pos))
        elif utype in ("Page", "Endpage"):
            out += _knitr(unit.get("body") or "", f"{utype} body at position {pos}", pos)
        elif utype == "Email":
            out += _knitr(unit.get("body") or "", f"Email body at position {pos}", pos)
            for m in _INLINE_R_RE.finditer(unit.get("subject") or ""):
                out.append(ExprRef(m.group(1), "subject", f"Email subject at position {pos}", pos))
        elif utype == "Survey":
            out += _survey_exprs(unit, pos)
    return out


def _survey_exprs(unit: dict, pos) -> list[ExprRef]:
    sd = unit.get("survey_data")
    if not isinstance(sd, dict):
        return []
    sname = sd.get("name", "(unnamed)")
    out: list[ExprRef] = []
    for item in sd.get("items", []):
        if not isinstance(item, dict):
            continue
        iname = item.get("name", "(unnamed)")
        showif = (item.get("showif") or "").strip()
        if showif:
            if showif.startswith("//js_only"):
                showif = showif[len("//js_only"):].strip()
            if showif:
                out.append(ExprRef(showif, "showif",
                                   f"Item '{iname}' showif in survey '{sname}' (position {pos})",
                                   pos, sname, iname))
        value = (item.get("value") or "").strip()
        if value and value != "sticky":
            out.append(ExprRef(value, "value",
                               f"Item '{iname}' value in survey '{sname}' (position {pos})",
                               pos, sname, iname))
        for m in _INLINE_R_RE.finditer(item.get("label") or ""):
            out.append(ExprRef(m.group(1), "knitr",
                               f"Item '{iname}' label in survey '{sname}' (position {pos})",
                               pos, sname, iname))
    return out


def _knitr(text: str, location: str, pos) -> list[ExprRef]:
    out: list[ExprRef] = []
    for m in _INLINE_R_RE.finditer(text):
        out.append(ExprRef(m.group(1), "knitr", f"{location} (inline R)", pos))
    for m in _R_CHUNK_RE.finditer(text):
        out.append(ExprRef(m.group(1), "knitr", f"{location} (R chunk)", pos))
    return out


def build_survey_items(structure: dict) -> dict[str, dict[str, dict]]:
    """Ordered {survey_name: {item_name: item_dict}} for every Survey unit."""
    surveys: dict[str, dict[str, dict]] = {}
    for unit in structure.get("units", []):
        if not isinstance(unit, dict) or unit.get("type") != "Survey":
            continue
        sd = unit.get("survey_data")
        if not isinstance(sd, dict):
            continue
        sname = sd.get("name")
        if not sname:
            continue
        items: dict[str, dict] = {}
        for item in sd.get("items", []):
            if isinstance(item, dict) and item.get("name"):
                items[item["name"]] = item
        surveys[sname] = items
    return surveys


def referenced_items(ref: ExprRef, surveys: dict[str, dict[str, dict]]) -> set[tuple[str, str]]:
    """(survey, item) pairs an expression reads.

    Combines explicit `survey$item` dollar references (any expression) with
    bare-name references resolved against the *containing* survey's items — formr
    evaluates showif/value/label inside `with(tail(survey, 1), ...)`, so refs
    there are bare.
    """
    found: set[tuple[str, str]] = set()
    for sname, var in _extract_dollar_refs(ref.expr):
        if sname in surveys and var in surveys[sname]:
            found.add((sname, var))
    if ref.survey and ref.survey in surveys:
        own = surveys[ref.survey]
        for tok in _IDENT_RE.findall(ref.expr):
            if tok in own and tok != ref.item:
                found.add((ref.survey, tok))
    return found


def api_targets(expr: str) -> list[str]:
    """Survey/run names referenced via formr_api_* calls (cross-run targets)."""
    out: list[str] = []
    for call in _API_CALL_RE.finditer(expr):
        args = call.group(1)
        for m in _API_ARG_RE.finditer(args):
            out.append(m.group(1))
    return out


@dataclass
class Classification:
    # survey -> item -> {"type", "dynamic", "reason"}
    items: dict[str, dict[str, dict]] = field(default_factory=dict)
    # (survey, item) -> set of comparison constants referencing it
    constants: dict[tuple[str, str], set[float]] = field(default_factory=dict)
    expressions: list[ExprRef] = field(default_factory=list)

    def dynamic_items(self, survey: str) -> list[str]:
        return [n for n, meta in self.items.get(survey, {}).items() if meta["dynamic"]]


def classify(structure: dict) -> Classification:
    surveys = build_survey_items(structure)
    exprs = iter_expressions(structure)

    result = Classification(expressions=exprs)
    for sname, items in surveys.items():
        result.items[sname] = {}
        for iname, item in items.items():
            itype = item.get("type", "")
            computed = itype in COMPUTED_TYPES or bool(
                (item.get("value") or "").strip() and (item.get("value") or "").strip() != "sticky"
            )
            display = itype in DISPLAY_TYPES
            result.items[sname][iname] = {
                "type": itype,
                "dynamic": computed and not display,
                "reason": "computed value" if computed and not display else "",
            }

    # Mark items referenced by any expression as dynamic, and collect their constants.
    for ref in exprs:
        consts = comparison_constants(ref.expr)
        for (sname, iname) in referenced_items(ref, surveys):
            meta = result.items.get(sname, {}).get(iname)
            if meta is None:
                continue
            if not meta["dynamic"]:
                meta["dynamic"] = True
                meta["reason"] = "referenced by R"
            elif meta["reason"] == "computed value":
                meta["reason"] = "computed + referenced"
            if consts:
                result.constants.setdefault((sname, iname), set()).update(consts)
    return result
