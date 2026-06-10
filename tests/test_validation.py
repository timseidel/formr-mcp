import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from formr_mcp.validation import validate_survey_data, validate_structure


class TestSurveyDataSettings:
    def _make_survey_unit(self, name, items, settings=None):
        unit = {
            "type": "Survey",
            "position": 10,
            "description": name,
            "special": "",
            "survey_data": {
                "name": name,
                "items": items,
            },
        }
        if settings is not None:
            unit["survey_data"]["settings"] = settings
        return unit

    def test_use_paging_nonzero_rejected(self):
        items = [{"type": "note", "name": "n1", "label": "Hi", "optional": 1}]
        unit = self._make_survey_unit("demo", items, {"use_paging": 1})
        errors = validate_structure({"units": [unit]})
        paging_errors = [e for e in errors if "use_paging" in e]
        assert len(paging_errors) == 1
        assert "must be 0 or omitted" in paging_errors[0]

    def test_use_paging_zero_accepted(self):
        items = [{"type": "note", "name": "n1", "label": "Hi", "optional": 1}]
        unit = self._make_survey_unit("demo", items, {"use_paging": 0})
        errors = validate_structure({"units": [unit]})
        paging_errors = [e for e in errors if "use_paging" in e]
        assert len(paging_errors) == 0

    def test_use_paging_absent_accepted(self):
        items = [{"type": "note", "name": "n1", "label": "Hi", "optional": 1}]
        unit = self._make_survey_unit("demo", items)
        errors = validate_structure({"units": [unit]})
        paging_errors = [e for e in errors if "use_paging" in e]
        assert len(paging_errors) == 0

    def test_page_items_rejected(self):
        items = [{"type": "note", "name": "n1", "label": "Hi", "optional": 1}]
        unit = self._make_survey_unit("demo", items, {"page_items": ["item1"]})
        errors = validate_structure({"units": [unit]})
        pi_errors = [e for e in errors if "page_items" in e]
        assert len(pi_errors) == 1
        assert "not supported" in pi_errors[0]

    def test_both_forbidden_settings_rejected(self):
        items = [{"type": "note", "name": "n1", "label": "Hi", "optional": 1}]
        unit = self._make_survey_unit("demo", items, {"use_paging": 1, "page_items": ["n1"]})
        errors = validate_structure({"units": [unit]})
        assert len(errors) >= 2

    def test_valid_settings_accepted(self):
        items = [{"type": "note", "name": "n1", "label": "Hi", "optional": 1}]
        unit = self._make_survey_unit("demo", items, {
            "add_percentage_points": 1,
            "enable_instant_validation": 0,
            "unlinked": 0,
        })
        errors = validate_structure({"units": [unit]})
        forbidden_errors = [e for e in errors if "use_paging" in e or "page_items" in e]
        assert len(forbidden_errors) == 0

    def test_use_paging_string_value_rejected(self):
        items = [{"type": "note", "name": "n1", "label": "Hi", "optional": 1}]
        unit = self._make_survey_unit("demo", items, {"use_paging": "1"})
        errors = validate_structure({"units": [unit]})
        paging_errors = [e for e in errors if "use_paging" in e]
        assert len(paging_errors) == 1