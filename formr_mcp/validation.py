KNOWN_TYPES = {
    "Survey",
    "Page",
    "Email",
    "Branch",
    "SkipForward",
    "SkipBackward",
    "External",
    "Pause",
    "Wait",
    "Shuffle",
    "PushMessage",
    "Privacy",
    "Endpage",
}

BRANCH_TYPES = {"Branch", "SkipForward", "SkipBackward"}

# Items that MUST define choices (mirrors PHP $hasChoices = true, no auto-generation)
CHOICES_REQUIRED = {
    "mc", "mc_button", "mc_multiple", "mc_multiple_button", "mc_heading",
    "choose_two_weekdays",
    "select_one", "select_multiple", "select_or_add_one",
    "range", "range_ticks", "rating_button",
    "add_to_home_screen", "push_notification", "request_cookie",
}

# Items that MUST NOT have choices (mirrors PHP $hasChoices = false)
CHOICES_FORBIDDEN = {
    "check", "check_button",
    "submit", "note", "note_iframe", "block",
    "text", "textarea", "number", "letters", "email", "url", "tel", "cc", "blank",
    "date", "datetime", "datetime-local", "time", "month", "week", "year", "yearmonth",
    "color", "geopoint",
    "file", "image", "audio", "video",
    "calculate", "hidden", "get", "server", "browser", "ip", "referrer", "random",
    "request_phone", "timezone",
}

# Items where choices are allowed but not required
# (PHP $hasChoices = true but has a validation exception or auto-generates)
CHOICES_OPTIONAL = {
    "select_or_add_multiple",
    "sex",
}

KNOWN_ITEM_TYPES = {
    "note", "note_iframe", "block", "submit",
    "text", "textarea", "number", "letters", "email", "url", "tel", "cc", "blank",
    "date", "datetime", "datetime-local", "time", "month", "week", "year", "yearmonth",
    "mc", "mc_button", "mc_multiple", "mc_multiple_button", "mc_heading",
    "check", "check_button", "choose_two_weekdays",
    "select_one", "select_multiple", "select_or_add_one", "select_or_add_multiple",
    "timezone",
    "range", "range_ticks", "rating_button", "sex",
    "calculate", "hidden", "get", "server", "browser", "ip", "referrer", "random",
    "file", "image", "audio", "video",
    "geopoint", "color",
    "request_phone", "add_to_home_screen", "push_notification", "request_cookie",
}


def get_unit_type_schemas() -> dict:
    return {
        "Survey": {
            "required": ["type", "position"],
            "optional": ["description", "special", "study_id", "survey_data"],
            "description": "A survey/questionnaire presented to the participant.",
        },
        "Page": {
            "required": ["type", "position"],
            "optional": ["description", "special", "body"],
            "description": "A markdown page with optional R knitr rendering.",
        },
        "Email": {
            "required": ["type", "position"],
            "optional": [
                "description",
                "special",
                "subject",
                "account_id",
                "recipient_field",
                "body",
                "cron_only",
            ],
            "description": "Sends an email to the participant.",
        },
        "Branch": {
            "required": ["type", "position", "condition", "if_true"],
            "optional": [
                "description",
                "special",
                "automatically_jump",
                "automatically_go_on",
            ],
            "description": "Branching unit: if condition is true, jump to if_true position.",
        },
        "SkipForward": {
            "required": ["type", "position", "condition", "if_true"],
            "optional": [
                "description",
                "special",
                "automatically_jump",
                "automatically_go_on",
            ],
            "description": "Skip forward unit: if condition is true, skip to if_true position.",
        },
        "SkipBackward": {
            "required": ["type", "position", "condition", "if_true"],
            "optional": ["description", "special"],
            "description": "Skip backward unit: allows looping back to earlier position.",
        },
        "External": {
            "required": ["type", "position"],
            "optional": ["description", "special", "address", "api_end"],
            "description": "External redirect or R expression evaluation.",
        },
        "Pause": {
            "required": ["type", "position"],
            "optional": [
                "description",
                "special",
                "wait_until_time",
                "wait_until_date",
                "wait_minutes",
                "relative_to",
                "body",
            ],
            "description": "Pauses the run for a set duration or until a date/time.",
        },
        "Wait": {
            "required": ["type", "position"],
            "optional": [
                "description",
                "special",
                "wait_until_time",
                "wait_until_date",
                "wait_minutes",
                "relative_to",
                "body",
            ],
            "description": "Wait unit (extends Pause). Body stores the advance-on-click position.",
        },
        "Shuffle": {
            "required": ["type", "position"],
            "optional": ["description", "special", "groups"],
            "description": "Randomly shuffles participants into groups.",
        },
        "PushMessage": {
            "required": ["type", "position"],
            "optional": [
                "description",
                "special",
                "message",
                "topic",
                "priority",
                "time_to_live",
                "badge_count",
                "vibrate",
                "require_interaction",
                "renotify",
                "silent",
            ],
            "description": "Sends a push notification.",
        },
        "Privacy": {
            "required": ["type", "position"],
            "optional": ["description", "special", "privacy_label", "tos_label"],
            "description": "Privacy consent and terms of service checkboxes.",
        },
        "Endpage": {
            "required": ["type", "position"],
            "optional": ["description", "special", "body"],
            "description": "End page displayed at the conclusion of a run.",
        },
    }


