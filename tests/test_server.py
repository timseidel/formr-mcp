import sys
import os
import json
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

sys.path.insert(0, "/Users/admin/Documents/repos/formr-mcp")

import server as server_mod
from server import VALID_SETTINGS, run_filepath, WORKSPACE_DIR, _normalize_survey_choices


class TestValidSettings:
    def test_known_settings_complete(self):
        expected = {
            "title", "description", "footer_text", "public_blurb",
            "privacy", "tos", "header_image_path", "custom_css", "custom_js",
            "custom_r", "cron_active", "use_material_design", "expiresOn",
            "expire_cookie_value", "expire_cookie_unit", "public", "locked",
        }
        assert VALID_SETTINGS == expected


class TestSettingsValidation:
    def test_rejects_unknown_settings(self):
        unknown = {"foo"} - VALID_SETTINGS
        assert unknown == {"foo"}

    def test_rejects_mix_of_known_and_unknown(self):
        settings = {"title": "Hello", "invalid_key": 1}
        unknown = set(settings) - VALID_SETTINGS
        assert unknown == {"invalid_key"}

    def test_all_known_settings_pass(self):
        settings = {"title": "Test", "locked": 0}
        unknown = set(settings) - VALID_SETTINGS
        assert unknown == set()


class TestRunFilepath:
    def test_derives_path_from_name(self):
        path = run_filepath("my-run")
        assert path == WORKSPACE_DIR / "my-run.json"

    def test_creates_workspace_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server_mod, "WORKSPACE_DIR", tmp_path / "ws")
        path = server_mod.run_filepath("test-run")
        assert (tmp_path / "ws").is_dir()
        assert path.name == "test-run.json"

    def test_bak_path(self):
        path = run_filepath("my-run")
        bak = path.with_suffix(".json.bak")
        assert bak == WORKSPACE_DIR / "my-run.json.bak"


class TestGetRunStructureToFile:
    def test_creates_file_and_writes_structure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server_mod, "WORKSPACE_DIR", tmp_path / "ws")

        mock_client = AsyncMock()
        mock_client.get_run_structure.return_value = {
            "units": [{"type": "Survey", "position": 10}]
        }
        monkeypatch.setattr(server_mod, "_client", lambda ctx: mock_client)

        result = asyncio.run(
            server_mod.get_run_structure_to_file("demo", ctx=MagicMock())
        )
        assert "wrote" in result
        filepath = tmp_path / "ws" / "demo.json"
        assert filepath.exists()
        data = json.loads(filepath.read_text())
        assert len(data["units"]) == 1

    def test_backs_up_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server_mod, "WORKSPACE_DIR", tmp_path / "ws")

        filepath = server_mod.run_filepath("demo")
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text('{"old": true}')

        mock_client = AsyncMock()
        mock_client.get_run_structure.return_value = {"units": []}
        monkeypatch.setattr(server_mod, "_client", lambda ctx: mock_client)

        asyncio.run(
            server_mod.get_run_structure_to_file("demo", ctx=MagicMock())
        )

        bak = filepath.with_suffix(".json.bak")
        assert bak.exists()
        assert json.loads(bak.read_text()) == {"old": True}

    def test_no_backup_when_no_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server_mod, "WORKSPACE_DIR", tmp_path / "ws")

        mock_client = AsyncMock()
        mock_client.get_run_structure.return_value = {"units": []}
        monkeypatch.setattr(server_mod, "_client", lambda ctx: mock_client)

        asyncio.run(
            server_mod.get_run_structure_to_file("new-run", ctx=MagicMock())
        )

        bak = server_mod.run_filepath("new-run").with_suffix(".json.bak")
        assert not bak.exists()


class TestUpdateRunStructureFromFile:
    def test_raises_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server_mod, "WORKSPACE_DIR", tmp_path / "ws")

        with pytest.raises(FileNotFoundError, match="No local file"):
            asyncio.run(
                server_mod.update_run_structure_from_file("nonexistent", ctx=MagicMock())
            )

    def test_removes_bak_on_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server_mod, "WORKSPACE_DIR", tmp_path / "ws")

        filepath = server_mod.run_filepath("demo")
        filepath.parent.mkdir(parents=True, exist_ok=True)

        structure = {
            "units": [{"type": "Survey", "position": 10, "survey_data": {"name": "s", "items": [
                {"type": "note", "name": "n1", "label": "Welcome", "optional": 1}
            ]}}]
        }
        filepath.write_text(json.dumps(structure))

        bak = filepath.with_suffix(".json.bak")
        bak.write_text('{"old": true}')

        mock_client = AsyncMock()
        mock_client.put_run_structure.return_value = None
        mock_client.get_run_structure.return_value = structure
        monkeypatch.setattr(server_mod, "_client", lambda ctx: mock_client)

        result = asyncio.run(
            server_mod.update_run_structure_from_file("demo", ctx=MagicMock())
        )
        assert "successfully updated" in result
        assert not bak.exists()

    def test_validation_error_preserves_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server_mod, "WORKSPACE_DIR", tmp_path / "ws")

        filepath = server_mod.run_filepath("bad-run")
        filepath.parent.mkdir(parents=True, exist_ok=True)

        bad_structure = {"units": [{"type": "Survey", "position": 10, "survey_data": {"name": "s", "items": []}, "condition": "x", "if_true": "not_int"}]}
        filepath.write_text(json.dumps(bad_structure))

        bak = filepath.with_suffix(".json.bak")
        bak.write_text('{"old": true}')

        with pytest.raises(ValueError, match="Structure validation failed"):
            asyncio.run(
                server_mod.update_run_structure_from_file("bad-run", ctx=MagicMock())
            )

        assert filepath.exists()
        assert bak.exists()