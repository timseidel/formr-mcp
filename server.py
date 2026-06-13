from __future__ import annotations

import json
import os
import webbrowser
from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator, Literal

from pydantic import Field

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context
from mcp.types import ToolAnnotations

# Load .env before importing project modules — they read env vars at import time
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path)

from formr_mcp.auth import AuthError, check_credentials
from formr_mcp.client import FormrClient, FormrClientError
from formr_mcp import documentation as doc
from formr_mcp import patterns as patterns_lib
from formr_mcp.analysis import analyze_run as run_analysis
from formr_mcp.editing import (
    add_run_unit as editing_add_run_unit,
    duplicate_run_units as editing_duplicate_run_units,
    remove_run_unit as editing_remove_run_unit,
    renormalize_positions as editing_renormalize_positions,
    shift_run_positions as editing_shift_run_positions,
)
from formr_mcp.summarize import find_items, summarize_run_structure
from formr_mcp.utils import (
    run_filepath,
    validate_run_name,
)
from formr_mcp.validation import get_unit_type_schemas, validate_structure

RunName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{2,254}$", min_length=3, max_length=255)]

BASE_URL = os.getenv("FORMR_BASE_URL", "")
CLIENT_ID = os.getenv("FORMR_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("FORMR_CLIENT_SECRET", "")
FLOWCHART_URL = os.getenv("FLOWCHART_URL", "https://formr-flowchart-test.tim-seidel.workers.dev")

VALID_SETTINGS = {
    "title", "description", "footer_text", "public_blurb",
    "privacy", "tos", "header_image_path", "custom_css", "custom_js",
    "custom_r", "cron_active", "expiresOn",
    "expire_cookie_value", "expire_cookie_unit", "public", "locked",
}


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
  FORMR_BASE_URL, FORMR_CLIENT_ID, FORMR_CLIENT_SECRET
Required scopes: survey:read, run:read, run:write, data:read (admin >= 2).
If tools return auth errors, the .env file is missing or misconfigured.

formr is a survey framework for psychology research. Runs are ordered
compositions of units (Surveys, Pages, Emails, Branches, etc.) where
execution flows by position number. Branching uses R expressions in
`condition` and jumps to the `if_true` position.

WORKFLOW — Always use the file-based workflow for run structures:
  1. Fetch:  get_run_structure_to_file(name) → .formr/<name>.json (backs up existing)
  2. Edit:   Use Read/Edit tools on .formr/<name>.json
  3. Upload: update_run_structure_from_file(name) → validates and uploads

PATTERNS — For complex runs (condition/covariate balancing, waiting rooms, loading screens,
live aggregate feedback, adaptive loops, personalized emails, external API/SMS calls, DRY R
functions), call list_patterns() then get_pattern(name) to learn the proven approach (structure
+ R idioms + gotchas) instead of re-deriving it. Patterns inform; you build the units. See
get_documentation("patterns") and get_documentation("custom-r-and-secrets").

DATA ACCESS — survey_unit_sessions / survey data frames = current participant only.
For all-participant data: formr_api_authenticate() with NO ARGUMENTS works in ALL run
R contexts (conditions, item values/showif, labels, page/email bodies, External units)
— formr auto-injects a run-scoped token (180 s, data:read). Exception: email subjects
/ push titles (plaintext, no R eval). For a DIFFERENT run: store credentials as run
secrets and pass them explicitly. Never use formr_connect() / formr_raw_results().
See get_documentation("data-access").""",
)


def _client(ctx: Context) -> FormrClient:
    return ctx.request_context.lifespan_context


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def whoami(ctx: Context = None) -> dict:
    """Get the authenticated user's profile."""
    return await _client(ctx).get_user_me()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def list_runs(name: RunName | None = None, ctx: Context = None) -> list[dict]:
    """List all runs. Optionally filter by exact name."""
    if name is not None:
        validate_run_name(name)
    return await _client(ctx).get_runs(name)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True, openWorldHint=False))
async def create_run(name: RunName, ctx: Context = None) -> dict:
    """Create a new run. Name must start with a letter, contain only a-z, 0-9, hyphens, and be 3-255 chars.

    Returns the created run name and link on success. Requires `run:write` OAuth scope.
    """
    validate_run_name(name)
    client = _client(ctx)
    return await client.create_run(name)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=False, openWorldHint=False))
async def delete_run(name: RunName, ctx: Context = None) -> str:
    """Permanently delete a run and all its data.
    """
    validate_run_name(name)
    await _client(ctx).delete_run(name)
    return f"Run '{name}' has been deleted."


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def get_run(name: RunName, ctx: Context = None) -> dict:
    """Get a single run by exact name."""
    validate_run_name(name)
    return await _client(ctx).get_run(name)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True, openWorldHint=False))
