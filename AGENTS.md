# formr-mcp — Agent Instructions

This project is a formr MCP server. When working with it:

## Running the server locally

```bash
uv run server.py
```

## Testing

```bash
uv run --with pytest pytest tests/
```

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
5. **formr source code**: Always consult the formr.org web app source (https://github.com/rubenarslan/formr) and the R package source (https://github.com/rubenarslan/formr/) to understand the software's design decisions. The formr codebase is the ground truth for how units, skip logic, Wait/Pause semantics, and session tables actually behave — documentation alone is incomplete.

When adding a new tool, register it in all four places. The test pattern is: create a temp directory, monkey-patch `WORKSPACE_DIR`, write a fixture JSON, call the function, read back and assert.

### Testing patterns

- **Monkey-patch `WORKSPACE_DIR`** to a temp directory for isolation. This avoids touching real run files.
- **Build incrementally**: Start with a minimal run (`units: []`, `settings: {}`), add units with `add_run_unit`, then verify position ordering and field values.
- **Test edge cases**: duplicate an already-duplicated unit (caught "copy:" stacking bug), insert at position 0 (boundary), compact after removal (position arithmetic).
- **Use `analyze_run` after edits** to verify the structure is valid before uploading.

### Implementation notes

- `remove_run_unit(compact=True)` shifts by 1, not by the original spacing. This is by design — call `renormalize_positions` to clean up afterwards.
- `renormalize_positions` renumbers positions to clean multiples (10, 20, 30...) and auto-updates all `if_true` and Wait `body` references.
- The `analyze_run` variable reference checker whitelists formr system columns (`created`, `modified`, `ended`, `expired`) since these exist in every survey but aren't in the `items` list.
- The common mistakes checker skips `=` in named function arguments (e.g. `units='days'` in `difftime()`).
- Wait `body` is a position reference; Pause/Page/Endpage/Email `body` is display content. The editing tools only remap Wait `body` via `POSITION_REF_FIELDS`.