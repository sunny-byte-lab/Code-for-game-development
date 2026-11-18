"""N.E.X.U.S. Conversation Manager.
Maintains multi-turn context memory, token window sliding, and history persistence.
"""

import time
import threading
from typing import List, Optional, Dict, Any
from nexus_ai.provider_base import ChatMessage, AIProvider, AIResponse


class ConversationManager:
    """Manages chat conversation history and interacts with the active AI provider."""

    def __init__(self, provider: AIProvider, system_prompt: Optional[str] = None, max_history: int = 20):
        self.provider = provider
        self.system_prompt = system_prompt or (
            "You are N.E.X.U.S., an advanced holographic tactical AI assistant. "
            "Keep responses concise, confident, structured, and focused on helping the user."
        )
        self.max_history = max_history
        self._history: List[ChatMessage] = []
        self._lock = threading.RLock()

    def set_provider(self, provider: AIProvider) -> None:
        with self._lock:
            self.provider = provider

    def add_message(self, role: str, content: str) -> ChatMessage:
        with self._lock:
            msg = ChatMessage(role=role, content=content, timestamp=time.time())
            self._history.append(msg)
            # Enforce max history window
            if len(self._history) > self.max_history:
                self._history = self._history[-self.max_history:]
            return msg

    def send_user_message(self, text: str) -> AIResponse:
        """Adds a user message, invokes the provider, stores assistant response, and returns the result."""
        with self._lock:
            self.add_message("user", text)
            response = self.provider.generate(self._history, system_prompt=self.system_prompt)
            if response.content:
                self.add_message("assistant", response.content)
            return response

    def get_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [m.to_dict() for m in self._history]

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()
