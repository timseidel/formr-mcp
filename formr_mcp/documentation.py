_TOPICS = {}


def _topic(name: str, title: str):
    def deco(fn):
        _TOPICS[name] = {"title": title, "get": fn}
        return fn
    return deco


def get_topics() -> list[dict]:
    return [
        {"name": k, "title": v["title"]}
        for k, v in _TOPICS.items()
    ]


def get_documentation(topic: str) -> str:
    entry = _TOPICS.get(topic)
    if not entry:
        available = ", ".join(_TOPICS)
        raise ValueError(
            f"Unknown topic '{topic}'. Available: {available}"
        )
    return entry["get"]()


# ── Item types ──────────────────────────────────────────────────────

@_topic("item-types", "All 56 survey item types with fields")
def _item_types():
    return r"""# Survey Item Types

Items are the building blocks of a survey. In a run structure's `survey_data`,
each item is a JSON object in the `items` array.

**Choices quick reference:**
- **Required** — items that show a list of options (radio, dropdown, checkbox group, slider, weekday picker, heading)
- **Forbidden** — items that collect free-form input, binary checkboxes, dates, files, or computed values
- **Optional** — `select_or_add_multiple` (can work with inline choices or without), `sex` (auto-set to Male/Female if absent)

## JSON vs Spreadsheet

When authoring items as JSON (via `survey_data`), these differences apply:

| Aspect | Spreadsheet | JSON |
|--------|-------------|------|
| `type` + options | Inline: `number 1,100,1` | Separate: `"type":"number"`, `"type_options":"1,100,1"` |
| `optional` | `*` = optional, `!` = force-required, empty = required | `1` = optional, `0`/absent = required |
| Inline choices | `choice1..choice12` columns | `choices` object: `{"cat":"Cat","dog":"Dog"}` or array |
| Choices sheet | Separate "choices" sheet | Not needed — inline `choices` or `choice_list` reference |
| Item order | `order` column (auto-assigned) | `item_order` field (int, 1-indexed) |
| `class` | Column in spreadsheet | Same field, same CSS values |
| `label_parsed` | Not applicable (no equivalent) | Set equal to `label`, or `null` |

## Common fields (every item type)

| JSON Field | Required | Description |
|------------|----------|-------------|
| `name` | **Yes** | Variable name. Alphanumeric + underscore, must start with a letter. |
| `type` | **Yes** | The item type string (see tables below). |
| `label` | No | Question text / display text. Supports HTML. |
| `optional` | No | `1` = optional, `0` or absent = required. |
| `class` | No | Space-separated CSS class names for styling. |
| `showif` | No | R expression controlling visibility (e.g. `age >= 18`). |
| `value` | No | Pre-set value, R expression, or `sticky` (remembers last value). |
| `choice_list` | No | Reference to a named choice list defined by another item. |
| `choices` | No | Inline choices as object `{"key":"Label"}` or array `["a","b"]`. |
| `type_options` | No | Type-specific options (min, max, step, auto, maxlength, etc.). |
| `item_order` | No | Integer display order (1-indexed). |
| `block_order` | No | Block ordering field for randomization. |
| `label_parsed` | No | HTML-parsed label. Set equal to `label` or `null`. |

## Display / Layout

| Type | Stores | Choices | Description |
|------|--------|---------|-------------|
| `note` | no storage | Forbidden | Markdown info text, full width. Always optional. Never saved. |
| `note_iframe` | no storage | Forbidden | Like `note` but renders R Markdown via iframe (OpenCPU knits the label). |
| `block` | no storage | Forbidden | Blocks progress until condition met. Rendered as danger alert. |
| `submit` | no storage | Forbidden | Submit/pagination button. `type_options` = auto-submit timeout (ms) or `auto`. |

## Simple Input

| Type | MySQL type | Choices | type_options | Description |
|------|-----------|---------|--------------|-------------|
| `text` | TEXT | Forbidden | maxlength or regex pattern | Single-line text. |
| `textarea` | MEDIUMTEXT | Forbidden | maxlength or regex pattern | Multi-line text. |
| `number` | INT UNSIGNED | Forbidden | `min,max,step` (default `0,10000000,1`) | Numeric input. Step `any` = decimals. |
| `letters` | TEXT | Forbidden | maxlength | Letters only (A-Za-z + basic punctuation). |
| `email` | VARCHAR(255) | Forbidden | — | Email with server-side validation. |
| `url` | VARCHAR(255) | Forbidden | — | URL with validation. |
| `tel` | VARCHAR(100) | Forbidden | — | Telephone (no validation pattern). |
| `cc` | VARCHAR(255) | Forbidden | — | Credit card with Luhn validation. |
| `blank` | TEXT | Forbidden | — | Only label text, no input field. Can still store a value. |

## Date / Time

All accept `min,max` in type_options (e.g. `2013-01-01,2014-01-01`, `-2years,now`). Choices: **Forbidden**.

| Type | MySQL | Format | Description |
|------|-------|--------|-------------|
| `date` | DATE | Y-m-d | Date picker. |
| `datetime` | DATETIME | Y-m-d\\TH:i | Date + time. |
| `datetime-local` | DATETIME | Y-m-d\\TH:i | Local date + time (no timezone). |
| `time` | TIME | H:i | Time picker. |
| `month` | DATE | Y-m | Month + year. |
| `week` | VARCHAR(9) | Y-mW | Week + year. |
| `year` | YEAR | Y | Year. |
| `yearmonth` | DATE | Y-m-01 | Year + month (stored as 1st of month). |

## Choice / Multiple Choice

| Type | MySQL | Widget | Choices | Description |
|------|-------|--------|---------|-------------|
| `mc` | TINYINT UNSIGNED | Radio buttons | **Required** | Choose one. Values stored as index number. |
| `mc_button` | TINYINT UNSIGNED | Button group (single) | **Required** | Like `mc` but rendered as large buttons. |
| `mc_multiple` | VARCHAR(40) | Checkboxes | **Required** | Choose many. Stored comma-separated. Always optional by default. |
| `mc_multiple_button` | VARCHAR(40) | Button group (multi) | **Required** | Like `mc_multiple` with toggle buttons. |
| `mc_heading` | no storage | Column header | **Required** | Displays choices as column headings. Not stored. |
| `check` | TINYINT UNSIGNED | Single checkbox | Forbidden | Yes/no (0 or 1). Does NOT use choices. |
| `check_button` | TINYINT UNSIGNED | Single toggle button | Forbidden | Like `check` but large toggle. |
| `choose_two_weekdays` | VARCHAR(40) | Special checkboxes | **Required** | Select exactly two weekdays. Must provide 5 choices (Mon–Fri). |

## Dropdown / Select

| Type | MySQL | Choices | Description |
|------|-------|---------|-------------|
| `select_one` | TEXT | **Required** | Dropdown, choose one. |
| `select_multiple` | VARCHAR(40) | **Required** | Multi-select dropdown. Values comma-separated. |
| `select_or_add_one` | TEXT | **Required** | Dropdown + custom option (Select2). `type_options`: `maxType` (max input length). |
| `select_or_add_multiple` | TEXT | Optional | Multi-select + add custom. `type_options`: `maxType,maxChoose`. Newline-separated. |
| `timezone` | VARCHAR(255) | Forbidden | All IANA timezones. Auto-detects browser timezone. |

## Slider / Scale

| Type | MySQL | Choices | type_options | Description |
|------|-------|---------|--------------|-------------|
| `range` | INT UNSIGNED | **Required** | `min,max,step` (0,100,1) | Slider. `choice1` = left label, `choice2` = right label. Value hidden. |
| `range_ticks` | INT UNSIGNED | **Required** | `min,max,step` (0,100,1) | Slider with tick marks + tooltip. |
| `rating_button` | SMALLINT | **Required** | `min,max,step` (1,5,1) | Numbered buttons. `choice1` = left label, `choice2` = right label. Choices auto-generated from range. |
| `sex` | TINYINT UNSIGNED | Optional | — | Male/female buttons. 1 = male, 2 = female. Choices auto-set if absent. |

## Hidden / Automatic (no user input)

All choices: **Forbidden**.

| Type | MySQL | type_options | Description |
|------|-------|--------------|-------------|
| `calculate` | MEDIUMTEXT | — | Executes R expression from `value`, stores result. |
| `hidden` | MEDIUMTEXT | — | Hidden input with preset `value`. Always optional. |
| `get` | TEXT | Query param name | Captures URL query string value (default: `referred_by`). |
| `server` | TEXT | $_SERVER key | Captures server variable (default: `HTTP_USER_AGENT`). |
| `browser` | TEXT | — | Alias for `server`. |
| `ip` | VARCHAR(46) | — | Stores participant's IP address. |
| `referrer` | TEXT | — | Stores last outside referrer URL. |
| `random` | INT UNSIGNED | `min,max` (0,1) | Generates random integer via `mt_rand()`. |

## File Upload

All accept optional `type_options` = max file size in MB. Choices: **Forbidden**.

| Type | Default accept | Description |
|------|----------------|-------------|
| `file` | image, video, audio, text, PDF | General file upload. Embeds as img/audio/video or link. |
| `image` | images + `capture=camera` | Image upload. Triggers camera on mobile. |
| `audio` | audio + `capture=microphone` | Audio upload. Uses microphone. |
| `video` | video + `capture=camcorder` | Video upload. Triggers camcorder. |

## Other

Choices: **Forbidden**.

| Type | MySQL | Description |
|------|-------|-------------|
| `geopoint` | TEXT | GPS coordinates via browser geolocation API. Read-only. |
| `color` | CHAR(7) | Color picker. Validates `#RRGGBB`. |

## PWA Family

| Type | MySQL | Choices | Description |
|------|-------|---------|-------------|
| `request_phone` | VARCHAR(20) | Forbidden | Detects mobile vs desktop. Shows QR code for phone transition. |
| `add_to_home_screen` | VARCHAR(20) | **Required** | Button to add PWA to home screen. |
| `push_notification` | TEXT | **Required** | Button to request push permission. Stores subscription JSON. |
| `request_cookie` | VARCHAR(20) | **Required** | Button for functional cookie consent. |

## Type Options (spreadsheet → JSON mapping)

In JSON, `type_options` is always a separate string field. When reading data
exported from spreadsheets, the type string may include inline options:

| Spreadsheet type column | JSON equivalent |
|------------------------|-----------------|
| `number 1,100,1` | `"type": "number", "type_options": "1,100,1"` |
| `text 100` | `"type": "text", "type_options": "100"` |
| `mc agreement` | `"type": "mc", "choice_list": "agreement"` |
| `submit auto` | `"type": "submit", "type_options": "auto"` |

When authoring JSON directly, always use the separate `type_options` and
`choice_list` fields — never embed options in the `type` string.

## Choice Lists

In JSON, define choices inline via the `choices` field (object or array)
or reference another item's choices via `choice_list`. There is no separate
choices sheet — the `choices` field on any item serves as the definition.
"""


