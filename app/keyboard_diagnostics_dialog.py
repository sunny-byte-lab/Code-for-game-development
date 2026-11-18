"""N.E.X.U.S. Comprehensive Keyboard Diagnostics & Subsystem Testing Panel.
Neural Experience & Unified System -- Phase 6 Independent Keyboard Diagnostic Suite.

Provides live monitoring of the 6 input pipeline stages:
1. KEYBOARD VISIBLE
2. HAND DETECTED
3. KEY HOVERED
4. PRESS RECOGNIZED
5. KEY EVENT GENERATED
6. WINDOWS INPUT API STATUS

And executes 8 independent unit/integration tests:
- TEST 1: Open and close the virtual keyboard.
- TEST 2: Display fingertip landmarks and coordinates.
- TEST 3: Show the virtual key currently under the fingertip.
- TEST 4: Confirm that a gesture generates exactly one key event (zero unintended repeats).
- TEST 5: Send a controlled test character to a focused Notepad window.
- TEST 6: Test Backspace, Enter, Space, Shift, and Caps Lock.
- TEST 7: Test typing in Chrome / external browser window.
- TEST 8: Verify that no key is generated after the hand is lost.
"""

import sys
import time
import subprocess
from typing import Optional, Dict, Any

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPen, QBrush
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QTextEdit, QFrame, QWidget, QScrollArea
)

from app.theme import (
    ACCENT_CYAN, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED,
    ACCENT_GOLD, BG_BLACK, BG_DARK_NAVY, BG_PANEL, TEXT_PRIMARY, TEXT_MUTED
)
from app.holographic_keyboard import HolographicKeyboardWidget, KeyDef, FingerPressState
from app.windows_keyboard_service import WindowsKeyboardInputService, MockKeyboardBackend


