"""Faithful local R evaluation harness.

Replicates the R context formr builds when it evaluates a run's expressions
(confirmed from Functions.php::opencpu_define_vars / UnitSession::getRunData),
without OpenCPU or any network:

  - each survey is an `as.data.frame(list(item = c(...)))` column-vector frame
  - showif / value / label run inside `with(tail(survey, 1), ...)`
  - branch conditions / relative_to run against the full frame with `$` refs
  - `settings.custom_r` is injected; `.formr$*` and `formr_api_*` are stubbed
    (the latter return the synthesized cross-run frames, so calls resolve locally)

Failures are then classified against formr's real break rules (Survey.php /
Branch.php): runtime error, NA, length-0, or a non-boolean/non-timestamp where a
boolean/timestamp is required.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from formr_mcp.analysis import _r_available
from formr_mcp.value_domains import to_r_literal


@dataclass
class Case:
    id: str
    expr: str
    kind: str  # condition | relative_to | showif | value | knitr | subject | address
    # survey_name -> {item_name: [python sample values...]} (column vectors, equal length)
    frames: dict[str, dict[str, list]] = field(default_factory=dict)
    current_survey: str | None = None  # context for with(tail(.,1)) — showif/value/label


@dataclass
class CaseResult:
    ok: bool
    error: str | None = None
    is_na: bool = False
    length: int = 0
    rclass: str = ""
    value: str = ""


def r_available() -> bool:
    return _r_available()


# ── verdict classification ───────────────────────────────────────────

_FUNC_NOT_FOUND_RE = re.compile(r'could not find function ["\'](.+?)["\']')
_OBJ_NOT_FOUND_RE = re.compile(r"object ['\"](.+?)['\"] not found")


def categorize_error(msg: str) -> tuple[str, str]:
    """Classify an R error message into (category, detail).

    Categories: undefined_function, undefined_object, runtime."""
    if not msg:
        return "runtime", "R runtime error: unknown error"
    m = _FUNC_NOT_FOUND_RE.search(msg)
    if m:
        fn = m.group(1)
        return "undefined_function", (
            f"function '{fn}()' is not defined (not in formr, base R, or custom_r) — "
            f"define it in the run's custom_r or load the package that provides it"
        )
    m = _OBJ_NOT_FOUND_RE.search(msg)
    if m:
        return "undefined_object", (
            f"object '{m.group(1)}' not found — references an item/variable that does "
            f"not exist in this context"
        )
    return "runtime", f"R runtime error: {msg}"


def classify(kind: str, r: CaseResult) -> tuple[str, str]:
    """Return (status, detail) where status in {ok, break, warn}."""
    if not r.ok:
        _, detail = categorize_error(r.error or "")
        return "break", detail
    if kind in ("condition",):
        if r.length == 0:
            return "break", "condition returns length-0 (no value)"
        if r.is_na:
            return "break", "condition returns NA — run gets stuck / retried"
        if "logical" not in r.rclass and not _is_time(r.rclass):
            return "break", f"condition is '{r.rclass}', not TRUE/FALSE or a timestamp"
        if r.length > 1:
            return "warn", f"condition has length {r.length}; only the first element is used"
        return "ok", "boolean/timestamp"
    if kind == "relative_to":
        if r.length == 0 or r.is_na:
            return "break", "relative_to is NA/empty — wait time cannot be computed"
        if not (_is_time(r.rclass) or "numeric" in r.rclass or "integer" in r.rclass):
            return "break", f"relative_to is '{r.rclass}', not a timestamp"
        return "ok", "timestamp"
    if kind == "value":
        if r.length == 0:
            return "break", "dynamic value returns length-0 — item marked always-invalid"
        if r.is_na:
            return "break", "dynamic value returns NA — item marked always-invalid"
        return "ok", "value produced"
    if kind == "showif":
        if r.length == 0:
            return "break", "showif returns length-0 — item marked always-invalid"
        if r.is_na:
            return "warn", "showif returns NA — visibility falls back to client-side JS"
        return "ok", "visible/hidden decided"
    # knitr / subject / address: only a runtime error is a hard break (handled above).
    return "ok", "rendered"


def _is_time(rclass: str) -> bool:
    return any(t in rclass for t in ("POSIXct", "POSIXt", "Date", "difftime"))


# ── R script generation + execution ──────────────────────────────────

_PREAMBLE = r"""
suppressWarnings(suppressMessages(try(library(formr), silent=TRUE)))
options(warn=-1)
.formr <- list(nr_of_participants=10L, login_link="https://example.org/s/ABCD",
               login_code="ABCD", run_name="run", access_token="stub",
               last_action_date=Sys.time(), session_last_active=Sys.time())