# ── Run concepts ────────────────────────────────────────────────────

@_topic("run-concepts", "How runs work — flow, positions, branching")
def _run_concepts():
    return """# Run Concepts

## What is a run?

A **run** is an ordered composition of **units** that participants traverse.
Think of it as a study timeline. Units execute sequentially by `position`.
The participant moves from one position to the next unless a branch redirects them.

## Key rules

- **Units are ordered by `position`** — an integer field. Lower positions execute first.
- **Sequential flow by default** — when a unit completes, the participant moves to the next higher position.
- **Pages are endpoints** — `Page` and `Endpage` units end the session (no auto-progress).
- **Runs start with content** — the first unit (lowest position) must never be a `Page` or `Endpage`. Use a `Survey` or `Privacy` unit as the entry point. `Page` and `Endpage` only appear after branching (e.g., after a `SkipForward` filter) to end the run or stop ineligible participants.
- **Branches redirect** — `Branch`, `SkipForward`, and `SkipBackward` use an R `condition` expression.
  If `TRUE`, the participant jumps to the `if_true` position.
- **Surveys collect data** — a `Survey` unit links to a survey definition (either existing `study_id` or inline `survey_data`).
- **Emails are sent automatically** — `Email` units fire when reached (or on cron for `cron_only=1`).
- **Pauses wait** — `Pause`/`Wait` units stall progress until a time, date, or duration passes.
- **External redirects** — `External` units send participants to a URL or evaluate an R expression.

## Position spacing

Use spaced positions (10, 20, 30...) so you can insert units between existing ones later.
Positions are integers. Duplicate positions are not allowed.

## Unit flow diagram

```
position 10: Survey "demographics"
    ↓ (auto-advance after submit)
position 20: Branch "age check"
    ├─ condition: age < 18 → if_true: 40 (skip to end)
    ↓ (condition FALSE)
position 30: Survey "main study"
    ↓
position 40: Page "end"
```

## Common patterns

### Filter (SkipForward)
SkipForward at position 10 checks a condition. If TRUE, jump to position 30 (main study).
If FALSE, fall through to position 20 (end page).

### Diary loop (SkipBackward)
After the diary survey at position 40, a SkipBackward at 50 checks if enough entries exist.
If not enough, jump back to position 20 (pause until next reminder).

### Longitudinal study
Survey (wave 1) → Pause (1 year) → Email (invitation) → Survey (wave 2) → Endpage.

### Reminder system
Wait unit (60 min) → Email (reminder). The Wait's `body` holds the position to redirect
to if the participant advances manually. The Email uses `cron_only=1` so only the cron
daemon sends it (not on first visit).

## Settings

Use `update_run_settings(name, settings)` to change a run's settings.
Pass only the fields you want to change. Available settings:

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Study display title |
| `description` | string | Markdown study description |
| `footer_text` | string | Markdown footer text |
| `public_blurb` | string | Text shown on public run listing |
| `privacy` | string | Markdown privacy policy |
| `tos` | string | Markdown terms of service |
| `header_image_path` | string | Path to header image |
| `custom_css` | string | Custom CSS content (written to file) |
| `custom_js` | string | Custom JavaScript content (written to file) |
| `custom_r` | string | Custom R functions (written to file) |
| `cron_active` | 0/1 | Whether cron daemon processes this run |
| `use_material_design` | 0/1 | Material design theme toggle |
| `expiresOn` | string | Run expiry date (YYYY-MM-DD, must be future) |
| `expire_cookie_value` | int | Cookie lifetime value (combined with unit) |
| `expire_cookie_unit` | string | Cookie lifetime unit: seconds, minutes, hours, days, months, years |
| `public` | int | Visibility: 0=admin/test-users only, 2=accessible with link; 1 and 3 are rarely used |
| `locked` | 0/1 | Lock run to prevent modifications |

### Clearing settings

When clearing a run setting field (e.g. `header_image_path`), passing `null` via
`update_run_settings` may be silently ignored by the formr API. Use an empty
string `""` instead:

```
# Does NOT clear the field:
update_run_settings(name, {"header_image_path": null})

# Correctly clears the field:
update_run_settings(name, {"header_image_path": ""})
```
"""


