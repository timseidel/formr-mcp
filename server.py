from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context
from mcp.types import ToolAnnotations

from formr_mcp.auth import AuthError, check_credentials
from formr_mcp.client import FormrClient, FormrClientError
from formr_mcp import documentation as doc
from formr_mcp.analysis import analyze_run as run_analysis
from formr_mcp.editing import (
    add_run_unit as editing_add_run_unit,
    duplicate_run_units as editing_duplicate_run_units,
    generate_survey_items as editing_generate_survey_items,
    remove_run_unit as editing_remove_run_unit,
    renormalize_positions as editing_renormalize_positions,
    shift_run_positions as editing_shift_run_positions,
)
from formr_mcp.summarize import find_items, summarize_run_structure
from formr_mcp.validation import get_unit_type_schemas, validate_structure

dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path)

BASE_URL = os.getenv("FORMR_BASE_URL", "")
CLIENT_ID = os.getenv("FORMR_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("FORMR_CLIENT_SECRET", "")

WORKSPACE_DIR = Path(".formr")

VALID_NAME = re.compile(r"^[a-z][a-z0-9-]{2,254}$")

VALID_SETTINGS = {
    "title", "description", "footer_text", "public_blurb",
    "privacy", "tos", "header_image_path", "custom_css", "custom_js",
    "custom_r", "cron_active", "use_material_design", "expiresOn",
    "expire_cookie_value", "expire_cookie_unit", "public", "locked",
}


def validate_run_name(name: str) -> None:
    if not VALID_NAME.match(name):
        raise ValueError(
            f"Invalid run name '{name}'. "
            f"Name must start with a letter, contain only a-z, 0-9, hyphens, "
            f"and be 3-255 characters long."
        )


def safe_run_filepath(name: str) -> Path:
    validate_run_name(name)
    path = (WORKSPACE_DIR / f"{name}.json").resolve()
    workspace_resolved = WORKSPACE_DIR.resolve()
    if not str(path).startswith(str(workspace_resolved)):
        raise ValueError("Path traversal detected: file path escapes workspace directory")
    return path


def run_filepath(name: str) -> Path:
    path = safe_run_filepath(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


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

WORKFLOW — Always use the file-based workflow for run structures:

  1. Fetch:  get_run_structure_to_file("run-name")
     Writes .formr/run-name.json. If it already exists, the previous
     version is backed up to .formr/run-name.json.bak.

  2. Edit:   Use Read/Edit tools on .formr/run-name.json directly.
     Change positions, add/remove units, update survey items, etc.

  3. Upload: update_run_structure_from_file("run-name")
     Reads .formr/run-name.json, validates, and uploads to formr.
     On validation errors: fix the file and retry.
     On success: the .bak file is removed; re-fetch when needed.

Available tools:
  get_run_structure_to_file(name) — fetch run structure to .formr/<name>.json
  update_run_structure_from_file(name) — upload from .formr/<name>.json
  update_run_settings(name, settings) — change run-level settings
  get_run(name) — run metadata (not structure)
  list_runs(name?) — list/filter runs
  create_run(name) — create new empty run
  delete_run(name, confirm) — delete a run and all data
  get_unit_types() — unit type schemas
  get_documentation(topic) — learn survey design
  get_documentation_topics() — list available topics
  summarize_run(name, detail) — readable summary of run structure (detail: 'units' or 'items')
  find_run_items(name, query?, item_type?) — search items across surveys by name/label/type
  analyze_run(name) — check R syntax, variable refs, branch flow, item consistency, common mistakes
  add_run_unit(name, unit_type, position, **kwargs) — add a unit to the local file
  remove_run_unit(name, position, compact?) — remove a unit from the local file
  duplicate_run_units(name, from_positions, to_start_position) — copy units to new positions
  shift_run_positions(name, from_position, delta) — shift units to make room or close gaps
  generate_survey_items(description, survey_name?, language?) — generate items JSON from a description""",
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
    if name is not None:
        validate_run_name(name)
    return await _client(ctx).get_runs(name)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True, openWorldHint=False))
async def create_run(name: str, ctx: Context = None) -> dict:
    """Create a new run. Name must start with a letter, contain only a-z, 0-9, hyphens, and be 3-255 chars.

    Returns the created run name and link on success. Requires `run:write` OAuth scope.
    """
    validate_run_name(name)
    client = _client(ctx)
    return await client.create_run(name)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=False, openWorldHint=False))
async def delete_run(name: str, confirm: bool = False, ctx: Context = None) -> str:
    """Permanently delete a run and all its data.

    Safety: call without `confirm` first to get a warning,
    then call again with `confirm=True` once the user has approved.
    """
    validate_run_name(name)
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
    validate_run_name(name)
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
    validate_run_name(name)
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
async def get_run_structure_to_file(name: str, ctx: Context = None) -> str:
    """Download the full run structure to .formr/<name>.json. Use this before editing.

    If the file already exists, the previous version is backed up to .formr/<name>.json.bak.
    Returns a short summary — the full structure is on disk, not in the response.
    """
    validate_run_name(name)
    client = _client(ctx)
    filepath = run_filepath(name)
    bak_path = filepath.with_suffix(".json.bak")

    if filepath.exists():
        os.replace(str(filepath), str(bak_path))

    structure = await client.get_run_structure(name)

    with open(filepath, "w") as f:
        json.dump(structure, f, indent=2)

    units = len(structure.get("units", []))
    size = os.path.getsize(filepath)
    backup_note = f"\nBackup saved to {bak_path}" if bak_path.exists() else ""

    return f"Run '{name}': wrote {units} units ({_format_size(size)}) to {filepath}{backup_note}"


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
async def update_run_structure_from_file(name: str, ctx: Context = None) -> str:
    """Read a run structure from .formr/<name>.json, validate, and upload to formr.

    Returns a summary on success, or validation errors to fix and retry.
    On success, the backup file (.formr/<name>.json.bak) is removed.
    To inspect the uploaded result, call get_run_structure_to_file again.
    """
    validate_run_name(name)
    filepath = run_filepath(name)
    bak_path = filepath.with_suffix(".json.bak")

    if not filepath.exists():
        raise FileNotFoundError(
            f"No local file for run '{name}'. "
            f"Call get_run_structure_to_file(\"{name}\") first."
        )

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

    if bak_path.exists():
        bak_path.unlink()

    return f"Run '{name}': successfully updated ({units} units)."


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


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def summarize_run(name: str, detail: str = "items", ctx: Context = None) -> str:
    """Summarize a run structure from the local file. Returns a readable overview of units and their items.

    Must call get_run_structure_to_file(name) first to fetch the structure.

    Use detail='units' for just unit-level info (no items), or detail='items' (default) to include all survey items.
    Strips HTML from labels for readability.
    """
    validate_run_name(name)
    return summarize_run_structure(name, detail=detail)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def find_run_items(name: str, query: str | None = None, item_type: str | None = None, ctx: Context = None) -> str:
    """Search for items across all surveys in a run. Returns matching items with survey context.

    Must call get_run_structure_to_file(name) first to fetch the structure.

    Filters:
    - query: search item names and labels (case-insensitive substring match)
    - item_type: filter by item type (e.g. 'mc', 'text', 'note', 'calculate')
    At least one filter is recommended; both can be combined.
    """
    validate_run_name(name)
    return find_items(name, query=query, item_type=item_type)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def analyze_run(name: str, ctx: Context = None) -> str:
    """Analyze a run structure for errors and warnings. Checks R syntax, variable references, branch flow, item consistency, and common mistakes.

    Must call get_run_structure_to_file(name) first to fetch the structure.

    Returns a structured report with error/warning counts. R syntax validation requires R to be installed.
    """
    validate_run_name(name)
    return run_analysis(name)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False, openWorldHint=False))
def add_run_unit(name: str, unit_type: str, position: int, description: str = "",
                insert_mode: str = "shift", ctx: Context = None, **kwargs) -> str:
    """Add a unit to a local run structure file. The file must exist (fetch with get_run_structure_to_file first).

    Unit types: Survey, Page, Email, Branch, SkipForward, SkipBackward, External, Pause, Wait, Shuffle, PushMessage, Privacy, Endpage.

    Common kwargs by unit type:
    - SkipForward/SkipBackward: condition (R expr), if_true (int position), automatically_jump (0/1), automatically_go_on (0/1)
    - Email: subject, body, account_id (int), recipient_field, cron_only (0/1)
    - Pause/Wait: wait_minutes, wait_until_time ("HH:MM:SS"), wait_until_date ("YYYY-MM-DD"), relative_to (R expr), body
    - Wait: body is an integer position for click-through (NOT display content)
    - Survey: study_id (int) or survey_data (dict with name, items, settings)
    - Endpage/Page: body (markdown/knitr content)
    - External: address (URL or R code), api_end (0/1)

    insert_mode: 'shift' (default) shifts existing units at >= position up by 10. 'overwrite' replaces any existing unit at that position.
    When shifting, position references (if_true, Wait body) in existing units are
    automatically updated to reflect new positions.
    """
    validate_run_name(name)
    return editing_add_run_unit(name, unit_type, position, description=description,
                               insert_mode=insert_mode, **kwargs)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=False, openWorldHint=False))
def remove_run_unit(name: str, position: int, compact: bool = False, ctx: Context = None) -> str:
    """Remove a unit at the given position from the local run structure file.

    The file must exist (fetch with get_run_structure_to_file first).
    After removing, call update_run_structure_from_file to upload.

    If compact is True, shifts all units at higher positions down by 1 to fill the gap.
    Position references (if_true on Branch/Skip units, body on Wait units) are
    automatically updated when compacting. Dangling references to the removed
    position are detected and reported as warnings.
    """
    validate_run_name(name)
    return editing_remove_run_unit(name, position, compact=compact)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False, openWorldHint=False))
def duplicate_run_units(name: str, from_positions: list[int], to_start_position: int,
                        shift_existing: bool = True, ctx: Context = None) -> str:
    """Copy units at from_positions to new positions starting at to_start_position in the local run structure file.

    Copies units in their original order, assigning new positions starting at
    to_start_position with gaps of 10 (e.g., 100, 110, 120...).

    If shift_existing is True (default), any existing units at conflicting positions
    are shifted up to make room. Set shift_existing=False to error on conflicts instead.

    Position references (if_true, Wait body) are automatically remapped:
    - Internal references within the copied block point to the new positions.
    - References in existing units that are shifted are updated accordingly.
    - References in copies pointing to shifted external positions are also updated.

    The file must exist (fetch with get_run_structure_to_file first).
    """
    validate_run_name(name)
    return editing_duplicate_run_units(name, from_positions, to_start_position,
                                       shift_existing=shift_existing)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False, openWorldHint=False))
def shift_run_positions(name: str, from_position: int, delta: int, ctx: Context = None) -> str:
    """Shift all units at positions >= from_position by delta in the local run structure file.

    Positive delta shifts positions up (making room for new units).
    Negative delta shifts positions down (closing gaps after removal).

    Position references (if_true on Branch/Skip units, body on Wait units) are
    automatically updated to reflect the new positions.

    The file must exist (fetch with get_run_structure_to_file first).
    """
    validate_run_name(name)
    return editing_shift_run_positions(name, from_position, delta)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False, openWorldHint=False))
def renormalize_positions(name: str, spacing: int = 10, ctx: Context = None) -> str:
    """Renumber all unit positions to clean multiples of spacing while preserving order.

    Assigns new positions: spacing, spacing*2, spacing*3, ... based on the current
    sorted order. All position references (if_true on Branch/Skip units, body on
    Wait units) are automatically updated to reflect the new positions.

    Useful after a series of edits that leave positions with gaps or irregular spacing
    (e.g., after compact removal which shifts by 1 instead of the standard 10).

    Safe to call on already-clean structures — positions already at clean multiples
    of spacing that are in the right order will remain (or nearly remain) the same.

    The file must exist (fetch with get_run_structure_to_file first).
    """
    validate_run_name(name)
    return editing_renormalize_positions(name, spacing=spacing)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def generate_survey_items(description: str, survey_name: str = "survey",
                           language: str = "en", ctx: Context = None) -> str:
    """Generate a survey items JSON array based on a description. Returns JSON
    text you can paste into your run structure. Does NOT modify any file.

    The description should specify what items you want, e.g.:
    "BFI-15 personality questionnaire in German with 5-point Likert scale"
    "ESM survey with activity, location, interaction partners, and 3 affect items"
    "Screening questionnaire for age, language, country, email, smartphone access"

    The LLM will generate well-formed item JSON with correct item_order,
    choices, choice_list, type_options, etc.
    """
    return editing_generate_survey_items(description, survey_name=survey_name,
                                          language=language)


if __name__ == "__main__":
    mcp.run()
