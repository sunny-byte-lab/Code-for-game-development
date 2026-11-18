"""Unit tests for safety controller, emergency stop, cooldowns, and drag release callbacks."""

import time
import pytest
from app.safety_controller import SafetyController, ControlMode


class TestSafetyController:
    def test_default_state_is_disabled(self):
        safety = SafetyController()
        # Security requirement: Gesture control strictly disabled by default at startup!
        assert safety.is_enabled is False
        assert safety.can_process_input() is False

    def test_explicit_enable_and_disable(self):
        safety = SafetyController(hand_stable_delay=0.01)
        safety.enable_control()
        assert safety.is_enabled is True

        # Input still not allowed until a hand is detected!
        assert safety.can_process_input() is False

        # Simulate hand detected
        safety.on_hand_detected()
        time.sleep(0.02)
        assert safety.can_process_input() is True

        # Disable
        safety.disable_control()
        assert safety.is_enabled is False
        assert safety.can_process_input() is False

    def test_emergency_stop_kills_input_and_releases_drag(self):
        safety = SafetyController()
        safety.enable_control()
        safety.on_hand_detected()

        drag_released = False
        def mock_release():
            nonlocal drag_released
            drag_released = True

        safety.cancel_drag_callback = mock_release

        # Trigger emergency stop
        safety.emergency_stop(source="TEST")

        assert safety.is_enabled is False
        assert safety.current_mode == ControlMode.EMERGENCY_STOP
        assert safety.can_process_input() is False
        assert drag_released is True

    def test_pause_and_resume(self):
        safety = SafetyController(hand_stable_delay=0.01)
        safety.enable_control()
        safety.on_hand_detected()
        time.sleep(0.02)
        assert safety.can_process_input() is True

        # Enter Pause mode
        safety.pause_control()
        assert safety.current_mode == ControlMode.PAUSED
        assert safety.can_process_input() is False

        # Resume
        safety.resume_control()
        assert safety.current_mode == ControlMode.MOUSE
        assert safety.can_process_input() is True

    def test_mode_switch_cooldown(self):
        safety = SafetyController(mode_change_cooldown=0.2)
        safety.enable_control()

        # Initial switch to APP_LAUNCH
        success1 = safety.switch_mode(ControlMode.APP_LAUNCH)
        assert success1 is True
        assert safety.current_mode == ControlMode.APP_LAUNCH

        # Immediate switch should be rejected by cooldown
        success2 = safety.switch_mode(ControlMode.SYSTEM_CONTROL)
        assert success2 is False
        assert safety.current_mode == ControlMode.APP_LAUNCH

        # Wait past cooldown
        time.sleep(0.25)
        success3 = safety.switch_mode(ControlMode.SYSTEM_CONTROL)
        assert success3 is True
        assert safety.current_mode == ControlMode.SYSTEM_CONTROL

    def test_system_state_lifecycle_and_reengagement(self):
        from app.safety_controller import SystemState
        safety = SafetyController(hand_stable_delay=0.01)

        # 1. DISABLED initially
        assert safety.system_state == SystemState.DISABLED

        # 2. READY when enabled without hand
        safety.enable_control()
        assert safety.system_state == SystemState.READY

        # 3. ACTIVE when hand detected
        safety.on_hand_detected()
        assert safety.system_state == SystemState.ACTIVE

        # 4. PAUSED
        safety.pause_control()
        assert safety.system_state == SystemState.PAUSED
        assert safety.can_process_input() is False

        # 5. Resume from PAUSED
        resumed = safety.resume_control()
        assert resumed is True
        assert safety.system_state == SystemState.ACTIVE

        # 6. EMERGENCY STOP
        safety.emergency_stop(source="UNIT_TEST")
        assert safety.system_state == SystemState.EMERGENCY_STOP
        assert safety.can_process_input() is False

        # 7. RESUME MUST NOT BYPASS EMERGENCY STOP!
        resume_attempt = safety.resume_control()
        assert resume_attempt is False
        assert safety.system_state == SystemState.EMERGENCY_STOP

        # 8. Deliberate re-engagement restores control
        safety.reengage_from_emergency()
        assert safety.system_state == SystemState.ACTIVE

    def test_camera_worker_dispatch_under_safety_states(self):
        """Verifies CameraWorker action dispatch obeys SafetyController states without NameError."""
        from app.camera_worker import CameraWorker
        from app.gesture_recognizer import GestureState, GestureType
        from app.safety_controller import SystemState

        safety = SafetyController()
        worker = CameraWorker(safety=safety)

        # 1. When disabled (not permitted)
        state_idle = GestureState(GestureType.NONE)
        status_disabled = worker._dispatch_actions(state_idle, None, fps=30.0)
        assert status_disabled.action_permitted is False
        assert status_disabled.system_state == SystemState.DISABLED.value

        # 2. Closed fist gesture must NOT trigger emergency stop (unwanted lock removed)
        state_fist = GestureState(GestureType.NONE, description="CLOSED FIST (RESTING HAND)")
        status_fist = worker._dispatch_actions(state_fist, None, fps=30.0)
        assert safety.system_state != SystemState.EMERGENCY_STOP
        assert "EMERGENCY" not in status_fist.last_action

        # 3. Manual emergency stop (via Esc or GUI button) halts control cleanly
        safety.emergency_stop(source="MANUAL [ESC]")
        assert safety.system_state == SystemState.EMERGENCY_STOP
        safety.reengage_from_emergency()
        assert safety.system_state != SystemState.EMERGENCY_STOP

    def test_thread_safe_signals_and_deduplication(self):
        """Verifies SafetySignals emits cleanly and deduplicates repeated hand state triggers."""
        from PySide6.QtCore import QObject
        from app.safety_controller import SystemState

        safety = SafetyController()

        received_states = []
        received_modes = []
        received_enables = []

        class MockQtReceiver(QObject):
            def on_state(self, s):
                received_states.append(s)
            def on_mode(self, m):
                received_modes.append(m)
            def on_enable(self, e):
                received_enables.append(e)

        receiver = MockQtReceiver()
        safety.register_state_listener(receiver.on_state)
        safety.register_mode_listener(receiver.on_mode)
        safety.register_enable_listener(receiver.on_enable)

        # 1. Enable control -> should emit enable_changed and state_changed
        safety.enable_control()
        assert received_enables == [True]
        assert received_states == [SystemState.READY]
        assert received_modes == []  # Mode did not change

        # 2. Hand detected -> state changes to ACTIVE, mode still unchanged
        safety.on_hand_detected()
        assert received_states == [SystemState.READY, SystemState.ACTIVE]
        assert received_modes == []  # Crucial: mode listener was not bombarded!

        # 3. Repeated on_hand_detected -> deduplicated, no new signal
        safety.on_hand_detected()
        assert len(received_states) == 2
        assert len(received_modes) == 0

        # 4. Mode switch -> mode signal emitted
        safety.switch_mode(ControlMode.KEYBOARD)
        assert received_modes == [ControlMode.KEYBOARD]

        # 5. Hand lost (after grace period) -> state changes, mode does NOT re-emit
        safety.hand_loss_grace_duration = 0.0
        safety.on_hand_lost()
        assert received_states[-1] == SystemState.READY
        assert len(received_modes) == 1

    def test_system_state_emergency_stopped_alias(self):
        """Verifies EMERGENCY_STOPPED alias prevents NameError and AttributeError."""
        from app.safety_controller import SystemState
        assert SystemState.EMERGENCY_STOP == SystemState.EMERGENCY_STOPPED
        assert SystemState.EMERGENCY_STOPPED.value == "EMERGENCY_STOP"

    def test_cross_thread_worker_safety_notification(self):
        """Verifies notifications triggered from a background thread marshal safely to the main GUI thread."""
        import threading
        from PySide6.QtCore import QCoreApplication

        app = QCoreApplication.instance()
        if app is None:
            app = QCoreApplication([])

        main_tid = threading.get_ident()
        callback_threads = []

        safety = SafetyController()
        safety.enable_control()
        safety.on_hand_detected()

        def on_state(state):
            callback_threads.append(threading.get_ident())

        safety.register_state_listener(on_state)

        # Trigger from a worker thread (simulating CameraWorker losing hand)
        def bg_worker():
            safety.hand_loss_grace_duration = 0.0
            safety.last_hand_seen_time = None
            safety.on_hand_lost()

        worker = threading.Thread(target=bg_worker)
        worker.start()
        worker.join()

        # Before pumping event loop: worker thread did not directly call GUI listener
        assert not any(t == worker.ident for t in callback_threads)

        # Pump Qt event loop: listener should be safely invoked on the main GUI thread
        app.processEvents()

        assert len(callback_threads) > 0
        assert all(t == main_tid for t in callback_threads)
