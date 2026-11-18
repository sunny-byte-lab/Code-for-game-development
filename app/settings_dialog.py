"""JARVIS Settings Dialog.
Allows interactive configuration of camera, 1€ filter smoothing, sensitivities,
cursor modes (absolute/relative), gesture thresholds, active ROI bounds, and applications.
"""

from typing import Optional, List, Dict, Any
from app import qt_bootstrap
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QCheckBox,
    QPushButton, QComboBox, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget, QWidget, QMessageBox, QGroupBox, QDoubleSpinBox
)
from app.settings_manager import SettingsManager
from app.camera_worker import CameraWorker
from app.calibration_wizard import NexusCalibrationWizard, JarvisCalibrationWizard
from app.theme import ACCENT_CYAN, ACCENT_BLUE, ACCENT_GREEN, ACCENT_GOLD, TEXT_PRIMARY


class SettingsDialog(QDialog):
    """Futuristic modal configuration dialog."""

    settings_applied = Signal()

    def __init__(self, settings_mgr: SettingsManager, camera_worker: Optional[CameraWorker] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings_mgr = settings_mgr
        self.camera_worker = camera_worker
        self.setWindowTitle("N.E.X.U.S. // SYSTEM CONFIGURATION")
        self.resize(720, 540)
        self.setStyleSheet("""
            QDialog {
                background-color: #060e1e;
                border: 2px solid #00f0ff;
            }
        """)

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        # Top Banner with Calibration Wizard shortcut
        top_bar = QHBoxLayout()
        lbl_head = QLabel("N.E.X.U.S. SYSTEM PARAMETERS")
        lbl_head.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {ACCENT_CYAN}; letter-spacing: 1px;")
        top_bar.addWidget(lbl_head)
        top_bar.addStretch()

        btn_launch_wiz = QPushButton("🎯 LAUNCH CALIBRATION WIZARD")
        btn_launch_wiz.setStyleSheet(f"""
            QPushButton {{
                background-color: #0e2b4d;
                border: 1px solid {ACCENT_CYAN};
                color: #ffffff;
                font-weight: bold;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background-color: #1a4270;
            }}
        """)
        btn_launch_wiz.clicked.connect(self._launch_calibration_wizard)
        top_bar.addWidget(btn_launch_wiz)
        main_layout.addLayout(top_bar)

        tabs = QTabWidget()

        # =============================================================
        # TAB 1: OPTICS & TRACKING
        # =============================================================
        tab_camera = QWidget()
        cam_layout = QVBoxLayout(tab_camera)
        cam_layout.setSpacing(12)

        # Camera selection
        cam_row = QHBoxLayout()
        cam_row.addWidget(QLabel("OPTICAL SENSOR DEVICE:"))
        self.combo_cam = QComboBox()
        available = CameraWorker.get_available_cameras()
        curr_cam = self.settings_mgr.get("camera", "index", default=0)
        for idx in available:
            tag = " (Primary / Integrated)" if idx == 0 else " (Secondary / Virtual)"
            self.combo_cam.addItem(f"Camera Device {idx}{tag}", idx)
            if idx == curr_cam:
                self.combo_cam.setCurrentIndex(self.combo_cam.count() - 1)
        cam_row.addWidget(self.combo_cam)
        cam_layout.addLayout(cam_row)

        # Tracking Landmark
        lm_row = QHBoxLayout()
        lm_row.addWidget(QLabel("ERGONOMIC TRACKING POINT:"))
        self.combo_landmark = QComboBox()
        self.combo_landmark.addItem("Index Fingertip (Default)", "index_tip")
        self.combo_landmark.addItem("Index Knuckle / MCP (Ultra-Stable)", "index_mcp")
        self.combo_landmark.addItem("Index Joint / PIP (Curled Hand)", "index_pip")
        self.combo_landmark.addItem("Palm Center (Relaxed Open Hand)", "hand_center")
        self.combo_landmark.addItem("Thumb-Index Midpoint", "thumb_index_mid")
        curr_lm = self.settings_mgr.get("mouse", "tracking_landmark", default="index_tip")
        for i in range(self.combo_landmark.count()):
            if self.combo_landmark.itemData(i) == curr_lm:
                self.combo_landmark.setCurrentIndex(i)
        lm_row.addWidget(self.combo_landmark)
        cam_layout.addLayout(lm_row)

        # Toggles
        self.chk_mirror = QCheckBox("MIRROR OPTICAL FEED (Natural Hand Mirroring)")
        self.chk_mirror.setChecked(self.settings_mgr.get("camera", "mirror", default=True))
        cam_layout.addWidget(self.chk_mirror)

        self.chk_hud = QCheckBox("RENDER HOLOGRAPHIC LANDMARK OVERLAYS & SKELETON")
        self.chk_hud.setChecked(self.settings_mgr.get("interface", "show_hud_overlays", default=True))
        cam_layout.addWidget(self.chk_hud)

        self.chk_anim = QCheckBox("ENABLE LIGHTWEIGHT HUD ROTATION ANIMATIONS")
        self.chk_anim.setChecked(self.settings_mgr.get("interface", "enable_animations", default=True))
        cam_layout.addWidget(self.chk_anim)

        cam_layout.addStretch()
        tabs.addTab(tab_camera, "OPTICS & SENSORS")

        # =============================================================
        # TAB 2: CURSOR SMOOTHING & PRECISION
        # =============================================================
        tab_precision = QWidget()
        prec_layout = QVBoxLayout(tab_precision)
        prec_layout.setSpacing(10)

        # Smoothing Engine
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("SMOOTHING ALGORITHM:"))
        self.combo_filter = QComboBox()
        self.combo_filter.addItem("1€ Filter (One Euro - Zero Lag Jitter Free)", "one_euro")
        self.combo_filter.addItem("Adaptive EMA (Velocity Scaled)", "adaptive_ema")
        self.combo_filter.addItem("Standard EMA (Exponential Moving Average)", "ema")
        curr_filt = self.settings_mgr.get("mouse", "smoothing_type", default="one_euro")
        for i in range(self.combo_filter.count()):
            if self.combo_filter.itemData(i) == curr_filt:
                self.combo_filter.setCurrentIndex(i)
        filter_row.addWidget(self.combo_filter)
        prec_layout.addLayout(filter_row)

        # 1€ Min Cutoff (Jitter reduction strength at rest)
        cutoff_val = self.settings_mgr.get("mouse", "one_euro_min_cutoff", default=1.0)
        self.lbl_cutoff = QLabel(f"LOW-SPEED JITTER FILTER (Min Cutoff): {cutoff_val:.2f} Hz")
        self.slider_cutoff = QSlider(Qt.Horizontal)
        self.slider_cutoff.setRange(10, 300)
        self.slider_cutoff.setValue(int(cutoff_val * 100))
        self.slider_cutoff.valueChanged.connect(
            lambda v: self.lbl_cutoff.setText(f"LOW-SPEED JITTER FILTER (Min Cutoff): {v / 100.0:.2f} Hz")
        )
        prec_layout.addWidget(self.lbl_cutoff)
        prec_layout.addWidget(self.slider_cutoff)

        # 1€ Beta (High speed responsiveness)
        beta_val = self.settings_mgr.get("mouse", "one_euro_beta", default=0.05)
        self.lbl_beta = QLabel(f"HIGH-SPEED SPEED FACTOR (Beta): {beta_val:.3f}")
        self.slider_beta = QSlider(Qt.Horizontal)
        self.slider_beta.setRange(1, 200)
        self.slider_beta.setValue(int(beta_val * 1000))
        self.slider_beta.valueChanged.connect(
            lambda v: self.lbl_beta.setText(f"HIGH-SPEED SPEED FACTOR (Beta): {v / 1000.0:.3f}")
        )
        prec_layout.addWidget(self.lbl_beta)
        prec_layout.addWidget(self.slider_beta)

        # Deadzone
        dead_val = self.settings_mgr.get("mouse", "deadzone_radius", default=4.0)
        self.lbl_deadzone = QLabel(f"MICRO-TREMOR DEADZONE: {dead_val:.1f} px")
        self.slider_deadzone = QSlider(Qt.Horizontal)
        self.slider_deadzone.setRange(0, 150)
        self.slider_deadzone.setValue(int(dead_val * 10))
        self.slider_deadzone.valueChanged.connect(
            lambda v: self.lbl_deadzone.setText(f"MICRO-TREMOR DEADZONE: {v / 10.0:.1f} px")
        )
        prec_layout.addWidget(self.lbl_deadzone)
        prec_layout.addWidget(self.slider_deadzone)

        # Cursor Mode & Invert
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("CONTROL MODE:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("Absolute Screen Mapping", "absolute")
        self.combo_mode.addItem("Relative Control (Trackpad/Joystick Mode)", "relative")
        curr_mode = self.settings_mgr.get("mouse", "cursor_mode", default="absolute")
        for i in range(self.combo_mode.count()):
            if self.combo_mode.itemData(i) == curr_mode:
                self.combo_mode.setCurrentIndex(i)
        mode_row.addWidget(self.combo_mode)

        self.chk_invert_x = QCheckBox("INVERT HORIZONTAL AXIS")
        self.chk_invert_x.setChecked(self.settings_mgr.get("mouse", "invert_x", default=False))
        mode_row.addWidget(self.chk_invert_x)
        prec_layout.addLayout(mode_row)

        prec_layout.addStretch()
        tabs.addTab(tab_precision, "SMOOTHING & PRECISION")

        # =============================================================
        # TAB 3: SENSITIVITY & ROI
        # =============================================================
        tab_sens = QWidget()
        sens_layout = QVBoxLayout(tab_sens)
        sens_layout.setSpacing(10)

        # Sensitivity Presets
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("SENSITIVITY PRESETS:"))
        self.btn_preset_low = QPushButton("LOW (0.8x)")
        self.btn_preset_med = QPushButton("MEDIUM (1.2x)")
        self.btn_preset_high = QPushButton("HIGH (1.8x)")
        preset_style = "QPushButton { background: rgba(0, 40, 80, 0.6); border: 1px solid #00d2ff; color: #e0f0ff; padding: 5px; font-weight: bold; border-radius: 3px; } QPushButton:hover { background: #00d2ff; color: #020810; }"
        self.btn_preset_low.setStyleSheet(preset_style)
        self.btn_preset_med.setStyleSheet(preset_style)
        self.btn_preset_high.setStyleSheet(preset_style)

        def _apply_preset(val: float):
            self.slider_sens_x.setValue(int(val * 10))
            self.slider_sens_y.setValue(int(val * 10))
            if self.camera_worker and hasattr(self.camera_worker, "mouse") and self.camera_worker.mouse:
                self.camera_worker.mouse.sensitivity = val
                self.camera_worker.mouse.sensitivity_x = val
                self.camera_worker.mouse.sensitivity_y = val

        self.btn_preset_low.clicked.connect(lambda: _apply_preset(0.8))
        self.btn_preset_med.clicked.connect(lambda: _apply_preset(1.2))
        self.btn_preset_high.clicked.connect(lambda: _apply_preset(1.8))
        preset_row.addWidget(self.btn_preset_low)
        preset_row.addWidget(self.btn_preset_med)
        preset_row.addWidget(self.btn_preset_high)
        sens_layout.addLayout(preset_row)

        # Fine Control Mode
        self.chk_fine_control = QCheckBox("FINE CONTROL MODE (40% Speed Dampening for Surgical Precision)")
        self.chk_fine_control.setChecked(self.settings_mgr.get("mouse", "fine_control_mode", default=True))
        sens_layout.addWidget(self.chk_fine_control)

        # Recalibrate Hand Position Button
        self.btn_recalibrate = QPushButton("RECALIBRATE HAND POSITION (CENTER RESTING POSE)")
        self.btn_recalibrate.setStyleSheet("QPushButton { background: rgba(0, 80, 120, 0.7); border: 1px solid #00f0ff; color: #00f0ff; font-weight: bold; padding: 8px; border-radius: 4px; } QPushButton:hover { background: #00f0ff; color: #020810; }")
        def _on_recalibrate_clicked():
            if self.camera_worker and hasattr(self.camera_worker, "mouse") and self.camera_worker.mouse:
                self.camera_worker.mouse.recalibrate_position()
                self.lbl_recal_status.setText("RECALIBRATED: Cursor centered, hand resting box updated!")
        self.btn_recalibrate.clicked.connect(_on_recalibrate_clicked)
        self.lbl_recal_status = QLabel("")
        self.lbl_recal_status.setStyleSheet("color: #00ffaa; font-size: 10px; font-weight: bold;")
        sens_layout.addWidget(self.btn_recalibrate)
        sens_layout.addWidget(self.lbl_recal_status)

        # Horizontal Sensitivity
        sx_val = self.settings_mgr.get("mouse", "sensitivity_x", default=1.2)
        self.lbl_sens_x = QLabel(f"HORIZONTAL SENSITIVITY: {sx_val:.1f}x")
        self.slider_sens_x = QSlider(Qt.Horizontal)
        self.slider_sens_x.setRange(10, 50)
        self.slider_sens_x.setValue(int(sx_val * 10))
        self.slider_sens_x.valueChanged.connect(
            lambda v: self.lbl_sens_x.setText(f"HORIZONTAL SENSITIVITY: {v / 10.0:.1f}x")
        )
        sens_layout.addWidget(self.lbl_sens_x)
        sens_layout.addWidget(self.slider_sens_x)

        # Vertical Sensitivity
        sy_val = self.settings_mgr.get("mouse", "sensitivity_y", default=2.2)
        self.lbl_sens_y = QLabel(f"VERTICAL SENSITIVITY: {sy_val:.1f}x")
        self.slider_sens_y = QSlider(Qt.Horizontal)
        self.slider_sens_y.setRange(10, 50)
        self.slider_sens_y.setValue(int(sy_val * 10))
        self.slider_sens_y.valueChanged.connect(
            lambda v: self.lbl_sens_y.setText(f"VERTICAL SENSITIVITY: {v / 10.0:.1f}x")
        )
        sens_layout.addWidget(self.lbl_sens_y)
        sens_layout.addWidget(self.slider_sens_y)

        # Active Region Bounds (ROI)
        roi_box = QGroupBox("ACTIVE CAMERA REGION (ROI BOUNDS)")
        roi_box.setStyleSheet("QGroupBox { color: #00f0ff; font-weight: bold; border: 1px solid #1a3560; margin-top: 10px; padding: 10px; }")
        roi_layout = QVBoxLayout(roi_box)

        # Horizontal margin
        hm_val = self.settings_mgr.get("mouse", "roi_left", default=0.16)
        self.lbl_roi_h = QLabel(f"HORIZONTAL MARGIN (Left/Right Border): {hm_val:.2f}")
        self.slider_roi_h = QSlider(Qt.Horizontal)
        self.slider_roi_h.setRange(2, 40)
        self.slider_roi_h.setValue(int(hm_val * 100))
        self.slider_roi_h.valueChanged.connect(
            lambda v: self.lbl_roi_h.setText(f"HORIZONTAL MARGIN (Left/Right Border): {v / 100.0:.2f}")
        )
        roi_layout.addWidget(self.lbl_roi_h)
        roi_layout.addWidget(self.slider_roi_h)

        # Vertical margin
        vm_val = self.settings_mgr.get("mouse", "roi_top", default=0.16)
        self.lbl_roi_v = QLabel(f"VERTICAL MARGIN (Top/Bottom Border): {vm_val:.2f}")
        self.slider_roi_v = QSlider(Qt.Horizontal)
        self.slider_roi_v.setRange(2, 40)
        self.slider_roi_v.setValue(int(vm_val * 100))
        self.slider_roi_v.valueChanged.connect(
            lambda v: self.lbl_roi_v.setText(f"VERTICAL MARGIN (Top/Bottom Border): {v / 100.0:.2f}")
        )
        roi_layout.addWidget(self.lbl_roi_v)
        roi_layout.addWidget(self.slider_roi_v)

        sens_layout.addWidget(roi_box)
        sens_layout.addStretch()
        tabs.addTab(tab_sens, "SENSITIVITY & ROI")

        # =============================================================
        # TAB 4: GESTURES & CLICKS
        # =============================================================
        tab_mouse = QWidget()
        mouse_layout = QVBoxLayout(tab_mouse)
        mouse_layout.setSpacing(10)

        # Pinch Threshold
        pinch_val = self.settings_mgr.get("mouse", "pinch_threshold", default=0.32)
        self.lbl_pinch = QLabel(f"PINCH ACTIVATION THRESHOLD: {pinch_val:.3f}")
        self.slider_pinch = QSlider(Qt.Horizontal)
        self.slider_pinch.setRange(15, 60)
        self.slider_pinch.setValue(int(pinch_val * 100))
        self.slider_pinch.valueChanged.connect(
            lambda v: self.lbl_pinch.setText(f"PINCH ACTIVATION THRESHOLD: {v / 100.0:.3f}")
        )
        mouse_layout.addWidget(self.lbl_pinch)
        mouse_layout.addWidget(self.slider_pinch)

        # Click Cooldown
        cd_val = self.settings_mgr.get("mouse", "click_cooldown", default=0.35)
        self.lbl_cd = QLabel(f"CLICK COOLDOWN: {cd_val:.2f}s")
        self.slider_cd = QSlider(Qt.Horizontal)
        self.slider_cd.setRange(15, 100)
        self.slider_cd.setValue(int(cd_val * 100))
        self.slider_cd.valueChanged.connect(
            lambda v: self.lbl_cd.setText(f"CLICK COOLDOWN: {v / 100.0:.2f}s")
        )
        mouse_layout.addWidget(self.lbl_cd)
        mouse_layout.addWidget(self.slider_cd)

        # Right Click Gesture Choice
        rc_row = QHBoxLayout()
        rc_row.addWidget(QLabel("RIGHT-CLICK GESTURE:"))
        self.combo_right_gesture = QComboBox()
        self.combo_right_gesture.addItem("Thumb to Middle Fingertip Pinch", "thumb_middle_pinch")
        self.combo_right_gesture.addItem("Index & Middle Pinch Together", "index_middle_pinch")
        curr_rc = self.settings_mgr.get("mouse", "right_click_gesture", default="thumb_middle_pinch")
        for i in range(self.combo_right_gesture.count()):
            if self.combo_right_gesture.itemData(i) == curr_rc:
                self.combo_right_gesture.setCurrentIndex(i)
        rc_row.addWidget(self.combo_right_gesture)
        mouse_layout.addLayout(rc_row)

        # Stabilization & Individual Gestures
        self.chk_stabilize = QCheckBox("ANTI-SLIP CLICK STABILIZATION (Freezes cursor jitter during pinch)")
        self.chk_stabilize.setChecked(self.settings_mgr.get("mouse", "click_stabilization", default=True))
        mouse_layout.addWidget(self.chk_stabilize)

        self.chk_drag = QCheckBox("ENABLE PINCH DRAG & DROP (Hold pinch to drag)")
        self.chk_drag.setChecked(self.settings_mgr.get("gestures_enabled", "drag_and_drop", default=True))
        mouse_layout.addWidget(self.chk_drag)

        self.chk_scroll = QCheckBox("ENABLE TWO-FINGER VERTICAL SCROLL")
        self.chk_scroll.setChecked(self.settings_mgr.get("gestures_enabled", "scroll", default=True))
        mouse_layout.addWidget(self.chk_scroll)

        self.chk_right = QCheckBox("ENABLE RIGHT-CLICK GESTURE")
        self.chk_right.setChecked(self.settings_mgr.get("gestures_enabled", "right_click", default=True))
        mouse_layout.addWidget(self.chk_right)

        mouse_layout.addStretch()
        tabs.addTab(tab_mouse, "GESTURES & CLICKS")

        # =============================================================
        # TAB 5: AIR KEYBOARD (HANDS-FREE DWELL & PINCH TYPING)
        # =============================================================
        tab_keyboard = QWidget()
        kb_layout = QVBoxLayout(tab_keyboard)
        kb_layout.setSpacing(10)

        # Typing Trigger Mode
        kb_mode_row = QHBoxLayout()
        kb_mode_row.addWidget(QLabel("AIR TYPING TRIGGER MODE:"))
        self.combo_typing_mode = QComboBox()
        self.combo_typing_mode.addItem("Dwell-to-Type (Hands-Free Pointing - Default)", "DWELL")
        self.combo_typing_mode.addItem("Pinch-to-Type (Thumb-Index Pinch)", "PINCH")
        self.combo_typing_mode.addItem("Hybrid (Dwell, Pinch, or Forward Tap)", "HYBRID")
        curr_typing_mode = self.settings_mgr.get("air_typing", "typing_mode", default="DWELL")
        for i in range(self.combo_typing_mode.count()):
            if self.combo_typing_mode.itemData(i) == curr_typing_mode:
                self.combo_typing_mode.setCurrentIndex(i)
        kb_mode_row.addWidget(self.combo_typing_mode)
        kb_layout.addLayout(kb_mode_row)

        # Dwell Duration Slider (0.30s - 1.00s)
        dwell_val = float(self.settings_mgr.get("air_typing", "dwell_duration", default=0.50))
        self.lbl_dwell = QLabel(f"DWELL ACTIVATION DURATION: {dwell_val:.2f} s")
        self.slider_dwell = QSlider(Qt.Horizontal)
        self.slider_dwell.setRange(30, 100)
        self.slider_dwell.setValue(int(round(dwell_val * 100)))
        self.slider_dwell.valueChanged.connect(
            lambda v: self.lbl_dwell.setText(f"DWELL ACTIVATION DURATION: {v / 100.0:.2f} s")
        )
        kb_layout.addWidget(self.lbl_dwell)
        kb_layout.addWidget(self.slider_dwell)

        # Tremor / Jitter Tolerance Slider (5.0 - 60.0 px)
        jitter_val = float(self.settings_mgr.get("air_typing", "dwell_jitter_tolerance", default=25.0))
        self.lbl_jitter = QLabel(f"NATURAL TREMOR TOLERANCE: {jitter_val:.1f} px")
        self.slider_jitter = QSlider(Qt.Horizontal)
        self.slider_jitter.setRange(5, 60)
        self.slider_jitter.setValue(int(round(jitter_val)))
        self.slider_jitter.valueChanged.connect(
            lambda v: self.lbl_jitter.setText(f"NATURAL TREMOR TOLERANCE: {v:.1f} px")
        )
        kb_layout.addWidget(self.lbl_jitter)
        kb_layout.addWidget(self.slider_jitter)

        # Keypress Cooldown Slider (0.05s - 0.50s)
        kb_cd_val = float(self.settings_mgr.get("air_typing", "keypress_cooldown", default=0.20))
        self.lbl_kb_cd = QLabel(f"KEYPRESS DEBOUNCE COOLDOWN: {kb_cd_val:.2f} s")
        self.slider_kb_cd = QSlider(Qt.Horizontal)
        self.slider_kb_cd.setRange(5, 50)
        self.slider_kb_cd.setValue(int(round(kb_cd_val * 100)))
        self.slider_kb_cd.valueChanged.connect(
            lambda v: self.lbl_kb_cd.setText(f"KEYPRESS DEBOUNCE COOLDOWN: {v / 100.0:.2f} s")
        )
        kb_layout.addWidget(self.lbl_kb_cd)
        kb_layout.addWidget(self.slider_kb_cd)

        # Two-Hand Confirmation Duration (0.20s - 1.00s)
        auto_act_val = float(self.settings_mgr.get("air_typing", "auto_activate_duration", default=0.40))
        self.lbl_auto_act = QLabel(f"TWO-HAND CONFIRMATION DURATION: {auto_act_val:.2f} s")
        self.slider_auto_act = QSlider(Qt.Horizontal)
        self.slider_auto_act.setRange(20, 100)
        self.slider_auto_act.setValue(int(round(auto_act_val * 100)))
        self.slider_auto_act.valueChanged.connect(
            lambda v: self.lbl_auto_act.setText(f"TWO-HAND CONFIRMATION DURATION: {v / 100.0:.2f} s")
        )
        kb_layout.addWidget(self.lbl_auto_act)
        kb_layout.addWidget(self.slider_auto_act)

        # Hand Loss Timeout (0.30s - 3.00s)
        auto_exit_val = float(self.settings_mgr.get("air_typing", "auto_exit_duration", default=0.80))
        self.lbl_auto_exit = QLabel(f"HAND LOSS TIMEOUT (GRACE PERIOD): {auto_exit_val:.2f} s")
        self.slider_auto_exit = QSlider(Qt.Horizontal)
        self.slider_auto_exit.setRange(30, 300)
        self.slider_auto_exit.setValue(int(round(auto_exit_val * 100)))
        self.slider_auto_exit.valueChanged.connect(
            lambda v: self.lbl_auto_exit.setText(f"HAND LOSS TIMEOUT (GRACE PERIOD): {v / 100.0:.2f} s")
        )
        kb_layout.addWidget(self.lbl_auto_exit)
        kb_layout.addWidget(self.slider_auto_exit)

        kb_layout.addStretch()
        tabs.addTab(tab_keyboard, "AIR KEYBOARD")

        # =============================================================
        # TAB 6: APPLICATIONS LAUNCHER
        # =============================================================
        tab_apps = QWidget()
        apps_layout = QVBoxLayout(tab_apps)

        self.table_apps = QTableWidget()
        self.table_apps.setColumnCount(3)
        self.table_apps.setHorizontalHeaderLabels(["NAME", "PATH / EXECUTABLE", "ENABLED"])
        self.table_apps.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        apps_list = self.settings_mgr.get("applications", default=[])
        self.table_apps.setRowCount(len(apps_list))
        for row, app in enumerate(apps_list):
            self.table_apps.setItem(row, 0, QTableWidgetItem(app.get("name", "")))
            self.table_apps.setItem(row, 1, QTableWidgetItem(app.get("path", "")))
            chk_item = QTableWidgetItem()
            chk_item.setCheckState(Qt.Checked if app.get("enabled", True) else Qt.Unchecked)
            self.table_apps.setItem(row, 2, chk_item)

        apps_layout.addWidget(self.table_apps)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ ADD APPLICATION")
        btn_add.clicked.connect(self._add_app_row)
        btn_row.addWidget(btn_add)

        btn_browse = QPushButton("BROWSE EXECUTABLE...")
        btn_browse.clicked.connect(self._browse_app_exe)
        btn_row.addWidget(btn_browse)
        apps_layout.addLayout(btn_row)

        tabs.addTab(tab_apps, "APPLICATIONS")

        main_layout.addWidget(tabs)

        # Footer Buttons
        footer = QHBoxLayout()
        btn_defaults = QPushButton("RESET DEFAULTS")
        btn_defaults.clicked.connect(self._reset_defaults)
        footer.addWidget(btn_defaults)

        footer.addStretch()

        btn_cancel = QPushButton("CANCEL")
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)

        btn_save = QPushButton("SAVE & APPLY")
        btn_save.setObjectName("EnableBtn")
        btn_save.clicked.connect(self._save_settings)
        footer.addWidget(btn_save)

        main_layout.addLayout(footer)

    def _launch_calibration_wizard(self) -> None:
        """Opens the full interactive calibration wizard."""
        if not self.camera_worker:
            QMessageBox.warning(self, "Camera Inactive", "Camera sensor must be online to calibrate.")
            return

        wiz = NexusCalibrationWizard(self.settings_mgr, self.camera_worker, self)
        wiz.calibration_applied.connect(self._on_wizard_applied)
        wiz.exec()

    def _on_wizard_applied(self) -> None:
        """Reloads UI fields after wizard completes."""
        self.accept()
        self.settings_applied.emit()

    def _add_app_row(self) -> None:
        row = self.table_apps.rowCount()
        self.table_apps.insertRow(row)
        self.table_apps.setItem(row, 0, QTableWidgetItem("New App"))
        self.table_apps.setItem(row, 1, QTableWidgetItem("C:\\Path\\to\\app.exe"))
        chk_item = QTableWidgetItem()
        chk_item.setCheckState(Qt.Checked)
        self.table_apps.setItem(row, 2, chk_item)

    def _browse_app_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Executable", "C:\\", "Applications (*.exe *.bat *.cmd);;All Files (*.*)"
        )
        if path:
            row = self.table_apps.currentRow()
            if row < 0:
                self._add_app_row()
                row = self.table_apps.rowCount() - 1
            self.table_apps.setItem(row, 1, QTableWidgetItem(path))
            import os
            name = os.path.splitext(os.path.basename(path))[0].capitalize()
            self.table_apps.setItem(row, 0, QTableWidgetItem(name))

    def _reset_defaults(self) -> None:
        reply = QMessageBox.question(
            self, "Reset Configuration", "Reset all settings to factory default values?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.settings_mgr.reset_defaults()
            self.accept()
            self.settings_applied.emit()

    def _save_settings(self) -> None:
        # Camera
        cam_idx = self.combo_cam.currentData()
        if cam_idx is not None:
            self.settings_mgr.set("camera", "index", cam_idx)
        self.settings_mgr.set("camera", "mirror", self.chk_mirror.isChecked())
        self.settings_mgr.set("interface", "show_hud_overlays", self.chk_hud.isChecked())
        self.settings_mgr.set("interface", "enable_animations", self.chk_anim.isChecked())

        # Landmark
        lm = self.combo_landmark.currentData()
        if lm:
            self.settings_mgr.set("mouse", "tracking_landmark", lm)

        # Precision & Smoothing
        self.settings_mgr.set("mouse", "smoothing_type", self.combo_filter.currentData())
        self.settings_mgr.set("mouse", "one_euro_min_cutoff", self.slider_cutoff.value() / 100.0)
        self.settings_mgr.set("mouse", "one_euro_beta", self.slider_beta.value() / 1000.0)
        self.settings_mgr.set("mouse", "deadzone_radius", self.slider_deadzone.value() / 10.0)
        self.settings_mgr.set("mouse", "cursor_mode", self.combo_mode.currentData())
        self.settings_mgr.set("mouse", "invert_x", self.chk_invert_x.isChecked())

        # Sensitivity & ROI
        sx = self.slider_sens_x.value() / 10.0
        sy = self.slider_sens_y.value() / 10.0
        self.settings_mgr.set("mouse", "sensitivity_x", sx)
        self.settings_mgr.set("mouse", "sensitivity_y", sy)
        self.settings_mgr.set("mouse", "sensitivity", (sx + sy) / 2.0)
        self.settings_mgr.set("mouse", "fine_control_mode", self.chk_fine_control.isChecked())

        # Live apply to running mouse instance if available
        if self.camera_worker and hasattr(self.camera_worker, "mouse") and self.camera_worker.mouse:
            self.camera_worker.mouse.sensitivity = (sx + sy) / 2.0
            self.camera_worker.mouse.sensitivity_x = sx
            self.camera_worker.mouse.sensitivity_y = sy
            self.camera_worker.mouse.set_fine_control(self.chk_fine_control.isChecked())
            self.camera_worker.mouse.deadzone_radius = self.slider_deadzone.value() / 10.0
            self.camera_worker.mouse.pinch_threshold = self.slider_pinch.value() / 100.0
            self.camera_worker.mouse.pinch_release_threshold = (self.slider_pinch.value() / 100.0) + 0.12
            self.camera_worker.mouse.click_cooldown = self.slider_cd.value() / 100.0
            self.camera_worker.mouse.click_stabilization = self.chk_stabilize.isChecked()

        hm = self.slider_roi_h.value() / 100.0
        vm = self.slider_roi_v.value() / 100.0
        self.settings_mgr.set("mouse", "roi_left", hm)
        self.settings_mgr.set("mouse", "roi_top", vm)
        self.settings_mgr.set("mouse", "roi_right", 1.0 - hm)
        self.settings_mgr.set("mouse", "roi_bottom", 1.0 - vm)
        self.settings_mgr.set("mouse", "active_margin_x", hm)
        self.settings_mgr.set("mouse", "active_margin_y", vm)

        # Gestures & Clicks
        pinch_val = self.slider_pinch.value() / 100.0
        self.settings_mgr.set("mouse", "pinch_threshold", pinch_val)
        self.settings_mgr.set("mouse", "pinch_release_threshold", pinch_val + 0.12)
        self.settings_mgr.set("mouse", "right_click_threshold", pinch_val)
        self.settings_mgr.set("mouse", "click_cooldown", self.slider_cd.value() / 100.0)
        self.settings_mgr.set("mouse", "right_click_gesture", self.combo_right_gesture.currentData())
        self.settings_mgr.set("mouse", "click_stabilization", self.chk_stabilize.isChecked())

        self.settings_mgr.set("gestures_enabled", "drag_and_drop", self.chk_drag.isChecked())
        self.settings_mgr.set("gestures_enabled", "scroll", self.chk_scroll.isChecked())
        self.settings_mgr.set("gestures_enabled", "right_click", self.chk_right.isChecked())

        # Air Keyboard Settings
        if hasattr(self, "combo_typing_mode"):
            self.settings_mgr.set("air_typing", "typing_mode", self.combo_typing_mode.currentData())
        if hasattr(self, "slider_dwell"):
            self.settings_mgr.set("air_typing", "dwell_duration", self.slider_dwell.value() / 100.0)
        if hasattr(self, "slider_jitter"):
            self.settings_mgr.set("air_typing", "dwell_jitter_tolerance", float(self.slider_jitter.value()))
        if hasattr(self, "slider_kb_cd"):
            self.settings_mgr.set("air_typing", "keypress_cooldown", self.slider_kb_cd.value() / 100.0)
        if hasattr(self, "slider_auto_act"):
            self.settings_mgr.set("air_typing", "auto_activate_duration", self.slider_auto_act.value() / 100.0)
        if hasattr(self, "slider_auto_exit"):
            self.settings_mgr.set("air_typing", "auto_exit_duration", self.slider_auto_exit.value() / 100.0)

        # Applications
        apps_list = []
        for row in range(self.table_apps.rowCount()):
            name_item = self.table_apps.item(row, 0)
            path_item = self.table_apps.item(row, 1)
            chk_item = self.table_apps.item(row, 2)
            if name_item and path_item:
                apps_list.append({
                    "id": name_item.text().lower().replace(" ", "_"),
                    "name": name_item.text(),
                    "path": path_item.text(),
                    "enabled": (chk_item.checkState() == Qt.Checked) if chk_item else True
                })
        self.settings_mgr.set("applications", apps_list)

        self.settings_mgr.save()
        self.accept()
        self.settings_applied.emit()
