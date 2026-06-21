# The Deep `analyze_run` Feature — Exhaustive Description

> Logical, Wittgenstein-strict description of the deep analyze feature as
> implemented in `formr_mcp/coverage.py` and its collaborator modules. Every
> statement below is grounded in a specific source-file locus; anything not
> stated here is *not* part of the feature.

---

## 1. Identity and Locus

1.1. The feature is a function invoked through one and only one MCP tool surface:
`analyze_run(name, deep=True, loop_bounds=None)`, defined at `server.py:369`
and dispatched to `formr_mcp/analysis.py:698`.

1.2. Its algorithmic substance lives in `formr_mcp/coverage.py`, function
`deep_analyze` (`coverage.py:483`), with collaborator modules: `depgraph.py`,
`value_domains.py`, `r_harness.py`, and visualization in `visualize.py`.

1.3. The feature is opt-in. When `deep=False` (default), `deep_analyze` is never
imported (`analysis.py:716–717` uses lazy import to avoid cycles).

1.4. The feature is non-destructive. The tool is annotated `readOnlyHint=True`
(`server.py:368`); `deep_analyze` neither writes to disk nor mutates the
structure dict; only `load_structure` reads `.formr/<name>.json`.

---

## 2. Termination / Feasibility Premise

2.1. Full input enumeration is infeasible: the input space is V^N over items.
The feature asks instead the weaker question *which inputs break the run*, and
answers it only over a bounded representative set (docstring at
`value_domains.py:1–22`; `coverage.py:8–15`).

2.2. Termination rests on three bounded subroutines plus a finite loop
simulation:

(a) Expression walk is bounded by the finite unit/item count.
(b) Domain construction is bounded per item by an equivalence-class count
(docstring at `value_domains.py:1–22`).
(c) Per-expression case count is bounded by `MAX_CASES_PER_EXPR = 60`
(`coverage.py:53`).
(d) Loop simulation is bounded by `max_iterations`, which itself is either
user-supplied via `loop_bounds`, inferred from the condition, defaulted to
`_DEFAULT_LOOP_MAX = 30` when a counter keyword is present, or held at zero
with a "may loop forever" verdict otherwise (`_DEFAULT_LOOP_MAX` at
`coverage.py:57`; `_infer_loop_max` at `coverage.py:153`).

---

## 3. The Expression Catalogue (Static, Determinate)

3.1. `iter_expressions` (`depgraph.py:46`) is the only entry to the corpus of
"R expressions in the run". It is purely structural: it emits one `ExprRef` per:

- `Branch` / `SkipForward` / `SkipBackward` `condition`;
- `Pause` / `Wait` `relative_to`;
- `Pause` / `Wait` / `External` / `Page` / `Endpage` / `Email` `body` knitr
  inline or chunk content;
- `External` `address` when non-http;
- `Email` `subject` inline-R;
- survey items' `showif` (post-`//js_only` strip), `value` (excluding literal
  `"sticky"`), and `label` knitr spans.

3.2. The catalogue is finite and acyclic over units; it does not follow
references across runs (those live in cross-run handling — §10).

---

## 4. Static/Dynamic Classification (Deterministic, No Execution)

4.1. `classify` (`depgraph.py:180`) partitions survey items into static and
dynamic by two independent sufficient conditions:

(a) Being computed — i.e., item type ∈ `COMPUTED_TYPES`
(calculate/get/random/server/browser/ip/referrer) OR having non-empty `value`
other than `"sticky"`.
(b) Being referenced by any R expression in §3.

4.2. `dynamic` is logical-or of (a) and (b), reduced to a single canonical
`reason`:

- "computed value" if (a) only;
- "referenced by R" if (b) only;
- "computed + referenced" if both.

4.3. The classification is a strict input/partition: an item is or is not
flagged by the classification, and the set of dynamic items equals the set of
items actually varied later. Nothing else is searched outside the run
structure.

4.4. Boundary constant collection is a strict projection of each R expression
onto numeric tokens adjacent to comparison operators (`_CMP_CONST_RE`,
`value_domains.py:283`); constants deduplicated into
`cls.constants[(survey, item)]`. Used only to inject `c-1, c, c+1` samples.

