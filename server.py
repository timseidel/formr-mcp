from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context

from formr_mcp.auth import AuthError, check_credentials
from formr_mcp.client import FormrClient, FormrClientError
from formr_mcp import documentation as doc
from formr_mcp.validation import get_unit_type_schemas, validate_structure

dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path)

BASE_URL = os.getenv("FORMR_BASE_URL", "")
CLIENT_ID = os.getenv("FORMR_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("FORMR_CLIENT_SECRET", "")


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

Use `get_unit_types()` for available unit schemas, `get_run_structure()`
to inspect existing runs, `update_run_settings()` to change run-level
settings (title, description, privacy, public, locked, etc.),
and `get_documentation(topic)` to learn about survey item types, R code
patterns, JSON survey authoring, and design best practices.""",
)


def _client(ctx: Context) -> FormrClient:
    return ctx.request_context.lifespan_context


@mcp.tool()
async def whoami(ctx: Context = None) -> dict:
    """Get the authenticated user's profile."""
    return await _client(ctx).get_user_me()


@mcp.tool()
async def list_runs(name: str | None = None, ctx: Context = None) -> list[dict]:
    """List all runs. Optionally filter by exact name."""
    return await _client(ctx).get_runs(name)


@mcp.tool()
async def create_run(name: str, ctx: Context = None) -> dict:
    """Create a new run. Name must start with a letter, contain only a-z, 0-9, hyphens, and be 3-255 chars.

    Returns the created run name and link on success. Requires `run:write` OAuth scope.
    """
    require(name, "name")
    client = _client(ctx)
    return await client.create_run(name)


@mcp.tool()
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


@mcp.tool()
async def get_run(name: str, ctx: Context = None) -> dict:
    """Get a single run by exact name."""
    require(name, "name")
    return await _client(ctx).get_run(name)


@mcp.tool()
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
    client = _client(ctx)
    await client.patch_run(name, settings)
    return await client.get_run(name)


@mcp.tool()
async def get_run_structure(name: str, ctx: Context = None) -> dict:
    """Download the full run structure (units, settings, files). Use this to inspect a run before editing."""
    require(name, "name")
    client = _client(ctx)
    await client.get_run(name)
    return await client.get_run_structure(name)


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


@mcp.tool()
async def update_run_structure(
    name: str, structure: dict, ctx: Context = None
) -> dict:
    """Replace a run's entire unit structure. Pass the modified structure JSON.

    Validation runs first — any errors are returned before hitting the server.
    On success, returns the updated structure from the server.
    """
    require(name, "name")
    client = _client(ctx)

    _normalize_survey_choices(structure)
    errors = validate_structure(structure)
    if errors:
        raise ValueError(
            "Structure validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    await client.get_run(name)
    await client.put_run_structure(name, structure)
    return await client.get_run_structure(name)


@mcp.tool()
def get_unit_types(ctx: Context = None) -> dict:
    """Get all supported run unit types and their required/optional fields. Use this to understand what can be created."""
    return get_unit_type_schemas()


@mcp.tool()
def get_documentation(topic: str, ctx: Context = None) -> str:
    """Get formr design documentation. Topics: item-types, run-concepts, r-code, survey-json, examples, best-practices. Use this to learn how to design formr surveys and runs."""
    return doc.get_documentation(topic)


@mcp.tool()
def get_documentation_topics(ctx: Context = None) -> list[dict]:
    """List all available documentation topics."""
    return doc.get_topics()


if __name__ == "__main__":
    mcp.run()