async def update_run_settings(name: RunName, settings: dict, ctx: Context = None) -> dict:
    """Update a run's settings. Pass only the settings you want to change.

    Common settings: title, description, public (0=admin/test-only, 2=link-accessible), locked (0/1),
    custom_css, custom_js, custom_r, cron_active, expiresOn, footer_text, public_blurb, privacy,
    tos, header_image_path, expire_cookie_value, expire_cookie_unit.

    custom_r holds run-level R functions/globals injected before every R evaluation — define
    repeating helpers here once and call them by name across units (DRY). See
    get_documentation("custom-r-and-secrets"). Note: secret VALUES are write-only and set in the
    admin UI, not here; the structure export lists their names under settings.secrets.

    Returns the full updated run with all settings.
    """
    validate_run_name(name)
    val = settings.get("use_material_design")
    if val is not None and val != 0:
        raise ValueError(
            "'use_material_design' must be 0 or omitted. "
            "Material Design is a legacy theme that is not supported. "
            "Use custom_css to style the survey instead."
        )
    settings.pop("use_material_design", None)
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
async def get_run_structure_to_file(name: RunName, ctx: Context = None) -> str:
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

    with open(filepath, "w", encoding="utf-8") as f:
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
async def update_run_structure_from_file(name: RunName, ctx: Context = None) -> str:
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
            f"No local file for run '{name}' at {filepath}. "
            f"Call get_run_structure_to_file(\"{name}\") first."
        )

    client = _client(ctx)

    with open(filepath, encoding="utf-8") as f:
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
def get_documentation(
    topic: Literal["item-types", "run-concepts", "r-code", "survey-json", "examples", "best-practices", "editing-tools", "unit-types-advanced", "data-access", "patterns", "custom-r-and-secrets"],
    section: str | None = None,
    ctx: Context = None,
) -> str:
    """Get formr design documentation. Call get_documentation_sections(topic) first to list
    available section names, then pass section= to retrieve just that H2 block.
    Omit section to get the full topic."""
    return doc.get_documentation(topic, section)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_documentation_topics(ctx: Context = None) -> list[dict]:
    """List all available documentation topics."""
    return doc.get_topics()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_documentation_sections(
    topic: Literal["item-types", "run-concepts", "r-code", "survey-json", "examples", "best-practices", "editing-tools", "unit-types-advanced", "data-access", "patterns", "custom-r-and-secrets"],
    ctx: Context = None,
) -> list[dict]:
    """List the H2 sections available within a documentation topic.
    Use this before get_documentation to find the specific section you need,
    then pass its name as the section argument."""
    return doc.get_sections(topic)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_patterns(ctx: Context = None) -> list[dict]:
    """List the available run-design patterns for complex runs.

    Each entry has a name, a title, and the problem it solves. When a request matches one
    (balancing/condition assignment, waiting rooms, loading screens, live aggregate feedback,
    adaptive loops, personalized emails, external API/SMS calls, DRY R functions), call
    get_pattern(name) to learn the approach instead of re-deriving it from scratch."""
    return patterns_lib.list_patterns()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_pattern(name: str, ctx: Context = None) -> dict:
    """Get a run-design pattern's approach: the problem it solves, when to use it, the
    structure (which units/fields), how it works, the reusable R idioms (key_r), and gotchas.

    Informational, not a copy-paste template — real runs differ too much for a fixed unit
    blueprint. Read it, then build the units adapted to the run with add_run_unit / Edit,
    reusing the key_r snippets and renaming to the run's real survey/item names. Finish with
    analyze_run + update_run_structure_from_file. Call list_patterns() first to see names."""
    return patterns_lib.get_pattern(name)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def summarize_run(name: RunName, detail: Literal["units", "items"] = "items", ctx: Context = None) -> str:
    """Summarize a run structure from the local file. Returns a readable overview of units and their items.

    Must call get_run_structure_to_file(name) first to fetch the structure.

    Use detail='units' for just unit-level info (no items), or detail='items' (default) to include all survey items.
    Strips HTML from labels for readability.
    """
    validate_run_name(name)
    return summarize_run_structure(name, detail=detail)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def find_run_items(name: RunName, query: str | None = None, item_type: str | None = None, ctx: Context = None) -> str:
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
def analyze_run(name: RunName, ctx: Context = None) -> str:
    """Analyze a run structure for errors and warnings. Checks R syntax, variable references, branch flow, item consistency, and common mistakes.

    Must call get_run_structure_to_file(name) first to fetch the structure.

    Returns a structured report with error/warning counts. R syntax validation requires R to be installed.
    """
    validate_run_name(name)
    return run_analysis(name)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False, openWorldHint=False))
