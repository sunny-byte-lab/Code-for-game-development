"""Tests for Phase 3: Windows PC Hardening, Physical Mouse Conflict Resolution,
Guaranteed Button Release Watchdog, and Secure Remote Protocol Gateway.
"""

import time
import socket
import json
import pytest
from unittest.mock import MagicMock, patch

from nexus_pc.hardware_safety import HardwareConflictResolver, GuaranteedButtonReleaseGuard
from nexus_pc.input_adapter import PCInputAdapter
from nexus_protocol.spec import ProtocolMessage, MessageType, CommandAction
from nexus_protocol.security import SecurityManager
from nexus_protocol.validator import CommandValidator
from nexus_protocol.server import RemoteProtocolServer
from nexus_core.command_router import CommandRouter
from nexus_core.lifecycle import AssistantState, AssistantMode
from app.virtual_mouse import VirtualMouse, MockMouseBackend, MouseState
from app.settings_manager import SettingsManager


# ============================================================================
# 1. PHYSICAL MOUSE CONFLICT RESOLUTION
# ============================================================================
class TestHardwareConflictResolution:
    """Verifies that physical mouse movement yields virtual control and prevents fighting."""

    def test_conflict_detection_when_physical_moves(self):
        resolver = HardwareConflictResolver(movement_threshold=20.0, yield_duration_seconds=1.0, enabled=True)
        # Mock get_real_cursor_pos to simulate user moving physical hardware mouse
        resolver.get_real_cursor_pos = MagicMock(return_value=(500, 500))
        resolver.record_virtual_move(100, 100)

        # Delta is hypot(500-100, 500-100) = ~565px > 20px threshold
        assert resolver.is_physical_mouse_active() is True

    def test_no_conflict_when_virtual_and_physical_align(self):
        resolver = HardwareConflictResolver(movement_threshold=20.0, yield_duration_seconds=1.0, enabled=True)
        resolver.get_real_cursor_pos = MagicMock(return_value=(102, 103))
        resolver.record_virtual_move(100, 100)

        # Delta is hypot(2, 3) = ~3.6px < 20px threshold
        assert resolver.is_physical_mouse_active() is False

    def test_yield_duration_enforced(self):
        resolver = HardwareConflictResolver(movement_threshold=20.0, yield_duration_seconds=0.20, enabled=True)
        resolver.get_real_cursor_pos = MagicMock(return_value=(500, 500))
        resolver.record_virtual_move(100, 100)

        assert resolver.is_physical_mouse_active() is True
        # Immediately after, still yielding
        assert resolver.is_physical_mouse_active() is True

        # Wait past yield timeout
        time.sleep(0.22)
        # Reset virtual position to match
        resolver.record_virtual_move(500, 500)
        assert resolver.is_physical_mouse_active() is False

    def test_virtual_mouse_yields_when_conflict_active(self):
        mock_backend = MockMouseBackend()
        vm = VirtualMouse(backend=mock_backend)
        # Enable conflict resolver with mock real cursor
        vm.conflict_resolver = HardwareConflictResolver(movement_threshold=20.0, yield_duration_seconds=0.5, enabled=True)
        vm.conflict_resolver.get_real_cursor_pos = MagicMock(return_value=(800, 600))
        vm.conflict_resolver.record_virtual_move(200, 200)

        # Attempt to dispatch raw move
        ok = vm._dispatch_raw_move(400, 400)
        assert ok is False  # Virtual move must be suppressed!
        assert vm.curr_x == 800.0
        assert vm.curr_y == 600.0


# ============================================================================
# 2. GUARANTEED BUTTON RELEASE WATCHDOG
# ============================================================================
class TestGuaranteedButtonRelease:
    """Verifies that mouse buttons can never become stuck down."""

    def test_watchdog_auto_releases_held_button(self):
        released_buttons = []
        guard = GuaranteedButtonReleaseGuard(
            release_callback=lambda btn: released_buttons.append(btn),
            max_click_duration=0.05
        )

        guard.mark_down("left")
        assert "left" in guard._held_buttons

        # Initially within timeout
        guard.verify_watchdog()
        assert len(released_buttons) == 0

        # Wait past max_click_duration
        time.sleep(0.07)
        guard.verify_watchdog()

        assert "left" in released_buttons
        assert "left" not in guard._held_buttons

    def test_normal_up_clears_button_without_watchdog_firing(self):
        released_buttons = []
        guard = GuaranteedButtonReleaseGuard(
            release_callback=lambda btn: released_buttons.append(btn),
            max_click_duration=0.05
        )

        guard.mark_down("left")
        guard.mark_up("left")
        time.sleep(0.06)
        guard.verify_watchdog()

        assert len(released_buttons) == 0

    def test_virtual_mouse_left_click_always_cleans_guard(self):
        mock_backend = MockMouseBackend()
        vm = VirtualMouse(backend=mock_backend)
        ok, msg = vm.left_click()
        assert ok is True
        assert "Left Click" in msg
        # Button guard held buttons must be empty after click completes
        if vm.button_guard:
            assert len(vm.button_guard._held_buttons) == 0


