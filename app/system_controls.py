"""JARVIS Windows System Controls Engine.
Manages Windows master volume via pycaw (with multimedia key fallback) and desktop window navigation.
"""

import logging
import pyautogui

logger = logging.getLogger("NEXUS.SystemControls")


class SystemControls:
    """Provides safe Windows desktop and audio system controls."""

    def __init__(self):
        self._volume_interface = None
        self._init_pycaw()

    def _init_pycaw(self) -> None:
        """Initializes pycaw COM endpoint volume interface."""
        try:
            from pycaw.pycaw import AudioUtilities
            devices = AudioUtilities.GetSpeakers()
            if hasattr(devices, "EndpointVolume") and devices.EndpointVolume is not None:
                self._volume_interface = devices.EndpointVolume
                logger.info("Pycaw direct EndpointVolume successfully initialized.")
                return

            # Legacy pycaw approach
            from pycaw.pycaw import IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            from ctypes import cast, POINTER
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            self._volume_interface = cast(interface, POINTER(IAudioEndpointVolume))
            logger.info("Pycaw legacy Audio Volume endpoint successfully initialized.")
        except Exception as e:
            logger.warning(f"Pycaw direct audio endpoint initialization failed: {e}. Using multimedia key fallback.")
            self._volume_interface = None

    def get_volume(self) -> int:
        """Returns current master volume percentage (0..100)."""
        if self._volume_interface:
            try:
                scalar = self._volume_interface.GetMasterVolumeLevelScalar()
                return int(round(scalar * 100))
            except Exception:
                pass
        return 50

    def set_volume(self, percent: int) -> None:
        """Sets master volume percentage (0..100)."""
        clamped = max(0, min(100, percent))
        if self._volume_interface:
            try:
                scalar = clamped / 100.0
                self._volume_interface.SetMasterVolumeLevelScalar(scalar, None)
                logger.info(f"[AUDIO] Volume set to {clamped}%")
                return
            except Exception as e:
                logger.error(f"Error setting volume via pycaw: {e}")

        # Fallback using simulated volume keys
        curr = self.get_volume()
        diff = clamped - curr
        key = "volumeup" if diff > 0 else "volumedown"
        steps = abs(diff) // 2
        for _ in range(steps):
            pyautogui.press(key, _pause=False)

    def volume_up(self, step: int = 5) -> int:
        """Increases volume by step percent."""
        if self._volume_interface:
            try:
                curr = self.get_volume()
                new_vol = min(100, curr + step)
                self.set_volume(new_vol)
                return new_vol
            except Exception:
                pass
        try:
            pyautogui.press("volumeup", _pause=False)
            logger.info("[AUDIO] Volume UP triggered.")
        except Exception:
            pass
        return self.get_volume()

    def volume_down(self, step: int = 5) -> int:
        """Decreases volume by step percent."""
        if self._volume_interface:
            try:
                curr = self.get_volume()
                new_vol = max(0, curr - step)
                self.set_volume(new_vol)
                return new_vol
            except Exception:
                pass
        try:
            pyautogui.press("volumedown", _pause=False)
            logger.info("[AUDIO] Volume DOWN triggered.")
        except Exception:
            pass
        return self.get_volume()

    def toggle_mute(self) -> bool:
        """Toggles audio mute state."""
        if self._volume_interface:
            try:
                is_muted = self._volume_interface.GetMute()
                self._volume_interface.SetMute(not is_muted, None)
                logger.info(f"[AUDIO] Mute state toggled: {not is_muted}")
                return bool(not is_muted)
            except Exception as e:
                logger.error(f"Error toggling mute via pycaw: {e}")

        try:
            pyautogui.press("volumemute", _pause=False)
            logger.info("[AUDIO] Volume MUTE key pressed.")
        except Exception:
            pass
        return False

    def switch_window(self) -> None:
        """Switches active Windows application (Alt+Tab)."""
        try:
            pyautogui.hotkey("alt", "tab", _pause=False)
            logger.info("[DESKTOP] Window switch (Alt+Tab) executed.")
        except Exception as e:
            logger.error(f"Error executing Alt+Tab: {e}")

    def minimize_active_window(self) -> None:
        """Minimizes the currently active window."""
        try:
            pyautogui.hotkey("win", "down", _pause=False)
            logger.info("[DESKTOP] Active window minimized (Win+Down).")
        except Exception as e:
            logger.error(f"Error minimizing window: {e}")

    def show_desktop(self) -> None:
        """Toggles Show Desktop (Win+D)."""
        try:
            pyautogui.hotkey("win", "d", _pause=False)
            logger.info("[DESKTOP] Show Desktop (Win+D) triggered.")
        except Exception as e:
            logger.error(f"Error showing desktop: {e}")

    def play_pause(self) -> bool:
        """Toggles media play/pause state."""
        try:
            pyautogui.press("playpause", _pause=False)
            logger.info("[MEDIA] Play/Pause triggered.")
            return True
        except Exception as e:
            logger.error(f"Error triggering media play/pause: {e}")
            return False

    def next_track(self) -> bool:
        """Skips to the next media track."""
        try:
            pyautogui.press("nexttrack", _pause=False)
            logger.info("[MEDIA] Next Track triggered.")
            return True
        except Exception as e:
            logger.error(f"Error skipping to next track: {e}")
            return False

    def previous_track(self) -> bool:
        """Skips to the previous media track."""
        try:
            pyautogui.press("prevtrack", _pause=False)
            logger.info("[MEDIA] Previous Track triggered.")
            return True
        except Exception as e:
            logger.error(f"Error skipping to previous track: {e}")
            return False

    def open_settings(self) -> bool:
        """Opens Windows Settings (Win+I)."""
        try:
            pyautogui.hotkey("win", "i", _pause=False)
            logger.info("[DESKTOP] Windows Settings opened (Win+I).")
            return True
        except Exception as e:
            logger.error(f"Error opening Windows Settings: {e}")
            return False

    def open_file_explorer(self) -> bool:
        """Opens Windows File Explorer (Win+E)."""
        try:
            pyautogui.hotkey("win", "e", _pause=False)
            logger.info("[DESKTOP] File Explorer opened (Win+E).")
            return True
        except Exception as e:
            logger.error(f"Error opening File Explorer: {e}")
            return False

    def next_slide(self) -> bool:
        """Advances to the next presentation slide (PageDown)."""
        try:
            pyautogui.press("pagedown", _pause=False)
            logger.info("[PRESENTATION] Next Slide (PageDown) executed.")
            return True
        except Exception as e:
            logger.error(f"Error advancing slide: {e}")
            return False

    def previous_slide(self) -> bool:
        """Navigates to previous presentation slide (PageUp)."""
        try:
            pyautogui.press("pageup", _pause=False)
            logger.info("[PRESENTATION] Previous Slide (PageUp) executed.")
            return True
        except Exception as e:
            logger.error(f"Error going to previous slide: {e}")
            return False

    def start_slideshow(self) -> bool:
        """Starts presentation slideshow from beginning (F5)."""
        try:
            pyautogui.press("f5", _pause=False)
            logger.info("[PRESENTATION] Start Slideshow (F5) executed.")
            return True
        except Exception as e:
            logger.error(f"Error starting slideshow: {e}")
            return False

    def exit_slideshow(self) -> bool:
        """Exits presentation slideshow (Escape)."""
        try:
            pyautogui.press("esc", _pause=False)
            logger.info("[PRESENTATION] Exit Slideshow (Escape) executed.")
            return True
        except Exception as e:
            logger.error(f"Error exiting slideshow: {e}")
            return False
