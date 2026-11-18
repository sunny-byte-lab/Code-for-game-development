"""N.E.X.U.S. Voice Service Abstraction."""

from abc import ABC, abstractmethod
from typing import Optional, Callable
from nexus_voice.intent_parser import VoiceIntent, VoiceIntentParser


class VoiceServiceBase(ABC):
    """Abstract interface for voice input and text-to-speech output."""

    def __init__(self, on_intent_callback: Optional[Callable[[VoiceIntent], None]] = None):
        self.on_intent_callback = on_intent_callback
        self.intent_parser = VoiceIntentParser()
        self.is_listening: bool = False

    @abstractmethod
    def start_listening(self) -> bool:
        """Begins asynchronous speech recognition."""
        pass

    @abstractmethod
    def stop_listening(self) -> None:
        """Stops speech recognition."""
        pass

    @abstractmethod
    def speak(self, text: str) -> bool:
        """Synthesizes speech output."""
        pass
