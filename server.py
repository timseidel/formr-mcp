from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context
from mcp.types import ToolAnnotations

from formr_mcp.auth import AuthError, check_credentials
from formr_mcp.client import FormrClient, FormrClientError
from formr_mcp import documentation as doc
from formr_mcp.validation import get_unit_type_schemas, validate_structure

dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path)

BASE_URL = os.getenv("FORMR_BASE_URL", "")
CLIENT_ID = os.getenv("FORMR_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("FORMR_CLIENT_SECRET", "")

VALID_SETTINGS = {
    "title", "description", "footer_text", "public_blurb",
    "privacy", "tos", "header_image_path", "custom_css", "custom_js",
    "custom_r", "cron_active", "use_material_design", "expiresOn",
    "expire_cookie_value", "expire_cookie_unit", "public", "locked",
}


def require(value: str, name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"'{name}' must not be empty")


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[FormrClient]:
    err = check_credentials(BASE_URL, CLIENT_ID, CLIENT_SECRET)
    if err:
        print("=" * 72)
        print("  formr-mcp: AUTHENTICATION NOT CONFIGURED")
        print("=" * 72)
        print()
        print(err)
        print()
        print("MCP tools will fail with auth errors until this is resolved.")
        print("=" * 72)

    client = FormrClient(BASE_URL, CLIENT_ID, CLIENT_SECRET)
    try:
        yield client
    finally:
        await client.aclose()


mcp = FastMCP(
    "formr-mcp",
    lifespan=lifespan,
    instructions="""You help design and manage formr survey runs and their structure.

SETUP: The user must configure a .env file with formr API credentials:
  FORMR_BASE_URL     — formr instance URL (e.g. http://localhost)
  FORMR_CLIENT_ID    — 32-char hex client ID from /admin/account#api
  FORMR_CLIENT_SECRET — 64-char hex secret from /admin/account#api
Required scopes: survey:read, run:read, run:write, data:read (admin >= 2).
If tools return auth errors, the .env file is missing or misconfigured.

formr is a survey framework for psychology research. Runs are ordered
compositions of units (Surveys, Pages, Emails, Branches, etc.) where
execution flows by position number. Branching uses R expressions in
`condition` and jumps to the `if_true` position.

WORKFLOW — Always use file-based editing for run structures:

  Step 1 — Fetch:
    get_run_structure_to_file("run-name", "/path/file.json")
    Writes full structure to file + auto-backup to file.json.bak.

  Step 2 — Create a working copy:
    Copy file.json → file.work.json (using cp or the file copy tool).
    Edit file.work.json only. Never edit the original or .bak directly.

  Step 3 — Edit:
    Use standard file Read/Edit tools on file.work.json.
    Change positions, add/remove units, update survey items, etc.

  Step 4 — Upload:
    update_run_structure_from_file("run-name", "/path/file.work.json")
    Validates, uploads, returns success or specific errors.

  Step 5 — On validation errors:
    Fix errors in file.work.json and retry Step 4.
    If stuck, restore: copy file.json.bak → file.work.json.

  Step 6 — On success:
    Next time, start from Step 1 again (fresh fetch).

Available tools:
  get_run_structure_to_file(name, filepath) — fetch to file
  update_run_structure_from_file(name, filepath) — upload from file
  update_run_settings(name, settings) — change run-level settings
  get_run(name) — run metadata (not structure)
  list_runs(name?) — list/filter runs
  create_run(name) — create new empty run
  delete_run(name, confirm) — delete a run and all data
  get_unit_types() — unit type schemas
  get_documentation(topic) — learn survey design
  get_documentation_topics() — list available topics""",
)


def _client(ctx: Context) -> FormrClient:
    return ctx.request_context.lifespan_context


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def whoami(ctx: Context = None) -> dict:
    """Get the authenticated user's profile."""
    return await _client(ctx).get_user_me()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def list_runs(name: str | None = None, ctx: Context = None) -> list[dict]:
    """List all runs. Optionally filter by exact name."""
    return await _client(ctx).get_runs(name)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True, openWorldHint=False))
async def create_run(name: str, ctx: Context = None) -> dict:
    """Create a new run. Name must start with a letter, contain only a-z, 0-9, hyphens, and be 3-255 chars.

    Returns the created run name and link on success. Requires `run:write` OAuth scope.
    """
    require(name, "name")
    client = _client(ctx)
    return await client.create_run(name)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=False, openWorldHint=False))
