"""N.E.X.U.S. Mock AI Provider.
Provides deterministic, fast offline responses for local testing and zero-credential fallback.
"""

from typing import List, Optional, Iterator
from nexus_ai.provider_base import AIProvider, ChatMessage, AIResponse


class MockAIProvider(AIProvider):
    """Deterministic, zero-credential AI provider for testing and offline mode."""

    def __init__(self, assistant_name: str = "N.E.X.U.S."):
        self.assistant_name = assistant_name

    @property
    def name(self) -> str:
        return "mock"

    @property
    def is_configured(self) -> bool:
        return True

    def generate(self, messages: List[ChatMessage], system_prompt: Optional[str] = None) -> AIResponse:
        last_user = ""
        for m in reversed(messages):
            if m.role == "user":
                last_user = m.content.strip().lower()
                break

        reply = self._generate_canned_reply(last_user)
        return AIResponse(content=reply, model="mock-neural-core-v1", usage={"total_tokens": len(reply.split())})

    def stream(self, messages: List[ChatMessage], system_prompt: Optional[str] = None) -> Iterator[str]:
        resp = self.generate(messages, system_prompt)
        words = resp.content.split(" ")
        for i, w in enumerate(words):
            yield w + (" " if i < len(words) - 1 else "")

    def _generate_canned_reply(self, prompt: str) -> str:
        if not prompt:
            return f"{self.assistant_name} Neural Core online. Optical sensors and gesture matrix active."
        if "status" in prompt or "system" in prompt:
            return "All subsystems operational. Tracking latency nominal (16ms). Air keyboard online."
        if "hello" in prompt or "hi" in prompt or "nexus" in prompt:
            return f"Greetings. {self.assistant_name} standing by. How may I assist your workflow?"
        if "help" in prompt:
            return "Available capabilities: Hand gesture mouse navigation, dual-hand air keyboard, system volume control, and remote mobile device pairing."
        return f"[{self.assistant_name}] Command received: '{prompt}'. Telemetry synchronized."