# ── R code ──────────────────────────────────────────────────────────

@_topic("r-code", "R code in formr — conditions, values, knitr")
def _r_code():
    return """# R Code in formr

formr evaluates R code via **OpenCPU** for dynamic content. R is used in:

## 1. Branch conditions

The `condition` field on Branch/SkipForward/SkipBackward units is an R expression
that must evaluate to `TRUE` (jump) or `FALSE` (continue):

```
nrow(diary) < 20
```

```
age >= 18
```

## 2. Item values (`value` column)

The `value` column on items can be an R expression. The `calculate` item type
always executes its `value` as R:

| Value | Effect |
|-------|--------|
| `nrow(friend_rate)` | Count of previous entries in this survey |
| `friend_list[, paste0("name_friend", friend_nr)]` | Lookup from another survey |
| `sticky` | Preserves last entered value |
| `ifelse(sex, "his", "her")` | Conditional text |
| `now()` | Current timestamp |

## 3. Showif conditions

The `showif` column controls item visibility. It's an R expression that must
evaluate to `TRUE` (show) or `FALSE` (hide):

```
age >= 18
```

```
nrow(friend_rate) < friend_list$nr_friends
```

Use `//js_only` prefix for JavaScript-only conditions (no server round-trip):
```
//js_only
nr_friends >= 1
```

## 4. Labels and body content (knitr)

Labels, page bodies, and email bodies support R **knitr** inline code.
Wrap R code in:

- Inline: `` `r expr` `` — e.g. `` Please rate _`r name`_. ``
- Block: ```` ```{r} code ``` ```` — e.g. for plots, tables, datatables

Example with ggplot:
``````
```{r}
library(ggplot2)
qplot(age, height, data = demographics)
```
``````

Example with DT datatable:
``````
```{r}
library(DT)
datatable(friends, options = list(pageLength = 5))
```
``````

## 5. Pause/Wait timing

The `relative_to` field on Pause/Wait units can be an R expression returning
a timestamp:

```
library(lubridate)
time_passed(minutes = x_minutes) && hour(now()) > 9 && hour(now()) < 22
```

## 6. Referencing survey data

Access previously collected data using `survey_name$variable_name`:

- `demographics$age` — the `age` variable from the `demographics` survey
- `nrow(diary)` — number of rows submitted for the `diary` survey
- `friend_list[, "name_friend1"]` — specific column from another survey

## 7. Available R packages

formr's OpenCPU instance has many R packages pre-installed, including:
`lubridate`, `ggplot2`, `dplyr`, `tidyr`, `DT`, `knitr`, and others from
CRAN. The OpenCPU Dockerfile defines which packages are available.

## 8. Special variables

- `survey_run_sessions$session` — current participant's session code
- `survey_run_sessions$created` — when the session was created
- `login_link` — placeholder in email bodies, replaced with participant login URL
"""


