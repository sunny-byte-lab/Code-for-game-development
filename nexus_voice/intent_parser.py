"""N.E.X.U.S. Voice Intent Parser.
Strictly whitelists voice keywords to safe, structured action intents.
Never allows arbitrary command or shell execution.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class VoiceIntent:
    action: str  # e.g. "VOLUME_UP", "LAUNCH_APP", "AI_QUERY"
    parameter: Optional[str] = None
    confidence: float = 1.0
    raw_phrase: str = ""


class VoiceIntentParser:
    """Parses raw spoken phrases into strongly-typed whitelisted actions."""

    APP_MAP = {
        "chrome": "google_chrome",
        "google chrome": "google_chrome",
        "browser": "google_chrome",
        "vscode": "visual_studio_code",
        "code": "visual_studio_code",
        "vs code": "visual_studio_code",
        "blender": "blender_3d",
        "notepad": "notepad",
        "explorer": "file_explorer",
        "file explorer": "file_explorer",
        "settings": "windows_settings",
        "windows settings": "windows_settings"
    }

    def parse_phrase(self, phrase: str) -> Optional[VoiceIntent]:
        """Maps a spoken phrase to a valid VoiceIntent or returns None if unwhitelisted."""
        if not phrase or not isinstance(phrase, str):
            return None

        clean = phrase.lower().strip()

        # Volume controls
        if any(k in clean for k in ("volume up", "increase volume", "louder")):
            return VoiceIntent(action="VOLUME_UP", raw_phrase=clean)
        if any(k in clean for k in ("volume down", "decrease volume", "quieter")):
            return VoiceIntent(action="VOLUME_DOWN", raw_phrase=clean)
        if clean in ("mute", "mute audio", "silence", "unmute"):
            return VoiceIntent(action="MUTE_AUDIO", raw_phrase=clean)

        # Control lifecycle
        if "emergency stop" in clean or clean in ("stop control", "emergency halt"):
            return VoiceIntent(action="EMERGENCY_STOP", raw_phrase=clean)
        if clean in ("pause", "pause control", "hold"):
            return VoiceIntent(action="PAUSE_CONTROL", raw_phrase=clean)
        if clean in ("resume", "resume control", "continue"):
            return VoiceIntent(action="RESUME_CONTROL", raw_phrase=clean)

        # Window navigation
        if "switch window" in clean or "next window" in clean:
            return VoiceIntent(action="SWITCH_WINDOW", raw_phrase=clean)

        # App Launching
        if clean.startswith("open ") or clean.startswith("launch "):
            app_target = clean.split(" ", 1)[1].strip()
            for key, app_id in self.APP_MAP.items():
                if key in app_target:
                    return VoiceIntent(action="LAUNCH_APP", parameter=app_id, raw_phrase=clean)

        # AI conversational query prefix
        if clean.startswith("ask nexus ") or clean.startswith("hey nexus ") or clean.startswith("nexus "):
            query = clean.replace("ask nexus ", "").replace("hey nexus ", "").replace("nexus ", "").strip()
            if query:
                return VoiceIntent(action="AI_QUERY", parameter=query, raw_phrase=clean)

        return None
