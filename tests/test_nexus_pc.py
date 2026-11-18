"""Unit tests for nexus_pc hardware safety, conflict resolver, and watchdog."""

import time
import pytest
from nexus_pc import HardwareConflictResolver, GuaranteedButtonReleaseGuard


def test_guaranteed_button_release_watchdog():
    released_buttons = []
    guard = GuaranteedButtonReleaseGuard(
        release_callback=lambda b: released_buttons.append(b),
        max_click_duration=0.05
    )

    guard.mark_down("left")
    guard.mark_down("right")

    # Within duration -> not released
    guard.verify_watchdog()
    assert len(released_buttons) == 0

    # Wait past duration
    time.sleep(0.06)
    guard.verify_watchdog()

    assert "left" in released_buttons
    assert "right" in released_buttons


def test_hardware_conflict_resolver():
    resolver = HardwareConflictResolver(movement_threshold=20.0, yield_duration_seconds=0.1)

    # Initial state
    assert resolver.is_physical_mouse_active() is False

    # Virtual move recorded
    rx, ry = resolver.get_real_cursor_pos()
    resolver.record_virtual_move(rx, ry)
    assert resolver.is_physical_mouse_active() is False

    # Simulate virtual tracking position far away from physical cursor
    resolver.record_virtual_move(rx + 100, ry + 100)
    assert resolver.is_physical_mouse_active() is True

    # Yield persists during timeout
    assert resolver.is_physical_mouse_active() is True

    # Reset
    resolver.reset_yield()
    assert resolver.is_physical_mouse_active() is False