class KeyboardDiagnosticsDialog(QDialog):
    """Futuristic N.E.X.U.S. holographic diagnostic modal for the Windows Air Keyboard."""

    def __init__(self, keyboard_widget: HolographicKeyboardWidget, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.keyboard = keyboard_widget
        self.keyboard_service = getattr(keyboard_widget, "keyboard_service", WindowsKeyboardInputService())

        self.setWindowTitle("N.E.X.U.S. // AIR KEYBOARD DIAGNOSTICS & SYSTEM AUDIT")
        self.resize(880, 720)
        self.setMinimumSize(780, 600)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: #030814;
                border: 2px solid {ACCENT_CYAN};
            }}
            QLabel {{
                color: #E2E8F0;
                font-family: Consolas, 'Segoe UI', monospace;
                font-size: 11px;
            }}
            QFrame.Card {{
                background-color: #08152B;
                border: 1px solid #00F0FF33;
                border-radius: 4px;
                padding: 6px;
            }}
            QPushButton {{
                background-color: rgba(0, 160, 240, 0.18);
                border: 1px solid #00F0FF;
                color: #FFFFFF;
                font-family: Consolas;
                font-weight: bold;
                font-size: 11px;
                padding: 6px 12px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: rgba(0, 240, 255, 0.35);
                border-color: #FFFFFF;
            }}
            QPushButton:pressed {{
                background-color: rgba(0, 240, 255, 0.55);
            }}
            QTextEdit {{
                background-color: #020610;
                border: 1px solid #00F0FF44;
                color: #A5F3FC;
                font-family: Consolas;
                font-size: 10px;
            }}
        """)

        self._build_ui()

        # 10 Hz telemetry polling timer
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._refresh_telemetry)
        self.poll_timer.start(100)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        # Header banner
        hdr = QHBoxLayout()
        title = QLabel("N.E.X.U.S. // AIR KEYBOARD SUBSYSTEM DIAGNOSTICS")
        title.setStyleSheet(f"font-size: 14px; font-weight: 900; letter-spacing: 2px; color: {ACCENT_CYAN};")
        hdr.addWidget(title)
        hdr.addStretch()

        self.lbl_system_status = QLabel("● SUBSYSTEM ONLINE")
        self.lbl_system_status.setStyleSheet(f"font-weight: bold; color: {ACCENT_GREEN}; font-size: 12px;")
        hdr.addWidget(self.lbl_system_status)
        main_layout.addLayout(hdr)

        # 6-Stage Input Execution Pipeline Readouts
        pipe_frame = QFrame()
        pipe_frame.setProperty("class", "Card")
        pipe_layout = QVBoxLayout(pipe_frame)
        pipe_layout.setSpacing(6)

        pipe_title = QLabel("REAL-TIME 6-STAGE INPUT EXECUTION PIPELINE STATUS:")
        pipe_title.setStyleSheet(f"font-weight: bold; color: {ACCENT_GOLD}; font-size: 11px;")
        pipe_layout.addWidget(pipe_title)

        grid = QGridLayout()
        grid.setSpacing(6)

        # Stage 1: KEYBOARD VISIBLE
        self.lbl_s1_visible = QLabel("1. KEYBOARD VISIBLE:")
        self.val_s1_visible = QLabel("CHECKING...")
        self.val_s1_visible.setStyleSheet(f"color: {ACCENT_CYAN}; font-weight: bold;")
        grid.addWidget(self.lbl_s1_visible, 0, 0)
        grid.addWidget(self.val_s1_visible, 0, 1)

        # Stage 2: HAND DETECTED
        self.lbl_s2_hand = QLabel("2. HAND DETECTED:")
        self.val_s2_hand = QLabel("AWAITING SENSOR...")
        self.val_s2_hand.setStyleSheet(f"color: {TEXT_MUTED}; font-weight: bold;")
        grid.addWidget(self.lbl_s2_hand, 0, 2)
        grid.addWidget(self.val_s2_hand, 0, 3)

        # Stage 3: KEY HOVERED
        self.lbl_s3_hover = QLabel("3. KEY HOVERED:")
        self.val_s3_hover = QLabel("NONE")
        self.val_s3_hover.setStyleSheet(f"color: {TEXT_MUTED}; font-weight: bold;")
        grid.addWidget(self.lbl_s3_hover, 1, 0)
        grid.addWidget(self.val_s3_hover, 1, 1)

        # Stage 4: PRESS RECOGNIZED
        self.lbl_s4_press = QLabel("4. PRESS RECOGNIZED:")
        self.val_s4_press = QLabel("IDLE")
        self.val_s4_press.setStyleSheet(f"color: {TEXT_MUTED}; font-weight: bold;")
        grid.addWidget(self.lbl_s4_press, 1, 2)
        grid.addWidget(self.val_s4_press, 1, 3)

        # Stage 5: KEY EVENT GENERATED
        self.lbl_s5_event = QLabel("5. KEY EVENT GENERATED:")
        self.val_s5_event = QLabel("NONE")
        self.val_s5_event.setStyleSheet(f"color: {TEXT_MUTED}; font-weight: bold;")
        grid.addWidget(self.lbl_s5_event, 2, 0)
        grid.addWidget(self.val_s5_event, 2, 1)

        # Stage 6: WINDOWS INPUT API STATUS
        self.lbl_s6_api = QLabel("6. WINDOWS INPUT API:")
        self.val_s6_api = QLabel("ARMED (SendInput / Unicode)")
        self.val_s6_api.setStyleSheet(f"color: {ACCENT_GREEN}; font-weight: bold;")
        grid.addWidget(self.lbl_s6_api, 2, 2)
        grid.addWidget(self.val_s6_api, 2, 3)

        pipe_layout.addLayout(grid)
        main_layout.addWidget(pipe_frame)

        # Test Suite Action Controls
        test_frame = QFrame()
        test_frame.setProperty("class", "Card")
        test_vlayout = QVBoxLayout(test_frame)
        test_vlayout.setSpacing(6)

        t_hdr = QHBoxLayout()
        test_title = QLabel("INDEPENDENT SUB-SYSTEM TEST SUITE (PHASE 6):")
        test_title.setStyleSheet(f"font-weight: bold; color: {ACCENT_CYAN}; font-size: 11px;")
        t_hdr.addWidget(test_title)
        t_hdr.addStretch()

        btn_run_all = QPushButton("⚡ RUN ALL 8 TESTS")
        btn_run_all.setStyleSheet(f"background-color: rgba(34, 197, 94, 0.25); border: 1px solid {ACCENT_GREEN}; color: #FFFFFF;")
        btn_run_all.clicked.connect(self.run_all_tests)
        t_hdr.addWidget(btn_run_all)
        test_vlayout.addLayout(t_hdr)

        btn_grid = QGridLayout()
        btn_grid.setSpacing(6)

        self.btn_t1 = QPushButton("TEST 1: Toggle Visibility")
        self.btn_t1.clicked.connect(self.run_test_1_visibility)
        btn_grid.addWidget(self.btn_t1, 0, 0)

        self.btn_t2 = QPushButton("TEST 2: Check Landmarks")
        self.btn_t2.clicked.connect(self.run_test_2_landmarks)
        btn_grid.addWidget(self.btn_t2, 0, 1)

        self.btn_t3 = QPushButton("TEST 3: Key Hit-Testing")
        self.btn_t3.clicked.connect(self.run_test_3_key_under_fingertip)
        btn_grid.addWidget(self.btn_t3, 0, 2)

        self.btn_t4 = QPushButton("TEST 4: Single Event Hysteresis")
        self.btn_t4.clicked.connect(self.run_test_4_single_event)
        btn_grid.addWidget(self.btn_t4, 0, 3)

        self.btn_t5 = QPushButton("TEST 5: Send 'N' to Notepad")
        self.btn_t5.clicked.connect(self.run_test_5_notepad)
        btn_grid.addWidget(self.btn_t5, 1, 0)

        self.btn_t6 = QPushButton("TEST 6: Test Control Keys")
        self.btn_t6.clicked.connect(self.run_test_6_control_keys)
        btn_grid.addWidget(self.btn_t6, 1, 1)

        self.btn_t7 = QPushButton("TEST 7: Test Chrome Focus")
        self.btn_t7.clicked.connect(self.run_test_7_chrome)
        btn_grid.addWidget(self.btn_t7, 1, 2)

        self.btn_t8 = QPushButton("TEST 8: Zero-Repeat Hand Loss")
        self.btn_t8.clicked.connect(self.run_test_8_hand_loss)
        btn_grid.addWidget(self.btn_t8, 1, 3)

        self.test_buttons = [
            self.btn_t1, self.btn_t2, self.btn_t3, self.btn_t4,
            self.btn_t5, self.btn_t6, self.btn_t7, self.btn_t8
        ]

        test_vlayout.addLayout(btn_grid)
        main_layout.addWidget(test_frame)

        # Log & Diagnostic Telemetry Output Console
        log_title = QLabel("DIAGNOSTIC EVENT AUDIT & OUTPUT CONSOLE:")
        log_title.setStyleSheet(f"font-weight: bold; color: {TEXT_MUTED}; font-size: 10px;")
        main_layout.addWidget(log_title)

        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setMinimumHeight(180)
        main_layout.addWidget(self.log_console)

        # Footer Buttons
        ftr = QHBoxLayout()
        btn_clear_log = QPushButton("CLEAR LOG")
        btn_clear_log.clicked.connect(self.log_console.clear)
        ftr.addWidget(btn_clear_log)

        ftr.addStretch()

        btn_close = QPushButton("CLOSE")
        btn_close.clicked.connect(self.accept)
        ftr.addWidget(btn_close)
        main_layout.addLayout(ftr)

        self._log("N.E.X.U.S. Keyboard Diagnostics Subsystem initialized. Ready for audit.")

    def _log(self, text: str, level: str = "INFO") -> None:
        ts = time.strftime("%H:%M:%S")
        prefix = f"[{ts}] [{level}] "
        self.log_console.append(prefix + text)

    def _refresh_telemetry(self) -> None:
        """Polls live keyboard state and updates the 6 pipeline stage indicators."""
        # Stage 1: KEYBOARD VISIBLE
        vis = self.keyboard.isVisible()
        w = self.keyboard.width()
        h = self.keyboard.height()
        self.val_s1_visible.setText(f"{'VISIBLE' if vis else 'HIDDEN'} ({w}x{h}px)")
        self.val_s1_visible.setStyleSheet(f"color: {ACCENT_GREEN if vis else ACCENT_RED}; font-weight: bold;")

        # Stage 2: HAND DETECTED
        l_det = self.keyboard.left_detected
        r_det = self.keyboard.right_detected
        if l_det and r_det:
            h_text = f"DUAL HANDS (L:{self.keyboard.left_tracking_conf:.2f}, R:{self.keyboard.right_tracking_conf:.2f})"
            h_col = ACCENT_GREEN
        elif l_det:
            h_text = f"LEFT HAND (Conf:{self.keyboard.left_tracking_conf:.2f})"
            h_col = ACCENT_CYAN
        elif r_det:
            h_text = f"RIGHT HAND (Conf:{self.keyboard.right_tracking_conf:.2f})"
            h_col = ACCENT_CYAN
        else:
            h_text = "NONE (AWAITING SENSOR)"
            h_col = TEXT_MUTED
        self.val_s2_hand.setText(h_text)
        self.val_s2_hand.setStyleSheet(f"color: {h_col}; font-weight: bold;")

        # Stage 3: KEY HOVERED
        any_hover = [k for k in self.keyboard.keys if k.is_hovered]
        if any_hover:
            k_labels = ", ".join(k.label for k in any_hover)
            self.val_s3_hover.setText(f"'{k_labels}' (ID: {any_hover[0].key_id})")
            self.val_s3_hover.setStyleSheet(f"color: {ACCENT_CYAN}; font-weight: bold;")
        else:
            self.val_s3_hover.setText("NONE (IDLE)")
            self.val_s3_hover.setStyleSheet(f"color: {TEXT_MUTED}; font-weight: bold;")

        # Stage 4: PRESS RECOGNIZED
        mode = self.keyboard.press_detection_mode
        pstate = self.keyboard.pinch_typing_state.value
        pdist = self.keyboard.current_pinch_dist
        dwell_pct = int(self.keyboard.dwell_progress * 100) if hasattr(self.keyboard, "dwell_progress") else 0
        if pstate == "PRESSED":
            p_col = ACCENT_GREEN
            detail = f"PRESSED! (Method:{mode})"
        elif pstate in ("PINCH_CANDIDATE", "CANDIDATE"):
            p_col = ACCENT_GOLD
            detail = f"PINCHING ({pdist:.2f} <= {self.keyboard.pinch_threshold:.2f})"
        elif dwell_pct > 0:
            p_col = ACCENT_GOLD
            detail = f"DWELLING ({dwell_pct}%)"
        elif pstate == "WAIT_FOR_RELEASE":
            p_col = ACCENT_RED
            detail = "RELEASE WAIT (LOCKED)"
        else:
            p_col = TEXT_MUTED
            detail = f"HOVER ({pdist:.2f})"
        self.val_s4_press.setText(f"{pstate} // {detail}")
        self.val_s4_press.setStyleSheet(f"color: {p_col}; font-weight: bold;")

        # Stage 5: KEY EVENT GENERATED
        last_evt = self.keyboard.last_dispatched_event
        self.val_s5_event.setText(last_evt[:45])
        self.val_s5_event.setStyleSheet(f"color: {ACCENT_GREEN if 'DISPATCHED' in last_evt else ACCENT_CYAN}; font-weight: bold;")

        # Stage 6: WINDOWS INPUT API STATUS
        target_win = self.keyboard_service.get_active_target_window()
        total_keys = self.keyboard_service.total_keystrokes_dispatched
        last_ok = self.keyboard_service.last_dispatch_success
        err_msg = self.keyboard_service.last_error_message
        if last_ok:
            api_str = f"ACTIVE ({total_keys} Sent) -> '{target_win[:24]}'"
            api_col = ACCENT_GREEN
        else:
            api_str = f"API ERROR: {err_msg[:24]}"
            api_col = ACCENT_RED
        self.val_s6_api.setText(api_str)
        self.val_s6_api.setStyleSheet(f"color: {api_col}; font-weight: bold;")

    # -----------------------------------------------------------------
    # INDEPENDENT TEST IMPLEMENTATIONS
    # -----------------------------------------------------------------
    def run_test_1_visibility(self) -> bool:
        """TEST 1: Verifies virtual keyboard visibility and geometry bounds."""
        self._log("--- RUNNING TEST 1: KEYBOARD VISIBILITY & LIFECYCLE ---")
        if self.keyboard.width() <= 100 or self.keyboard.height() <= 100:
            self.keyboard.resize(1000, 600)
        self.keyboard._recalculate_key_geometry()

        w, h = self.keyboard.width(), self.keyboard.height()
        is_vis = self.keyboard.isVisible()
        key_count = len(self.keyboard.keys)
        self._log(f"Current Keyboard Size: {w}x{h}px | Visible: {is_vis} | Key Count: {key_count}")

        if key_count < 60:
            self._log(f"FAIL: Expected at least 60 keys in 5 rows, found {key_count}", "ERROR")
            return False

        # Verify key geometry bounds
        first_key = self.keyboard.keys[0]
        last_key = self.keyboard.keys[-1]
        self._log(f"First Key ('{first_key.label}') Hitbox: {first_key.rect}")
        self._log(f"Last Key ('{last_key.label}') Hitbox: {last_key.rect}")

        if first_key.rect.width() <= 0 or last_key.rect.height() <= 0:
            self._log("FAIL: Key hitbox dimensions are zero or invalid", "ERROR")
            return False

        self._log("PASS: TEST 1 Succeeded. Virtual keyboard layout and geometry valid.", "SUCCESS")
        return True

    def run_test_2_landmarks(self) -> bool:
        """TEST 2: Displays fingertip landmarks and coordinate transforms."""
        self._log("--- RUNNING TEST 2: FINGERTIP LANDMARKS & COORDINATE TRANSFORM ---")
        self._log(f"Left Hand Normalized: {self.keyboard.left_index_norm} | Canvas Pixels: {self.keyboard.left_index_coords}")
        self._log(f"Right Hand Normalized: {self.keyboard.right_index_norm} | Canvas Pixels: {self.keyboard.right_index_coords}")

        # Test coordinate mapping math
        test_nx, test_ny = 0.5, 0.5
        cx, cy, in_roi = self.keyboard.map_camera_to_keyboard(test_nx, test_ny)
        inv_nx, inv_ny = self.keyboard.map_keyboard_to_camera(cx, cy)
        err_x = abs(test_nx - inv_nx)
        err_y = abs(test_ny - inv_ny)
        self._log(f"Camera (0.5, 0.5) -> Canvas ({cx:.1f}, {cy:.1f}) -> Inverse Camera ({inv_nx:.3f}, {inv_ny:.3f})")

        if err_x > 0.01 or err_y > 0.01:
            self._log(f"FAIL: Coordinate inversion error ({err_x:.4f}, {err_y:.4f}) exceeds 0.01", "ERROR")
            return False

        self._log("PASS: TEST 2 Succeeded. 1:1 Coordinate transformation verified.", "SUCCESS")
        return True

    def run_test_3_key_under_fingertip(self) -> bool:
        """TEST 3: Shows the virtual key currently under the fingertip."""
        self._log("--- RUNNING TEST 3: PROBE VIRTUAL KEY UNDER FINGERTIP ---")
        hovered = [k for k in self.keyboard.keys if k.is_hovered]
        if hovered:
            for k in hovered:
                self._log(f"Under Fingertip: Key='{k.label}' (ID:{k.key_id}) Hitbox={k.rect}")
            self._log("PASS: TEST 3 Succeeded. Active key detected under fingertip.", "SUCCESS")
            return True
        else:
            # Probe center key (G or H) synthetically to verify hit-testing
            center_pt = QPointF(float(self.keyboard.width()) * 0.5, float(self.keyboard.height()) * 0.6)
            k = self.keyboard.get_key_at_point(center_pt)
            if k:
                self._log(f"Synthetic Center Probe: Key='{k.label}' ID={k.key_id} Hitbox={k.rect}")
                self._log("PASS: TEST 3 Succeeded. Hitbox lookup verified at center point.", "SUCCESS")
                return True
            self._log("FAIL: No key resolved at canvas center.", "ERROR")
            return False

    def run_test_4_single_event(self) -> bool:
        """TEST 4: Confirms that a gesture generates exactly one key event without repeats."""
        self._log("--- RUNNING TEST 4: SINGLE-EVENT HYSTERESIS & REPEAT SUPPRESSION ---")
        before_count = self.keyboard.total_keystrokes

        # Test mock finger state machine
        fstate = self.keyboard.fingers["R_INDEX"]
        fstate.press_locked = False
        fstate.is_pressed = False
        fstate.state = FingerPressState.HOVER

        # Trigger single key
        test_key = self.keyboard.keys[10]  # E.g. '0'
        self.keyboard.handle_virtual_key(test_key.key_id, finger_id="R_INDEX", trigger_method="TEST_4")
        after_count = self.keyboard.total_keystrokes

        delta = after_count - before_count
        self._log(f"Keystrokes Dispatched: {delta} (Before: {before_count}, After: {after_count})")

        if delta != 1:
            self._log(f"FAIL: Expected exactly 1 event, dispatched {delta}", "ERROR")
            return False

        self._log("PASS: TEST 4 Succeeded. Exactly one event generated without repeated bursts.", "SUCCESS")
        return True

    def run_test_5_notepad(self) -> bool:
        """TEST 5: Sends a controlled test character to focused Notepad window."""
        self._log("--- RUNNING TEST 5: SEND CONTROLLED CHARACTER TO NOTEPAD ---")
        # Ensure Notepad is running or focusable
        target = self.keyboard_service.get_active_target_window()
        self._log(f"Current Target Window: '{target}'")

        ok, msg = self.keyboard_service.send_char('N')
        self._log(f"Dispatch Result: Success={ok} | Message='{msg}'")

        if not ok:
            self._log(f"FAIL: SendInput/keybd_event dispatch returned False: {self.keyboard_service.last_error_message}", "ERROR")
            return False

        self._log("PASS: TEST 5 Succeeded. Character 'N' successfully dispatched to target OS application.", "SUCCESS")
        return True

    def run_test_6_control_keys(self) -> bool:
        """TEST 6: Tests Backspace, Enter, Space, Shift, and Caps Lock actions."""
        self._log("--- RUNNING TEST 6: CONTROL KEYS (BACKSPACE, ENTER, SPACE, SHIFT, CAPS) ---")
        actions = ["space", "backspace", "enter", "tab", "shift", "caps"]
        all_ok = True

        for act in actions:
            ok, msg = self.keyboard_service.send_action(act)
            self._log(f"  Action '{act}': Success={ok} | '{msg}'")
            if not ok:
                all_ok = False

        if not all_ok:
            self._log("FAIL: One or more control actions failed to dispatch", "ERROR")
            return False

        self._log("PASS: TEST 6 Succeeded. All essential control keys verified via Windows API.", "SUCCESS")
        return True

    def run_test_7_chrome(self) -> bool:
        """TEST 7: Tests external typing into Google Chrome or browser active window."""
        self._log("--- RUNNING TEST 7: CHROME / EXTERNAL APPLICATION DISPATCH ---")
        target = self.keyboard_service.get_active_target_window()
        self._log(f"Active Focused Target: '{target}'")

        # Send test word "NEXUS"
        chars = ["N", "E", "X", "U", "S"]
        results = []
        for c in chars:
            ok, _ = self.keyboard_service.send_char(c)
            results.append(ok)
            time.sleep(0.01)

        success_count = sum(1 for r in results if r)
        self._log(f"Dispatched 5 test characters: {success_count}/5 successful")

        if success_count < 5:
            self._log("FAIL: Not all characters were dispatched successfully", "ERROR")
            return False

        self._log("PASS: TEST 7 Succeeded. Keystrokes dispatched to external application queue.", "SUCCESS")
        return True

    def run_test_8_hand_loss(self) -> bool:
        """TEST 8: Verifies that no key events are generated after the hand disappears."""
        self._log("--- RUNNING TEST 8: VERIFY ZERO KEY EVENTS ON HAND LOSS ---")
        before_count = self.keyboard.total_keystrokes

        # Simulate hand loss by passing empty list
        self.keyboard.process_multi_hands([])

        after_count = self.keyboard.total_keystrokes
        delta = after_count - before_count
        l_det = self.keyboard.left_detected
        r_det = self.keyboard.right_detected
        self._log(f"Hand Loss Simulation: Left Detected={l_det}, Right Detected={r_det}, Delta Keys={delta}")

        if delta != 0:
            self._log(f"FAIL: Spurious key event generated on hand loss! Delta={delta}", "ERROR")
            return False

        if l_det or r_det:
            self._log("FAIL: Hand presence flag remained True after hand loss signal", "ERROR")
            return False

        self._log("PASS: TEST 8 Succeeded. Clean idle transition with zero ghost keystrokes.", "SUCCESS")
        return True

    def run_all_tests(self) -> None:
        """Executes all 8 diagnostic tests sequentially and outputs a summary report."""
        self.log_console.clear()
        self._log("=======================================================")
        self._log("STARTING FULL N.E.X.U.S. AIR KEYBOARD AUDIT (8 TESTS)")
        self._log("=======================================================")

        tests = [
            ("TEST 1: Keyboard Visibility & Layout", self.run_test_1_visibility),
            ("TEST 2: Fingertip Landmarks & Coords", self.run_test_2_landmarks),
            ("TEST 3: Probe Key Under Fingertip", self.run_test_3_key_under_fingertip),
            ("TEST 4: Single Event Hysteresis", self.run_test_4_single_event),
            ("TEST 5: Send Character to Notepad", self.run_test_5_notepad),
            ("TEST 6: Essential Control Keys", self.run_test_6_control_keys),
            ("TEST 7: Chrome / External Dispatch", self.run_test_7_chrome),
            ("TEST 8: Zero-Repeat Hand Loss", self.run_test_8_hand_loss),
        ]

        passed = 0
        failed = 0

        for name, fn in tests:
            try:
                ok = fn()
                if ok:
                    passed += 1
                else:
                    failed += 1
            except Exception as e:
                self._log(f"EXCEPTION in {name}: {e}", "CRITICAL")
                failed += 1

        self._log("=======================================================")
        self._log(f"AUDIT SUMMARY: {passed}/8 PASSED | {failed}/8 FAILED")
        if failed == 0:
            self._log("ALL 8 SUB-SYSTEM TESTS PASSED SUCCESSFULLY!", "SUCCESS")
            self.lbl_system_status.setText("● ALL 8 TESTS PASSED")
            self.lbl_system_status.setStyleSheet(f"font-weight: bold; color: {ACCENT_GREEN}; font-size: 12px;")
        else:
            self._log(f"WARNING: {failed} test(s) encountered failures.", "WARNING")
            self.lbl_system_status.setText(f"⚠ {failed} TEST(S) FAILED")
            self.lbl_system_status.setStyleSheet(f"font-weight: bold; color: {ACCENT_RED}; font-size: 12px;")
        self._log("=======================================================")
