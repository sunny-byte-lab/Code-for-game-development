"""N.E.X.U.S. PC Input Adapter.
Provides Windows OS-level mouse and keyboard execution for local and remote commands.
"""

import logging
from typing import Optional, Tuple
from app.virtual_mouse import VirtualMouse, WindowsMouseBackend
from app.windows_keyboard_service import WindowsKeyboardInputService
from nexus_pc.hardware_safety import HardwareConflictResolver, GuaranteedButtonReleaseGuard

logger = logging.getLogger("NEXUS.PC.InputAdapter")


class PCInputAdapter:
    """Unified Windows input adapter with hardware conflict protection."""

    def __init__(self,
                 mouse_controller: Optional[VirtualMouse] = None,
                 keyboard_service: Optional[WindowsKeyboardInputService] = None):
        self.mouse = mouse_controller or VirtualMouse()
        self.kb = keyboard_service or WindowsKeyboardInputService()
        self.conflict_resolver = HardwareConflictResolver()
        self.watchdog = GuaranteedButtonReleaseGuard(self.mouse_up)

    def move_relative(self, dx: float, dy: float) -> bool:
        """Moves Windows cursor relatively (e.g. from mobile remote touchpad)."""
        if self.conflict_resolver.is_physical_mouse_active():
            return False

        rx, ry = self.conflict_resolver.get_real_cursor_pos()
        target_x = rx + int(round(dx))
        target_y = ry + int(round(dy))

        ok = self.mouse.backend.set_cursor_pos(target_x, target_y)
        if ok:
            self.conflict_resolver.record_virtual_move(target_x, target_y)
        return ok

    def move_absolute(self, norm_x: float, norm_y: float) -> bool:
        """Moves Windows cursor to absolute screen position."""
        if self.conflict_resolver.is_physical_mouse_active():
            return False

        w, h = self.mouse.screen_w, self.mouse.screen_h
        target_x = max(0, min(w - 1, int(norm_x * w)))
        target_y = max(0, min(h - 1, int(norm_y * h)))

        ok = self.mouse.backend.set_cursor_pos(target_x, target_y)
        if ok:
            self.conflict_resolver.record_virtual_move(target_x, target_y)
        return ok

    def click(self, button: str = "left") -> bool:
        """Sends atomic click with guaranteed release."""
        try:
            self.watchdog.mark_down(button)
            return self.mouse.backend.click(button)
        finally:
            self.watchdog.mark_up(button)
            self.mouse.backend.mouse_up(button)

    def mouse_down(self, button: str = "left") -> bool:
        self.watchdog.mark_down(button)
        return self.mouse.backend.mouse_down(button)

    def mouse_up(self, button: str = "left") -> bool:
        self.watchdog.mark_up(button)
        return self.mouse.backend.mouse_up(button)

    def scroll(self, delta: int) -> bool:
        return self.mouse.backend.scroll(delta)

    def press_key(self, key_id: str, char: str = "") -> bool:
        """Dispatches keypress to active foreground application."""
        if char:
            return self.kb.send_char(char)
        elif key_id:
            return self.kb.send_key_action(key_id)
        return False

    def type_string(self, text: str) -> bool:
        """Types a full string into the active target window."""
        return self.kb.send_text(text)

    def release_all_buttons(self) -> None:
        """Guaranteed cleanup for all virtual mouse buttons."""
        self.mouse.release_all_buttons()
        self.watchdog.verify_watchdog()
