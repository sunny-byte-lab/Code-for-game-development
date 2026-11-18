"""JARVIS Settings and Configuration Manager.
Handles loading, saving, validating, and managing default preferences from config.json.
"""

import json
import os
import shutil
import logging
from typing import Dict, Any, List

logger = logging.getLogger("NEXUS.Settings")

DEFAULT_CONFIG: Dict[str, Any] = {
    "camera": {
        "index": 0,
        "width": 640,
        "height": 480,
        "fps_target": 30,
        "mirror": True
    },
    "tracking": {
        "detection_confidence": 0.70,
        "tracking_confidence": 0.70,
        "max_num_hands": 1
    },
    "mouse": {
        "sensitivity": 1.0,
        "sensitivity_preset": "medium",
        "fine_control_mode": True,
        "fine_control_scale": 0.40,
        "sensitivity_x": 1.0,
        "sensitivity_y": 1.0,
        "smoothing": 0.65,
        "smoothing_type": "one_euro",
        "one_euro_min_cutoff": 0.8,
        "one_euro_beta": 0.04,
        "deadzone_radius": 6.0,
        "tracking_loss_grace_s": 0.30,
        "physical_priority_timeout": 1.5,
        "active_margin_x": 0.16,
        "active_margin_y": 0.16,
        "roi_left": 0.16,
        "roi_top": 0.16,
        "roi_right": 0.84,
        "roi_bottom": 0.84,
        "invert_x": False,
        "cursor_mode": "absolute",
        "relative_speed": 4.0,
        "relative_deadzone": 0.03,
        "tracking_landmark": "index_tip",
        "pinch_normalized": True,
        "pinch_threshold": 0.28,
        "pinch_release_threshold": 0.40,
        "right_click_threshold": 0.28,
        "right_click_gesture": "thumb_middle_pinch",
        "click_cooldown": 0.20,
        "click_stabilization": True,
        "click_stabilization_ms": 160,
        "drag_hold_duration": 0.45,
        "scroll_speed": 35.0,
        "scroll_deadzone": 0.015
    },
    "gestures_enabled": {
        "cursor_move": True,
        "left_click": True,
        "drag_and_drop": True,
        "right_click": True,
        "scroll": True,
        "open_palm_pause": False,
        "fist_emergency_stop": False
    },
    "interface": {
        "enable_animations": True,
        "show_landmarks": True,
        "show_hud_overlays": True,
        "show_radar_sweep": True,
        "theme": "iron_man_dark"
    },
    "applications": [
        {
            "id": "notepad",
            "name": "Notepad",
            "path": "notepad.exe",
            "enabled": True,
            "description": "Windows Text Editor"
        },
        {
            "id": "explorer",
            "name": "File Explorer",
            "path": "explorer.exe",
            "enabled": True,
            "description": "Windows File Manager"
        },
        {
            "id": "settings",
            "name": "Windows Settings",
            "path": "ms-settings:",
            "enabled": True,
            "description": "Windows System Settings"
        },
        {
            "id": "chrome",
            "name": "Google Chrome",
            "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "enabled": True,
            "description": "Web Browser"
        },
        {
            "id": "vscode",
            "name": "Visual Studio Code",
            "path": "Code.exe",
            "enabled": True,
            "description": "Source Code Editor"
        },
        {
            "id": "blender",
            "name": "Blender 3D",
            "path": "blender.exe",
            "enabled": False,
            "description": "3D Creation Suite"
        },
        {
            "id": "godot",
            "name": "Godot Engine",
            "path": "godot.exe",
            "enabled": False,
            "description": "2D/3D Game Engine"
        }
    ],
    "safety": {
        "require_explicit_enable": True,
        "emergency_keyboard_key": "Escape",
        "confirm_launches": False
    },
    "voice": {
        "enabled": False,
        "energy_threshold": 300
    },
    "air_typing": {
        "enabled": True,
        "auto_activate": True,
        "auto_activate_duration": 0.40,
        "auto_exit_duration": 0.80,
        "typing_mode": "DWELL",
        "dwell_duration": 0.50,
        "dwell_jitter_tolerance": 25.0,
        "press_threshold": 0.22,
        "release_threshold": 0.12,
        "sensitivity_x": 1.35,
        "sensitivity_y": 1.35,
        "keypress_cooldown": 0.20,
        "backspace_repeat": False,
        "external_typing": True
    }
}


