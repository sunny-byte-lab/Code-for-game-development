"""N.E.X.U.S. Configuration Manager.
Thread-safe configuration loading, saving, and validation.
"""

import os
import json
import logging
import threading
from typing import Any, Dict, Optional, Callable, List
from nexus_config.schema import (
    NexusRootConfig, CameraConfig, TrackingConfig, MouseConfig,
    GesturesEnabledConfig, InterfaceConfig, AirTypingConfig,
    RemoteProtocolConfig, AIConfig, VoiceConfig
)

logger = logging.getLogger("NEXUS.Config")


class ConfigManager:
    """Thread-safe configuration manager providing typed access and validation."""

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self._lock = threading.RLock()
        self._listeners: List[Callable[[str, Any], None]] = []
        self.data: NexusRootConfig = NexusRootConfig()
        self.load()

    def add_listener(self, callback: Callable[[str, Any], None]) -> None:
        """Subscribes a listener to configuration changes."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, Any], None]) -> None:
        """Unsubscribes a listener."""
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _notify(self, key: str, value: Any) -> None:
        """Dispatches change notifications to all listeners."""
        for cb in list(self._listeners):
            try:
                cb(key, value)
            except Exception as e:
                logger.error(f"Error in config listener callback: {e}")

    def load(self) -> NexusRootConfig:
        """Loads configuration from JSON file with fallback to defaults."""
        with self._lock:
            if not os.path.exists(self.config_path):
                logger.info(f"Config file '{self.config_path}' not found. Initializing with default schema.")
                self.save()
                return self.data

            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self.data = self._deserialize_root(raw)
                logger.info(f"Configuration successfully loaded from '{self.config_path}'.")
            except Exception as e:
                logger.warning(f"Error reading '{self.config_path}' ({e}). Reverting to default configuration.")
                self.data = NexusRootConfig()
            return self.data

    def save(self) -> bool:
        """Persists current configuration to JSON file atomically."""
        with self._lock:
            try:
                tmp_path = f"{self.config_path}.tmp"
                out_dict = self.data.to_dict()
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(out_dict, f, indent=4)
                if os.path.exists(self.config_path):
                    os.replace(tmp_path, self.config_path)
                else:
                    os.rename(tmp_path, self.config_path)
                logger.info(f"Configuration successfully saved to '{self.config_path}'.")
                return True
            except Exception as e:
                logger.error(f"Failed to save configuration to '{self.config_path}': {e}")
                return False

    def get(self, section: str, key: Optional[str] = None, default: Any = None) -> Any:
        """Retrieves a configuration value safely."""
        with self._lock:
            root_dict = self.data.to_dict()
            if section not in root_dict:
                return default
            sec_val = root_dict[section]
            if key is None:
                return sec_val
            if isinstance(sec_val, dict):
                return sec_val.get(key, default)
            return default

    def set(self, section: str, key: str, value: Any, auto_save: bool = False) -> None:
        """Sets a configuration field with validation and notification."""
        with self._lock:
            if hasattr(self.data, section):
                sec_obj = getattr(self.data, section)
                if isinstance(sec_obj, dict):
                    sec_obj[key] = value
                elif hasattr(sec_obj, key):
                    # Typecast / boundary sanitization
                    curr_val = getattr(sec_obj, key)
                    sanitized = self._sanitize_value(section, key, value, curr_val)
                    setattr(sec_obj, key, sanitized)
                    self._notify(f"{section}.{key}", sanitized)
            if auto_save:
                self.save()

    def _sanitize_value(self, section: str, key: str, val: Any, curr_default: Any) -> Any:
        """Performs boundary and type checking on numerical and boolean settings."""
        try:
            if isinstance(curr_default, bool):
                return bool(val)
            elif isinstance(curr_default, int):
                val_int = int(val)
                if key in ("width", "height"):
                    return max(160, min(3840, val_int))
                if key == "fps_target":
                    return max(10, min(120, val_int))
                if key == "max_num_hands":
                    return max(1, min(4, val_int))
                if key == "port":
                    return max(1024, min(65535, val_int))
                return val_int
            elif isinstance(curr_default, float):
                val_float = float(val)
                if key in ("detection_confidence", "tracking_confidence", "smoothing"):
                    return max(0.1, min(0.99, val_float))
                if key in ("sensitivity", "sensitivity_x", "sensitivity_y"):
                    return max(0.2, min(8.0, val_float))
                if key == "dwell_duration":
                    return max(0.20, min(2.0, val_float))
                if key == "auto_activate_duration":
                    return max(0.10, min(2.0, val_float))
                if key == "auto_exit_duration":
                    return max(0.20, min(5.0, val_float))
                return val_float
            return val
        except (ValueError, TypeError):
            return curr_default

    def _deserialize_root(self, raw: Dict[str, Any]) -> NexusRootConfig:
        """Reconstructs strongly-typed NexusRootConfig from raw JSON dictionary."""
        cfg = NexusRootConfig()
        if "camera" in raw and isinstance(raw["camera"], dict):
            for k, v in raw["camera"].items():
                if hasattr(cfg.camera, k):
                    setattr(cfg.camera, k, v)

        if "tracking" in raw and isinstance(raw["tracking"], dict):
            for k, v in raw["tracking"].items():
                if hasattr(cfg.tracking, k):
                    setattr(cfg.tracking, k, v)

        if "mouse" in raw and isinstance(raw["mouse"], dict):
            for k, v in raw["mouse"].items():
                if hasattr(cfg.mouse, k):
                    setattr(cfg.mouse, k, v)

        if "gestures_enabled" in raw and isinstance(raw["gestures_enabled"], dict):
            for k, v in raw["gestures_enabled"].items():
                if hasattr(cfg.gestures_enabled, k):
                    setattr(cfg.gestures_enabled, k, v)

        if "interface" in raw and isinstance(raw["interface"], dict):
            for k, v in raw["interface"].items():
                if hasattr(cfg.interface, k):
                    setattr(cfg.interface, k, v)

        if "air_typing" in raw and isinstance(raw["air_typing"], dict):
            for k, v in raw["air_typing"].items():
                if hasattr(cfg.air_typing, k):
                    setattr(cfg.air_typing, k, v)

        if "remote_protocol" in raw and isinstance(raw["remote_protocol"], dict):
            for k, v in raw["remote_protocol"].items():
                if hasattr(cfg.remote_protocol, k):
                    setattr(cfg.remote_protocol, k, v)

        if "ai" in raw and isinstance(raw["ai"], dict):
            for k, v in raw["ai"].items():
                if hasattr(cfg.ai, k):
                    setattr(cfg.ai, k, v)

        if "voice" in raw and isinstance(raw["voice"], dict):
            for k, v in raw["voice"].items():
                if hasattr(cfg.voice, k):
                    setattr(cfg.voice, k, v)

        if "applications" in raw and isinstance(raw["applications"], list):
            cfg.applications = raw["applications"]

        return cfg
