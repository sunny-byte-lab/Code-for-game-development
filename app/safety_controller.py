"""JARVIS Safety and Mode Controller.
Enforces safety gates, control modes, state transitions, debouncing, and emergency stop procedures.
"""

import time
import enum
import logging
from typing import Optional, Callable, Tuple, List
from PySide6.QtCore import QObject, Signal, Qt, QCoreApplication, QThread

logger = logging.getLogger("NEXUS.Safety")


class SafetySignals(QObject):
    """Qt signal bridge for thread-safe cross-thread GUI notification."""
    sig_notify = Signal()              # Cross-thread worker-to-GUI dispatch trigger
    mode_changed = Signal(object)      # ControlMode
    state_changed = Signal(object)     # SystemState
    enable_changed = Signal(bool)      # bool


class SystemState(enum.Enum):
    """Centralized lifecycle state of the JARVIS desktop input controller."""
    DISABLED = "DISABLED"              # Control explicitly turned off (standby)
    READY = "READY"                    # Control enabled, optical sensor awaiting hand input
    ACTIVE = "ACTIVE"                  # Control enabled and hand actively tracked
    PAUSED = "PAUSED"                  # Temporarily suspended (via Open Palm or GUI pause)
    EMERGENCY_STOP = "EMERGENCY_STOP"  # Emergency kill switch tripped; requires explicit re-engagement
    EMERGENCY_STOPPED = "EMERGENCY_STOP" # Alias for backward compatibility


class ControlMode(enum.Enum):
    """Functional target operating mode of the JARVIS gesture engine."""
    MOUSE = "MOUSE MODE"
    DESKTOP_CONTROL = "MOUSE MODE"        # Canonical alias for full desktop control
    DESKTOP = "MOUSE MODE"                # Short alias
    APP_LAUNCH = "APP LAUNCH MODE"
    SYSTEM_CONTROL = "SYSTEM CONTROL MODE"
    SYSTEM = "SYSTEM CONTROL MODE"        # Short alias
    LAB_3D = "3D LAB MODE"
    HOLOGRAM_CONTROL = "3D LAB MODE"      # Canonical alias for 3D holographic lab
    HOLOGRAM = "3D LAB MODE"              # Short alias
    PRESENTATION = "PRESENTATION MODE"    # Dedicated slide presentation mode
    KEYBOARD = "KEYBOARD MODE"            # Dedicated holographic keyboard mode
    HOLO_KEYBOARD = "KEYBOARD MODE"       # Canonical alias
    AIR_TYPING = "AIR TYPING MODE"        # Dedicated two-hand air typing mode
    AIR_KEYBOARD = "AIR TYPING MODE"      # Canonical alias
    GLOBAL_KEYBOARD = "GLOBAL KEYBOARD MODE"
    GLOBAL_AIR_KEYBOARD = "GLOBAL KEYBOARD MODE"
    PAUSED = "PAUSED MODE"
    EMERGENCY_STOP = "EMERGENCY STOP"


