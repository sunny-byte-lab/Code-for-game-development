"""Unit tests for safe application launching, path validation, and App Launch Mode cycling."""

import time
import pytest
from app.app_launcher import AppLauncher


class TestAppLauncher:
    def test_path_validation(self):
        # Valid Windows URIs
        assert AppLauncher.validate_target("ms-settings:") is True
        assert AppLauncher.validate_target("calc:") is True

        # Valid system binaries usually in Windows PATH
        assert AppLauncher.validate_target("notepad.exe") is True
        assert AppLauncher.validate_target("cmd.exe") is True

        # Invalid paths
        assert AppLauncher.validate_target("") is False
        assert AppLauncher.validate_target(None) is False
        assert AppLauncher.validate_target("C:\\NonExistentFolder123\\FakeApp99.exe") is False

    def test_app_cycling(self):
        apps = [
            {"id": "notepad", "name": "Notepad", "path": "notepad.exe", "enabled": True},
            {"id": "explorer", "name": "Explorer", "path": "explorer.exe", "enabled": True},
            {"id": "disabled", "name": "Disabled", "path": "fake.exe", "enabled": False}
        ]
        launcher = AppLauncher(apps)
        assert len(launcher.get_enabled_apps()) == 2

        # Cycle next
        launcher.selected_index = 0
        assert launcher.get_selected_app()["id"] == "notepad"
        launcher.next_app()
        assert launcher.get_selected_app()["id"] == "explorer"
        launcher.next_app()
        # Wraps back
        assert launcher.get_selected_app()["id"] == "notepad"

        # Cycle prev
        launcher.prev_app()
        assert launcher.get_selected_app()["id"] == "explorer"

    def test_launch_cooldown_throttling(self):
        apps = [{"id": "notepad", "name": "Notepad", "path": "notepad.exe", "enabled": True}]
        launcher = AppLauncher(apps, launch_cooldown=0.5)

        # Set last_launch_time to now
        launcher.last_launch_time = time.time()
        # Immediate subsequent launch should be throttled
        result = launcher.launch_app(apps[0])
        assert result is False