# ============================================================================
# 3. SECURE REMOTE PROTOCOL SERVER & VALIDATION
# ============================================================================
class TestSecureRemoteProtocol:
    """Tests end-to-end PIN pairing, token authentication, command allowlisting, and router execution."""

    def test_pin_pairing_success_and_token_creation(self):
        security = SecurityManager(pin_timeout_seconds=60)
        pin = security.generate_pairing_pin()
        assert len(pin) == 6
        assert pin.isdigit()

        ok, token, reason = security.verify_pin_and_create_session(pin, "phone_001", "Pixel 8")
        assert ok is True
        assert token is not None
        assert reason == "PAIRING_SUCCESS"
        assert security.active_session_count == 1

        # Second attempt with same PIN must fail (one-time use)
        ok2, _, reason2 = security.verify_pin_and_create_session(pin, "phone_002", "iPhone 15")
        assert ok2 is False

    def test_unauthenticated_command_rejected(self):
        server = RemoteProtocolServer(host="127.0.0.1", port=8991)
        msg = ProtocolMessage(
            msg_type=MessageType.COMMAND,
            token="invalid_or_fake_token",
            nonce=1,
            timestamp=time.time(),
            payload={"action": "CLICK", "parameters": {"button": "left"}}
        )
        reply = server._process_message(msg)
        assert reply is not None
        assert reply.msg_type == MessageType.AUTH_FAILED

    def test_unauthorized_shell_command_strictly_rejected(self):
        validator = CommandValidator()
        # Attempt to inject raw OS shell commands
        bad_commands = ["bash", "sh", "powershell", "cmd.exe", "rm -rf /", "DEL /F /Q C:\\*"]
        for bad_cmd in bad_commands:
            ok, action, payload, err = validator.validate_command(bad_cmd, {})
            assert ok is False
            assert "REJECTED" in err or "DISALLOWED" in err or "INVALID" in err

    def test_command_routing_via_command_router(self):
        router = CommandRouter()
        # Valid MOUSE_MOVE action
        ok, msg = router.route_command(CommandAction.MOUSE_MOVE, {"dx": 10.0, "dy": -5.0})
        assert ok is True
        assert "MOUSE_MOVE" in msg or "MOVED" in msg

        # Valid VOLUME_UP action
        ok_v, msg_v = router.route_command(CommandAction.VOLUME_UP, {"step": 5})
        assert ok_v is True

        # Safety interlock enforcement: in EMERGENCY_STOP, non-RESUME commands are blocked
        router.set_state(AssistantState.EMERGENCY_STOP)
        ok_blocked, err = router.route_command(CommandAction.CLICK, {"button": "left"})
        assert ok_blocked is False
        assert "SAFETY_INTERLOCK_ACTIVE" in err

        # Resume allows commands again
        ok_res, _ = router.route_command(CommandAction.RESUME, {})
        assert ok_res is True
        assert router.state == AssistantState.ACTIVE

    def test_pc_input_adapter_hardware_integration(self):
        mock_backend = MockMouseBackend()
        vm = VirtualMouse(backend=mock_backend)
        adapter = PCInputAdapter(mouse_controller=vm)

        # Move relative
        ok = adapter.move_relative(15.0, 20.0)
        assert ok is True

        # Click
        ok_c = adapter.click("left")
        assert ok_c is True
        assert any(e.event_type == "CLICK" and e.button == "left" for e in mock_backend.events)

        # Release all
        adapter.release_all_buttons()
        assert vm.is_dragging is False


# ============================================================================
# 4. REMOTE PROTOCOL SERVER BACKGROUND SOCKET
# ============================================================================
class TestRemoteServerSocketLifecycle:
    """Tests background thread socket listening, HELLO, and client termination."""

    def test_server_starts_and_stops_cleanly(self):
        # Bind to high ephemeral port
        server = RemoteProtocolServer(host="127.0.0.1", port=9876)
        try:
            assert server.start() is True
            assert server.is_running is True
            time.sleep(0.15)
        finally:
            server.stop()
            assert server.is_running is False

    def test_hello_and_pairing_handshake_flow(self):
        server = RemoteProtocolServer(host="127.0.0.1", port=8765)
        # 1. HELLO handshake
        hello_msg = ProtocolMessage(msg_type=MessageType.HELLO)
        reply = server._process_message(hello_msg)
        assert reply is not None
        assert reply.msg_type == MessageType.HELLO
        assert reply.payload["pairing_required"] is True

        # 2. PAIR_REQUEST with valid PIN
        pin = server.security.generate_pairing_pin()
        pair_msg = ProtocolMessage(
            msg_type=MessageType.PAIR_REQUEST,
            payload={"pin": pin, "device_id": "test_phone_99", "device_name": "Galaxy S24"}
        )
        pair_reply = server._process_message(pair_msg)
        assert pair_reply is not None
        assert pair_reply.msg_type == MessageType.AUTH_SUCCESS
        assert pair_reply.token is not None

        # 3. HEARTBEAT
        hb_msg = ProtocolMessage(msg_type=MessageType.HEARTBEAT)
        hb_reply = server._process_message(hb_msg)
        assert hb_reply is not None
        assert hb_reply.msg_type == MessageType.HEARTBEAT
        assert hb_reply.payload["status"] == "ALIVE"

        # 4. DISCONNECT
        disc_msg = ProtocolMessage(
            msg_type=MessageType.DISCONNECT,
            token=pair_reply.token,
            nonce=1,
            timestamp=time.time()
        )
        disc_reply = server._process_message(disc_msg)
        assert disc_reply is not None
        assert disc_reply.msg_type == MessageType.DISCONNECT
        assert server.security.active_session_count == 0