---

## 5. Per-Item Value Domains (Depend on Item Type Only)

5.1. `item_domain` (`value_domains.py:157`) is a pure function of
`(item_dict, boundary_constants)` with fixed dispatch:

| Item family | Samples produced |
|---|---|
| `_CODE_CHOICE_TYPES` (mc, mc_button, rating_button, range, range_ticks) and other `CHOICES_REQUIRED` | Choice codes; ≤6 codes ⇒ all codes; else min/max + intersecting boundary constants |
| `_NAME_CHOICE_TYPES` (select_one, select_or_add_one) | First 4 names; `select_or_add_one` adds one "added (other)" sample |
| `_MULTI_CHOICE_TYPES` (mc_multiple, select_multiple, …) | "" (none), one, comma-joined "several" |
| `check` / `check_button` | {0, 1} |
| `_NUMBER_TYPES` (number, year) | min, min-1, max, max+1, boundary c-1/c/c+1, fallback {−1, 0, 1, 100} |
| `_COMPUTED_TYPES` | {0, 1, −1} ∪ boundary c-1/c/c+1 |
| `_TEXT_TYPES` | "", "x", "a longer answer" |
| `_DATE_TYPES` | One valid per-type example date |
| Display-only / unknown | `Sample("value", "generic value")` |

5.2. NA is appended to every domain (`value_domains.py:186`). NA is the maximal
equivalence class — the stated most common real breakage source
(`value_domains.py:7–8`).

5.3. Becoming a sample is closed under dedup by `(is_na, value)` and is
order-preserving (`value_domains.py:188`).

---

## 6. Frame Construction (How an Input Combination Becomes R Data)

6.1. For each expression, `referenced_items` (`depgraph.py:138`) computes the
exact items the expression reads by:

(a) scanning `_extract_dollar_refs(expr)` (only `survey$item` pairs where both
halves exist in `surveys`); plus
(b) when `ref.survey` is set, scanning bare names via `_IDENT_RE.findall(expr)`
against the *containing* survey's items, excluding `ref.item` itself (it is
being defined, not read).

6.2. Every survey named either by a dollar ref or by being `ref.survey` becomes
a frame, even if no items in that survey are varied (`coverage.py:510–517`).
This mirrors formr's `getRunData` column-per-item semantics.

6.3. Frames are always 1-row for top-level case evaluation (`coverage.py:545–550`);
every non-display item gets either the varied sample or a representative one
(`_representative` at `coverage.py:436`), and `_add_system_columns` adds
`created`, `modified`, `ended`, `expired` (`coverage.py:87–99`).

6.4. `relative_to` Branch-path uses full frames with `$` semantics; `showif` /
`value` / `knitr` use `with(tail(survey, 1L), ...)` (`r_harness.py:206–208`);
raw `condition` / `address` / `knitr` evaluate bare (`r_harness.py:208`).

6.5. **The R context is causally minimal**. `_PREAMBLE` (`r_harness.py:126–154`)
pre-defines `current`, `first`, `last`, `finished`, `expired`, `shuffle`
(one-row frame), `survey_unit_sessions` (3 rows), `survey_run_sessions` /
`survey_users` / `externals` (1 row), and `.formr` / `.now`. These exist in
every real formr run; omitting them would yield false "object not found" breaks.

6.6. `settings.custom_r` is wrapped in `tryCatch` (`r_harness.py:158–162`) then
executed; failures are surfaced as a soft warning keyed `__customr_error__`,
never an exception (`coverage.py:569–572`).

---

## 7. Input-Combination Strategy (The Anti-Blow-Up)

7.1. `_assignments` (`coverage.py:445`) defines search policy:

(a) Compute the full cross-product count `T = ∏|domainᵢ|`.
(b) If `T ≤ MAX_CASES_PER_EXPR (60)` → yield the full Cartesian product.
(c) Otherwise: yield a base assignment (first non-NA sample of each); for each
variable, vary it across all its samples keeping others at base; finally
append one all-NA assignment.