async def delete_run(name: str, confirm: bool = False, ctx: Context = None) -> str:
    """Permanently delete a run and all its data.

    Safety: call without `confirm` first to get a warning,
    then call again with `confirm=True` once the user has approved.
    """
    require(name, "name")
    if not confirm:
        return (
            f"⚠️  This will permanently delete run '{name}' and all collected data. "
            f"This cannot be undone. Call again with `confirm=True` to proceed."
        )
    await _client(ctx).delete_run(name)
    return f"Run '{name}' has been deleted."


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def get_run(name: str, ctx: Context = None) -> dict:
    """Get a single run by exact name."""
    require(name, "name")
    return await _client(ctx).get_run(name)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True, openWorldHint=False))
async def update_run_settings(name: str, settings: dict, ctx: Context = None) -> dict:
    """Update a run's settings. Pass only the settings you want to change.

    Available settings: title, description, footer_text, public_blurb,
    privacy, tos, header_image_path, custom_css, custom_js, custom_r,
    cron_active, use_material_design, expiresOn,
    expire_cookie_value, expire_cookie_unit,
    public (0=admin/test-users only, 2=accessible with link; 1 and 3 are rarely used),
    locked (0/1).

    Returns the full updated run with all settings.
    """
    require(name, "name")
    unknown = set(settings) - VALID_SETTINGS
    if unknown:
        raise ValueError(
            f"Unknown settings: {', '.join(sorted(unknown))}. "
            f"Valid settings: {', '.join(sorted(VALID_SETTINGS))}"
        )
    client = _client(ctx)
    await client.patch_run(name, settings)
    return await client.get_run(name)


def _format_size(bytes: int) -> str:
    if bytes < 1024:
        return f"{bytes} B"
    if bytes < 1024 * 1024:
        return f"{bytes / 1024:.1f} KB"
    return f"{bytes / 1024 / 1024:.1f} MB"


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def get_run_structure_to_file(name: str, filepath: str, ctx: Context = None) -> str:
    """Download the full run structure to a JSON file. Use this before editing.

    If `filepath` already exists, the previous version is backed up to `filepath.bak`.
    Returns a short summary — the full structure is on disk, not in the response.
    """
    require(name, "name")
    require(filepath, "filepath")
    client = _client(ctx)

    if os.path.exists(filepath):
        os.replace(filepath, filepath + ".bak")

    structure = await client.get_run_structure(name)

    with open(filepath, "w") as f:
        json.dump(structure, f, indent=2)

    units = len(structure.get("units", []))
    size = os.path.getsize(filepath)

    return (
        f"Run '{name}': wrote {units} units ({_format_size(size)}) to {filepath}\n"
        f"Backup saved to {filepath}.bak"
    )


def _normalize_survey_choices(structure: dict) -> None:
    """Ensure inline survey items with 'choices' also carry 'choice_list' (set to
    the item's name), matching the round-trip format that formr's createFromData()
    expects.  Without this, items with choices but no choice_list are silently
    dropped by the server."""
    for unit in structure.get("units", []):
        if unit.get("type") == "Survey" and isinstance(unit.get("survey_data"), dict):
            items = unit["survey_data"].get("items", [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and item.get("choices") and not item.get("choice_list"):
                        item_name = item.get("name")
                        if item_name:
                            item["choice_list"] = item_name


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False, openWorldHint=False))
async def update_run_structure_from_file(name: str, filepath: str, ctx: Context = None) -> str:
    """Read a run structure from a JSON file, validate, and upload to formr.

    Returns a summary on success, or validation errors to fix and retry.
    To inspect the uploaded result, call `get_run_structure_to_file` again.
    """
    require(name, "name")
    require(filepath, "filepath")
    client = _client(ctx)

    with open(filepath) as f:
        structure = json.load(f)

    _normalize_survey_choices(structure)
    errors = validate_structure(structure)
    if errors:
        raise ValueError(
            "Structure validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    await client.put_run_structure(name, structure)
    result = await client.get_run_structure(name)
    units = len(result.get("units", []))

    return (
        f"Run '{name}': successfully updated ({units} units).\n"
        f"To re-inspect, run: get_run_structure_to_file(\"{name}\", \"{filepath}\")"
    )


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_unit_types(ctx: Context = None) -> dict:
    """Get all supported run unit types and their required/optional fields. Use this to understand what can be created."""
    return get_unit_type_schemas()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_documentation(topic: str, ctx: Context = None) -> str:
    """Get formr design documentation. Topics: item-types, run-concepts, r-code, survey-json, examples, best-practices. Use this to learn how to design formr surveys and runs."""
    return doc.get_documentation(topic)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_documentation_topics(ctx: Context = None) -> list[dict]:
    """List all available documentation topics."""
    return doc.get_topics()


if __name__ == "__main__":
    mcp.run()
