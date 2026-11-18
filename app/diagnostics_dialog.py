"""N.E.X.U.S. Automated Diagnostics & Telemetry Screen.
Displays real-time status of all 5 control pipeline stages, camera hardware,
screen resolution, coordinate mappings, and last action execution results.
"""

from typing import Optional
from app import qt_bootstrap
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QTextEdit, QWidget
)
from app.theme import (
    NEXUS_STYLESHEET, ACCENT_CYAN, ACCENT_BLUE, ACCENT_GREEN,
    ACCENT_RED, ACCENT_GOLD, BG_BLACK, BG_DARK_NAVY, BG_PANEL, TEXT_MUTED
)
from app.camera_worker import CameraWorker, ControlPipelineStatus
from app.safety_controller import SafetyController
from app.virtual_mouse import VirtualMouse
from app.camera_device_utils import (
    open_windows_camera_settings,
    check_camera_permission,
    probe_camera_devices
)


class NexusDiagnosticsDialog(QDialog):
    """Futuristic N.E.X.U.S. diagnostics modal window."""

    def __init__(self,
                 camera_worker: CameraWorker,
                 safety: SafetyController,
                 mouse: VirtualMouse,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.camera_worker = camera_worker
        self.safety = safety
        self.mouse = mouse

        self.setWindowTitle("N.E.X.U.S. // SYSTEM DIAGNOSTICS & TELEMETRY")
        self.resize(780, 660)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: #050b18;
                border: 2px solid {ACCENT_CYAN};
            }}
            QLabel {{
                color: #e0f0ff;
                font-family: Consolas, 'Segoe UI', monospace;
            }}
            QFrame.DiagCard {{
                background-color: #09152b;
                border: 1px solid #143560;
                border-radius: 4px;
                padding: 8px;
            }}
        """)

        self.latest_status: Optional[ControlPipelineStatus] = None
        self._build_ui()

        # Connect live pipeline signal
        self.camera_worker.pipeline_updated.connect(self._on_pipeline_update)

        # Refresh timer (10 Hz update for labels)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_display)
        self.timer.start(100)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(10)

        # Banner
        top_row = QHBoxLayout()
        title = QLabel("N.E.X.U.S. SUBSYSTEM HEALTH & DIAGNOSTICS")
        title.setStyleSheet(f"font-size: 15px; font-weight: 900; letter-spacing: 2px; color: {ACCENT_CYAN};")
        top_row.addWidget(title)
        top_row.addStretch()

        self.lbl_overall = QLabel("● SYSTEM NOMINAL")
        self.lbl_overall.setStyleSheet(f"font-weight: bold; color: {ACCENT_GREEN}; font-size: 12px;")
        top_row.addWidget(self.lbl_overall)
        main_layout.addLayout(top_row)

        # 5-Stage Control Pipeline Grid
        pipe_box = QFrame()
        pipe_box.setProperty("class", "DiagCard")
        pipe_layout = QVBoxLayout(pipe_box)

        lbl_pipe_head = QLabel("FIVE-STAGE INPUT EXECUTION PIPELINE:")
        lbl_pipe_head.setStyleSheet(f"font-weight: bold; color: {ACCENT_GOLD}; font-size: 11px;")
        pipe_layout.addWidget(lbl_pipe_head)

        grid = QGridLayout()
        grid.setSpacing(6)

        # Stage 1: Optical Tracking
        grid.addWidget(QLabel("1. OPTICAL TRACKING:"), 0, 0)
        self.val_stage1 = QLabel("CHECKING...")
        self.val_stage1.setStyleSheet("font-weight: bold;")
        grid.addWidget(self.val_stage1, 0, 1)

        # Stage 2: Gesture Classification
        grid.addWidget(QLabel("2. GESTURE RECOGNIZED:"), 1, 0)
        self.val_stage2 = QLabel("NONE")
        self.val_stage2.setStyleSheet(f"font-weight: bold; color: {ACCENT_CYAN};")
        grid.addWidget(self.val_stage2, 1, 1)

        # Stage 3: Control State Manager
        grid.addWidget(QLabel("3. CONTROL LIFECYCLE:"), 2, 0)
        self.val_stage3 = QLabel("DISABLED")
        self.val_stage3.setStyleSheet("font-weight: bold;")
        grid.addWidget(self.val_stage3, 2, 1)

        # Stage 4: Safety Permission Gate
        grid.addWidget(QLabel("4. SAFETY GATE:"), 3, 0)
        self.val_stage4 = QLabel("STANDBY")
        self.val_stage4.setStyleSheet("font-weight: bold;")
        grid.addWidget(self.val_stage4, 3, 1)

        # Stage 5: Desktop Action Executed
        grid.addWidget(QLabel("5. LAST DESKTOP ACTION:"), 4, 0)
        self.val_stage5 = QLabel("NONE")
        self.val_stage5.setStyleSheet("font-weight: bold;")
        grid.addWidget(self.val_stage5, 4, 1)

        # Stage 6: System Input Dispatch API (SendInput)
        grid.addWidget(QLabel("6. SYSTEM INPUT DISPATCH:"), 5, 0)
        self.val_stage6 = QLabel("SendInput (Win32)")
        self.val_stage6.setStyleSheet(f"font-weight: bold; color: {ACCENT_GREEN};")
        grid.addWidget(self.val_stage6, 5, 1)

        # Stage 7: Mouse Scroll Status
        grid.addWidget(QLabel("7. SCROLL STATUS:"), 6, 0)
        self.val_stage7 = QLabel("IDLE")
        self.val_stage7.setStyleSheet(f"font-weight: bold; color: {TEXT_MUTED};")
        grid.addWidget(self.val_stage7, 6, 1)

        # Stage 8: Click & Movement State
        grid.addWidget(QLabel("8. CLICK & MOVE STATUS:"), 7, 0)
        self.val_stage8 = QLabel("CLICK: IDLE | MOVE: ACTIVE")
        self.val_stage8.setStyleSheet(f"font-weight: bold; color: {ACCENT_CYAN};")
        grid.addWidget(self.val_stage8, 7, 1)

        # Stage 9: Screen & Hand Coords
        grid.addWidget(QLabel("9. DESKTOP / HAND COORDS:"), 8, 0)
        self.val_coords = QLabel("X: 0, Y: 0")
        self.val_coords.setStyleSheet("font-weight: bold;")
        grid.addWidget(self.val_coords, 8, 1)

        pipe_layout.addLayout(grid)
        main_layout.addWidget(pipe_box)

        # Two-Finger & Multi-Finger Optical Classification
        tf_box = QFrame()
        tf_box.setProperty("class", "DiagCard")
        tf_layout = QVBoxLayout(tf_box)

        lbl_tf_head = QLabel("TWO-FINGER ROTATION-INVARIANT CLASSIFICATION:")
        lbl_tf_head.setStyleSheet(f"font-weight: bold; color: {ACCENT_CYAN}; font-size: 11px;")
        tf_layout.addWidget(lbl_tf_head)

        tf_grid = QGridLayout()
        tf_grid.setSpacing(6)

        tf_grid.addWidget(QLabel("DETECTED HAND & CONFIDENCE:"), 0, 0)
        self.val_tf_hand = QLabel("NONE (0%)")
        self.val_tf_hand.setStyleSheet("font-weight: bold;")
        tf_grid.addWidget(self.val_tf_hand, 0, 1)

        tf_grid.addWidget(QLabel("TWO-FINGER STATUS:"), 0, 2)
        self.val_tf_status = QLabel("OFF")
        self.val_tf_status.setStyleSheet("font-weight: bold;")
        tf_grid.addWidget(self.val_tf_status, 0, 3)

        tf_grid.addWidget(QLabel("INDEX FINGER:"), 1, 0)
        self.val_tf_index = QLabel("FOLDED")
        self.val_tf_index.setStyleSheet("font-weight: bold;")
        tf_grid.addWidget(self.val_tf_index, 1, 1)

        tf_grid.addWidget(QLabel("MIDDLE FINGER:"), 1, 2)
        self.val_tf_middle = QLabel("FOLDED")
        self.val_tf_middle.setStyleSheet("font-weight: bold;")
        tf_grid.addWidget(self.val_tf_middle, 1, 3)

        tf_grid.addWidget(QLabel("RING FINGER:"), 2, 0)
        self.val_tf_ring = QLabel("FOLDED")
        self.val_tf_ring.setStyleSheet("font-weight: bold;")
        tf_grid.addWidget(self.val_tf_ring, 2, 1)

        tf_grid.addWidget(QLabel("LITTLE FINGER:"), 2, 2)
        self.val_tf_pinky = QLabel("FOLDED")
        self.val_tf_pinky.setStyleSheet("font-weight: bold;")
        tf_grid.addWidget(self.val_tf_pinky, 2, 3)

        tf_layout.addLayout(tf_grid)
        main_layout.addWidget(tf_box)

        # Hardware & Operating System Integration
        hw_box = QFrame()
        hw_box.setProperty("class", "DiagCard")
        hw_layout = QGridLayout(hw_box)

        hw_layout.addWidget(QLabel("OPTICAL SENSOR:"), 0, 0)
        self.val_cam = QLabel(f"Device Index {self.camera_worker.camera_index} (DirectShow/MSMF)")
        hw_layout.addWidget(self.val_cam, 0, 1)

        hw_layout.addWidget(QLabel("SENSOR FPS:"), 0, 2)
        self.val_fps = QLabel("0.0 FPS")
        hw_layout.addWidget(self.val_fps, 0, 3)

        hw_layout.addWidget(QLabel("SCREEN DIMENSIONS:"), 1, 0)
        self.val_screen = QLabel(f"{self.mouse.screen_w} x {self.mouse.screen_h} px")
        hw_layout.addWidget(self.val_screen, 1, 1)

        hw_layout.addWidget(QLabel("CURSOR MODE:"), 1, 2)
        self.val_mode = QLabel(f"{self.mouse.cursor_mode.upper()} (1€ Filter)")
        hw_layout.addWidget(self.val_mode, 1, 3)

        hw_layout.addWidget(QLabel("CAMERA PERMISSION:"), 2, 0)
        self.val_perm = QLabel("CHECKING...")
        hw_layout.addWidget(self.val_perm, 2, 1)

        hw_layout.addWidget(QLabel("DETECTED HARDWARE:"), 2, 2)
        self.val_hw_name = QLabel("Integrated Camera")
        hw_layout.addWidget(self.val_hw_name, 2, 3)

        main_layout.addWidget(hw_box)

        # Live Error / Event Stream
        err_box = QFrame()
        err_box.setProperty("class", "DiagCard")
        err_layout = QVBoxLayout(err_box)
        err_layout.addWidget(QLabel("DIAGNOSTIC EVENT & ERROR STREAM:"))
        self.txt_events = QTextEdit()
        self.txt_events.setReadOnly(True)
        self.txt_events.setFixedHeight(120)
        self.txt_events.setStyleSheet("background: #020610; color: #a0c0e0; font-family: Consolas; font-size: 10px; border: 1px solid #102444;")
        err_layout.addWidget(self.txt_events)
        main_layout.addWidget(err_box)

        # Action Buttons
        btn_row = QHBoxLayout()

        btn_test_click = QPushButton("🎯 DISPATCH TEST CLICK")
        btn_test_click.setStyleSheet(f"background-color: #0c264a; border: 1px solid {ACCENT_CYAN}; color: #ffffff; padding: 6px 12px; font-weight: bold;")
        btn_test_click.clicked.connect(self._test_click)
        btn_row.addWidget(btn_test_click)

        btn_test_center = QPushButton("🎯 CENTER CURSOR")
        btn_test_center.setStyleSheet(f"background-color: #0c264a; border: 1px solid {ACCENT_BLUE}; color: #ffffff; padding: 6px 12px; font-weight: bold;")
        btn_test_center.clicked.connect(self._test_center)
        btn_row.addWidget(btn_test_center)

        btn_rescan = QPushButton("🔄 RE-QUERY SCREEN")
        btn_rescan.setStyleSheet(f"background-color: #0c264a; border: 1px solid {ACCENT_BLUE}; color: #ffffff; padding: 6px 12px; font-weight: bold;")
        btn_rescan.clicked.connect(self._rescan_screen)
        btn_row.addWidget(btn_rescan)

        btn_privacy = QPushButton("🔓 CAMERA PRIVACY SETTINGS")
        btn_privacy.setStyleSheet(f"background-color: #3b200a; border: 1px solid {ACCENT_GOLD}; color: #ffffff; padding: 6px 12px; font-weight: bold;")
        btn_privacy.clicked.connect(open_windows_camera_settings)
        btn_row.addWidget(btn_privacy)

        btn_row.addStretch()

        btn_close = QPushButton("DISMISS")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)

        main_layout.addLayout(btn_row)

    def _on_pipeline_update(self, status: ControlPipelineStatus) -> None:
        self.latest_status = status

    def _refresh_display(self) -> None:
        st = self.latest_status
        if st is not None:
            # Stage 1: Hand
            if st.hand_detected:
                self.val_stage1.setText(f"TRACKED ({st.hand_landmarks_count} landmarks)")
                self.val_stage1.setStyleSheet(f"font-weight: bold; color: {ACCENT_GREEN};")
            else:
                self.val_stage1.setText("NO HAND IN SENSOR VIEW")
                self.val_stage1.setStyleSheet("font-weight: bold; color: #ff3366;")

            # Stage 2: Gesture
            self.val_stage2.setText(st.gesture_name)

            # Stage 3: Lifecycle
            self.val_stage3.setText(f"{st.system_state} [{st.control_mode}]")
            if st.system_state == "ACTIVE":
                self.val_stage3.setStyleSheet(f"font-weight: bold; color: {ACCENT_GREEN};")
            elif st.system_state == "READY":
                self.val_stage3.setStyleSheet(f"font-weight: bold; color: {ACCENT_CYAN};")
            elif st.system_state == "EMERGENCY_STOP":
                self.val_stage3.setStyleSheet(f"font-weight: bold; color: {ACCENT_RED};")
            else:
                self.val_stage3.setStyleSheet(f"font-weight: bold; color: {ACCENT_GOLD};")

            # Stage 4: Safety Gate
            if st.action_permitted:
                self.val_stage4.setText("PERMITTED (DESKTOP INPUT ENGAGED)")
                self.val_stage4.setStyleSheet(f"font-weight: bold; color: {ACCENT_GREEN};")
            else:
                self.val_stage4.setText(f"BLOCKED ({st.permission_reason})")
                self.val_stage4.setStyleSheet(f"font-weight: bold; color: {ACCENT_GOLD};")

            # Stage 5: Execution
            if st.last_action_success:
                self.val_stage5.setText(st.last_action)
                self.val_stage5.setStyleSheet(f"font-weight: bold; color: {ACCENT_CYAN};")
            else:
                self.val_stage5.setText(f"FAILED: {st.last_action_error or st.last_action}")
                self.val_stage5.setStyleSheet(f"font-weight: bold; color: {ACCENT_RED};")

            # Stage 6: Input API
            api_name = getattr(st, "input_api", "SendInput (Win32)")
            self.val_stage6.setText(api_name)
            self.val_stage6.setStyleSheet(f"font-weight: bold; color: {ACCENT_GREEN};")

            # Stage 7: Scroll Status
            sc_st = getattr(st, "scroll_status", "IDLE")
            self.val_stage7.setText(sc_st)
            sc_col = ACCENT_GREEN if sc_st in ("UP", "DOWN") else TEXT_MUTED
            self.val_stage7.setStyleSheet(f"font-weight: bold; color: {sc_col};")

            # Stage 8: Click & Movement Status
            c_st = getattr(st, "click_state", "IDLE")
            mv_st = getattr(st, "mouse_movement_status", "ACTIVE")
            self.val_stage8.setText(f"CLICK: {c_st} | MOVE: {mv_st}")
            c_col = ACCENT_GREEN if ("CONFIRMED" in c_st or "CLICK" in c_st) else (ACCENT_GOLD if ("LOCKED" in c_st or "CANDIDATE" in c_st) else ACCENT_CYAN)
            self.val_stage8.setStyleSheet(f"font-weight: bold; color: {c_col};")

            # Stage 9: Screen & Hand Coords
            if st.cursor_coords:
                self.val_coords.setText(f"X: {st.cursor_coords[0]}, Y: {st.cursor_coords[1]}")
            else:
                self.val_coords.setText("X: 0, Y: 0 (NO TRACKING)")

            # Two-Finger & Multi-Finger Telemetry
            h_lbl = getattr(st, "hand_label", "NONE")
            t_conf = int(getattr(st, "tracking_confidence", 0.0) * 100)
            self.val_tf_hand.setText(f"{h_lbl.upper()} ({t_conf}%)")
            self.val_tf_hand.setStyleSheet(f"font-weight: bold; color: {ACCENT_GREEN if t_conf > 70 else ACCENT_GOLD};")

            tf_st = getattr(st, "two_finger_status", "OFF")
            self.val_tf_status.setText(tf_st)
            self.val_tf_status.setStyleSheet(f"font-weight: bold; color: {ACCENT_GREEN if tf_st == 'STABLE' else (ACCENT_GOLD if tf_st == 'EVALUATING' else '#888888')};")

            idx_s = getattr(st, "index_finger_state", "FOLDED")
            self.val_tf_index.setText(idx_s)
            self.val_tf_index.setStyleSheet(f"font-weight: bold; color: {ACCENT_GREEN if idx_s == 'EXTENDED' else '#888888'};")

            mid_s = getattr(st, "middle_finger_state", "FOLDED")
            self.val_tf_middle.setText(mid_s)
            self.val_tf_middle.setStyleSheet(f"font-weight: bold; color: {ACCENT_GREEN if mid_s == 'EXTENDED' else '#888888'};")

            ring_s = getattr(st, "ring_finger_state", "FOLDED")
            self.val_tf_ring.setText(ring_s)
            self.val_tf_ring.setStyleSheet(f"font-weight: bold; color: {ACCENT_GREEN if ring_s == 'EXTENDED' else '#888888'};")

            pinky_s = getattr(st, "pinky_finger_state", "FOLDED")
            self.val_tf_pinky.setText(pinky_s)
            self.val_tf_pinky.setStyleSheet(f"font-weight: bold; color: {ACCENT_GREEN if pinky_s == 'EXTENDED' else '#888888'};")

            # FPS
            self.val_fps.setText(f"{st.fps:.1f} FPS")
            self.val_cam.setText(f"Device Index {st.camera_index}")

        # Update screen size & camera permission
        self.val_screen.setText(f"{self.mouse.screen_w} x {self.mouse.screen_h} px")
        fine_status = " [FINE CTRL]" if self.mouse.fine_control_mode else ""
        stab_status = " [STABILIZED]" if self.mouse.is_stabilized else ""
        self.val_mode.setText(f"{self.mouse.cursor_mode.upper()} ({self.mouse.smoothing_type}) | Sens: {self.mouse.effective_sensitivity:.2f}x{fine_status} | {self.mouse.click_state_name}{stab_status}")
        cam_idx = self.camera_worker.camera_index
        has_perm, reason = check_camera_permission(cam_idx)
        if has_perm:
            self.val_perm.setText("ALLOWED (OS ACCESS GRANTED)")
            self.val_perm.setStyleSheet(f"font-weight: bold; color: {ACCENT_GREEN};")
        else:
            self.val_perm.setText("BLOCKED (0x80070005: PRIVACY RESTRICTED)")
            self.val_perm.setStyleSheet(f"font-weight: bold; color: {ACCENT_RED};")

    def _test_click(self) -> None:
        ok, msg = self.mouse.left_click()
        self.txt_events.append(f"[MANUAL TEST] Click -> {msg} (Success={ok})")

    def _test_center(self) -> None:
        cx, cy = self.mouse.screen_w // 2, self.mouse.screen_h // 2
        ok = self.mouse._dispatch_raw_move(cx, cy)
        self.txt_events.append(f"[MANUAL TEST] Center Cursor -> ({cx}, {cy}) (Success={ok})")

    def _rescan_screen(self) -> None:
        self.mouse.update_screen_size()
        self.val_screen.setText(f"{self.mouse.screen_w} x {self.mouse.screen_h} px")
        self.txt_events.append(f"[SYSTEM] Rescanned screen resolution: {self.mouse.screen_w} x {self.mouse.screen_h}")


# Backwards compatibility alias
JarvisDiagnosticsDialog = NexusDiagnosticsDialog
