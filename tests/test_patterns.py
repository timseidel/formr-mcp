import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from formr_mcp import documentation as doc
from formr_mcp import patterns
from formr_mcp.analysis import _check_variable_references
from formr_mcp.summarize import summarize_run_structure
from formr_mcp.utils import save_structure


EXPECTED_NAMES = {
    "loading-screen",
    "balanced-assignment",
    "covariate-balancing",
    "waiting-room",
    "live-aggregate-feedback",
    "adaptive-loop",
    "personalized-email",
    "external-api-dispatch",
    "json-state-store",
    "dry-r-functions",
}


class TestRegistry:
    def test_expected_patterns_present(self):
        assert set(patterns.pattern_names()) == EXPECTED_NAMES

    def test_pattern_names_unique(self):
        names = patterns.pattern_names()
        assert len(names) == len(set(names))

    def test_list_patterns_shape(self):
        catalog = patterns.list_patterns()
        assert len(catalog) == len(EXPECTED_NAMES)
        for entry in catalog:
            assert set(entry) == {"name", "title", "problem"}
            assert all(isinstance(entry[k], str) and entry[k] for k in entry)

    def test_get_pattern_unknown_raises_with_available(self):
        with pytest.raises(ValueError) as exc:
            patterns.get_pattern("does-not-exist")
        msg = str(exc.value)
        assert "does-not-exist" in msg
        assert "loading-screen" in msg


class TestPatternContents:
    @pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
    def test_informational_fields_present(self, name):
        p = patterns.get_pattern(name)
        for key in ("name", "title", "problem", "when_to_use", "source",
                    "structure", "how_it_works", "key_r", "gotchas"):
            assert key in p, f"{name} missing {key}"
        assert p["name"] == name
        assert isinstance(p["structure"], str) and p["structure"].strip()
        assert isinstance(p["how_it_works"], str) and p["how_it_works"].strip()
        assert isinstance(p["gotchas"], list) and p["gotchas"]
        assert "improvement_materials/" in p["source"]

    def test_no_copy_paste_blueprint(self):
        # Patterns inform; they must not ship a drop-in unit blueprint.
        for name in patterns.pattern_names():
            assert "blueprint" not in patterns.get_pattern(name)

    @pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
    def test_key_r_well_formed(self, name):
        key_r = patterns.get_pattern(name)["key_r"]
        assert isinstance(key_r, list)
        for snippet in key_r:
            assert set(snippet) == {"label", "code"}
            assert snippet["label"].strip()
            assert snippet["code"].strip()


class TestCustomRAndSecrets:
    def test_dry_pattern_references_custom_r(self):
        p = patterns.get_pattern("dry-r-functions")
        blob = (p["structure"] + p["how_it_works"]).lower()
        assert "custom_r" in blob

    def test_external_api_uses_secrets_and_custom_r(self):
        p = patterns.get_pattern("external-api-dispatch")
        codes = " ".join(s["code"] for s in p["key_r"])
        assert ".formr$secret_" in codes  # credentials from run secrets
        assert "custom_r" in (p["how_it_works"] + codes).lower()

    def test_json_state_store_models_append_only_and_races(self):
        p = patterns.get_pattern("json-state-store")
        blob = (p["how_it_works"] + " " + " ".join(p["gotchas"])).lower()
        # formr is append-only (new row per evaluation) — the correct mental model.
        assert "append-only" in blob
        assert "new" in blob and "row" in blob
        # The hazard is races on stale snapshots, NOT lost writes / clobbered cells.
        assert "race" in blob
        assert "no locking" in blob or "atomic" in blob
        assert "lost write" in blob  # explicitly stated there are none
        # And reads must resolve history to the latest per key.
        assert "latest" in blob
        # Schema-match-with-session and tombstone gotchas must be present.
        assert any("session" in g and "fallback" in g.lower() for g in p["gotchas"])
        assert any("tombstone" in g.lower() for g in p["gotchas"])

    def test_doc_topic_registered(self):
        names = [t["name"] for t in doc.get_topics()]
        assert "custom-r-and-secrets" in names
        body = doc.get_documentation("custom-r-and-secrets")
        assert ".formr$secret_" in body
        assert "custom_r" in body

    def test_var_ref_check_skips_custom_r_names(self):
        """A `name$col` whose `name` is defined in settings.custom_r must NOT be flagged as a
        missing survey — custom_r globals are injected into every R context."""
        structure = {
            "settings": {"custom_r": "lookup <- data.frame(a = 1)"},
            "units": [
                {"type": "Survey", "position": 10, "survey_data": {
                    "name": "s", "items": [
                        {"type": "calculate", "name": "c1", "item_order": 1,
                         "value": "lookup$a + 1"},
                    ]}},
            ],
        }
        assert _check_variable_references(structure) == []

    def test_var_ref_check_still_flags_real_missing_survey(self):
        structure = {
            "settings": {},
            "units": [
                {"type": "Survey", "position": 10, "survey_data": {
                    "name": "s", "items": [
                        {"type": "calculate", "name": "c1", "item_order": 1,
                         "value": "nonexistent$col + 1"},
                    ]}},
            ],
        }
        findings = _check_variable_references(structure)
        assert any("nonexistent" in f["message"] for f in findings)


class TestSummarizeSurfacesCustomRAndSecrets:
    def test_summary_lists_custom_r_functions_and_secrets(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORMR_WORKSPACE_DIR", str(tmp_path))
        # utils caches WORKSPACE_DIR at import; patch it directly too.
        import formr_mcp.utils as utils
        monkeypatch.setattr(utils, "WORKSPACE_DIR", tmp_path)
        structure = {
            "name": "demo-run",
            "settings": {
                "custom_r": "is_done <- function(x) TRUE\nhelper2 = function(y) y",
                "secrets": ["sms_id", "sms_pw"],
            },
            "units": [
                {"type": "Survey", "position": 10, "survey_data": {
                    "name": "s", "items": [
                        {"type": "submit", "name": "submit", "item_order": 1}]}},
            ],
        }
        save_structure("demo-run", structure)
        out = summarize_run_structure("demo-run", detail="units")
        assert "custom_r functions: is_done, helper2" in out
        assert ".formr$secret_sms_id" in out
        assert ".formr$secret_sms_pw" in out