# formr built-in run objects — present in every real run context, so model them
# here to avoid false "object not found" errors (mirrors UnitSession::getRunData).
.now <- Sys.time()
survey_unit_sessions <- data.frame(
  position = c(10L, 20L, 30L), unit_id = c(1L, 2L, 3L),
  type = c("Survey", "Pause", "Survey"),
  created = rep(.now, 3), modified = rep(.now, 3), ended = rep(.now, 3),
  expired = as.POSIXct(rep(NA_real_, 3), origin = "1970-01-01"),
  queued = as.POSIXct(rep(NA_real_, 3), origin = "1970-01-01"),
  stringsAsFactors = FALSE)
survey_run_sessions <- data.frame(created = .now, modified = .now,
  position = 30L, last_access = .now, stringsAsFactors = FALSE)
survey_users <- data.frame(created = .now, modified = .now, stringsAsFactors = FALSE)
externals <- data.frame(created = .now, modified = .now, stringsAsFactors = FALSE)
shuffle <- data.frame(group = 1L, unit = 1L, level = 1L, stringsAsFactors = FALSE)
"""

# Run custom_r so a missing package / broken line does not abort the whole script;
# a sentinel line lets the caller surface the problem.
_CUSTOM_R_WRAP = r"""
tryCatch({{
{custom_r}
}}, error = function(e) cat("__CUSTOMR_ERROR__|", gsub("[\r\n|]", " ", conditionMessage(e)), "\n", sep=""))
"""

_CASE_TEMPLATE = r"""
local({{
  id <- {id!r}
  out <- tryCatch({{
{frames}
    .frames <- list({frame_list})
    .api <- function(...) {{ a <- list(...); k <- a[["survey_name"]]; if (is.null(k)) k <- a[["run_name"]];
      if (!is.null(k) && k %in% names(.frames)) return(.frames[[k]]);
      if (length(.frames)) return(.frames[[1]]); data.frame() }}
    formr_api_authenticate <- function(...) invisible(TRUE)
    formr_api_fetch_results <- .api
    formr_api_results <- .api
    formr_api_session_results <- .api
    formr_aggregate <- .api
    v <- {eval_expr}
    list(ok=TRUE, isna=(length(v) > 0 && all(is.na(v))), len=length(v),
         cls=paste(class(v), collapse=","),
         val=paste(utils::head(as.character(v), 5L), collapse=";"))
  }}, error=function(e) list(ok=FALSE, msg=conditionMessage(e)))
  cat(jsonlite::toJSON(c(list(id=id), out), auto_unbox=TRUE, null="null"), "\n", sep="")
}})
"""


def _frame_code(name: str, columns: dict[str, list]) -> str:
    if not columns:
        return f"    `{name}` <- data.frame()"
    cols = ", ".join(
        f"`{item}` = c({', '.join(to_r_literal(v) for v in vals)})"
        for item, vals in columns.items()
    )
    return f"    `{name}` <- data.frame({cols}, stringsAsFactors=FALSE)"


def _build_case_block(case: Case) -> str:
    frames = "\n".join(_frame_code(n, cols) for n, cols in case.frames.items()) or "    # no frames"
    frame_list = ", ".join(f"`{n}` = `{n}`" for n in case.frames)
    # Collapse newlines before embedding: R's parse(text=...) treats \n as real
    # line breaks, so "}\nelse" on separate lines triggers "unexpected 'else'".
    _expr = re.sub(r"\s*\r?\n\s*", " ", case.expr)
    expr_lit = json.dumps(_expr)
    if case.current_survey:
        eval_expr = f"with(tail(`{case.current_survey}`, 1L), eval(parse(text={expr_lit})))"
    else:
        eval_expr = f"eval(parse(text={expr_lit}))"
    return _CASE_TEMPLATE.format(
        id=case.id, frames=frames, frame_list=frame_list, eval_expr=eval_expr
    )


def evaluate(cases: list[Case], custom_r: str = "", timeout: int = 90) -> dict[str, CaseResult]:
    """Evaluate cases in a single Rscript process. Empty dict if R is unavailable."""
    if not cases or not r_available():
        return {}

    script = [_PREAMBLE]
    if custom_r and custom_r.strip():
        script.append(_CUSTOM_R_WRAP.format(custom_r=custom_r))
    script += [_build_case_block(c) for c in cases]
    source = "\n".join(script)

    with tempfile.NamedTemporaryFile("w", suffix=".R", delete=False, encoding="utf-8") as fh:
        fh.write(source)
        script_path = fh.name
    try:
        proc = subprocess.run(
            ["Rscript", "--vanilla", script_path],
            capture_output=True, text=True, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    finally:
        Path(script_path).unlink(missing_ok=True)

    results: dict[str, CaseResult] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("__CUSTOMR_ERROR__|"):
            msg = line.split("|", 1)[1].strip()
            results["__customr_error__"] = CaseResult(ok=False, error=msg)
            continue
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        cid = str(d.get("id"))
        if d.get("ok"):
            results[cid] = CaseResult(
                ok=True, is_na=bool(d.get("isna")), length=int(d.get("len", 0)),
                rclass=str(d.get("cls", "")), value=str(d.get("val", "")),
            )
        else:
            results[cid] = CaseResult(ok=False, error=str(d.get("msg", "unknown error")))
    return results
