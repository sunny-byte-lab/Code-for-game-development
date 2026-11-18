"""N.E.X.U.S. Command Validator & Whitelist Enforcement.
Validates structured payloads, bounds-checks parameters, and prevents command injection.
"""

from typing import Dict, Any, Tuple, Optional, Set
from nexus_protocol.spec import CommandAction


class CommandValidator:
    """Enforces strict command allowlists and boundary validation."""

    VALID_BUTTONS: Set[str] = {"left", "right", "middle"}
    VALID_MODES: Set[str] = {"MOUSE", "KEYBOARD", "AIR_TYPING", "APP_LAUNCH", "SYSTEM_CONTROL", "PAUSED"}

    def __init__(self, allowed_apps: Optional[Set[str]] = None):
        self.allowed_apps: Set[str] = allowed_apps or {
            "notepad", "file_explorer", "windows_settings",
            "google_chrome", "visual_studio_code", "blender_3d"
        }

    def validate_command(self, action_name: str, payload: Dict[str, Any]) -> Tuple[bool, Optional[CommandAction], Dict[str, Any], str]:
        """Validates that action is in allowlist and payload adheres to schema."""
        try:
            action = CommandAction(action_name)
        except ValueError:
            return False, None, {}, f"REJECTED_UNKNOWN_ACTION: '{action_name}'"

        sanitized_payload: Dict[str, Any] = {}

        if action == CommandAction.MOUSE_MOVE:
            dx = float(payload.get("dx", 0.0))
            dy = float(payload.get("dy", 0.0))
            # Clamp deltas to prevent absurd jumps
            sanitized_payload["dx"] = max(-500.0, min(500.0, dx))
            sanitized_payload["dy"] = max(-500.0, min(500.0, dy))
            if "abs_x" in payload and "abs_y" in payload:
                sanitized_payload["abs_x"] = max(0.0, min(1.0, float(payload["abs_x"])))
                sanitized_payload["abs_y"] = max(0.0, min(1.0, float(payload["abs_y"])))

        elif action in (CommandAction.CLICK, CommandAction.MOUSE_DOWN, CommandAction.MOUSE_UP):
            btn = str(payload.get("button", "left")).lower()
            if btn not in self.VALID_BUTTONS:
                return False, None, {}, f"INVALID_MOUSE_BUTTON: '{btn}'"
            sanitized_payload["button"] = btn

        elif action == CommandAction.SCROLL:
            delta = int(payload.get("delta", 0))
            sanitized_payload["delta"] = max(-1200, min(1200, delta))

        elif action == CommandAction.KEY_PRESS:
            key_id = str(payload.get("key_id", ""))
            char = str(payload.get("char", ""))
            if len(key_id) > 20 or len(char) > 5:
                return False, None, {}, "INVALID_KEY_SPECIFICATION"
            sanitized_payload["key_id"] = key_id
            sanitized_payload["char"] = char

        elif action == CommandAction.TYPE_TEXT:
            text = str(payload.get("text", ""))
            if len(text) > 500:
                return False, None, {}, "TEXT_TOO_LONG (MAX 500 CHARS)"
            sanitized_payload["text"] = text

        elif action == CommandAction.VOLUME_SET:
            percent = int(payload.get("percent", 50))
            sanitized_payload["percent"] = max(0, min(100, percent))

        elif action in (CommandAction.VOLUME_UP, CommandAction.VOLUME_DOWN):
            step = int(payload.get("step", 5))
            sanitized_payload["step"] = max(1, min(25, step))

        elif action == CommandAction.LAUNCH_APP:
            app_id = str(payload.get("app_id", "")).strip().lower()
            if app_id not in self.allowed_apps:
                return False, None, {}, f"APP_NOT_WHITELISTED: '{app_id}'"
            sanitized_payload["app_id"] = app_id

        elif action == CommandAction.AI_QUERY:
            query = str(payload.get("query", "")).strip()
            if not query or len(query) > 1000:
                return False, None, {}, "INVALID_AI_QUERY (EMPTY OR >1000 CHARS)"
            sanitized_payload["query"] = query

        elif action == CommandAction.SET_MODE:
            mode = str(payload.get("mode", "")).upper()
            if mode not in self.VALID_MODES:
                return False, None, {}, f"INVALID_MODE: '{mode}'"
            sanitized_payload["mode"] = mode

        # Empty payloads for atomic triggers
        elif action in (CommandAction.MUTE_AUDIO, CommandAction.SWITCH_WINDOW, CommandAction.EMERGENCY_STOP, CommandAction.PAUSE, CommandAction.RESUME):
            pass

        return True, action, sanitized_payload, "OK"
