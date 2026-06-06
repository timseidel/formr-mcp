import sys
sys.path.insert(0, "/Users/admin/Documents/repos/formr-mcp")

from server import _normalize_survey_choices


def test_mc_with_choices_sets_choice_list():
    structure = {
        "units": [{
            "type": "Survey",
            "position": 10,
            "survey_data": {
                "name": "test",
                "items": [
                    {"type": "mc", "name": "q1", "label": "Test?", "choices": {"1": "A", "2": "B"}},
                ],
            },
        }]
    }
    _normalize_survey_choices(structure)
    item = structure["units"][0]["survey_data"]["items"][0]
    assert item["choice_list"] == "q1"


def test_existing_choice_list_preserved():
    structure = {
        "units": [{
            "type": "Survey",
            "position": 10,
            "survey_data": {
                "name": "test",
                "items": [
                    {"type": "mc", "name": "q1", "label": "Test?", "choices": {"1": "A", "2": "B"}, "choice_list": "existing"},
                ],
            },
        }]
    }
    _normalize_survey_choices(structure)
    item = structure["units"][0]["survey_data"]["items"][0]
    assert item["choice_list"] == "existing"


def test_no_choices_noop():
    structure = {
        "units": [{
            "type": "Survey",
            "position": 10,
            "survey_data": {
                "name": "test",
                "items": [
                    {"type": "text", "name": "q1", "label": "Test?"},
                ],
            },
        }]
    }
    _normalize_survey_choices(structure)
    item = structure["units"][0]["survey_data"]["items"][0]
    assert "choice_list" not in item


def test_select_one_choices():
    structure = {
        "units": [{
            "type": "Survey",
            "position": 10,
            "survey_data": {
                "name": "test",
                "items": [
                    {"type": "select_one", "name": "color", "label": "Color?", "choices": {"r": "Red", "b": "Blue"}},
                ],
            },
        }]
    }
    _normalize_survey_choices(structure)
    item = structure["units"][0]["survey_data"]["items"][0]
    assert item["choice_list"] == "color"


def test_mc_heading_shared_list():
    structure = {
        "units": [{
            "type": "Survey",
            "position": 10,
            "survey_data": {
                "name": "test",
                "items": [
                    {"type": "mc_heading", "name": "likert5", "label": "", "choices": {"1": "SD", "2": "D", "3": "N", "4": "A", "5": "SA"}},
                    {"type": "mc", "name": "item1", "label": "Q1", "choice_list": "likert5"},
                ],
            },
        }]
    }
    _normalize_survey_choices(structure)
    items = structure["units"][0]["survey_data"]["items"]
    assert items[0]["choice_list"] == "likert5"
    assert items[1]["choice_list"] == "likert5"


def test_missing_name_no_crash():
    structure = {
        "units": [{
            "type": "Survey",
            "position": 10,
            "survey_data": {
                "name": "test",
                "items": [
                    {"type": "mc", "choices": {"1": "A"}},
                ],
            },
        }]
    }
    _normalize_survey_choices(structure)
    item = structure["units"][0]["survey_data"]["items"][0]
    assert "choice_list" not in item


def test_choices_array_format():
    structure = {
        "units": [{
            "type": "Survey",
            "position": 10,
            "survey_data": {
                "name": "test",
                "items": [
                    {"type": "mc", "name": "q1", "label": "Test?", "choices": ["Yes", "No"]},
                ],
            },
        }]
    }
    _normalize_survey_choices(structure)
    item = structure["units"][0]["survey_data"]["items"][0]
    assert item["choice_list"] == "q1"


if __name__ == "__main__":
    test_mc_with_choices_sets_choice_list()
    test_existing_choice_list_preserved()
    test_no_choices_noop()
    test_select_one_choices()
    test_mc_heading_shared_list()
    test_missing_name_no_crash()
    test_choices_array_format()
    print("All tests passed!")
