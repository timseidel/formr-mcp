"""Per-item value domains and equivalence-class sampling for deterministic
run validation.

Every formr item type maps to a value domain. Rather than enumerating the full
domain (infeasible — V^N over items), we pick a small set of *representative*
samples per item: one per equivalence class plus boundary values pulled from the
comparisons that actually reference the item, and **always** an NA class
(not-yet-answered / skipped — the single most common cause of real breakage).

Value semantics mirror the formr server (confirmed from the SurveyItem class
hierarchy):
  - mc / mc_button            → the choice *code* (key), 0-based ints by default
  - rating_button             → 1..N integer scale
  - range / range_ticks       → integer scale from choices / type_options
  - mc_multiple               → comma-joined subset of codes
  - number                    → decimal, min/max/step from type_options
  - check / check_button      → 0 or 1
  - select_one / *_add_one    → the choice *name*
  - text-likes                → "", short, long strings
  - date/time-likes           → a valid representative string
  - computed (calculate/get/random/...) → numeric-generic (produced by R)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from formr_mcp.validation import CHOICES_REQUIRED

# Item types whose stored value is the numeric choice *code* (key/index).
_CODE_CHOICE_TYPES = {"mc", "mc_button", "rating_button", "range", "range_ticks"}
# Item types whose stored value is the choice *name* (label key as text).
_NAME_CHOICE_TYPES = {"select_one", "select_or_add_one"}
# Multi-select: comma- or json-joined codes/names.
_MULTI_CHOICE_TYPES = {"mc_multiple", "mc_multiple_button", "select_multiple", "select_or_add_multiple"}
# Items whose value is produced by R / the server, not entered — numeric-generic.
_COMPUTED_TYPES = {"calculate", "get", "random", "server", "browser", "ip", "referrer"}
# Free numeric input.
_NUMBER_TYPES = {"number", "year"}
# Free text input.
_TEXT_TYPES = {
    "text", "textarea", "email", "url", "tel", "cc", "letters", "color",
    "timezone", "request_phone", "request_cookie",
}
_DATE_TYPES = {
    "date", "datetime", "datetime-local", "time", "month", "week", "yearmonth",
}


@dataclass(frozen=True)
class RRaw:
    """A raw R expression that should be emitted verbatim (not quoted) — e.g. a
    POSIXct system column like Sys.time(), or as.POSIXct(NA)."""

    code: str


@dataclass(frozen=True)
class Sample:
    """One representative value for an item, tagged with its equivalence class."""

    value: object  # int | float | str | None (None == NA / missing)
    label: str
    is_na: bool = False


def to_r_literal(value: object) -> str:
    """Render a Python sample value as an R literal."""
    if isinstance(value, RRaw):
        return value.code
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    s = str(value)
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")
    return f'"{s}"'


# ── choice / constraint parsing ──────────────────────────────────────

def parse_choice_codes(item: dict) -> list:
    """Return the ordered choice codes (keys) for a choice-based item.

    Accepts `choices` as a dict {code: label} or a list. Numeric-looking codes
    are returned as ints so they compare against boundary constants.
    """
    choices = item.get("choices")
    codes: list = []
    if isinstance(choices, dict):
        codes = list(choices.keys())
    elif isinstance(choices, list):
        # A plain list of labels → 1-based codes (formr convention for list form).
        codes = list(range(1, len(choices) + 1))
    out: list = []
    for c in codes:
        if isinstance(c, str) and re.fullmatch(r"-?\d+", c):
            out.append(int(c))
        else:
            out.append(c)
    return out


def parse_choice_names(item: dict) -> list[str]:
    """Return choice *names* (labels/keys as strings) for name-stored items."""
    choices = item.get("choices")
    if isinstance(choices, dict):
        return [str(k) for k in choices.keys()]
    if isinstance(choices, list):
        return [str(c) for c in choices]
    return []


def parse_number_constraints(item: dict) -> tuple[float | None, float | None]:
    """Extract (min, max) from an item's type_options (string or dict), if any."""
    opts = item.get("type_options")
    lo = hi = None
    if isinstance(opts, dict):
        lo = _as_num(opts.get("min"))
        hi = _as_num(opts.get("max"))
    elif isinstance(opts, str):
        # Formats seen: "0,100", "0,100,1" (min,max,step) or "min=0;max=100".
        m = re.findall(r"-?\d+(?:\.\d+)?", opts)
        if "min" in opts or "max" in opts:
            mlo = re.search(r"min\s*[=:]\s*(-?\d+(?:\.\d+)?)", opts)
            mhi = re.search(r"max\s*[=:]\s*(-?\d+(?:\.\d+)?)", opts)
            lo = float(mlo.group(1)) if mlo else None
            hi = float(mhi.group(1)) if mhi else None
        elif len(m) >= 2:
            lo, hi = float(m[0]), float(m[1])
    return lo, hi