class SafetyController:
    """Monitors system safety, state transitions, debouncing, and kill switches."""

    def __init__(self, mode_change_cooldown: float = 0.8, hand_stable_delay: float = 0.15):
        # By default, gesture-generated system control is STRICTLY DISABLED at startup!
        self.is_enabled: bool = False
        self._is_paused: bool = False
        self._is_emergency: bool = False

        self.current_mode: ControlMode = ControlMode.MOUSE
        self.previous_mode: ControlMode = ControlMode.MOUSE
        self.is_global_keyboard: bool = False

        # Timers & Debouncing
        self.mode_change_cooldown: float = mode_change_cooldown
        self.hand_stable_delay: float = hand_stable_delay
        self.last_mode_change_time: float = 0.0
        self.hand_first_seen_time: Optional[float] = None
        self.last_hand_seen_time: Optional[float] = None
        self.is_hand_present: bool = False
        self.hand_loss_grace_duration: float = 0.30

        # Active drag cancellation callback (provided by VirtualMouse)
        self.cancel_drag_callback: Optional[Callable[[], None]] = None

        # Thread-safe Qt signal bridge
        self.signals = SafetySignals()
        self.signals.sig_notify.connect(self._do_notify, Qt.ConnectionType.QueuedConnection)

        # State change listeners (direct callbacks for non-GUI / test consumers)
        self.mode_listeners: List[Callable[[ControlMode], None]] = []
        self.enable_listeners: List[Callable[[bool], None]] = []
        self.state_listeners: List[Callable[[SystemState], None]] = []

        # Deduplication cache to prevent signal storms and redundant GUI repolishing
        self._last_notified_state: Optional[SystemState] = self.system_state
        self._last_notified_mode: Optional[ControlMode] = self.current_mode
        self._last_notified_enabled: Optional[bool] = self.is_enabled

    @property
    def system_state(self) -> SystemState:
        """Calculates current centralized system state."""
        if self._is_emergency or self.current_mode == ControlMode.EMERGENCY_STOP:
            return SystemState.EMERGENCY_STOP
        if self._is_paused or self.current_mode == ControlMode.PAUSED:
            return SystemState.PAUSED
        if not self.is_enabled:
            return SystemState.DISABLED
        if self.is_hand_present:
            return SystemState.ACTIVE
        return SystemState.READY

    def register_mode_listener(self, cb: Callable[[ControlMode], None]) -> None:
        """Registers a mode listener. If callback belongs to a QObject, connects via Qt signal."""
        owner = getattr(cb, "__self__", None)
        if isinstance(owner, QObject):
            self.signals.mode_changed.connect(cb, Qt.ConnectionType.AutoConnection)
        else:
            self.mode_listeners.append(cb)

    def register_enable_listener(self, cb: Callable[[bool], None]) -> None:
        """Registers an enable listener. If callback belongs to a QObject, connects via Qt signal."""
        owner = getattr(cb, "__self__", None)
        if isinstance(owner, QObject):
            self.signals.enable_changed.connect(cb, Qt.ConnectionType.AutoConnection)
        else:
            self.enable_listeners.append(cb)

    def register_state_listener(self, cb: Callable[[SystemState], None]) -> None:
        """Registers a state listener. If callback belongs to a QObject, connects via Qt signal."""
        owner = getattr(cb, "__self__", None)
        if isinstance(owner, QObject):
            self.signals.state_changed.connect(cb, Qt.ConnectionType.AutoConnection)
        else:
            self.state_listeners.append(cb)

    def _notify_all(self) -> None:
        """Thread-safe notification entry point.

        If called from a background worker thread, safely marshals the notification
        to the Qt Main GUI thread via QueuedConnection to guarantee zero access violations.
        If called from the main thread or in a test environment, executes immediately.
        """
        app = QCoreApplication.instance()
        if app is not None and QThread.currentThread() != app.thread():
            self.signals.sig_notify.emit()
            return
        self._do_notify()

    def _do_notify(self) -> None:
        """Centralized notification executed on the main GUI thread with deduplication."""
        curr_state = self.system_state
        curr_mode = self.current_mode
        curr_enabled = self.is_enabled

        # 1. State change notification (only on actual change)
        if curr_state != self._last_notified_state:
            self._last_notified_state = curr_state
            try:
                self.signals.state_changed.emit(curr_state)
            except Exception as e:
                logger.error(f"Error emitting state_changed signal: {e}")

            for cb in list(self.state_listeners):
                try:
                    cb(curr_state)
                except Exception as e:
                    logger.error(f"Error in state listener: {e}")

        # 2. Mode change notification (only on actual change)
        if curr_mode != self._last_notified_mode:
            self._last_notified_mode = curr_mode
            try:
                self.signals.mode_changed.emit(curr_mode)
            except Exception as e:
                logger.error(f"Error emitting mode_changed signal: {e}")

            for cb in list(self.mode_listeners):
                try:
                    cb(curr_mode)
                except Exception as e:
                    logger.error(f"Error in mode listener: {e}")

        # 3. Enable state change notification (only on actual change)
        if curr_enabled != self._last_notified_enabled:
            self._last_notified_enabled = curr_enabled
            try:
                self.signals.enable_changed.emit(curr_enabled)
            except Exception as e:
                logger.error(f"Error emitting enable_changed signal: {e}")

            for cb in list(self.enable_listeners):
                try:
                    cb(curr_enabled)
                except Exception as e:
                    logger.error(f"Error in enable listener: {e}")

    def enable_control(self) -> None:
        """Explicitly enables gesture-driven desktop interaction."""
        self._is_emergency = False
        self._is_paused = False
        self.is_enabled = True
        if self.current_mode in (ControlMode.EMERGENCY_STOP, ControlMode.PAUSED):
            self.current_mode = self.previous_mode if self.previous_mode not in (ControlMode.EMERGENCY_STOP, ControlMode.PAUSED) else ControlMode.MOUSE
        logger.warning(f"[SAFETY PROTOCOL] Gesture-generated desktop control has been ENABLED ({self.system_state.value}).")
        self._notify_all()

    def disable_control(self) -> None:
        """Safely disables gesture control without triggering emergency state."""
        self.release_active_drag()
        self.is_enabled = False
        self._is_paused = False
        logger.info("[SAFETY PROTOCOL] Gesture control safely DISABLED.")
        self._notify_all()

    def pause_control(self) -> None:
        """Puts system into PAUSED mode (e.g. open palm or pause button)."""
        if self._is_emergency or self.current_mode == ControlMode.EMERGENCY_STOP:
            logger.info("[SAFETY PROTOCOL] Cannot pause while emergency stop is active.")
            return

        if not self._is_paused:
            self.release_active_drag()
            self._is_paused = True
            if self.current_mode not in (ControlMode.PAUSED, ControlMode.EMERGENCY_STOP):
                self.previous_mode = self.current_mode
            self.current_mode = ControlMode.PAUSED
            logger.info("[SAFETY PROTOCOL] System entered PAUSED mode.")
            self._notify_all()

    def resume_control(self) -> bool:
        """Resumes from PAUSED mode back to active control. Strictly fails if in emergency stop."""
        if self._is_emergency or self.current_mode == ControlMode.EMERGENCY_STOP:
            logger.warning("[SAFETY PROTOCOL] Refusing resume: Emergency stop is active. Deliberate re-engagement required.")
            return False

        if self._is_paused or self.current_mode == ControlMode.PAUSED:
            self._is_paused = False
            self.current_mode = self.previous_mode if self.previous_mode not in (ControlMode.PAUSED, ControlMode.EMERGENCY_STOP) else ControlMode.MOUSE
            self.last_mode_change_time = time.time()
            logger.info(f"[SAFETY PROTOCOL] System resumed: {self.current_mode.value} (State: {self.system_state.value}).")
            self._notify_all()
            return True
        return False

    def emergency_stop(self, source: str = "GUI") -> None:
        """CRITICAL: Immediately cuts off virtual input and locks the system in EMERGENCY_STOP."""
        self.release_active_drag()
        self.is_enabled = False
        self._is_paused = False
        self._is_emergency = True
        self.current_mode = ControlMode.EMERGENCY_STOP
        self.last_mode_change_time = time.time()
        logger.critical(f"[EMERGENCY STOP ENGAGED via {source}] Virtual input halted immediately. Requires deliberate re-engagement.")
        self._notify_all()

    def reengage_from_emergency(self) -> None:
        """Deliberately clears the emergency stop and re-enables control safely."""
        logger.warning("[SAFETY PROTOCOL] Deliberate re-engagement requested from EMERGENCY_STOP.")
        self.enable_control()

    def release_active_drag(self) -> None:
        """Safety helper to release any virtual mouse button currently held down."""
        if self.cancel_drag_callback:
            try:
                self.cancel_drag_callback()
            except Exception as e:
                logger.error(f"Error cancelling active drag: {e}")

    def toggle_global_keyboard(self) -> bool:
        """Toggles Global Windows Air Keyboard Mode."""
        self.is_global_keyboard = not self.is_global_keyboard
        if self.is_global_keyboard:
            logger.info("[SAFETY] Global Keyboard mode engaged.")
        else:
            logger.info("[SAFETY] Global Keyboard mode disengaged.")
        self._notify_all()
        return self.is_global_keyboard

    def set_global_keyboard(self, enabled: bool) -> None:
        """Sets Global Windows Air Keyboard Mode state."""
        if self.is_global_keyboard != enabled:
            self.is_global_keyboard = enabled
            self._notify_all()

    def switch_mode(self, new_mode: ControlMode, force: bool = False) -> bool:
        """Switches active control mode with cooldown check."""
        now = time.time()
        if not force and (now - self.last_mode_change_time < self.mode_change_cooldown):
            return False

        if self._is_emergency or self.current_mode == ControlMode.EMERGENCY_STOP:
            logger.warning("[SAFETY PROTOCOL] Cannot switch mode while in EMERGENCY_STOP.")
            return False

        if new_mode == self.current_mode:
            return True

        self.release_active_drag()
        if self.current_mode not in (ControlMode.PAUSED, ControlMode.EMERGENCY_STOP):
            self.previous_mode = self.current_mode
        self.current_mode = new_mode
        self.last_mode_change_time = now
        logger.info(f"[MODE SWITCH] Active mode switched to: {new_mode.value}")
        self._notify_all()
        return True

    def on_hand_detected(self) -> None:
        """Called when a hand landmark is tracked in the frame."""
        now = time.time()
        was_present = self.is_hand_present
        self.is_hand_present = True
        self.last_hand_seen_time = now
        if not was_present or self.hand_first_seen_time is None:
            self.hand_first_seen_time = now
            self._notify_all()

    def on_hand_lost(self) -> None:
        """Called when hand is not visible in current frame. Applies a brief grace period."""
        now = time.time()
        # If within grace period, keep tracking active to smooth over single-frame drops
        if self.last_hand_seen_time and (now - self.last_hand_seen_time < self.hand_loss_grace_duration):
            return

        if self.is_hand_present:
            self.is_hand_present = False
            self.hand_first_seen_time = None
            self.release_active_drag()
            self._notify_all()

    def check_action_permission(self) -> Tuple[bool, str]:
        """Validates all safety gates and returns (permitted: bool, diagnostic_reason: str)."""
        if self._is_emergency or self.current_mode == ControlMode.EMERGENCY_STOP:
            return False, "EMERGENCY_STOP_ENGAGED"
        if not self.is_enabled:
            return False, "CONTROL_DISABLED"
        if self._is_paused or self.current_mode == ControlMode.PAUSED:
            return False, "CONTROL_PAUSED"
        if not self.is_hand_present:
            return False, "NO_HAND_DETECTED"
        if self.hand_first_seen_time and (time.time() - self.hand_first_seen_time < self.hand_stable_delay):
            return False, "INITIAL_STABILIZING"
        return True, "PERMITTED"

    def can_process_input(self) -> bool:
        """Backward-compatible helper returning True if desktop input is permitted."""
        permitted, _ = self.check_action_permission()
        return permitted
