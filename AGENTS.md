# formr-mcp — Agent Instructions

This project is a formr MCP server. When working with it:

## Run structure editing

Always use the file-based workflow. Do NOT pass large JSON structures through tool call arguments.

1. `get_run_structure_to_file("run-name", "path/file.json")` — fetch
2. Copy to a working file (e.g. `file.work.json`)
3. Edit the working file with Read/Edit tools
4. `update_run_structure_from_file("run-name", "path/file.work.json")` — upload
5. On errors, fix and retry; if stuck, restore from `file.json.bak`

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

## Data Protection

- Under all conditions, leaking of participant data to llm models must be prohibited by design!