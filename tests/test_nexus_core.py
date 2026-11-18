"""Unit tests for nexus_core command routing, event bus, and safety interlocks."""

import pytest
from nexus_core import CommandRouter, EventBus, AssistantState, AssistantMode
from nexus_protocol import CommandAction


def test_event_bus_pub_sub():
    bus = EventBus()
    events = []

    bus.subscribe("mode_changed", lambda data: events.append(data))
    bus.publish("mode_changed", "KEYBOARD")

    assert len(events) == 1
    assert events[0] == "KEYBOARD"

    # Wildcard listener
    wildcard_events = []
    bus.subscribe("*", lambda data: wildcard_events.append(data))
    bus.publish("any_event", 42)
    assert 42 in wildcard_events


def test_command_router_dispatch():
    router = CommandRouter()

    # Route volume command
    ok, msg = router.route_command(CommandAction.VOLUME_UP, {"step": 5})
    assert ok is True
    assert "VOLUME_UP" in msg

    # Route mode change
    m_ok, m_msg = router.route_command(CommandAction.SET_MODE, {"mode": "KEYBOARD"})
    assert m_ok is True
    assert router.mode == AssistantMode.KEYBOARD


def test_command_router_emergency_stop_interlock():
    router = CommandRouter()
    assert router.state == AssistantState.ACTIVE

    # Trigger emergency stop
    e_ok, _ = router.route_command(CommandAction.EMERGENCY_STOP, {})
    assert e_ok is True
    assert router.state == AssistantState.EMERGENCY_STOP

    # Subsequent commands blocked by safety interlock
    v_ok, v_err = router.route_command(CommandAction.VOLUME_UP, {"step": 5})
    assert v_ok is False
    assert "SAFETY_INTERLOCK_ACTIVE" in v_err

    # Resume command clears interlock
    r_ok, _ = router.route_command(CommandAction.RESUME, {})
    assert r_ok is True
    assert router.state == AssistantState.ACTIVE
