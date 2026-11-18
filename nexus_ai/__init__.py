"""N.E.X.U.S. AI Subsystem Package."""

from nexus_ai.provider_base import AIProvider, ChatMessage, AIResponse
from nexus_ai.mock_provider import MockAIProvider
from nexus_ai.gemini_provider import GeminiProvider
from nexus_ai.openai_provider import OpenAIProvider
from nexus_ai.conversation_manager import ConversationManager


def create_ai_provider(provider_type: str = "mock", api_key: str = "", model_name: str = "", **kwargs) -> AIProvider:
    """Factory helper to instantiate the configured AI provider."""
    p_type = (provider_type or "mock").lower()
    if p_type == "gemini":
        return GeminiProvider(api_key=api_key, model_name=model_name or "gemini-1.5-flash")
    elif p_type in ("openai", "local", "ollama"):
        base_url = kwargs.get("base_url", "https://api.openai.com/v1")
        if p_type == "ollama":
            base_url = "http://127.0.0.1:11434/v1"
        return OpenAIProvider(api_key=api_key, model_name=model_name or "gpt-4o-mini", base_url=base_url)
    return MockAIProvider()


__all__ = [
    "AIProvider",
    "ChatMessage",
    "AIResponse",
    "MockAIProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "ConversationManager",
    "create_ai_provider"
]
