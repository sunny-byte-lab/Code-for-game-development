"""JARVIS Optional Voice Commands Module.
Provides isolated, optional speech command recognition with strictly whitelisted actions.
Never executes arbitrary shell or system commands.
"""

import time
import logging
from typing import Optional, Callable
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger("NEXUS.Voice")


class VoiceCommander(QThread):
    """Optional speech recognition thread for hands-free voice trigger fallback."""

    command_detected = Signal(str)
    voice_status = Signal(str)

    def __init__(self, callback_dispatcher: Optional[Callable[[str], None]] = None):
        super().__init__()
        self.callback_dispatcher = callback_dispatcher
        self._running = False
        self._recognizer = None
        self._microphone = None
        self.is_available = self._check_dependencies()

    def _check_dependencies(self) -> bool:
        """Gracefully probes for speech_recognition without failing app boot."""
        try:
            import speech_recognition as sr
            self._recognizer = sr.Recognizer()
            self._microphone = sr.Microphone()
            logger.info("SpeechRecognition module & microphone detected.")
            return True
        except Exception as e:
            logger.info(f"Optional Voice Control offline (speech_recognition / microphone not active: {e}). Core gesture engine unaffected.")
            return False

    def run(self) -> None:
        if not self.is_available or self._microphone is None:
            self.voice_status.emit("VOICE MODULE OFFLINE (HARDWARE NOT DETECTED)")
            return

        import speech_recognition as sr
        self._running = True
        self.voice_status.emit("VOICE COMMANDS LISTENING...")

        with self._microphone as source:
            try:
                self._recognizer.adjust_for_ambient_noise(source, duration=1.0)
            except Exception:
                pass

        while self._running:
            try:
                with self._microphone as source:
                    audio = self._recognizer.listen(source, timeout=3.0, phrase_time_limit=4.0)
                try:
                    phrase = self._recognizer.recognize_google(audio).lower().strip()
                    logger.info(f"[VOICE HEARD] '{phrase}'")
                    self._dispatch_whitelisted_phrase(phrase)
                except sr.UnknownValueError:
                    pass
                except sr.RequestError as e:
                    self.voice_status.emit("VOICE SERVICE NETWORK TIMEOUT")
                    time.sleep(2.0)
            except Exception:
                time.sleep(1.0)

    def _dispatch_whitelisted_phrase(self, phrase: str) -> None:
        """Matches against strictly whitelisted command keywords."""
        matched = None
        if "open chrome" in phrase:
            matched = "LAUNCH_CHROME"
        elif "open vs code" in phrase or "open vscode" in phrase:
            matched = "LAUNCH_VSCODE"
        elif "open blender" in phrase:
            matched = "LAUNCH_BLENDER"
        elif "open godot" in phrase:
            matched = "LAUNCH_GODOT"
        elif "open notepad" in phrase:
            matched = "LAUNCH_NOTEPAD"
        elif "open explorer" in phrase or "open file explorer" in phrase:
            matched = "LAUNCH_EXPLORER"
        elif "increase volume" in phrase or "volume up" in phrase:
            matched = "VOLUME_UP"
        elif "decrease volume" in phrase or "volume down" in phrase:
            matched = "VOLUME_DOWN"
        elif "mute audio" in phrase or phrase == "mute":
            matched = "MUTE_AUDIO"
        elif "switch window" in phrase:
            matched = "SWITCH_WINDOW"
        elif "pause" in phrase:
            matched = "PAUSE_CONTROL"
        elif "resume" in phrase:
            matched = "RESUME_CONTROL"
        elif "emergency stop" in phrase or "stop control" in phrase:
            matched = "EMERGENCY_STOP"

        if matched:
            self.command_detected.emit(matched)
            if self.callback_dispatcher:
                self.callback_dispatcher(matched)

    def stop(self) -> None:
        self._running = False
        self.wait(1000)
