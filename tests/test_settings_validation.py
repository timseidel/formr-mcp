import sys
sys.path.insert(0, "/Users/admin/Documents/repos/formr-mcp")

from server import VALID_SETTINGS


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