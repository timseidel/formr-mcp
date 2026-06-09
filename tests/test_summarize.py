import os
import sys
import json

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from formr_mcp.summarize import summarize_run_structure, find_items, _strip_html, _truncate


SAMPLE_RUN = {
    "name": "test-run",
    "settings": {"title": "Test Study", "public": 2},
    "units": [
        {
            "type": "Survey",
            "position": 10,
            "description": "welcome",
            "survey_data": {
                "name": "welcome",
                "items": [
                    {
                        "type": "note",
                        "name": "note_welcome",
                        "label": "<h1>Welcome!</h1>",
                        "optional": 1,
                    },
                    {
                        "type": "mc",
                        "name": "consent",
                        "label": "Do you agree?",
                        "choices": {"1": "Yes", "2": "No"},
                        "optional": 0,
                    },
                    {
                        "type": "submit",
                        "name": "page1",
                        "label": "Continue",
                        "optional": 0,
                    },
                ],
            },
        },
        {
            "type": "SkipForward",
            "position": 20,
            "condition": "consent == 2",
            "if_true": 60,
            "description": "skip to end if no consent",
            "automatically_jump": 1,
            "automatically_go_on": 1,
        },
        {
            "type": "Survey",
            "position": 30,
            "description": "personality",
            "survey_data": {
                "name": "personality",
                "items": [
                    {
                        "type": "mc_heading",
                        "name": "likert_head",
                        "label": "",
                        "choices": {"1": "SD", "2": "D", "3": "N", "4": "A", "5": "SA"},
                    },
                    {
                        "type": "mc",
                        "name": "bfi_e_1",
                        "label": "I am outgoing.",
                        "choice_list": "likert_head",
                    },
                    {
                        "type": "mc",
                        "name": "bfi_n_1",
                        "label": "I worry often.",
                        "choice_list": "likert_head",
                    },
                    {
                        "type": "text",
                        "name": "open_comment",
                        "label": "Any comments?",
                    },
                    {
                        "type": "calculate",
                        "name": "score_e",
                        "value": "mean(bfi_e_1)",
                        "label": "",
                    },
                    {
                        "type": "submit",
                        "name": "page2",
                        "label": "Submit",
                    },
                ],
            },
        },
        {
            "type": "Pause",
            "position": 40,
            "description": "wait 1 day",
            "wait_minutes": 1440,
        },
        {
            "type": "Endpage",
            "position": 50,
            "body": "<h2>Thank you!</h2><p>You're done.</p>",
        },
        {
            "type": "Endpage",
            "position": 60,
            "body": "You were filtered out.",
        },
    ],
}


@pytest.fixture
def run_file(tmp_path, monkeypatch):
    import formr_mcp.utils as utils_mod

    monkeypatch.setattr("formr_mcp.utils.WORKSPACE_DIR", tmp_path / "ws")
    filepath = tmp_path / "ws" / "test-run.json"
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps(SAMPLE_RUN))
    return filepath


class TestStripHtml:
    def test_basic_tags(self):
        assert _strip_html("<h1>Hello</h1>") == "Hello"

    def test_nested_tags(self):
        assert _strip_html("<div><b>Bold</b> text</div>") == "Bold text"

    def test_img_tag(self):
        assert _strip_html('<img src="x.png" alt="Logo">') == ""
        assert _strip_html("<p>Before <img src='x.png'> after</p>") == "Before after"

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_no_html(self):
        assert _strip_html("Plain text") == "Plain text"


class TestTruncate:
    def test_short_string(self):
        assert _truncate("Hello", 10) == "Hello"

    def test_long_string(self):
        assert _truncate("A" * 200, 120) == "A" * 117 + "..."

    def test_exact_length(self):
        assert _truncate("A" * 120, 120) == "A" * 120


class TestSummarizeRunStructure:
    def test_items_detail_includes_items(self, run_file):
        result = summarize_run_structure("test-run", detail="items")
        assert 'Survey "welcome" (3 items)' in result
        assert "[mc] consent: Do you agree?" in result
        assert "[note] note_welcome: Welcome!" in result

    def test_units_detail_omits_items(self, run_file):
        result = summarize_run_structure("test-run", detail="units")
        assert 'Survey "welcome" (3 items)' in result
        assert "[mc] consent" not in result

    def test_skip_forward_shows_condition(self, run_file):
        result = summarize_run_structure("test-run")
        assert "SkipForward → 60" in result
        assert "consent == 2" in result

    def test_endpage_body_is_cleaned(self, run_file):
        result = summarize_run_structure("test-run")
        assert "Thank you! You're done." in result
        assert "<h2>" not in result

    def test_pause_shows_wait_minutes(self, run_file):
        result = summarize_run_structure("test-run")
        assert "Wait: 1440 minutes" in result

    def test_settings_shown(self, run_file):
        result = summarize_run_structure("test-run")
        assert "Title: Test Study" in result
        assert "Visibility: link-accessible" in result

    def test_calculate_shows_value(self, run_file):
        result = summarize_run_structure("test-run")
        assert "= mean(bfi_e_1)" in result

    def test_file_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("formr_mcp.utils.WORKSPACE_DIR", tmp_path / "nonexistent")
        with pytest.raises(FileNotFoundError, match="No local file"):
            summarize_run_structure("missing")

    def test_empty_label_note(self, run_file):
        result = summarize_run_structure("test-run")
        lines = result.split("\n")
        mc_heading_lines = [l for l in lines if "likert_head" in l]
        assert len(mc_heading_lines) == 1
        assert "[mc_heading]" in mc_heading_lines[0]


class TestFindItems:
    def test_search_by_name_prefix(self, run_file):
        result = find_items("test-run", query="bfi")
        assert "bfi_e_1" in result
        assert "bfi_n_1" in result
        assert "2 match(es)" in result

    def test_search_by_label_text(self, run_file):
        result = find_items("test-run", query="agree")
        assert "consent" in result

    def test_filter_by_type(self, run_file):
        result = find_items("test-run", item_type="mc")
        assert "consent" in result
        assert "bfi_e_1" in result
        assert "[mc]" in result
        assert "[submit]" not in result

    def test_combined_query_and_type(self, run_file):
        result = find_items("test-run", query="bfi", item_type="mc")
        assert "bfi_e_1" in result
        assert "bfi_n_1" in result
        assert "[mc]" in result

    def test_no_matches(self, run_file):
        result = find_items("test-run", query="nonexistent_xyz")
        assert "No items found" in result

    def test_no_filters_returns_all(self, run_file):
        result = find_items("test-run")
        assert "consent" in result
        assert "bfi_e_1" in result

    def test_file_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("formr_mcp.utils.WORKSPACE_DIR", tmp_path / "nonexistent")
        with pytest.raises(FileNotFoundError, match="No local file"):
            find_items("missing")

    def test_html_stripped_from_labels(self, run_file):
        result = find_items("test-run", query="Welcome")
        assert "Welcome!" in result
        assert "<h1>" not in result