# formr-mcp — Agent Instructions

This project is a formr MCP server. When working with it:

## Run structure editing

Always use the file-based workflow. Do NOT pass large JSON structures through tool call arguments.

1. `get_run_structure_to_file("run-name")` — fetches to `.formr/run-name.json`
2. Edit `.formr/run-name.json` with Read/Edit tools
3. `update_run_structure_from_file("run-name")` — validates and uploads

On success, the backup (`.formr/run-name.json.bak`) is auto-removed.
On validation error, fix the file and retry. If stuck, restore from `.bak`.

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