7.2. The policy guarantees coverage of: every single-variable change
(especially NA per item — always reachable via all-NA or single-NA inside a
variable's own sample list). It does *not* guarantee intersection coverage
between two NA'd items.

7.3. Cross-run items add a synthetic dimension `__rows__ ∈ {0, 1, 3}`
(`ROW_COUNTS`, `coverage.py:54`), varying only the row count of synthesized
frames.

7.4. The case count per expression is therefore
`≤ max(∏|domain|, max_cases_per_expr, |domain| + 1)`.

---

## 8. Evaluation Harness (One Rscript Process)

8.1. `r_harness.evaluate` (`r_harness.py:214`) concatenates `_PREAMBLE`,
optional `custom_r`, and one `_build_case_block` per `Case`
(`r_harness.py:198–211`) into a single file; calls `Rscript --vanilla` once
with a 90-second timeout; returns a `{case_id: CaseResult}` map.

8.2. R returns JSON one line per case: `{id, ok, isna, len, cls, val}`; non-OK
uses `msg`. Ids are unique strings like `e{i}` indexed by enumeration position
(`coverage.py:555`).

8.3. If R is unavailable: `r_available()` returns False, `evaluate` returns
`{}`, and `DeepResult.r_available` mirrors this (`coverage.py:486`); the system
degrades non-fatally (test `test_deep_without_r_degrades`,
`tests/test_deep_validation.py:384`).

8.4. Newlines inside expressions are flattened before `parse(text=...)`
(`r_harness.py:202–204`) to avoid R's "unexpected 'else'" failure — concretely
exercised by `test_multiline_ifelse_no_parse_error`
(`tests/test_deep_validation.py:164`).

---

## 9. Verdict Classification (Per formr's Actual Break Rules)

9.1. `classify(kind, r)` (`r_harness.py:83`) maps a `CaseResult` to one of
`(ok, break, warn)`:

| Kind | Break conditions |
|---|---|
| `condition` | length = 0; is_na; rclass not logical/time; (length > 1 → warning since only first used) |
| `relative_to` | length = 0 or NA; rclass not a time/numeric/integer |
| `value` | length = 0; NA |
| `showif` | length = 0 breaks; NA warns (falls back to client-side JS) |
| `knitr` / `subject` / `address` | Only a runtime hard error is a break |

9.2. Error categorization (`r_harness.categorize_error`, `r_harness.py:61`)
parses R error strings into three kinds — `undefined_function`,
`undefined_object`, `runtime` — so users get actionable human text.

9.3. Severity **promotion/demotion** is applied post-hoc in the deep walk
(`coverage.py:585–595`):

- Same-survey `showif` returning NA is demoted from warn → info
(`coverage.py:589–591`). This is formr-faithful: formr re-evaluates such
showifs in-browser. Cross-survey showif NA is kept as warn.
- All other warnings stay as warnings.

9.4. Verdict → outcome is therefore (a) the plan's invariant and (b) formr's
contract, faithfully.

---

## 10. Cross-Run Resolution

10.1. `api_targets` (`depgraph.py:158`) extracts `survey_name=` / `run_name=`
arguments from `formr_api_*` calls.

10.2. `_resolve_survey_items` (`coverage.py:390`) first looks in the current
run; if missing, tries `load_structure(name)` from the local workspace
`.formr/`, recursing ≤ 10 levels (no infinite loop via `seen` set). Status
reported through `result.cross_run` as `resolved …` or `flagged …`.

10.3. Resolved cross-run frames are synthesized by `_synth_frame`
(`coverage.py:424`) — one representative value per non-display item repeated
across `__rows__` rows, with system columns added (`all_ended=False`, i.e.
ongoing).

10.4. The feature therefore **cannot** simulate real cross-run data;
unknown/unfetchable targets are explicitly surfaced as flags, not silently
passed.

---

## 11. Branch-Path Coverage (Static Deductions After Evaluation)

11.1. After every case is evaluated,
`branch_truth: dict[location, {True:…, False:…}]` is built by examining
condition cases whose R type includes `"logical"` and not NA
(`coverage.py:604–611`).

11.2. `_branch_and_loop_coverage` (`coverage.py:616`) assigns one verdict per
branching unit:

| Condition + result | Verdict |
|---|---|
| `SkipBackward` | "info — loop back-edge (termination assessed under Loops)"; never re-warned here (`coverage.py:643`–644) |
| Condition matches `_RUNTIME_DEP_RE` (shuffle, Sys.time, expired, formr_api*, etc.) | "info — reachability depends on runtime state" — silences false positives |
| Both True and False observed | "ok — both branches reachable" |
| Only True | "warn — condition ALWAYS true; fall-through may be dead" |
| Only False | "warn — condition NEVER true; jump target may be unreachable" |
| No boolean outcome | "info — no boolean outcome observed (R missing or aggregate/external logic)" |

11.3. The classifications "dead branch" and "always-true" thus assert
observations *over the tested inputs*, not semantics; they're tagged as
warnings, not errors.

---

## 12. Loop Termination Analysis

12.1. `if_true` defines the body: positions in
`[min(target, back_pos), max(...)]` (`coverage.py:251`). Body surveys
(`_find_loop_body`, `coverage.py:126`) are the units whose data frames grow.

12.2. Max iterations are chosen by precedence (`coverage.py:666–673`):

(a) explicit `loop_bounds[position]`; else
(b) `_infer_loop_max` regex on the condition (`coverage.py:115`–199); else
(c) if `_LOOP_COUNTER_RE.search`: `_DEFAULT_LOOP_MAX = 30`; else
(d) `None`.

12.3. `_infer_loop_max` recognizes `nrow(X)` comparisons, `finished(X)`
comparisons, and `length(X$var)`. For `nrow(X) < 14` returns 14; for `== 5`
returns 6; for `X != 5` falls through to default. Multiple bounds take the
min.

12.4. `_simulate_loop` (`coverage.py:210`) constructs *growing* frames: at
iteration `i`, body surveys have exactly `i` rows, all with
`ended = real-timestamp` (so `finished()` counts them), `expired = NA`. Each
iteration evaluates:

- The SkipBackward condition (full frames with `$`, no `with/tail`);
- Every exit branch (`Branch` / `SkipForward` in the body) using the same
  body frames plus refs in its own condition (`coverage.py:299–335`).

12.5. Termination logic (`coverage.py:344–378`):

- Exit branch TRUE → terminate at that iteration;
- SkipBackward condition FALSE → terminate at that iteration;
- Both tracked with minimum-iteration rule;
- If neither fires through `max_iter` → "condition remained TRUE through N
  iterations — may loop forever".

12.6. ESM idiom fallback (`coverage.py:690–699`): if `_infer_loop_max` returned
`None` *but* the body contains a date/count exit branch
(`_loop_has_exit_branch`, `coverage.py:714`; regex `_EXIT_SIGNAL_RE` at
`coverage.py:39`), the loop is reported as bounded with detail "exit Branch —
verify that exit can fire". This is an under-approximation: it never asserts
termination semantics; it asks the human to verify.

12.7. Fully deriving unboundedness is impossible offline; the feature's strongest
claim is "may loop forever" or, with exit branch, "verify manually".

---

## 13. Rendered Output (The `render_report` Function)

13.1. The deep-pass output (`coverage.py:736`) renders exactly five sections,
each with `lines`, `errors`, `warnings` tallies:

- `## Item Map (static vs dynamic)` — counts per survey, dynamic items with
  reason, static remainder;
- `## Deterministic Evaluation` — total cases, per-expression 🔴/⚠/✅; shows
  up to 4 breaking and 3 warning entries *per expression* post-dedup
  (`_dedup` at `coverage.py:838`); appends an "All simulated inputs evaluated
  without breaking" pass line when clean;
- `## Branch-Path Coverage` — one line per branch unit with verdict icon;
- `## Loops` — one line per SkipBackward with `max_iterations`,
  `terminates_at`, condition-breaks sub-entries;
- `## Cross-Run References` — dedup'd table of resolved/flagged statuses
  (`_dedup_cross` at `coverage.py:848`).

13.2. Severity tallies do not double-count: same-survey showif NA infoses are
suppressed in output (`coverage.py:788–790`); dedup is keyed on
`(detail, inputs)`.

13.3. The non-deep `analyze_run` (`analysis.py:698`) runs seven static checks
(R syntax via `_validate_r_syntax`; variable refs via
`_check_variable_references`; branch flow; item consistency; common mistakes;
item quality; flow semantics) *and then* adds `deep_lines` lines,
`deep_errors`, `deep_warnings` into the final tally (`analysis.py:716–720,
737, 738`). The clean-run early-return at `analysis.py:736` is gated on
`deep_errors == 0 and deep_warnings == 0`.

---

## 14. Visualization (`visualize_analysis`, `visualize.py`)

14.1. `visualize_analysis` (`server.py:399`) calls `deep_analyze` and
`render_html` (`visualize.py:123`), writes
`.formr/<name>.analysis.html`, opens via `webbrowser.open`. It is annotated
`destructiveHint=False, idempotentHint=True`.

14.2. `render_html` produces a self-contained page (Mermaid via CDN, no other
network) containing:

- `Flow` section (`render_mermaid`, `visualize.py:39`) with sequential + dashed
  branch edges and `ok/warn/info` colored nodes;
- `Item Map` table including the sampled domains for each item
  (`result.domains`);
- `Expression Traces` grouped by location with up to `_ROW_CAP = 64` rows
  (`visualize.py:120`);
- `Branch Decisions`;
- `Loops`;
- `Cross-Run References`.

14.3. The visualization is diagnostic/dev per its docstring
(`server.py:401`).

---

## 15. Properties Implied By Construction

15.1. **Termination**: bounded — see §2.2. Every subroutine: list walking,
domain construction, case enumeration, loop simulation, Rscript process
(`timeout = 90`).

15.2. **Determinism**: same `(structure, loop_bounds)` → same `DeepResult`.
There is no randomness: domains are type-dispatched; Rscript output parsing is
line-by-line; loop simulation is parameterized.

15.3. **Falsity of completeness**: The feature does *not* claim to find every
break. Two failure modes are explicitly out of reach:

(a) Multi-variable NA interactions (only all-NA + one-variable-at-a-time are
covered under the cap; §7.2).
(b) State-dependent reachability (shuffle/time/cron/aggregate flagged as info,
not determined; §11.2).

15.4. **Soundness of sound verdicts**: A "All simulated inputs evaluated
without breaking" implies soundness only over the equivalence classes sampled,
not over the full input domain.

15.5. **Soundness of break verdicts**: A break verdict records that the run's R
evaluates an expression to one of the breaking outcomes for a concrete sampled
input, constituting a verifiable counterexample absent tool-time differences
between formr and `_PREAMBLE`.

15.6. **Partial faithfulness to formr**: `r_harness._PREAMBLE` and
`classify`'s break/error rules are claimed derived from `Functions.php`,
`Survey.php`, `Branch.php`, `UnitSession::getRunData` (docstring
`r_harness.py:1–16`). The verifier's value semantics mirror `SurveyItem`
(`value_domains.py:10–22`). **Faithfulness is a documented precondition; it is
not re-checked at runtime against the formr source.**

15.7. **No participant data leakage**: Per `AGENTS.md`, the feature operates
only on structure files (`load_structure`), never result frames. R frames are
*synthetic* (`_synth_frame`, representative values), not participant data
(`coverage.py:424–433`, `r_harness.py:189`). This is a stated-and-constructed
invariant — the feature literally has no path to participant records.

15.8. **Side-effect surface**: writing `.formr/<name>.analysis.html`
(visualization tool only) and calling one subprocess (`Rscript`). Otherwise the
deep path mutates nothing (`deep_analyze` builds and returns a fresh
`DeepResult` with plain local state).

15.9. **Failure-mode posture**: `R not available`, `custom_r errors`,
`cross-run JSON missing`, `loop bound not inferable`, `unbounded loop`,
`multiline if-else parse fix` — each has determinate, tested coping behavior
(see `tests/test_deep_validation.py`).

---

### Closure

This exhausts the feature's logical behaviour as implemented: what it walks,
what it varies, what it evaluates, how it classifies, what it cannot decide,
and what invariants hold across all inputs. Anything not stated above is not
part of the feature.