# ── Survey JSON ─────────────────────────────────────────────────────

@_topic("survey-json", "How to author surveys as JSON (inline survey_data)")
def _survey_json():
    return r"""# Survey JSON Authoring

Surveys can be embedded directly in a run structure via the `survey_data`
field on a Survey unit, instead of uploading a separate spreadsheet. The
`survey_data` field is a JSON object containing the survey name, items,
and settings.

## Structure

```json
{
    "type": "Survey",
    "position": 10,
    "description": "demographics survey",
    "survey_data": {
        "name": "demographics",
        "items": [ ... ],
        "settings": { ... }
    }
}
```

## Items Array

Each item in `items` is a JSON object with these fields:

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `type` | **Yes** | string | Item type (see the item-types topic) |
| `name` | **Yes** | string | Variable name. Alphanumeric + underscore, must start with a letter. |
| `label` | **Yes** | string | Question text / display text. Supports HTML. |
| `optional` | No | int | `0` = required, `1` = optional. Default `0`. |
| `class` | No | string | Space-separated CSS class names. |
| `showif` | No | string | R expression controlling visibility (e.g. `age >= 18`). |
| `value` | No | string | Pre-set value, R expression, or `sticky` (remembers last value). |
| `choice_list` | No | string/null | Reference to a named choice list (from `choices` on another item). |
| `type_options` | No | string/null | Type-specific options (min,max,step, auto, maxlength, etc.). |
| `choices` | No | object or array/null | Inline choices (see below). |
| `block_order` | No | string | Block ordering field for randomization. |
| `item_order` | No | int | Display order (1-indexed, sequential). |
| `label_parsed` | No | string/null | HTML-parsed version of label. Set equal to `label` when creating; can be `null`. |

## Choices

Choices can be specified in two formats:

**Object format** (preferred):
```json
{
    "type": "mc",
    "name": "favorite_color",
    "label": "What's your favorite?",
    "choices": {
        "red": "Red",
        "blue": "Blue",
        "green": "Green"
    }
}
```

**Array format** (legacy, values = labels):
```json
{
    "type": "mc",
    "name": "datenschutz",
    "label": "Do you consent?",
    "choices": ["nein", "ja"]
}
```

When using `choice_list` instead of inline `choices`, reference another item's
name or a shared list name:
```json
{
    "type": "mc",
    "name": "item1",
    "label": "First item",
    "choice_list": "likert5",
    "choices": {
        "1": "Strongly disagree",
        "2": "Disagree",
        "3": "Neutral",
        "4": "Agree",
        "5": "Strongly agree"
    }
},
{
    "type": "mc",
    "name": "item2",
    "label": "Second item",
    "choice_list": "likert5"
}
```

## Type Options

In JSON, `type_options` is always a **separate string field**. Unlike the
spreadsheet format, you do NOT append options to the type string:

| Spreadsheet | JSON equivalent |
|-------------|-----------------|
| `number 1,100,1` | `"type": "number", "type_options": "1,100,1"` |
| `text 100` | `"type": "text", "type_options": "100"` |
| `submit auto` | `"type": "submit", "type_options": "auto"` |

## Optional Flag

In JSON, `optional` is an integer:
- `0` or absent = required
- `1` = optional
- (The spreadsheet `*` and `!` conventions do not apply to JSON.)

## Page Breaks

Same as spreadsheets: a `submit` item creates a page break. Items before it
are rendered as one page. Multiple `submit` items = multi-page survey.

```json
{"type": "submit", "name": "page1", "label": "Continue"}
```

## Settings Object

The `settings` object (optional) controls survey behavior:

```json
"settings": {
    "maximum_number_displayed": 0,
    "displayed_percentage_maximum": 100,
    "add_percentage_points": 0,
    "enable_instant_validation": 0,
    "expire_after": 0,
    "google_file_id": null,
    "unlinked": 0,
    "expire_invitation_after": 0,
    "expire_invitation_grace": 0,
    "hide_results": 0,
    "use_paging": 0
}
```

Most settings default to `0`/`false`. The key ones:
- `enable_instant_validation` — validate on blur (1) or on submit (0)
- `add_percentage_points` — show progress bar (%)
- `displayed_percentage_maximum` — progress bar max
- `unlinked` — allow anonymous (unlinked) sessions
- `hide_results` — hide results from participants

## Full Example

```json
{
    "type": "Survey",
    "description": "welcome and consent",
    "position": 10,
    "special": "",
    "survey_data": {
        "name": "welcome",
        "items": [
            {
                "type": "note",
                "name": "note_welcome",
                "label": "<h1>Welcome!</h1>",
                "optional": 1,
                "class": "label_align_center",
                "showif": "",
                "value": "",
                "block_order": "",
                "item_order": 1
            },
            {
                "type": "mc_button",
                "name": "consent",
                "label": "Do you consent?",
                "optional": 0,
                "class": "",
                "showif": "",
                "value": "",
                "choice_list": null,
                "type_options": null,
                "block_order": "",
                "item_order": 2,
                "choices": {
                    "1": "Yes",
                    "2": "No"
                }
            },
            {
                "type": "number",
                "name": "age",
                "label": "How old are you?",
                "optional": 0,
                "class": "",
                "showif": "consent == 1",
                "value": "",
                "choice_list": null,
                "type_options": "0,120,1",
                "block_order": "",
                "item_order": 3
            },
            {
                "type": "submit",
                "name": "page1",
                "label": "Continue",
                "optional": 0,
                "class": "",
                "showif": "",
                "value": "",
                "choice_list": null,
                "type_options": null,
                "block_order": "",
                "item_order": 4
            }
        ],
        "settings": {
            "maximum_number_displayed": 0,
            "displayed_percentage_maximum": 100,
            "add_percentage_points": 1,
            "enable_instant_validation": 0,
            "expire_after": 0,
            "google_file_id": null,
            "unlinked": 0,
            "expire_invitation_after": 0,
            "expire_invitation_grace": 0,
            "hide_results": 0,
            "use_paging": 0
        }
    }
}
```

## CSS Classes

Use the `class` field for layout control (same as spreadsheet):

| Class | Effect |
|-------|--------|
| `clear` | New line before this item |
| `right150` | Float right, 150px wide |
| `align_horizontally` | Display items side by side |
| `label_as_placeholder` | Use label as input placeholder text |
| `hide_label` | Hide the label, show only input |
| `label_align_center` | Center-align the label |
| `answer_align_center` | Center-align answer options |
| `mc_vertical` | Stack MC options vertically |
| `mc_width80` | Set MC item width to 80% |
| `right_offset100` | Right offset 100px |
| `space_bottom_30` | Bottom margin 30px |
| `hidden` | Visually hidden (useful for auto-submit) |

## Key Differences from Spreadsheet Authoring

1. No choices sheet — inline `choices` or `choice_list` references instead
2. No `choice1..choice12` columns — use `choices` object instead
3. `type_options` is a separate field, not appended to the type string
4. `optional` is `0`/`1` integer, not `*`/`!`
5. `label_parsed` should mirror `label` or be `null`
6. Items use `item_order` (int) instead of spreadsheet row `order`
7. No separate Google Sheets import — JSON is uploaded as part of the run structure
"""


