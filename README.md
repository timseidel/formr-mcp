# formr-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) server for the [formr](https://formr.org) survey framework. Let LLM agents inspect, create, and edit formr run structures, manage settings, and get design guidance — all through natural language.

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager
- **formr instance** with admin (≥ 2) API access — create credentials at `<base_url>/admin/account#api`
- **R** (optional) — enables R syntax validation in `analyze_run`

## Quick Start

```bash
git clone https://github.com/timseidel/formr-mcp && cd formr-mcp
cp .env.example .env
# Edit .env with your formr instance URL and API credentials
uv sync
uv run server.py
```

### Environment Variables

| Variable | Description |
|---|---|
| `FORMR_BASE_URL` | formr instance URL (e.g. `http://localhost`) |
| `FORMR_CLIENT_ID` | 32-char hex client ID from `/admin/account#api` |
| `FORMR_CLIENT_SECRET` | 64-char hex secret from `/admin/account#api` |
| `FLOWCHART_URL` | (optional) URL of the formr Flowchart Generator (default: `https://formr-flowchart-test.pages.dev`) |

## MCP Client Configuration

### opencode

Add to `opencode.json` in your project root:

```json
{
  "mcp": {
    "formr-mcp": {
      "type": "local",
      "command": ["uv", "run", "server.py"],
      "enabled": true
    }
  }
}
```

Or copy from the included example:

```bash
cp opencode.json.example opencode.json
```

### Claude Desktop

Add to `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "formr-mcp": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/formr-mcp", "server.py"],
      "env": {
        "FORMR_BASE_URL": "http://localhost",
        "FORMR_CLIENT_ID": "your_client_id",
        "FORMR_CLIENT_SECRET": "your_client_secret"
      }
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json` in your project:

```json
{
  "mcpServers": {
    "formr-mcp": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/formr-mcp", "server.py"]
    }
  }
}
```

Set `FORMR_BASE_URL`, `FORMR_CLIENT_ID`, and `FORMR_CLIENT_SECRET` in a `.env` file in the project root.

## Available Tools

### Run Management

| Tool | Description |
|---|---|
| `list_runs` | List all runs, optionally filter by name |
| `get_run` | Get run metadata by exact name |
| `create_run` | Create a new empty run |
| `delete_run` | Permanently delete a run and all its data |
| `whoami` | Get the authenticated user's profile |

### Structure Editing

| Tool | Description |
|---|---|
| `get_run_structure_to_file` | Fetch full structure to `.formr/<name>.json` (backs up existing) |
| `update_run_structure_from_file` | Validate and upload from `.formr/<name>.json` |
| `update_run_settings` | Change run-level settings (title, visibility, etc.) |

### Inspection & Analysis

| Tool | Description |
|---|---|
| `summarize_run` | Human-readable overview (`detail="units"` or `"items"`) |
| `find_run_items` | Search items by name/label substring and/or type |
| `analyze_run` | Check R syntax, variable refs, branch flow, item consistency |
| `open_flowchart` | Upload run structure and get a shareable flowchart URL (expires in 24h) |

### Documentation

| Tool | Description |
|---|---|
| `get_documentation` | Learn formr design (topics: `item-types`, `run-concepts`, `r-code`, `survey-json`, `examples`, `best-practices`) |
| `get_unit_types` | Get all supported unit types and their required/optional fields |
| `get_documentation_topics` | List available documentation topics |

## Structure Editing Workflow

Run structures can be large. Use the **file-based workflow** instead of passing JSON through tool arguments:

```
1. Fetch   get_run_structure_to_file("my-run")
           → writes .formr/my-run.json

2. Edit    Use your editor/agent to modify .formr/my-run.json

3. Upload  update_run_structure_from_file("my-run")
           → validates, uploads, removes backup on success
```

- If `.formr/my-run.json` already exists, the previous version is backed up to `.formr/my-run.json.bak`
- On upload validation errors, fix the file and retry — restore from `.bak` if stuck
- The `.formr/` directory is gitignored

## Project Structure

```
formr-mcp/
├── server.py                  # MCP server entry point, tool definitions
├── formr_mcp/
│   ├── auth.py                # OAuth2 client credentials flow
│   ├── client.py              # HTTP client for formr REST API
│   ├── documentation.py       # Built-in design documentation topics
│   ├── analysis.py            # Run structure analysis (R syntax, refs, flow)
│   ├── summarize.py           # Run summarization and item search
│   └── validation.py          # Structure validation (types, positions, choices)
├── tests/
│   ├── test_server.py         # Server and tool tests
│   ├── test_analysis.py       # Analysis module tests
│   ├── test_summarize.py       # Summarization tests
│   └── test_normalize_choices.py # Choice normalization tests
├── .env.example               # Environment variable template
├── opencode.json.example      # opencode MCP config template
└── pyproject.toml             # Project metadata and dependencies
```

## Testing

```bash
uv run --with pytest pytest tests/
```

## Data Protection

This server interacts with the formr **admin API** only. It accesses run structures, survey definitions, and settings — **never participant response data**. Runs are fetched and edited as structural JSON, not as data exports.

## License

MIT