def validate_survey_data(survey_data: object, unit_label: str) -> list[str]:
    errors = []

    if not isinstance(survey_data, dict):
        errors.append(f"{unit_label}: 'survey_data' must be a JSON object")
        return errors

    name = survey_data.get("name")
    if not isinstance(name, str) or not name:
        errors.append(f"{unit_label}: 'survey_data.name' is required and must be a non-empty string")

    items = survey_data.get("items")
    if not isinstance(items, list):
        errors.append(f"{unit_label}: 'survey_data.items' is required and must be an array")
        return errors

    if len(items) == 0:
        errors.append(f"{unit_label}: 'survey_data.items' must have at least one item")

    for j, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"{unit_label}: item at index {j} must be a JSON object")
            continue

        item_type = item.get("type")
        if not isinstance(item_type, str) or not item_type:
            errors.append(f"{unit_label}: item at index {j} is missing 'type'")
        elif item_type not in KNOWN_ITEM_TYPES:
            errors.append(
                f"{unit_label}: item at index {j}: unknown item type '{item_type}'"
            )

        item_name = item.get("name")
        if not isinstance(item_name, str) or not item_name:
            errors.append(f"{unit_label}: item at index {j} is missing 'name'")

        optional = item.get("optional")
        if optional is not None and (not isinstance(optional, int) or optional not in (0, 1)):
            errors.append(
                f"{unit_label}: item '{item_name or j}': 'optional' must be 0 or 1, "
                f"got {type(optional).__name__}"
            )

        item_order = item.get("item_order")
        if item_order is not None and (not isinstance(item_order, int) or isinstance(item_order, bool)):
            errors.append(
                f"{unit_label}: item '{item_name or j}': 'item_order' must be an integer"
            )

        choice_list = item.get("choice_list")
        choices = item.get("choices")
        has_choices = bool(choices) or bool(choice_list)

        if choices is not None and not isinstance(choices, (dict, list)):
            errors.append(
                f"{unit_label}: item '{item_name or j}': 'choices' must be an object or array"
            )

        if item_type in CHOICES_REQUIRED and not has_choices:
            errors.append(
                f"{unit_label}: item '{item_name or j}' (type '{item_type}'): "
                f"requires 'choices' or 'choice_list' — this item type must have choices defined"
            )
        elif item_type in CHOICES_FORBIDDEN and choices:
            errors.append(
                f"{unit_label}: item '{item_name or j}' (type '{item_type}'): "
                f"must not have 'choices' — this item type does not support choices"
            )

        type_options = item.get("type_options")
        if type_options is not None and not isinstance(type_options, (str, type(None))):
            errors.append(
                f"{unit_label}: item '{item_name or j}': 'type_options' must be a string or null"
            )

    settings = survey_data.get("settings")
    if settings is not None and not isinstance(settings, dict):
        errors.append(f"{unit_label}: 'survey_data.settings' must be a JSON object")

    return errors


def validate_structure(data: dict) -> list[str]:
    errors = []

    if not isinstance(data, dict):
        return ["Structure must be a JSON object"]

    if "units" not in data:
        return ["Structure must contain a 'units' array"]
    if not isinstance(data["units"], list):
        return ["'units' must be an array"]

    units = data["units"]
    positions = {}

    for i, unit in enumerate(units):
        if not isinstance(unit, dict):
            errors.append(f"Unit at index {i} must be a JSON object")
            continue

        unit_type = unit.get("type")
        if not isinstance(unit_type, str) or not unit_type:
            errors.append(f"Unit at index {i} is missing 'type'")
            continue

        if unit_type not in KNOWN_TYPES:
            known = ", ".join(sorted(KNOWN_TYPES))
            errors.append(
                f"Unit '{unit_type}' at index {i}: unknown type. "
                f"Valid types: {known}"
            )
            continue

        if "position" not in unit:
            errors.append(f"Unit '{unit_type}' at index {i} is missing 'position'")
            continue

        pos = unit["position"]
        if not isinstance(pos, int) or isinstance(pos, bool):
            errors.append(
                f"Unit '{unit_type}' at index {i}: 'position' must be an integer, got {type(pos).__name__}"
            )
            continue

        if pos in positions:
            errors.append(
                f"Duplicate position {pos}: '{unit_type}' at index {i} "
                f"and '{positions[pos]}' at index {positions[f'_{pos}']}"
            )
        else:
            positions[pos] = unit_type
            positions[f"_{pos}"] = i

        if unit_type in BRANCH_TYPES:
            if_true = unit.get("if_true")
            if if_true is not None and (
                not isinstance(if_true, int) or isinstance(if_true, bool)
            ):
                errors.append(
                    f"Branch unit '{unit_type}' at position {pos}: "
                    f"'if_true' must be an integer, got {type(if_true).__name__}"
                )

        if unit_type == "Survey" and "survey_data" in unit:
            survey_errors = validate_survey_data(
                unit["survey_data"],
                f"Survey unit at position {pos}",
            )
            errors.extend(survey_errors)

    for i, unit in enumerate(units):
        if not isinstance(unit, dict):
            continue
        pos = unit.get("position")
        unit_type = unit.get("type", "?")
        if not isinstance(pos, int):
            continue
        if unit_type in BRANCH_TYPES:
            if_true = unit.get("if_true")
            if isinstance(if_true, int) and if_true not in positions:
                errors.append(
                    f"Branch unit '{unit_type}' at position {pos}: "
                    f"'if_true'={if_true} does not match any unit position"
                )

    if positions:
        first_pos = min(p for p in positions if isinstance(p, int))
        first_type = positions[first_pos]
        if first_type in ("Page", "Endpage"):
            errors.append(
                f"The run starts with a '{first_type}' at position {first_pos} — "
                f"Page and Endpage units must follow a content unit (e.g. Survey), "
                f"not lead the run. Use a Survey or Privacy unit as the entry point."
            )

    return errors