def _as_num(v: object) -> float | None:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _num(v: object) -> int | float:
    """Coerce a float to int when it is integral (cleaner R literals/labels)."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


# ── domain construction ──────────────────────────────────────────────

_NA = Sample(None, "NA (not answered)", is_na=True)


def item_domain(item: dict, boundary_constants: set[float] | None = None) -> list[Sample]:
    """Representative samples for an item, given comparison constants that
    reference it (for boundary-value injection)."""
    itype = item.get("type", "")
    optional = item.get("optional", 0)
    consts = boundary_constants or set()

    samples: list[Sample]
    if itype in _CODE_CHOICE_TYPES or (itype in CHOICES_REQUIRED and itype not in _NAME_CHOICE_TYPES and itype not in _MULTI_CHOICE_TYPES):
        samples = _code_choice_domain(item, consts)
    elif itype in _NAME_CHOICE_TYPES:
        samples = _name_choice_domain(item)
    elif itype in _MULTI_CHOICE_TYPES:
        samples = _multi_choice_domain(item)
    elif itype in ("check", "check_button"):
        samples = [Sample(0, "unchecked"), Sample(1, "checked")]
    elif itype in _NUMBER_TYPES:
        samples = _number_domain(item, consts)
    elif itype in _COMPUTED_TYPES:
        samples = _numeric_generic(consts)
    elif itype in _TEXT_TYPES:
        samples = [Sample("", "empty string"), Sample("x", "short text"), Sample("a longer answer", "long text")]
    elif itype in _DATE_TYPES:
        samples = [Sample(_date_example(itype), "valid date/time")]
    else:
        # Unknown / display-only — a single generic value is enough.
        samples = [Sample("value", "generic value")]

    # NA always matters: unanswered items, optional items, skipped branches.
    samples = samples + [_NA]
    # De-dup by (value, is_na) preserving order.
    seen: set = set()
    out: list[Sample] = []
    for s in samples:
        key = (s.is_na, s.value)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _code_choice_domain(item: dict, consts: set[float]) -> list[Sample]:
    codes = parse_choice_codes(item)
    if not codes:
        # rating_button/range with no explicit choices: derive scale from type_options.
        lo, hi = parse_number_constraints(item)
        lo = int(lo) if lo is not None else 1
        hi = int(hi) if hi is not None else 5
        codes = list(range(lo, hi + 1))
    numeric = [c for c in codes if isinstance(c, (int, float))]
    picks: list = []
    if numeric:
        picks = [min(numeric), max(numeric)]
        # boundary constants that fall on/near a valid code
        for c in consts:
            cn = _num(c)
            if cn in numeric and cn not in picks:
                picks.append(cn)
    else:
        picks = codes[:2]
    samples = [Sample(_num(p), f"choice code {p}") for p in picks]
    if len(codes) <= 6:
        # small choice sets: include every code (cheap, exhaustive coverage)
        samples = [Sample(_num(c), f"choice code {c}") for c in codes]
    return samples


def _name_choice_domain(item: dict) -> list[Sample]:
    names = parse_choice_names(item)
    samples = [Sample(n, f"choice '{n}'") for n in names[:4]]
    if item.get("type") == "select_or_add_one":
        samples.append(Sample("custom typed answer", "added (other) value"))
    if not samples:
        samples = [Sample("value", "generic value")]
    return samples


def _multi_choice_domain(item: dict) -> list[Sample]:
    codes = parse_choice_codes(item) or parse_choice_names(item)
    samples = [Sample("", "none selected")]
    if codes:
        samples.append(Sample(str(codes[0]), "one selected"))
    if len(codes) >= 2:
        samples.append(Sample(f"{codes[0]},{codes[1]}", "several selected"))
    return samples


def _number_domain(item: dict, consts: set[float]) -> list[Sample]:
    lo, hi = parse_number_constraints(item)
    picks: list = []
    if lo is not None:
        picks += [lo, lo - 1]  # at and below min (below = invalid input → break risk)
    if hi is not None:
        picks += [hi, hi + 1]
    if lo is None and hi is None:
        picks += [-1, 0, 1, 100]
    # boundary constants from comparisons: c-1, c, c+1
    for c in consts:
        picks += [c - 1, c, c + 1]
    if not picks:
        picks = [0, 1]
    return [Sample(_num(p), f"number {(_num(p))}") for p in dict.fromkeys(picks)]


def _numeric_generic(consts: set[float]) -> list[Sample]:
    picks = [0, 1, -1]
    for c in consts:
        picks += [c - 1, c, c + 1]
    return [Sample(_num(p), f"value {_num(p)}") for p in dict.fromkeys(picks)]


def _date_example(itype: str) -> str:
    return {
        "time": "12:00",
        "month": "2025-06",
        "yearmonth": "2025-06",
        "week": "2025-W25",
        "datetime": "2025-06-20 12:00:00",
        "datetime-local": "2025-06-20T12:00",
    }.get(itype, "2025-06-20")


# ── boundary-constant extraction ─────────────────────────────────────

# Matches numeric literals adjacent to a comparison operator, e.g. `>= 18`, `x==5`.
_CMP_CONST_RE = re.compile(r"(?:[<>]=?|==|!=)\s*(-?\d+(?:\.\d+)?)|(-?\d+(?:\.\d+)?)\s*(?:[<>]=?|==|!=)")


def comparison_constants(expr: str) -> set[float]:
    """Numeric constants used in comparisons within an R expression."""
    out: set[float] = set()
    for m in _CMP_CONST_RE.finditer(expr):
        token = m.group(1) or m.group(2)
        if token is not None:
            try:
                out.add(float(token))
            except ValueError:
                pass
    return out
