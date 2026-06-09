"""Shared utilities for run name validation and file path handling.

These are used across server.py, editing.py, analysis.py, and summarize.py.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

WORKSPACE_DIR = Path(".formr")

VALID_NAME = __import__("re").compile(r"^[a-z][a-z0-9-]{2,254}$")


def validate_run_name(name: str) -> None:
    """Validate a run name. Raises ValueError if invalid.

    Name must start with a letter, contain only a-z, 0-9, hyphens,
    and be 3-255 characters long.
    """
    if not VALID_NAME.match(name):
        raise ValueError(
            f"Invalid run name '{name}'. "
            f"Name must start with a letter, contain only a-z, 0-9, hyphens, "
            f"and be 3-255 characters long."
        )


def safe_run_filepath(name: str) -> Path:
    """Validate name and return a safe file path within the workspace.

    Raises ValueError if name is invalid or path traversal is detected.
    """
    validate_run_name(name)
    path = (WORKSPACE_DIR / f"{name}.json").resolve()
    workspace_resolved = WORKSPACE_DIR.resolve()
    if not str(path).startswith(str(workspace_resolved)):
        raise ValueError("Path traversal detected: file path escapes workspace directory")
    return path


def run_filepath(name: str) -> Path:
    """Like safe_run_filepath but also creates the workspace directory if needed."""
    path = safe_run_filepath(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_structure(name: str) -> dict:
    """Load a run structure from the workspace.

    Raises FileNotFoundError if the file does not exist.
    """
    filepath = safe_run_filepath(name)
    if not filepath.exists():
        raise FileNotFoundError(
            f"No local file for run '{name}'. "
            f"Call get_run_structure_to_file(\"{name}\") first."
        )
    with open(filepath) as f:
        return json.load(f)


def save_structure(name: str, structure: dict) -> str:
    """Save a run structure to the workspace, creating a backup first.

    Returns a summary string like 'Saved 5 units to .formr/name.json'.
    """
    path = safe_run_filepath(name)
    bak_path = path.with_suffix(".json.bak")
    if path.exists():
        shutil.copy2(str(path), str(bak_path))
    with open(path, "w") as f:
        json.dump(structure, f, indent=4, ensure_ascii=False)
    units = len(structure.get("units", []))
    return f"Saved {units} units to {path}"