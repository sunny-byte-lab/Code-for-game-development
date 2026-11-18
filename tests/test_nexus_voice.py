"""Unit tests for nexus_voice intent parsing and whitelisted keyword execution."""

import pytest
from nexus_voice import VoiceIntentParser, VoiceIntent


def test_voice_intent_parser_whitelisted_commands():
    parser = VoiceIntentParser()

    # Volume
    i1 = parser.parse_phrase("please volume up")
    assert i1 is not None and i1.action == "VOLUME_UP"

    i2 = parser.parse_phrase("decrease volume a bit")
    assert i2 is not None and i2.action == "VOLUME_DOWN"

    i3 = parser.parse_phrase("mute audio")
    assert i3 is not None and i3.action == "MUTE_AUDIO"

    # Emergency halt
    i4 = parser.parse_phrase("emergency stop")
    assert i4 is not None and i4.action == "EMERGENCY_STOP"

    # App Launching
    i5 = parser.parse_phrase("open chrome")
    assert i5 is not None and i5.action == "LAUNCH_APP"
    assert i5.parameter == "google_chrome"

    i6 = parser.parse_phrase("launch vscode")
    assert i6 is not None and i6.action == "LAUNCH_APP"
    assert i6.parameter == "visual_studio_code"

    # AI Query prefix
    i7 = parser.parse_phrase("hey nexus what is the weather")
    assert i7 is not None and i7.action == "AI_QUERY"
    assert i7.parameter == "what is the weather"


def test_voice_intent_parser_rejects_unwhitelisted():
    parser = VoiceIntentParser()
    assert parser.parse_phrase("format c:") is None
    assert parser.parse_phrase("delete all files") is None
    assert parser.parse_phrase("shutdown -r -t 0") is None
    assert parser.parse_phrase("") is None