class SettingsManager:
    """Manages persistent application settings with validation and fallbacks."""

    def __init__(self, config_path: str = "config.json"):
        self.config_path = os.path.abspath(config_path)
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        """Loads configuration from file or creates default if missing or corrupted."""
        if not os.path.exists(self.config_path):
            logger.info(f"Config file not found at {self.config_path}. Initializing with defaults.")
            self._save_data(DEFAULT_CONFIG)
            return json.loads(json.dumps(DEFAULT_CONFIG))

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            validated = self._validate_and_merge(loaded, DEFAULT_CONFIG)
            return validated
        except Exception as e:
            logger.error(f"Error loading config file: {e}. Reverting to defaults.")
            return json.loads(json.dumps(DEFAULT_CONFIG))

    def _validate_and_merge(self, loaded: Any, defaults: Any) -> Any:
        """Recursively validates and fills missing fields from defaults."""
        if not isinstance(loaded, dict) or not isinstance(defaults, dict):
            return loaded if loaded is not None else defaults

        result = {}
        for key, default_val in defaults.items():
            if key not in loaded:
                result[key] = default_val
            else:
                user_val = loaded[key]
                if isinstance(default_val, dict) and isinstance(user_val, dict):
                    result[key] = self._validate_and_merge(user_val, default_val)
                elif isinstance(default_val, (int, float)) and isinstance(user_val, (int, float)):
                    # Sanitize numerical ranges
                    result[key] = self._sanitize_number(key, user_val, default_val)
                else:
                    result[key] = user_val

        # Preserve custom user keys in loaded
        for key, val in loaded.items():
            if key not in result:
                result[key] = val

        return result

    def _sanitize_number(self, key: str, value: float, default: float) -> float:
        """Clamp configuration numbers within safe, workable bounds."""
        ranges = {
            "sensitivity": (0.5, 6.0),
            "sensitivity_x": (0.5, 6.0),
            "sensitivity_y": (0.5, 6.0),
            "smoothing": (0.05, 0.95),
            "one_euro_min_cutoff": (0.05, 5.0),
            "one_euro_beta": (0.0, 1.0),
            "deadzone_radius": (0.0, 20.0),
            "relative_speed": (0.5, 12.0),
            "relative_deadzone": (0.005, 0.15),
            "pinch_threshold": (0.015, 1.20),
            "pinch_release_threshold": (0.025, 1.50),
            "right_click_threshold": (0.015, 1.20),
            "click_cooldown": (0.10, 2.0),
            "click_stabilization_ms": (0, 500),
            "drag_hold_duration": (0.15, 2.0),
            "active_margin_x": (0.0, 0.45),
            "active_margin_y": (0.0, 0.45),
            "roi_left": (0.0, 0.45),
            "roi_top": (0.0, 0.45),
            "roi_right": (0.55, 1.0),
            "roi_bottom": (0.55, 1.0),
            "detection_confidence": (0.1, 1.0),
            "tracking_confidence": (0.1, 1.0),
            "dwell_duration": (0.30, 1.0),
            "dwell_jitter_tolerance": (5.0, 60.0),
            "auto_activate_duration": (0.10, 2.0),
            "auto_exit_duration": (0.20, 5.0),
            "index": (0, 16)
        }
        if key in ranges:
            min_val, max_val = ranges[key]
            if value < min_val or value > max_val:
                logger.warning(f"Setting '{key}' value {value} out of range ({min_val}-{max_val}). Clamping.")
                return max(min_val, min(max_val, type(default)(value)))
        return value

    def save(self) -> bool:
        """Saves current configuration data to file."""
        return self._save_data(self.data)

    def _save_data(self, data: Dict[str, Any]) -> bool:
        try:
            temp_path = self.config_path + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            if os.path.exists(self.config_path):
                os.remove(self.config_path)
            shutil.move(temp_path, self.config_path)
            logger.info("Configuration saved successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            return False

    def reset_defaults(self) -> None:
        """Resets all settings to factory defaults and saves."""
        self.data = json.loads(json.dumps(DEFAULT_CONFIG))
        self.save()
        logger.info("Configuration reset to defaults.")

    def get(self, *keys: str, default: Any = None) -> Any:
        """Safe nested retrieval. Example: get('mouse', 'sensitivity')."""
        curr = self.data
        for k in keys:
            if isinstance(curr, dict) and k in curr:
                curr = curr[k]
            else:
                return default
        return curr

    def set(self, *keys_and_value: Any) -> None:
        """Safe nested setter. Last argument is value. Example: set('mouse', 'sensitivity', 2.5)."""
        if len(keys_and_value) < 2:
            return
        keys = keys_and_value[:-1]
        value = keys_and_value[-1]

        curr = self.data
        for k in keys[:-1]:
            if k not in curr or not isinstance(curr[k], dict):
                curr[k] = {}
            curr = curr[k]
        curr[keys[-1]] = value

    @staticmethod
    def validate_app_path(path: str) -> bool:
        """Validates if an executable or URI is valid on Windows."""
        if not path or not isinstance(path, str):
            return False
        clean = path.strip()
        # Windows URI schemes like ms-settings: or http:
        if ":" in clean and ("\\" not in clean and "/" not in clean):
            return True
        # Executable file exists directly
        if os.path.isfile(clean):
            return True
        # Check PATH environment
        if shutil.which(clean):
            return True
        return False
