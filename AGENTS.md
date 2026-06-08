# formr-mcp — Agent Instructions

This project is a formr MCP server. When working with it:

## Run structure editing

Always use the file-based workflow. Do NOT pass large JSON structures through tool call arguments.

1. `get_run_structure_to_file("run-name")` — fetches to `.formr/run-name.json`
2. Edit `.formr/run-name.json` with Read/Edit tools
3. `update_run_structure_from_file("run-name")` — validates and uploads

On success, the backup (`.formr/run-name.json.bak`) is auto-removed.
On validation error, fix the file and retry. If stuck, restore from `.bak`.

### Incremental editing tools (programmatic)

For systematic changes, use the editing tools instead of manual JSON edits:

- `add_run_unit(name, type, position, **kwargs)` — add a unit; auto-shifts existing units at the same position up by 10
- `remove_run_unit(name, position, compact=False)` — remove a unit; `compact=True` closes the position gap by shifting later units down by 10
- `duplicate_run_units(name, source_positions, new_start)` — copy a block of units to a new position range; descriptions get a "copy: " prefix (but won't stack on re-duplication)
- `shift_run_positions(name, from_position, delta)` — shift all units at `from_position` or later by `delta` (positive=up, negative=down); does NOT update `if_true` targets automatically
- `generate_survey_items(name, survey_description, items)` — generate item dicts from a simple spec; returns JSON for manual insertion into the run structure file

These operate on `.formr/<name>.json` directly. Call `get_run_structure_to_file` first to ensure the file exists.

### Position management caveats

- Positions are integers, typically spaced by 10 to allow insertions. When editing creates gaps or overlaps, use `shift_run_positions` to rearrange.
- `add_run_unit` auto-shifts to avoid collisions, but only at the exact position. Planning positions with gaps (10, 20, 30…) is best practice.
- `remove_run_unit` with `compact=True` shifts subsequent units down to close the gap. Without compact, you get a hole that can be filled later.
- `if_true` (skip targets) and `body` (Wait jump targets) contain position references. `shift_run_positions` does NOT update these — you must edit them manually after shifting. `duplicate_run_units` copies `if_true` values as-is, which is correct when the target is outside the copied block but may need adjustment when it's inside.

## Running the server locally

```bash
uv run server.py
```

## Testing

```bash
uv run --with pytest pytest tests/
```

## Read-only inspection tools

These tools read from the local `.formr/<name>.json` file (call `get_run_structure_to_file` first):

- `summarize_run(name, detail)` — human-readable overview. `detail="units"` for unit-level only, `detail="items"` (default) to include all survey items. Strips HTML from labels.
- `find_run_items(name, query?, item_type?)` — search items by name/label substring and/or item type (e.g. `"mc"`, `"text"`, `"calculate"`).
- `analyze_run(name)` — check for structural errors: Page/Endpage blocking, Wait body validation, Email/Pause R syntax extraction.

These avoid the need to write custom Python scripts for common queries like "what questions does this run ask?" or "where are the SCSKD items?".

## Code style

- Keep tools focused on file I/O, not inline JSON
- No caching library needed — files are the cache
- Return short summaries, never the full structure
- Run structure files live in `.formr/` (auto-created, gitignored)

## Data Protection

- Under all conditions, leaking of participant data to llm models must be prohibited by design!

## MCP development workflow

### The fetch-edit-upload cycle

The core workflow is always: (1) fetch to file, (2) edit the file, (3) validate and upload. This avoids passing large JSON through tool call arguments, keeps a `.bak` for rollback, and makes edits inspectable with git diff or Read.

### Cross-referencing between code and run structures

When adding features, trace the data flow end-to-end:

1. **Tool definition** (`server.py`): Tool name, docstring, and parameter schema define the MCP interface.
2. **Implementation** (`formr_mcp/` modules): The Python function that does the work. Must read/write the `.formr/` JSON files.
3. **Tests** (`tests/test_*.py`): Create a minimal run structure fixture, write to `.formr/<name>.json`, call the function, assert on the result file.
4. **Documentation** (`formr_mcp/documentation.py`): If the feature changes how users should design runs, update the relevant topic.

When adding a new tool, register it in all four places. The test pattern is: create a temp directory, monkey-patch `WORKSPACE_DIR`, write a fixture JSON, call the function, read back and assert.

### Testing patterns

- **Monkey-patch `WORKSPACE_DIR`** to a temp directory for isolation. This avoids touching real run files.
- **Build incrementally**: Start with a minimal run (`units: []`, `settings: {}`), add units with `add_run_unit`, then verify position ordering and field values.
- **Test edge cases**: duplicate an already-duplicated unit (caught "copy:" stacking bug), insert at position 0 (boundary), compact after removal (position arithmetic).
- **Use `analyze_run` after edits** to verify the structure is valid before uploading.

### Common formr pitfalls (discovered during VIBE exercise)

- **Page/Endpage blocking**: An Endpage unit at position X blocks all units after X — even if they're in a different branch. This is the #1 mistake. The analyzer now detects this.
- **Wait `body` is a position integer**, not display content. Pause `body` IS display content. Confusing these breaks the run silently.
- **`if_true` must point to a real position** and is NOT auto-updated by shift/duplicate tools. Always verify skip targets after structural edits.
- **`survey_unit_sessions`** is the system table for ESM timing — it was previously undocumented but is essential for any longitudinal design.
- **`cron_only=1`** on Email units means "only send via cron, not during participant visit" — critical for ESM reminders.
- **External unit `address`** can contain full R scripts (not just URLs) — this is how SMS gateway calls work in the manual VIBE study.
- **`api_end=0`** on External means fire-and-forget (auto-advance), `api_end=1` means wait for callback.