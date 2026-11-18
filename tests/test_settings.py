"""Unit tests for SettingsManager configuration validation, loading, saving, and defaults."""

import os
import tempfile
import pytest
from app.settings_manager import SettingsManager, DEFAULT_CONFIG


class TestSettingsManager:
    def test_default_config_creation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            conf_path = os.path.join(tmp_dir, "test_config.json")
            assert not os.path.exists(conf_path)

            sm = SettingsManager(conf_path)
            assert os.path.exists(conf_path)
            assert sm.get("camera", "index") == 0
            assert sm.get("mouse", "sensitivity") == DEFAULT_CONFIG["mouse"]["sensitivity"]

    def test_validation_and_sanitization(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            conf_path = os.path.join(tmp_dir, "test_config.json")
            sm = SettingsManager(conf_path)

            # Test out of range sensitivity clamped
            clamped = sm._sanitize_number("sensitivity", 99.0, 2.0)
            assert clamped == 6.0

            clamped_low = sm._sanitize_number("sensitivity", -5.0, 2.0)
            assert clamped_low == 0.5

    def test_nested_get_and_set(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            conf_path = os.path.join(tmp_dir, "test_config.json")
            sm = SettingsManager(conf_path)

            sm.set("mouse", "sensitivity", 3.5)
            assert sm.get("mouse", "sensitivity") == 3.5

            sm.save()

            # Reload from disk
            sm2 = SettingsManager(conf_path)
            assert sm2.get("mouse", "sensitivity") == 3.5

    def test_reset_defaults(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            conf_path = os.path.join(tmp_dir, "test_config.json")
            sm = SettingsManager(conf_path)
            sm.set("camera", "index", 5)
            assert sm.get("camera", "index") == 5

            sm.reset_defaults()
            assert sm.get("camera", "index") == 0
