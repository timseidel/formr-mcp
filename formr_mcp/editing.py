"""Tools for incrementally editing a local run structure file.

These operate on .formr/<name>.json (which must exist, fetched via
get_run_structure_to_file). After editing, call update_run_structure_from_file
to upload.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

WORKSPACE_DIR = Path(".formr")

VALID_NAME = re.compile(r"^[a-z][a-z0-9-]{2,254}$")

# Unit type → required + optional fields (mirrors validation.py schemas)
UNIT_SCHEMAS: dict[str, dict[str, list[str]]] = {
    "Survey": {
        "required": ["type", "position"],
        "optional": ["description", "special", "study_id", "survey_data"],
    },
    "Page": {
        "required": ["type", "position"],
        "optional": ["description", "special", "body"],
    },
    "Email": {
        "required": ["type", "position"],
        "optional": ["description", "special", "subject", "account_id", "recipient_field", "body", "cron_only"],
    },
    "Branch": {
        "required": ["type", "position", "condition", "if_true"],
        "optional": ["description", "special", "automatically_jump", "automatically_go_on"],
    },
    "SkipForward": {
        "required": ["type", "position", "condition", "if_true"],
        "optional": ["description", "special", "automatically_jump", "automatically_go_on"],
    },
    "SkipBackward": {
        "required": ["type", "position", "condition", "if_true"],
        "optional": ["description", "special"],
    },
    "External": {
        "required": ["type", "position"],
        "optional": ["description", "special", "address", "api_end", "expire_after"],
    },
    "Pause": {
        "required": ["type", "position"],
        "optional": ["description", "special", "wait_until_time", "wait_until_date", "wait_minutes", "relative_to", "body"],
    },
    "Wait": {
        "required": ["type", "position"],
        "optional": ["description", "special", "wait_until_time", "wait_until_date", "wait_minutes", "relative_to", "body"],
    },
    "Shuffle": {
        "required": ["type", "position"],
        "optional": ["description", "special", "groups"],
    },
    "PushMessage": {
        "required": ["type", "position"],
        "optional": ["description", "special", "message", "topic", "priority", "time_to_live", "badge_count", "vibrate", "require_interaction", "renotify", "silent"],
    },
    "Privacy": {
        "required": ["type", "position"],
        "optional": ["description", "special", "privacy_label", "tos_label"],
    },
    "Endpage": {
        "required": ["type", "position"],
        "optional": ["description", "special", "body"],
    },
}

VALID_UNIT_TYPES = list(UNIT_SCHEMAS.keys())

# Fields that must be integers
INT_FIELDS = {"position", "if_true", "account_id", "cron_only", "automatically_jump", "automatically_go_on", "api_end", "expire_after"}


def _validate_run_name(name: str) -> None:
    if not VALID_NAME.match(name):
        raise ValueError(
            f"Invalid run name '{name}'. "
            f"Name must start with a letter, contain only a-z, 0-9, hyphens, "
            f"and be 3-255 characters long."
        )


def _safe_path(name: str) -> Path:
    _validate_run_name(name)
    path = (WORKSPACE_DIR / f"{name}.json").resolve()
    workspace_resolved = WORKSPACE_DIR.resolve()
    if not str(path).startswith(str(workspace_resolved)):
        raise ValueError("Path traversal detected: file path escapes workspace directory")
    return path


def _load(name: str) -> dict:
    path = _safe_path(name)
    if not path.exists():
        raise FileNotFoundError(
            f"No local file for run '{name}'. "
            f"Call get_run_structure_to_file(\"{name}\") first."
        )
    with open(path) as f:
        return json.load(f)


def _save(name: str, structure: dict) -> str:
    path = _safe_path(name)
    # Backup existing file
    bak_path = path.with_suffix(".json.bak")
    if path.exists():
        import shutil
        shutil.copy2(str(path), str(bak_path))
    with open(path, "w") as f:
        json.dump(structure, f, indent=4, ensure_ascii=False)
    units = len(structure.get("units", []))
    return f"Saved {units} units to {path}"


def _coerce_field(key: str, value: Any) -> Any:
    """Coerce a field value to the expected type for formr."""
    if key in INT_FIELDS and isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if key == "position" and isinstance(value, str) and value.isdigit():
        return int(value)
    if key == "if_true" and isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def _build_unit(unit_type: str, position: int, **kwargs) -> dict:
    """Build a unit dict with defaults for the given type."""
    if unit_type not in UNIT_SCHEMAS:
        raise ValueError(
            f"Unknown unit type '{unit_type}'. "
            f"Valid types: {', '.join(sorted(UNIT_SCHEMAS))}"
        )

    schema = UNIT_SCHEMAS[unit_type]
    unit: dict[str, Any] = {"type": unit_type, "position": position}

    # Add description if provided
    if "description" in kwargs:
        unit["description"] = kwargs.pop("description")
    elif "special" not in kwargs:
        unit["description"] = ""

    # Add special if provided
    if "special" in kwargs:
        unit["special"] = kwargs.pop("special")

    # Add position-specific defaults
    if unit_type == "SkipForward":
        unit.setdefault("automatically_jump", 1)
        unit.setdefault("automatically_go_on", 1)

    # Add remaining kwargs
    for key, value in kwargs.items():
        unit[key] = _coerce_field(key, value)

    # Ensure required fields are present
    for req in schema["required"]:
        if req not in unit:
            if req == "type":
                pass  # already set
            elif req == "position":
                pass  # already set
            elif req == "condition":
                raise ValueError(f"Branch/Skip unit requires 'condition'")
            elif req == "if_true":
                raise ValueError(f"Branch/Skip unit requires 'if_true'")

    return unit


# ── Public API ────────────────────────────────────────────────────────

def add_run_unit(name: str, unit_type: str, position: int, **kwargs) -> str:
    """Add a unit to the local run structure file.

    If insert_mode is 'shift' and the position is already occupied,
    all units at that position or higher are shifted up by 10.
    If insert_mode is 'overwrite', any existing unit at that position is replaced.
    Default is 'shift'.
    """
    insert_mode = kwargs.pop("insert_mode", "shift")
    structure = _load(name)
    units = structure.get("units", [])

    unit = _build_unit(unit_type, position, **kwargs)

    existing_positions = {u.get("position") for u in units if isinstance(u.get("position"), int)}

    if position in existing_positions:
        if insert_mode == "overwrite":
            units = [u for u in units if u.get("position") != position]
        elif insert_mode == "shift":
            # Shift all units at >= position up by 10
            for u in units:
                p = u.get("position")
                if isinstance(p, int) and p >= position:
                    u["position"] = p + 10
        else:
            raise ValueError(f"Unknown insert_mode '{insert_mode}'. Use 'shift' or 'overwrite'.")

    units.append(unit)
    units.sort(key=lambda u: u.get("position", 0))
    structure["units"] = units

    saved = _save(name, structure)
    desc = unit.get("description", "")
    return (
        f"Added {unit_type} at position {position}"
        + (f" ('{desc}')" if desc else "")
        + (f" (shifted existing positions >= {position} up by 10)" if insert_mode == "shift" and position in existing_positions else "")
        + f". {saved}"
    )


def remove_run_unit(name: str, position: int, compact: bool = False) -> str:
    """Remove a unit at the given position from the local run structure file.

    If compact is True, shifts all units at higher positions down to fill the gap.
    """
    structure = _load(name)
    units = structure.get("units", [])

    removed = None
    remaining = []
    for u in units:
        p = u.get("position")
        if p == position:
            removed = u
        else:
            remaining.append(u)

    if removed is None:
        raise ValueError(f"No unit found at position {position}")

    if compact:
        for u in remaining:
            p = u.get("position")
            if isinstance(p, int) and p > position:
                u["position"] = p - 1

    structure["units"] = remaining
    saved = _save(name, structure)

    unit_type = removed.get("type", "?")
    desc = removed.get("description", "")
    gap_shift = " (compacted positions to fill gap)" if compact else ""
    return (
        f"Removed {unit_type} at position {position}"
        + (f" ('{desc}')" if desc else "")
        + f"{gap_shift}. {saved}"
    )


def duplicate_run_units(name: str, from_positions: list[int], to_start_position: int,
                         shift_existing: bool = True) -> str:
    """Copy units at from_positions to new positions starting at to_start_position.

    Units are copied in order of their original positions. New positions are
    assigned sequentially starting at to_start_position, with gaps incrementing
    by default (10, 20, 30...).

    If shift_existing is True and any new position conflicts with existing units,
    all existing units at >= to_start_position are shifted up to make room.
    """
    structure = _load(name)
    units = structure.get("units", [])

    units_by_pos = {u.get("position"): u for u in units if isinstance(u.get("position"), int)}

    # Find source units
    source_units = []
    for p in sorted(from_positions):
        if p not in units_by_pos:
            raise ValueError(f"No unit found at position {p}")
        source_units.append(copy.deepcopy(units_by_pos[p]))

    if not source_units:
        raise ValueError("from_positions is empty")

    # Calculate new positions
    # Use a step of 10 between each copied unit group, preserving relative order
    new_positions = []
    for i in range(len(source_units)):
        new_positions.append(to_start_position + (i * 10))

    # Check for conflicts and shift if needed
    existing_positions = {u.get("position") for u in units if isinstance(u.get("position"), int)}
    max_new_pos = max(new_positions)

    if shift_existing:
        # Find the minimum existing position that conflicts
        conflicts = [p for p in existing_positions if to_start_position <= p]
        if conflicts:
            shift_by = max(new_positions) - min(conflicts) + 10
            for u in units:
                p = u.get("position")
                if isinstance(p, int) and p >= min(conflicts) and p not in from_positions:
                    u["position"] = p + shift_by
    else:
        for np in new_positions:
            if np in existing_positions:
                raise ValueError(
                    f"Position {np} already occupied. Use shift_existing=True or choose a different to_start_position."
                )

    # Create new units
    src_desc_prefix = ""
    for src, new_pos in zip(source_units, new_positions):
        new_unit = copy.deepcopy(src)
        new_unit["position"] = new_pos
        # Add "copy" prefix to description to distinguish from originals
        # But don't stack "copy:" prefixes on re-duplication
        if "description" in new_unit and new_unit["description"]:
            desc = new_unit["description"]
            if not desc.startswith("copy: "):
                new_unit["description"] = f"copy: {desc}"
        units.append(new_unit)

    units.sort(key=lambda u: u.get("position", 0))
    structure["units"] = units
    saved = _save(name, structure)

    return (
        f"Duplicated {len(source_units)} unit(s) from positions "
        f"{','.join(str(p) for p in sorted(from_positions))} → "
        f"new positions {','.join(str(p) for p in new_positions)}. {saved}"
    )


def shift_run_positions(name: str, from_position: int, delta: int) -> str:
    """Shift all units at positions >= from_position by delta.

    Positive delta shifts positions up (making room). Negative delta shifts
    positions down (closing gaps). Useful for inserting groups of units or
    compacting gaps.

    Does not update branch if_true targets — those must be updated manually.
    """
    if delta == 0:
        return "No change: delta is 0."

    structure = _load(name)
    units = structure.get("units", [])

    affected = 0
    for u in units:
        p = u.get("position")
        if isinstance(p, int) and p >= from_position:
            u["position"] = p + delta
            affected += 1

    if affected == 0:
        return f"No units at positions >= {from_position} to shift."

    units.sort(key=lambda u: u.get("position", 0))
    structure["units"] = units
    saved = _save(name, structure)

    direction = "up" if delta > 0 else "down"
    return (
        f"Shifted {affected} unit(s) at positions >= {from_position} "
        f"{direction} by {abs(delta)}. "
        f"Note: Check and update any branch if_true targets manually. {saved}"
    )


def generate_survey_items(description: str, survey_name: str = "survey",
                          language: str = "en") -> str:
    """Generate a survey items JSON array based on a description.

    This is a helper that returns JSON text you can use when editing a run
    structure. It does NOT modify any file — you paste the result into your
    run structure or use it with add_run_unit.

    The description should specify what items you want (e.g., "BFI-15 personality
    questionnaire in German with 5-point Likert scale").
    """
    # This is intentionally a lightweight stub — the LLM is the real generator.
    # We just provide structure and guidance.
    return json.dumps({
        "hint": "Use the description to ask the LLM to generate items. "
                "Then paste the items array into your run structure.",
        "description": description,
        "survey_name": survey_name,
        "language": language,
        "template": [
            {
                "type": "note",
                "name": "note_intro",
                "label": f"<h2>{description}</h2>",
                "optional": 1,
                "item_order": 1,
            },
            {
                "type": "submit",
                "name": "page1",
                "label": "Continue" if language == "en" else "Weiter",
                "item_order": 2,
            },
        ],
    }, indent=2, ensure_ascii=False)