# ── Examples ────────────────────────────────────────────────────────

@_topic("examples", "Example run structures you can learn from")
def _examples():
    return r"""# Example Run Structures

These are working examples from the formr documentation. Use them as reference
for designing your own runs.

---

## 1. Basic Diary

A daily diary study with reminder emails and a loop.

```json
{
    "name": "BasicDiary",
    "units": [
        {
            "type": "Survey",
            "description": "demographics and contact info",
            "position": 10,
            "special": ""
        },
        {
            "type": "Pause",
            "description": "diary beginning: a pause until the diary is accessible",
            "position": 20,
            "special": "",
            "wait_until_time": "17:00:00",
            "body": "## Thank you for your participation\r\n\r\nWe will invite you to participate again tomorrow around 5pm."
        },
        {
            "type": "Email",
            "description": "diary invitation: sent after the pause above expires",
            "position": 30,
            "special": "",
            "account_id": 2,
            "subject": "Diary invitation",
            "recipient_field": "most recent reported address",
            "body": "Dear participant,\r\n\r\nplease fill out your diary now.\r\n\r\n{{login_link}}"
        },
        {
            "type": "Survey",
            "description": "diary: main diary survey (this one is repeated)",
            "position": 40,
            "special": ""
        },
        {
            "type": "SkipBackward",
            "description": "end of diary loop",
            "position": 50,
            "special": "",
            "condition": "nrow(diary) < 20",
            "if_true": 20
        },
        {
            "type": "Endpage",
            "description": "end of study",
            "position": 60,
            "special": "",
            "body": "## It's over\r\n\r\nThanks for participating."
        }
    ]
}
```

**Pattern**: Survey → Pause → Email → Survey → SkipBackward(→Pause) → Endpage.

---

## 2. Experience Sampling (ESM)

Random-interval reminders throughout the day.

```json
{
    "name": "Experience_sampling",
    "units": [
        {
            "type": "Survey",
            "description": "get email, intro survey",
            "position": 10
        },
        {
            "type": "Pause",
            "description": "wait random time between 5-100min, only 9am-10pm",
            "position": 20,
            "relative_to": "library(lubridate)\r\nx_minutes = sample(5:100, 1)\r\nhour_now = hour(now())\r\ntime_passed(minutes = x_minutes) && hour_now > 9 && hour_now < 22",
            "body": "# Wait\r\nPlease wait for your first reminder."
        },
        {
            "type": "Email",
            "description": "reminder",
            "position": 30,
            "account_id": 1,
            "subject": "Time to tell us about your experiences!",
            "recipient_field": "most recent reported address",
            "body": "Time to tell us!\r\n\r\n{{login_link}}"
        },
        {
            "type": "Survey",
            "description": "experience sampling survey",
            "position": 40
        },
        {
            "type": "SkipBackward",
            "description": "loop the experience sampling",
            "position": 50,
            "condition": "nrow(experience_survey) < 100",
            "if_true": 30
        },
        {
            "type": "Endpage",
            "description": "end",
            "position": 60,
            "body": "kthxbye"
        }
    ]
}
```

**Key**: Uses `relative_to` with `lubridate` for random intervals, and `hour(now())` for time-of-day gating.

---

## 3. Filter / Screening

Skip participants who don't meet criteria.

```json
{
    "name": "Filter",
    "units": [
        {
            "type": "SkipForward",
            "description": "Filter condition, those with true can go on",
            "position": 10,
            "condition": "survey1$variable == 1",
            "automatically_jump": 1,
            "if_true": 30,
            "automatically_go_on": 1
        },
        {
            "type": "Endpage",
            "description": "Filtered people end here.",
            "position": 20,
            "title": "Filtered",
            "body": "You can't take part."
        }
    ]
}
```

**Pattern**: SkipForward (check condition → jump to 30) → Endpage (if condition false).

---

## 4. Reminder System

Send a reminder if participant hasn't responded within 60 minutes.

```json
{
    "name": "Reminder",
    "units": [
        {
            "type": "Wait",
            "description": "send a reminder if participant doesn't react within 60 minutes",
            "position": 10,
            "wait_minutes": 60,
            "body": 30
        },
        {
            "type": "Email",
            "description": "Reminder",
            "position": 20,
            "account_id": 2,
            "body": "Hey,\r\n\r\ndidn't you forget about your favourite study?\r\n{{login_link}}",
            "cron_only": 1
        }
    ]
}
```

**Key**: Wait's `body` = position to redirect on manual advance (30). Email's `cron_only=1` = only cron sends it.

---

## 5. Longitudinal Study

Wave-based design with 1-year gap.

```json
{
    "name": "Longitudinal_study",
    "units": [
        {
            "type": "Survey",
            "description": "wave1: initial survey, have to collect contact info here",
            "position": 110
        },
        {
            "type": "Pause",
            "description": "wait 1 year for wave 2",
            "position": 120,
            "wait_minutes": 525600,
            "body": "## Thank you\r\n\r\nWe'll recontact you in a year."
        },
        {
            "type": "Email",
            "description": "wave2: invitation",
            "position": 200,
            "account_id": 1,
            "subject": "Longitudinal study: Wave 2",
            "recipient_field": "most recent reported address",
            "body": "Remember us?\r\n\r\n{{login_link}}"
        },
        {
            "type": "Survey",
            "description": "wave2: survey",
            "position": 210
        },
        {
            "type": "Endpage",
            "description": "end",
            "position": 300,
            "body": "## Thank you\r\n\r\nYou could repeat 120-210 for more waves."
        }
    ],
    "settings": {
        "cron_active": 1,
        "footer_text": "Contact [study admin](mailto:email@example.com)"
    }
}
```

**Pattern**: Uses wide position gaps (110, 120, 200, 210, 300) to insert future waves.

---

## 6. Social Network Study

Complex multi-survey design with R calculations and dynamic item display.

The run has these units:
- Survey "friend_list" — asks how many friends, collects names/sex/type/size for up to 8 friends using `showif` conditions and inline choices
- Survey "friend_rate" — one friend at a time using `calculate` items to look up previous answers, inline R in labels, and `showif` on submit buttons to control flow
- SkipBackward — loops back to friend_rate until all friends rated
- Endpage — shows a DT datatable summary and ggplot

Key techniques demonstrated:
- `showif` with JavaScript-only (`//js_only`) for immediate client-side hide/show
- `calculate` items calling `nrow()`, `paste0()` for cross-survey lookups
- Inline R in labels: `` `r name` ``, `` `r his` ``
- Conditional submit buttons with different `showif` conditions

---

## 7. Inline Survey Data (JSON)

A run with surveys embedded directly in the structure via `survey_data`.
Each Survey unit defines its items inline as JSON objects.

```json
{
    "name": "RunWithInlineSurveys",
    "units": [
        {
            "type": "Survey",
            "description": "Consent and demographics",
            "position": 10,
            "special": "",
            "survey_data": {
                "name": "demographics",
                "items": [
                    {
                        "type": "note",
                        "name": "note_welcome",
                        "label": "<h1>Study Information</h1>",
                        "optional": 1,
                        "class": "label_align_center",
                        "showif": "",
                        "value": "",
                        "block_order": "",
                        "item_order": 1
                    },
                    {
                        "type": "mc_button",
                        "name": "consent",
                        "label": "Do you agree to participate?",
                        "optional": 0,
                        "class": "",
                        "showif": "",
                        "value": "",
                        "choice_list": null,
                        "type_options": null,
                        "block_order": "",
                        "item_order": 2,
                        "choices": {
                            "1": "Yes",
                            "2": "No"
                        }
                    },
                    {
                        "type": "number",
                        "name": "age",
                        "label": "Age in years",
                        "optional": 0,
                        "class": "",
                        "showif": "consent == 1",
                        "value": "",
                        "choice_list": null,
                        "type_options": "0,120,1",
                        "block_order": "",
                        "item_order": 3
                    },
                    {
                        "type": "submit",
                        "name": "page1",
                        "label": "Continue",
                        "optional": 0,
                        "class": "",
                        "showif": "",
                        "value": "",
                        "choice_list": null,
                        "type_options": null,
                        "block_order": "",
                        "item_order": 4
                    }
                ],
                "settings": {
                    "maximum_number_displayed": 0,
                    "displayed_percentage_maximum": 100,
                    "add_percentage_points": 1,
                    "enable_instant_validation": 0,
                    "expire_after": 0,
                    "google_file_id": null,
                    "unlinked": 0,
                    "expire_invitation_after": 0,
                    "expire_invitation_grace": 0,
                    "hide_results": 0,
                    "use_paging": 0
                }
            }
        },
        {
            "type": "Survey",
            "description": "Personality items with shared choice list",
            "position": 20,
            "special": "",
            "survey_data": {
                "name": "personality",
                "items": [
                    {
                        "type": "mc_heading",
                        "name": "head_likert",
                        "label": "",
                        "optional": 0,
                        "class": "mc_width80",
                        "showif": "",
                        "value": "",
                        "choice_list": null,
                        "type_options": null,
                        "block_order": "",
                        "item_order": 1,
                        "choices": {
                            "1": "Strongly disagree",
                            "2": "Disagree",
                            "3": "Neutral",
                            "4": "Agree",
                            "5": "Strongly agree"
                        }
                    },
                    {
                        "type": "mc",
                        "name": "extraversion",
                        "label": "I enjoy social gatherings.",
                        "optional": 0,
                        "class": "hide_label mc_width80",
                        "showif": "",
                        "value": "",
                        "choice_list": "head_likert",
                        "type_options": null,
                        "block_order": "",
                        "item_order": 2
                    },
                    {
                        "type": "mc",
                        "name": "neuroticism",
                        "label": "I worry about things often.",
                        "optional": 0,
                        "class": "hide_label mc_width80",
                        "showif": "",
                        "value": "",
                        "choice_list": "head_likert",
                        "type_options": null,
                        "block_order": "",
                        "item_order": 3
                    },
                    {
                        "type": "submit",
                        "name": "page2",
                        "label": "Submit",
                        "optional": 0,
                        "class": "",
                        "showif": "",
                        "value": "",
                        "choice_list": null,
                        "type_options": "auto",
                        "block_order": "",
                        "item_order": 4
                    }
                ],
                "settings": {
                    "maximum_number_displayed": 0,
                    "displayed_percentage_maximum": 100,
                    "add_percentage_points": 1,
                    "enable_instant_validation": 0,
                    "expire_after": 0,
                    "google_file_id": null,
                    "unlinked": 0,
                    "expire_invitation_after": 0,
                    "expire_invitation_grace": 0,
                    "hide_results": 0,
                    "use_paging": 0
                }
            }
        },
        {
            "type": "Endpage",
            "description": "end",
            "position": 30,
            "special": "",
            "body": "## Thank you"
        }
    ]
}
```

**Key techniques demonstrated:**
- `survey_data` embedding items as JSON objects with all fields
- `choices` as key-value objects (string → string)
- Shared choice list via `choice_list` referencing a `mc_heading` item's choices
- `type_options` as separate field (e.g. `"0,120,1"`, `"auto"`)
- Survey settings object controlling progress bar and validation
- Multiple Survey units in one run, each with independent survey_data
"""