def add_run_unit(name: RunName, unit_type: str, position: int, description: str = "",
                insert_mode: Literal["shift", "overwrite"] = "shift",
                unit_fields: dict | None = None, ctx: Context = None) -> str:
    """Add a unit to a local run structure file. The file must exist (fetch with get_run_structure_to_file first).

    unit_fields — unit-type-specific fields (see get_unit_types() for full schema):
      Branch/SkipForward/SkipBackward: condition (R expr), if_true (int position)
      Email: subject, body, account_id (int), recipient_field
      Survey: study_id (int) or survey_data (dict)
      External: address (URL or R code)
      Wait: body (int position — NOT display content)
      Page/Endpage: body (markdown)
      Pause: wait_minutes, wait_until_time, wait_until_date, relative_to

    insert_mode: 'shift' (default) shifts units at >= position up by 10; 'overwrite' replaces. Position references are auto-remapped.
    """
    validate_run_name(name)
    return editing_add_run_unit(name, unit_type, position, description=description,
                               insert_mode=insert_mode, **(unit_fields or {}))


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=False, openWorldHint=False))
def remove_run_unit(name: RunName, position: int, compact: bool = False, ctx: Context = None) -> str:
    """Remove a unit at the given position from the local run structure file.

    The file must exist (fetch with get_run_structure_to_file first).
    After removing, call update_run_structure_from_file to upload.
    compact=True shifts higher positions down by 1 and remaps references; dangling references are reported.
    """
    validate_run_name(name)
    return editing_remove_run_unit(name, position, compact=compact)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False, openWorldHint=False))
def duplicate_run_units(name: RunName, from_positions: list[int], to_start_position: int,
                        shift_existing: bool = True, ctx: Context = None) -> str:
    """Copy units at from_positions to new positions starting at to_start_position in the local run structure file.

    Copies units in original order with gaps of 10 (e.g., 100, 110, 120...).
    shift_existing=True (default) shifts conflicting units up; False errors on conflicts.
    Position references are automatically remapped. The file must exist (fetch with get_run_structure_to_file first).
    """
    validate_run_name(name)
    return editing_duplicate_run_units(name, from_positions, to_start_position,
                                       shift_existing=shift_existing)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False, openWorldHint=False))
def shift_run_positions(name: RunName, from_position: int, delta: int, ctx: Context = None) -> str:
    """Shift all units at positions >= from_position by delta in the local run structure file.

    Positive delta shifts up (making room), negative shifts down (closing gaps).
    Position references are automatically remapped. The file must exist (fetch with get_run_structure_to_file first).
    """
    validate_run_name(name)
    return editing_shift_run_positions(name, from_position, delta)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False, openWorldHint=False))
def renormalize_positions(name: RunName, spacing: Annotated[int, Field(ge=1)] = 10, ctx: Context = None) -> str:
    """Renumber all unit positions to clean multiples of spacing while preserving order.

    Safe to call on already-clean structures. Position references are automatically remapped.
    Useful after edits that leave gaps (e.g., compact removal shifts by 1).
    The file must exist (fetch with get_run_structure_to_file first).
    """
    validate_run_name(name)
    return editing_renormalize_positions(name, spacing=spacing)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False, openWorldHint=True))
async def open_flowchart(name: RunName, ctx: Context = None) -> str:
    """Open a flowchart visualization of a run in the browser.

    Uploads the local run structure to the formr Flowchart Generator (an external
    Cloudflare Worker) and returns a shareable URL. The link expires after 24 hours.
    """
    validate_run_name(name)

    filepath = run_filepath(name)

    if not filepath.exists():
        raise FileNotFoundError(
            f"No local file for run '{name}'. "
            f"Call get_run_structure_to_file(\"{name}\") first."
        )

    with open(filepath, encoding="utf-8") as f:
        structure = json.load(f)

    if not isinstance(structure, dict) or "units" not in structure:
        raise ValueError(f"Invalid run structure in {filepath}: missing 'units' key")

    payload = json.dumps(structure, separators=(",", ":"))
    if len(payload) > 1024 * 1024:
        raise ValueError(
            f"Run structure is too large ({len(payload) / 1024:.0f} KB). "
            f"Maximum size is 1 MB."
        )

    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{FLOWCHART_URL}/api/share",
            content=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()

    webbrowser.open(result["url"])

    return f"Flowchart link for run '{name}' (expires in 24h):\n\n  {result['url']}"


if __name__ == "__main__":
    mcp.run()
