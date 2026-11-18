"""Unit tests for nexus_ai provider abstractions, conversation manager, and mock engine."""

import pytest
from nexus_ai import create_ai_provider, ConversationManager, MockAIProvider, ChatMessage


def test_mock_ai_provider_generation():
    provider = MockAIProvider()
    assert provider.name == "mock"
    assert provider.is_configured is True

    resp = provider.generate([ChatMessage(role="user", content="System status")])
    assert "operational" in resp.content.lower()
    assert resp.model == "mock-neural-core-v1"


def test_conversation_manager_turn_taking():
    provider = MockAIProvider()
    conv = ConversationManager(provider, max_history=4)

    # First turn
    r1 = conv.send_user_message("Hello")
    assert "Greetings" in r1.content
    assert len(conv.get_history()) == 2  # user + assistant

    # Second turn
    r2 = conv.send_user_message("Help")
    assert "Available capabilities" in r2.content
    assert len(conv.get_history()) == 4

    # Third turn enforces max_history sliding window
    conv.send_user_message("status")
    assert len(conv.get_history()) == 4  # trimmed to max 4


def test_create_ai_provider_factory():
    p_mock = create_ai_provider("mock")
    assert isinstance(p_mock, MockAIProvider)

    p_gemini = create_ai_provider("gemini", api_key="test_key_123456789")
    assert p_gemini.name == "gemini"
    assert p_gemini.is_configured is True

    p_openai = create_ai_provider("openai", api_key="sk-test123456")
    assert p_openai.name == "openai"
    assert p_openai.is_configured is True
