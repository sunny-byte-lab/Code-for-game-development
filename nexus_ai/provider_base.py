"""N.E.X.U.S. AI Provider Abstraction.
Defines interfaces and message models for conversational AI backends.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Iterator


@dataclass
class ChatMessage:
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {"role": self.role, "content": self.content, "timestamp": self.timestamp}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMessage":
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", time.time())
        )


@dataclass
class AIResponse:
    content: str
    model: str
    usage: Dict[str, int] = field(default_factory=dict)
    finish_reason: str = "stop"
    error: Optional[str] = None


class AIProvider(ABC):
    """Abstract base class for all AI conversational backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Returns the provider identifier name (e.g. 'gemini', 'openai', 'mock')."""
        pass

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Returns True if the provider has necessary API credentials or endpoints."""
        pass

    @abstractmethod
    def generate(self, messages: List[ChatMessage], system_prompt: Optional[str] = None) -> AIResponse:
        """Generates a complete response for the given conversation messages."""
        pass

    @abstractmethod
    def stream(self, messages: List[ChatMessage], system_prompt: Optional[str] = None) -> Iterator[str]:
        """Yields chunks of generated text in real time."""
        pass
