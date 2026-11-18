"""JARVIS Application Launcher Engine.
Validates executable paths, runs applications safely via subprocess, and manages APP LAUNCH MODE cycling.
"""

import os
import time
import shutil
import subprocess
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("NEXUS.AppLauncher")


class AppLauncher:
    """Safely manages application registration, validation, and launching."""

    def __init__(self, apps_config: Optional[List[Dict[str, Any]]] = None, launch_cooldown: float = 1.5):
        self.launch_cooldown = launch_cooldown
        self.last_launch_time: float = 0.0
        self.selected_index: int = 0
        self.apps: List[Dict[str, Any]] = apps_config or []

    def set_apps(self, apps_config: List[Dict[str, Any]]) -> None:
        """Updates the internal list of configured applications."""
        self.apps = [app for app in apps_config if isinstance(app, dict)]
        if self.selected_index >= len(self.apps):
            self.selected_index = max(0, len(self.apps) - 1)

    def get_enabled_apps(self) -> List[Dict[str, Any]]:
        """Returns only enabled applications."""
        return [app for app in self.apps if app.get("enabled", True)]

    def next_app(self) -> int:
        """Cycles selection to the next enabled application."""
        enabled = self.get_enabled_apps()
        if not enabled:
            return 0
        self.selected_index = (self.selected_index + 1) % len(enabled)
        return self.selected_index

    def prev_app(self) -> int:
        """Cycles selection to the previous enabled application."""
        enabled = self.get_enabled_apps()
        if not enabled:
            return 0
        self.selected_index = (self.selected_index - 1 + len(enabled)) % len(enabled)
        return self.selected_index

    def get_selected_app(self) -> Optional[Dict[str, Any]]:
        """Returns the currently selected app in App Launch Mode."""
        enabled = self.get_enabled_apps()
        if not enabled:
            return None
        idx = max(0, min(self.selected_index, len(enabled) - 1))
        return enabled[idx]

    @staticmethod
    def clean_path(path: str) -> str:
        """Strips surrounding quotes and expands environment variables."""
        if not path or not isinstance(path, str):
            return ""
        return os.path.expandvars(path.strip(' "\''))

    @staticmethod
    def validate_target(path: str) -> bool:
        """Checks if the target path or command can be safely launched."""
        if not path or not isinstance(path, str):
            return False
        clean = AppLauncher.clean_path(path)
        if not clean:
            return False
        # Windows URI scheme (e.g. ms-settings:, calc:, etc.)
        if ":" in clean and ("\\" not in clean and "/" not in clean):
            return True
        # Direct absolute or relative path
        if os.path.isfile(clean):
            return True
        # Resolved in system PATH
        if shutil.which(clean):
            return True
        return False

    def launch_by_id(self, app_id: str) -> bool:
        """Launches an application by its registered id."""
        for app in self.apps:
            if app.get("id") == app_id:
                return self.launch_app(app)
        logger.warning(f"Application id '{app_id}' not found in registry.")
        return False

    def launch_selected(self) -> bool:
        """Launches the currently selected app in App Launch Mode."""
        selected = self.get_selected_app()
        if selected:
            return self.launch_app(selected)
        logger.warning("No application selected to launch.")
        return False

    def launch_app(self, app_info: Dict[str, Any]) -> bool:
        """Safely executes the application using subprocess without shell=True."""
        now = time.time()
        if now - self.last_launch_time < self.launch_cooldown:
            logger.info("Application launch throttled by cooldown timer.")
            return False

        path = self.clean_path(app_info.get("path", ""))
        name = app_info.get("name", "Unknown App")

        if not self.validate_target(path):
            logger.error(f"[LAUNCH ERROR] Application path for '{name}' is invalid: '{path}'")
            return False

        try:
            # Handle Windows URI schemes (e.g. ms-settings:)
            if ":" in path and ("\\" not in path and "/" not in path):
                os.startfile(path)
                logger.info(f"[NEXUS PROTOCOL] Launched Windows URI: {path}")
            else:
                # Launch standalone executable via subprocess safely without shell=True in isolated process group
                resolved_bin = shutil.which(path) or path
                flags = 0
                if sys.platform == "win32":
                    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                subprocess.Popen([resolved_bin], shell=False, creationflags=flags)
                logger.info(f"[NEXUS PROTOCOL] Executed binary: '{name}' -> {resolved_bin}")

            self.last_launch_time = now
            return True
        except Exception as e:
            logger.error(f"[LAUNCH ERROR] Failed to start '{name}': {e}")
            return False