# ── Best practices ──────────────────────────────────────────────────

@_topic("best-practices", "Design patterns and recommendations")
def _best_practices():
    return """# Best Practices

## Run Design

**Position spacing**: Use gaps (10, 20, 30, ...) so you can insert units between
existing ones. Never use consecutive positions (1, 2, 3) unless the run is final.

**Branch always has a fallthrough**: Make sure there's a default path when all
branch conditions are FALSE. The fallthrough continues to the next position.

**Test with a small session**: Before launching, create a test session with
`testing=true` and walk through the entire run.

**Cron for automated actions**: Set `cron_active=1` in settings and use
`cron_only=1` on Email units that should only fire from cron, not on first visit.

## Survey Design

**Inline survey_data**: Embed surveys directly in the run structure via
`survey_data` on Survey units. Each survey defines `name`, `items[]`,
and optional `settings{}`.

**Items as JSON objects**: Each item has fields: `type`, `name`, `label`,
`optional` (0/1), `class`, `showif`, `value`, `choice_list`, `type_options`,
`choices`, `block_order`, `item_order`. Set `label_parsed` equal to `label`.

**Inline choices**: Use the `choices` field instead of a separate choices
sheet. Object format gives explicit key-value pairs; array format uses
values as labels.

**Shared choice lists**: Define choices on one item (e.g. a `mc_heading`),
then reference them via `choice_list` on other items. No separate sheet needed.

**Page breaks with submit**: A `submit` item creates a page break. Items
before it are one page. Multiple submit items = multi-page survey.

**Showif for adaptive questioning**: Use `showif` to show/hide items based on
previous answers. Prefix with `//js_only` for instant client-side response.

**Calculate for computed values**: Use `calculate` items for on-the-fly
computations. The R expression in `value` runs when the page is submitted.

**Validation via type_options**: Set min/max on numbers, patterns on text,
auto-submit on submit buttons.

**Sticky values**: Use `value = "sticky"` on items to preserve the last entered
value (useful for diary studies).

## R Code

**Reference surveys by name**: The survey name becomes the data frame name.
`demographics$age` accesses the `age` variable from the `demographics` survey.

**nrow() for counting**: `nrow(diary)` counts how many times the `diary` survey
has been filled out. Useful for loop conditions.

**lubridate for timing**: Use `library(lubridate)` for date arithmetic in pause
conditions and showif expressions.

**Package availability**: OpenCPU has many CRAN packages. If you need one that's
not installed, it needs to be added to the OpenCPU Dockerfile.

## Common Mistakes

1. **Survey unit without study_id or survey_data** — a Survey unit must either
   reference an existing survey (`study_id`) or include inline `survey_data`.
   Without one of these, the survey won't work. When embedding `survey_data`,
   also include the original `study_id` if the survey already exists on the
   server (the API preserves the link).
2. **Wrong account_id on Email units** — the email account must be owned by the
   run owner. Check ownership before importing.
3. **Branch if_true points to itself** — creates an infinite loop. Always point
   to a different position.
4. **Missing cron_active** — Pause/Wait/Email units won't process without
   `cron_active=1` in settings.
 5. **Overlapping position numbers** — duplicates cause undefined behavior.
    Always use unique positions.
6. **Page/Endpage as first unit** — the lowest position in a run must be a
     content unit like `Survey` or `Privacy`. `Page` and `Endpage` end the
     session and cannot serve as the entry point. If you need a landing page
     for filtered-out participants, put a `Survey` first, then a `SkipForward`
     to check eligibility, and let the `Endpage` follow as a fallthrough.
 7. **Using `null` to clear settings** — when clearing a run setting field (e.g.
    `header_image_path`), passing `null` may be silently ignored by the formr
    API. Use an empty string `""` instead: `update_run_settings(name,
    {"header_image_path": ""})`.
"""
