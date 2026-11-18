"""JARVIS Interactive Calibration Wizard.
Guides users through webcam selection, comfortable hand distance, custom movement ROI definition,
interactive in-dialog cursor sandbox testing, scale-invariant pinch calibration, and saving preferences.
Desktop control is never enabled during calibration.
"""

import os
import sys
import math
import time
from typing import Optional, Tuple, List

# Ensure parent project root is in sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# If invoked directly via external python, auto-forward to project .venv
if __name__ == "__main__":
    _venv_py = os.path.join(_project_root, ".venv", "Scripts", "python.exe")
    if os.path.isfile(_venv_py):
        try:
            if os.path.abspath(sys.executable).lower() != os.path.abspath(_venv_py).lower():
                import subprocess
                sys.exit(subprocess.call([_venv_py] + sys.argv))
        except Exception:
            pass

from app import qt_bootstrap
qt_bootstrap.setup_qt_environment()
from PySide6.QtCore import Qt, Signal, QTimer, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush, QImage
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QSlider, QComboBox, QFrame, QProgressBar, QMessageBox,
    QRadioButton, QButtonGroup
)

from app.settings_manager import SettingsManager
from app.hand_tracker import HandTracker, HandLandmarkData, INDEX_TIP, WRIST, MIDDLE_MCP
from app.filter import PointFilter2D
from app.camera_worker import CameraWorker
from app.theme import (
    ACCENT_CYAN, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED, ACCENT_GOLD,
    BG_BLACK, BG_DARK_NAVY, BG_PANEL
)


class CalibrationPreviewWidget(QWidget):
    """Camera view inside the wizard showing live landmarks, ROI brackets, and distance guide."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(440, 310)
        self.current_image: Optional[QImage] = None
        self.roi_bounds: Tuple[float, float, float, float] = (0.16, 0.16, 0.84, 0.84)
        self.distance_status: str = "SEARCHING FOR OPTICAL SYNC..."
        self.distance_color: QColor = QColor(255, 60, 90)
        self.tracking_point: Optional[Tuple[float, float]] = None

    def update_feed(self, image: QImage, hand: Optional[HandLandmarkData], roi: Tuple[float, float, float, float]) -> None:
        self.current_image = image
        self.roi_bounds = roi

        if hand:
            scale = hand.hand_scale
            # Hand scale typically ranges 0.12 - 0.28 depending on distance
            if scale < 0.10:
                self.distance_status = "DISTANCE: TOO FAR (MOVE CLOSER)"
                self.distance_color = QColor(255, 200, 0)
            elif scale > 0.32:
                self.distance_status = "DISTANCE: TOO CLOSE (MOVE BACK)"
                self.distance_color = QColor(255, 200, 0)
            else:
                self.distance_status = "DISTANCE: OPTIMAL (STABLE SYNC)"
                self.distance_color = QColor(0, 255, 140)

            self.tracking_point = hand.get_tracking_point("index_tip")
        else:
            self.distance_status = "NO HAND DETECTED"
            self.distance_color = QColor(255, 60, 90)
            self.tracking_point = None

        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        painter.fillRect(0, 0, w, h, QColor(6, 12, 24))

        if self.current_image and not self.current_image.isNull():
            scaled = self.current_image.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            sx = (scaled.width() - w) // 2
            sy = (scaled.height() - h) // 2
            painter.drawImage(0, 0, scaled, sx, sy, w, h)
        else:
            painter.setPen(QColor(0, 240, 255, 120))
            painter.setFont(QFont("Consolas", 10, QFont.Bold))
            painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "AWAITING SENSOR INPUT...")

        # Draw ROI Box
        rl, rt, rr, rb = self.roi_bounds
        bx1, by1 = int(w * rl), int(h * rt)
        bx2, by2 = int(w * rr), int(h * rb)

        pen_roi = QPen(QColor(0, 240, 255, 200), 2, Qt.DashLine)
        painter.setPen(pen_roi)
        painter.drawRect(bx1, by1, bx2 - bx1, by2 - by1)

        # Highlight tracking point if present
        if self.tracking_point:
            tx = int(self.tracking_point[0] * w)
            ty = int(self.tracking_point[1] * h)
            painter.setPen(QPen(QColor(255, 220, 0), 2))
            painter.drawEllipse(QPointF(tx, ty), 10, 10)
            painter.drawPoint(QPointF(tx, ty))

        # Bottom distance banner
        painter.fillRect(0, h - 26, w, 26, QColor(4, 10, 22, 210))
        painter.setFont(QFont("Consolas", 9, QFont.Bold))
        painter.setPen(self.distance_color)
        painter.drawText(12, h - 8, self.distance_status)


class CursorTestCanvas(QFrame):
    """Virtual testing canvas allowing users to test cursor smoothness and click accuracy safely."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(480, 260)
        self.setStyleSheet("background-color: #040914; border: 2px solid #00f0ff; border-radius: 6px;")

        # Virtual cursor position within canvas
        self.cur_x = 240.0
        self.cur_y = 130.0
        self.is_pinching = False
        self.click_count = 0

        # Targets to test hitting
        self.targets = [
            (80, 60, "TARGET 1"),
            (400, 60, "TARGET 2"),
            (240, 130, "CENTER"),
            (80, 200, "TARGET 3"),
            (400, 200, "TARGET 4"),
        ]
        self.target_radius = 24
        self.active_hit = None

    def update_cursor(self, norm_x: float, norm_y: float, is_pinch: bool) -> None:
        w = self.width()
        h = self.height()
        self.cur_x = max(10.0, min(float(w - 10), norm_x * w))
        self.cur_y = max(10.0, min(float(h - 10), norm_y * h))

        if is_pinch and not self.is_pinching:
            # Check if hitting a target
            self.click_count += 1
            for tx, ty, name in self.targets:
                dist = math.hypot(self.cur_x - tx, self.cur_y - ty)
                if dist < self.target_radius:
                    self.active_hit = name
                    break

        self.is_pinching = is_pinch
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw Targets
        for tx, ty, name in self.targets:
            is_hit = (self.active_hit == name)
            color = QColor(0, 255, 140) if is_hit else QColor(0, 160, 255)
            painter.setPen(QPen(color, 2))
            painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 40)))
            painter.drawEllipse(QPointF(tx, ty), self.target_radius, self.target_radius)

            painter.setFont(QFont("Consolas", 7, QFont.Bold))
            painter.setPen(color)
            painter.drawText(QRectF(tx - 35, ty - 8, 70, 16), Qt.AlignCenter, name)

        # Draw Virtual Cursor
        pen_cur = QPen(QColor(255, 220, 0) if not self.is_pinching else QColor(0, 255, 100), 2)
        painter.setPen(pen_cur)
        painter.setBrush(QBrush(QColor(255, 220, 0, 80) if not self.is_pinching else QColor(0, 255, 100, 140)))
        painter.drawEllipse(QPointF(self.cur_x, self.cur_y), 9, 9)

        # Crosshairs
        painter.drawLine(QPointF(self.cur_x - 14, self.cur_y), QPointF(self.cur_x + 14, self.cur_y))
        painter.drawLine(QPointF(self.cur_x, self.cur_y - 14), QPointF(self.cur_x, self.cur_y + 14))

        # Click telemetry footer
        painter.setFont(QFont("Consolas", 8))
        painter.setPen(QColor(0, 240, 255))
        status = f"CLICKS: {self.click_count} | HIT: {self.active_hit or 'NONE'}"
        painter.drawText(12, self.height() - 10, status)


class NexusCalibrationWizard(QDialog):
    """Complete Interactive Step-by-Step Calibration Wizard for N.E.X.U.S."""

    calibration_applied = Signal()

    def __init__(self, settings_mgr: Optional[SettingsManager] = None, camera_worker: Optional[CameraWorker] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings_mgr = settings_mgr or SettingsManager()
        self.camera_worker = camera_worker or CameraWorker()

        self.setWindowTitle("N.E.X.U.S. // TACTICAL CALIBRATION WIZARD")
        self.setFixedSize(860, 580)
        self.setStyleSheet("""
            QDialog {
                background-color: #050b18;
                border: 2px solid #00f0ff;
            }
        """)

        # Working calibration states
        self.working_roi_left = float(self.settings_mgr.get("mouse", "roi_left", default=0.16))
        self.working_roi_top = float(self.settings_mgr.get("mouse", "roi_top", default=0.16))
        self.working_roi_right = float(self.settings_mgr.get("mouse", "roi_right", default=0.84))
        self.working_roi_bottom = float(self.settings_mgr.get("mouse", "roi_bottom", default=0.84))

        self.working_sens_x = float(self.settings_mgr.get("mouse", "sensitivity_x", default=2.2))
        self.working_sens_y = float(self.settings_mgr.get("mouse", "sensitivity_y", default=2.2))
        self.working_filter_type = str(self.settings_mgr.get("mouse", "smoothing_type", default="one_euro"))
        self.working_min_cutoff = float(self.settings_mgr.get("mouse", "one_euro_min_cutoff", default=1.0))
        self.working_beta = float(self.settings_mgr.get("mouse", "one_euro_beta", default=0.05))

        self.working_pinch_th = float(self.settings_mgr.get("mouse", "pinch_threshold", default=0.32))
        self.working_release_th = float(self.settings_mgr.get("mouse", "pinch_release_threshold", default=0.44))
        self.working_tracking_landmark = str(self.settings_mgr.get("mouse", "tracking_landmark", default="index_tip"))

        # Range recording state
        self.is_recording_roi = False
        self.recorded_points: List[Tuple[float, float]] = []

        # Local test filter for canvas
        self.test_filter = PointFilter2D(
            filter_type=self.working_filter_type,
            min_cutoff=self.working_min_cutoff,
            beta=self.working_beta
        )

        self.last_hand: Optional[HandLandmarkData] = None
        self.last_frame: Optional[QImage] = None

        self._build_ui()

        # Connect live frame feed from camera worker
        self.camera_worker.frame_ready.connect(self._on_live_frame)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(12)

        # Header Title
        head_layout = QHBoxLayout()
        self.lbl_title = QLabel("TACTICAL CALIBRATION WIZARD")
        self.lbl_title.setStyleSheet(f"font-size: 16px; font-weight: 900; letter-spacing: 2px; color: {ACCENT_CYAN};")
        self.lbl_step = QLabel("[STEP 1/5] OPTICAL SYNC & POSITIONING")
        self.lbl_step.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {ACCENT_GOLD}; letter-spacing: 1px;")
        head_layout.addWidget(self.lbl_title)
        head_layout.addStretch()
        head_layout.addWidget(self.lbl_step)
        main_layout.addLayout(head_layout)

        # Progress bar
        self.wizard_progress = QProgressBar()
        self.wizard_progress.setRange(1, 5)
        self.wizard_progress.setValue(1)
        self.wizard_progress.setFixedHeight(5)
        self.wizard_progress.setTextVisible(False)
        self.wizard_progress.setStyleSheet(f"""
            QProgressBar {{ background: #0c1830; border: none; }}
            QProgressBar::chunk {{ background: {ACCENT_CYAN}; }}
        """)
        main_layout.addWidget(self.wizard_progress)

        # Stacked Pages
        self.pages = QStackedWidget()
        self._init_step1_page()
        self._init_step2_page()
        self._init_step3_page()
        self._init_step4_page()
        self._init_step5_page()
        main_layout.addWidget(self.pages, stretch=1)

        # Bottom Navigation
        nav_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("CANCEL")
        self.btn_cancel.clicked.connect(self.reject)
        nav_layout.addWidget(self.btn_cancel)

        nav_layout.addStretch()

        self.btn_back = QPushButton("<< BACK")
        self.btn_back.setEnabled(False)
        self.btn_back.clicked.connect(self._prev_page)
        nav_layout.addWidget(self.btn_back)

        self.btn_next = QPushButton("NEXT >>")
        self.btn_next.setObjectName("EnableBtn")
        self.btn_next.clicked.connect(self._next_page)
        nav_layout.addWidget(self.btn_next)

        main_layout.addLayout(nav_layout)

    # -------------------------------------------------------------
    # PAGE 1: Optical Sensor & Hand Distance
    # -------------------------------------------------------------
    def _init_step1_page(self) -> None:
        page = QWidget()
        layout = QHBoxLayout(page)

        # Left: Preview widget
        self.preview_step1 = CalibrationPreviewWidget()
        layout.addWidget(self.preview_step1)

        # Right: Instructions & Controls
        right_layout = QVBoxLayout()
        right_layout.setSpacing(12)

        desc = QLabel(
            "<b>STEP 1: SENSOR SELECTION & POSITIONING</b><br><br>"
            "1. Select your preferred laptop or USB webcam below.<br>"
            "2. Position your hand comfortably in front of the lens (approx. 1.5 - 2.5 ft).<br>"
            "3. Ensure room lighting provides clear contrast between fingers and background.<br>"
            "4. Verify the bottom status turns <b>GREEN (OPTIMAL DISTANCE)</b>."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #c0d8f0; line-height: 140%;")
        right_layout.addWidget(desc)

        # Camera selection dropdown
        cam_row = QHBoxLayout()
        cam_row.addWidget(QLabel("ACTIVE SENSOR:"))
        self.combo_cam = QComboBox()
        available = CameraWorker.get_available_cameras()
        curr_cam = self.settings_mgr.get("camera", "index", default=0)
        for idx in available:
            tag = " (Primary / Integrated)" if idx == 0 else " (Secondary / Virtual)"
            self.combo_cam.addItem(f"Sensor Device {idx}{tag}", idx)
            if idx == curr_cam:
                self.combo_cam.setCurrentIndex(self.combo_cam.count() - 1)
        self.combo_cam.currentIndexChanged.connect(self._on_cam_changed)
        cam_row.addWidget(self.combo_cam)
        right_layout.addLayout(cam_row)

        right_layout.addStretch()
        layout.addLayout(right_layout)
        self.pages.addWidget(page)

    # -------------------------------------------------------------
    # PAGE 2: Hand Movement Region (ROI)
    # -------------------------------------------------------------
    def _init_step2_page(self) -> None:
        page = QWidget()
        layout = QHBoxLayout(page)

        self.preview_step2 = CalibrationPreviewWidget()
        layout.addWidget(self.preview_step2)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(10)

        desc = QLabel(
            "<b>STEP 2: DEFINE COMFORTABLE MOVEMENT REGION</b><br><br>"
            "The dashed rectangle represents the active camera space that maps to your full desktop.<br><br>"
            "Click <b>RECORD NATURAL RANGE</b> and move your hand comfortably to all four corners. "
            "N.E.X.U.S. will automatically calibrate your optimal movement bounds without arm strain!"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #c0d8f0;")
        right_layout.addWidget(desc)

        self.btn_record_roi = QPushButton("⏺ RECORD NATURAL RANGE")
        self.btn_record_roi.setFixedHeight(36)
        self.btn_record_roi.setStyleSheet("font-weight: bold; background-color: #0e2b4d; border: 1px solid #00f0ff;")
        self.btn_record_roi.clicked.connect(self._toggle_record_roi)
        right_layout.addWidget(self.btn_record_roi)

        self.lbl_record_status = QLabel("Status: Ready to record natural range.")
        self.lbl_record_status.setStyleSheet("color: #a0c0e0; font-family: Consolas; font-size: 11px;")
        right_layout.addWidget(self.lbl_record_status)

        # Preset Buttons
        preset_row = QHBoxLayout()
        btn_compact = QPushButton("COMPACT ROI")
        btn_compact.clicked.connect(lambda: self._set_roi_preset(0.25, 0.22, 0.75, 0.78))
        btn_balanced = QPushButton("BALANCED ROI")
        btn_balanced.clicked.connect(lambda: self._set_roi_preset(0.16, 0.16, 0.84, 0.84))
        btn_wide = QPushButton("WIDE ROI")
        btn_wide.clicked.connect(lambda: self._set_roi_preset(0.10, 0.10, 0.90, 0.90))
        preset_row.addWidget(btn_compact)
        preset_row.addWidget(btn_balanced)
        preset_row.addWidget(btn_wide)
        right_layout.addLayout(preset_row)

        right_layout.addStretch()
        layout.addLayout(right_layout)
        self.pages.addWidget(page)

    # -------------------------------------------------------------
    # PAGE 3: Cursor Smoothing & Sensitivity (In-Wizard Sandbox)
    # -------------------------------------------------------------
    def _init_step3_page(self) -> None:
        page = QWidget()
        layout = QHBoxLayout(page)

        # Virtual Canvas for safe in-wizard testing
        canvas_col = QVBoxLayout()
        self.test_canvas = CursorTestCanvas()
        canvas_col.addWidget(self.test_canvas)
        lbl_hint = QLabel("Move hand to target circles. (Desktop input remains safe & disabled).")
        lbl_hint.setStyleSheet("color: #6090b0; font-size: 10px;")
        canvas_col.addWidget(lbl_hint)
        layout.addLayout(canvas_col)

        # Settings Sliders
        controls = QVBoxLayout()
        controls.setSpacing(10)

        title = QLabel("<b>STEP 3: PRECISION & SMOOTHING</b>")
        title.setStyleSheet(f"color: {ACCENT_CYAN};")
        controls.addWidget(title)

        # Tracking Landmark Choice
        controls.addWidget(QLabel("ERGONOMIC TRACKING POINT:"))
        self.combo_landmark = QComboBox()
        self.combo_landmark.addItem("Index Fingertip (Default)", "index_tip")
        self.combo_landmark.addItem("Index Knuckle / MCP (Ultra-Stable)", "index_mcp")
        self.combo_landmark.addItem("Index Joint / PIP (Curled Hand)", "index_pip")
        self.combo_landmark.addItem("Palm Center (Relaxed Open Hand)", "hand_center")
        self.combo_landmark.addItem("Thumb-Index Midpoint", "thumb_index_mid")

        curr_lm = self.working_tracking_landmark
        for i in range(self.combo_landmark.count()):
            if self.combo_landmark.itemData(i) == curr_lm:
                self.combo_landmark.setCurrentIndex(i)
        self.combo_landmark.currentIndexChanged.connect(self._on_landmark_changed)
        controls.addWidget(self.combo_landmark)

        # Sensitivity X Slider
        self.lbl_sens_x = QLabel(f"HORIZONTAL SENSITIVITY: {self.working_sens_x:.1f}x")
        self.slider_sens_x = QSlider(Qt.Horizontal)
        self.slider_sens_x.setRange(10, 50)
        self.slider_sens_x.setValue(int(self.working_sens_x * 10))
        self.slider_sens_x.valueChanged.connect(self._on_sens_x_changed)
        controls.addWidget(self.lbl_sens_x)
        controls.addWidget(self.slider_sens_x)

        # Sensitivity Y Slider
        self.lbl_sens_y = QLabel(f"VERTICAL SENSITIVITY: {self.working_sens_y:.1f}x")
        self.slider_sens_y = QSlider(Qt.Horizontal)
        self.slider_sens_y.setRange(10, 50)
        self.slider_sens_y.setValue(int(self.working_sens_y * 10))
        self.slider_sens_y.valueChanged.connect(self._on_sens_y_changed)
        controls.addWidget(self.lbl_sens_y)
        controls.addWidget(self.slider_sens_y)

        # Smoothing Algorithm
        controls.addWidget(QLabel("SMOOTHING ALGORITHM:"))
        filt_row = QHBoxLayout()
        self.radio_1euro = QRadioButton("1€ Filter (Optimal)")
        self.radio_adaptive = QRadioButton("Adaptive EMA")
        self.radio_1euro.setChecked(self.working_filter_type == "one_euro")
        self.radio_adaptive.setChecked(self.working_filter_type != "one_euro")
        self.radio_1euro.toggled.connect(self._on_filter_type_changed)
        filt_row.addWidget(self.radio_1euro)
        filt_row.addWidget(self.radio_adaptive)
        controls.addLayout(filt_row)

        controls.addStretch()
        layout.addLayout(controls)
        self.pages.addWidget(page)

    # -------------------------------------------------------------
    # PAGE 4: Pinch & Click Calibration
    # -------------------------------------------------------------
    def _init_step4_page(self) -> None:
        page = QWidget()
        layout = QHBoxLayout(page)

        # Left preview
        self.preview_step4 = CalibrationPreviewWidget()
        layout.addWidget(self.preview_step4)

        # Right controls
        controls = QVBoxLayout()
        controls.setSpacing(12)

        desc = QLabel(
            "<b>STEP 4: PINCH-TO-CLICK CALIBRATION</b><br><br>"
            "N.E.X.U.S. uses scale-normalized pinch distance so clicking works effortlessly at any camera distance.<br><br>"
            "Pinch your thumb and index finger together naturally. Watch the visual feedback below:"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #c0d8f0;")
        controls.addWidget(desc)

        # Live Pinch Distance Readout
        self.lbl_live_pinch = QLabel("CURRENT PINCH DISTANCE: --")
        self.lbl_live_pinch.setStyleSheet("font-family: Consolas; font-size: 13px; font-weight: bold; color: #00f0ff;")
        controls.addWidget(self.lbl_live_pinch)

        self.pinch_bar = QProgressBar()
        self.pinch_bar.setRange(0, 100)
        self.pinch_bar.setFixedHeight(14)
        self.pinch_bar.setStyleSheet("""
            QProgressBar { background: #0c1830; border: 1px solid #163660; border-radius: 4px; }
            QProgressBar::chunk { background: #00f0ff; }
        """)
        controls.addWidget(self.pinch_bar)

        # Click indicator box
        self.lbl_click_feedback = QLabel("STATUS: PINCH OPEN")
        self.lbl_click_feedback.setAlignment(Qt.AlignCenter)
        self.lbl_click_feedback.setFixedHeight(34)
        self.lbl_click_feedback.setStyleSheet("background-color: #0b1a34; border: 1px solid #1a3560; color: #a0c0e0; font-weight: bold;")
        controls.addWidget(self.lbl_click_feedback)

        # Auto-Tune Threshold Button
        btn_autotune = QPushButton("🎯 AUTO-CALIBRATE PINCH THRESHOLD")
        btn_autotune.setFixedHeight(34)
        btn_autotune.clicked.connect(self._autotune_pinch)
        controls.addWidget(btn_autotune)

        # Threshold Slider
        self.lbl_th_slider = QLabel(f"PINCH ACTIVATION THRESHOLD: {self.working_pinch_th:.3f}")
        self.slider_pinch_th = QSlider(Qt.Horizontal)
        self.slider_pinch_th.setRange(15, 60)
        self.slider_pinch_th.setValue(int(self.working_pinch_th * 100))
        self.slider_pinch_th.valueChanged.connect(self._on_pinch_slider_changed)
        controls.addWidget(self.lbl_th_slider)
        controls.addWidget(self.slider_pinch_th)

        controls.addStretch()
        layout.addLayout(controls)
        self.pages.addWidget(page)

    # -------------------------------------------------------------
    # PAGE 5: Review & Save
    # -------------------------------------------------------------
    def _init_step5_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(14)

        title = QLabel("<b>STEP 5: CALIBRATION PROFILE REVIEW</b>")
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {ACCENT_CYAN};")
        layout.addWidget(title)

        self.lbl_summary = QLabel()
        self.lbl_summary.setStyleSheet("""
            background-color: #081224;
            border: 1px solid #1c3b70;
            border-radius: 6px;
            padding: 16px;
            font-family: Consolas;
            color: #d0e8ff;
            line-height: 160%;
        """)
        layout.addWidget(self.lbl_summary)

        btn_save = QPushButton("💾 SAVE CALIBRATION & APPLY TO N.E.X.U.S.")
        btn_save.setObjectName("EnableBtn")
        btn_save.setFixedHeight(44)
        btn_save.setStyleSheet("font-size: 13px; font-weight: bold; letter-spacing: 1.5px;")
        btn_save.clicked.connect(self._save_and_apply)
        layout.addWidget(btn_save)

        self.pages.addWidget(page)

    # -------------------------------------------------------------
    # EVENT HANDLERS & LOGIC
    # -------------------------------------------------------------
    def _on_live_frame(self, image: QImage, hand: Optional[HandLandmarkData], gesture_state) -> None:
        self.last_frame = image
        self.last_hand = hand

        curr_page = self.pages.currentIndex()
        roi = (self.working_roi_left, self.working_roi_top, self.working_roi_right, self.working_roi_bottom)

        if curr_page == 0:
            self.preview_step1.update_feed(image, hand, roi)
        elif curr_page == 1:
            self.preview_step2.update_feed(image, hand, roi)
            if self.is_recording_roi and hand:
                pt = hand.get_tracking_point(self.working_tracking_landmark)
                self.recorded_points.append(pt)
                self.lbl_record_status.setText(f"Recording... {len(self.recorded_points)} coordinates captured.")
        elif curr_page == 2:
            # Map tracking point to test canvas [0..1]
            if hand:
                pt = hand.get_tracking_point(self.working_tracking_landmark)
                # Apply ROI mapping
                clamped_x = max(self.working_roi_left, min(self.working_roi_right, pt[0]))
                clamped_y = max(self.working_roi_top, min(self.working_roi_bottom, pt[1]))
                rw = max(0.05, self.working_roi_right - self.working_roi_left)
                rh = max(0.05, self.working_roi_bottom - self.working_roi_top)
                norm_x = (clamped_x - self.working_roi_left) / rw
                norm_y = (clamped_y - self.working_roi_top) / rh

                # Sensitivity multiplier
                norm_x = max(0.0, min(1.0, (norm_x - 0.5) * self.working_sens_x + 0.5))
                norm_y = max(0.0, min(1.0, (norm_y - 0.5) * self.working_sens_y + 0.5))

                # Smooth with test filter
                fx, fy = self.test_filter.filter(norm_x, norm_y)

                # Check pinch
                is_p = hand.norm_pinch_distance < self.working_pinch_th
                self.test_canvas.update_cursor(fx, fy, is_p)
        elif curr_page == 3:
            self.preview_step4.update_feed(image, hand, roi)
            if hand:
                p_dist = hand.norm_pinch_distance
                self.lbl_live_pinch.setText(f"CURRENT PINCH DISTANCE: {p_dist:.3f}")
                pct = max(0, min(100, int((1.0 - (p_dist / (self.working_pinch_th * 2.0))) * 100)))
                self.pinch_bar.setValue(pct)

                if p_dist < self.working_pinch_th:
                    self.lbl_click_feedback.setText("STATUS: 🟢 CLICK ACTIVATED!")
                    self.lbl_click_feedback.setStyleSheet("background-color: #082d20; border: 1px solid #00ff88; color: #00ff88; font-weight: bold;")
                else:
                    self.lbl_click_feedback.setText("STATUS: PINCH OPEN")
                    self.lbl_click_feedback.setStyleSheet("background-color: #0b1a34; border: 1px solid #1a3560; color: #a0c0e0; font-weight: bold;")

    def _on_cam_changed(self, idx: int) -> None:
        device_idx = self.combo_cam.currentData()
        if device_idx is not None:
            self.camera_worker.set_camera_index(device_idx)

    def _toggle_record_roi(self) -> None:
        if not self.is_recording_roi:
            self.is_recording_roi = True
            self.recorded_points.clear()
            self.btn_record_roi.setText("⏹ FINISH & APPLY RECORDING")
            self.btn_record_roi.setStyleSheet("font-weight: bold; background-color: #3b0c19; border: 1px solid #ff2a5f;")
            self.lbl_record_status.setText("Recording hand movement range... Move hand freely!")
        else:
            self.is_recording_roi = False
            self.btn_record_roi.setText("⏺ RECORD NATURAL RANGE")
            self.btn_record_roi.setStyleSheet("font-weight: bold; background-color: #0e2b4d; border: 1px solid #00f0ff;")

            if len(self.recorded_points) > 15:
                xs = [p[0] for p in self.recorded_points]
                ys = [p[1] for p in self.recorded_points]
                min_x, max_x = min(xs), max(xs)
                min_y, max_y = min(ys), max(ys)

                # Add a 5% margin so corners are reachable without boundary clipping
                span_x = max_x - min_x
                span_y = max_y - min_y
                if span_x > 0.1 and span_y > 0.1:
                    self.working_roi_left = max(0.02, min_x + span_x * 0.05)
                    self.working_roi_right = min(0.98, max_x - span_x * 0.05)
                    self.working_roi_top = max(0.02, min_y + span_y * 0.05)
                    self.working_roi_bottom = min(0.98, max_y - span_y * 0.05)
                    self.lbl_record_status.setText(f"ROI calibrated: [{self.working_roi_left:.2f}, {self.working_roi_top:.2f}, {self.working_roi_right:.2f}, {self.working_roi_bottom:.2f}]")
            else:
                self.lbl_record_status.setText("Not enough tracking samples. Move hand across view and try again.")

    def _set_roi_preset(self, l: float, t: float, r: float, b: float) -> None:
        self.working_roi_left = l
        self.working_roi_top = t
        self.working_roi_right = r
        self.working_roi_bottom = b
        self.lbl_record_status.setText(f"Preset applied: [{l:.2f}, {t:.2f}, {r:.2f}, {b:.2f}]")

    def _on_landmark_changed(self, idx: int) -> None:
        self.working_tracking_landmark = str(self.combo_landmark.currentData())

    def _on_sens_x_changed(self, val: int) -> None:
        self.working_sens_x = val / 10.0
        self.lbl_sens_x.setText(f"HORIZONTAL SENSITIVITY: {self.working_sens_x:.1f}x")

    def _on_sens_y_changed(self, val: int) -> None:
        self.working_sens_y = val / 10.0
        self.lbl_sens_y.setText(f"VERTICAL SENSITIVITY: {self.working_sens_y:.1f}x")

    def _on_filter_type_changed(self) -> None:
        self.working_filter_type = "one_euro" if self.radio_1euro.isChecked() else "adaptive_ema"
        self.test_filter.update_parameters(filter_type=self.working_filter_type)

    def _on_pinch_slider_changed(self, val: int) -> None:
        self.working_pinch_th = val / 100.0
        self.working_release_th = self.working_pinch_th + 0.12
        self.lbl_th_slider.setText(f"PINCH ACTIVATION THRESHOLD: {self.working_pinch_th:.3f}")

    def _autotune_pinch(self) -> None:
        if self.last_hand:
            curr_dist = self.last_hand.norm_pinch_distance
            # Set threshold slightly above current distance
            self.working_pinch_th = max(0.20, min(0.50, curr_dist * 1.15))
            self.working_release_th = self.working_pinch_th + 0.12
            self.slider_pinch_th.setValue(int(self.working_pinch_th * 100))
            QMessageBox.information(self, "Auto-Tuned", f"Optimal threshold set to {self.working_pinch_th:.3f}!")

    def _update_step_labels(self) -> None:
        idx = self.pages.currentIndex() + 1
        steps = [
            "OPTICAL SYNC & POSITIONING",
            "MOVEMENT REGION (ROI)",
            "PRECISION & SMOOTHING",
            "PINCH-TO-CLICK CALIBRATION",
            "PROFILE REVIEW & SAVE"
        ]
        self.lbl_step.setText(f"[STEP {idx}/5] {steps[idx-1]}")
        self.wizard_progress.setValue(idx)
        self.btn_back.setEnabled(idx > 1)
        self.btn_next.setText("NEXT >>" if idx < 5 else "FINISH")

        if idx == 5:
            # Build review summary
            lm_text = self.working_tracking_landmark.upper().replace("_", " ")
            filt_text = "1€ Filter (One Euro)" if self.working_filter_type == "one_euro" else "Adaptive EMA"
            summary_text = (
                f"<b>CALIBRATION SUMMARY:</b><br><br>"
                f"• <b>Active Tracking Point:</b> {lm_text}<br>"
                f"• <b>Movement Bounds (ROI):</b> Left={self.working_roi_left:.2f}, Top={self.working_roi_top:.2f}, Right={self.working_roi_right:.2f}, Bottom={self.working_roi_bottom:.2f}<br>"
                f"• <b>Sensitivity:</b> Horizontal={self.working_sens_x:.1f}x | Vertical={self.working_sens_y:.1f}x<br>"
                f"• <b>Smoothing Engine:</b> {filt_text}<br>"
                f"• <b>Scale-Normalized Pinch Threshold:</b> {self.working_pinch_th:.3f} (Release: {self.working_release_th:.3f})<br>"
                f"• <b>Click Stabilization:</b> Active (Anti-Slip Guard)<br><br>"
                f"<i>Click 'SAVE CALIBRATION' below to persist these settings into N.E.X.U.S.</i>"
            )
            self.lbl_summary.setText(summary_text)

    def _next_page(self) -> None:
        curr = self.pages.currentIndex()
        if curr < self.pages.count() - 1:
            self.pages.setCurrentIndex(curr + 1)
            self._update_step_labels()
        else:
            self._save_and_apply()

    def _prev_page(self) -> None:
        curr = self.pages.currentIndex()
        if curr > 0:
            self.pages.setCurrentIndex(curr - 1)
            self._update_step_labels()

    def _save_and_apply(self) -> None:
        """Persists calibrated configuration into SettingsManager and applies to running systems."""
        # Camera
        cam_idx = self.combo_cam.currentData()
        if cam_idx is not None:
            self.settings_mgr.set("camera", "index", cam_idx)

        # Mouse & ROI
        self.settings_mgr.set("mouse", "roi_left", self.working_roi_left)
        self.settings_mgr.set("mouse", "roi_top", self.working_roi_top)
        self.settings_mgr.set("mouse", "roi_right", self.working_roi_right)
        self.settings_mgr.set("mouse", "roi_bottom", self.working_roi_bottom)
        self.settings_mgr.set("mouse", "active_margin_x", self.working_roi_left)
        self.settings_mgr.set("mouse", "active_margin_y", self.working_roi_top)

        # Sensitivity & Smoothing
        self.settings_mgr.set("mouse", "sensitivity_x", self.working_sens_x)
        self.settings_mgr.set("mouse", "sensitivity_y", self.working_sens_y)
        self.settings_mgr.set("mouse", "sensitivity", (self.working_sens_x + self.working_sens_y) / 2.0)
        self.settings_mgr.set("mouse", "smoothing_type", self.working_filter_type)
        self.settings_mgr.set("mouse", "tracking_landmark", self.working_tracking_landmark)

        # Pinch
        self.settings_mgr.set("mouse", "pinch_normalized", True)
        self.settings_mgr.set("mouse", "pinch_threshold", self.working_pinch_th)
        self.settings_mgr.set("mouse", "pinch_release_threshold", self.working_release_th)
        self.settings_mgr.set("mouse", "right_click_threshold", self.working_pinch_th)

        # Save to disk
        self.settings_mgr.save()

        # Emit signal to notify parent window
        self.calibration_applied.emit()
        self.accept()

    def closeEvent(self, event) -> None:
        try:
            self.camera_worker.frame_ready.disconnect(self._on_live_frame)
        except Exception:
            pass
        event.accept()


# Backwards compatibility alias
JarvisCalibrationWizard = NexusCalibrationWizard


if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)
    _wizard = NexusCalibrationWizard()
    _wizard.show()
    sys.exit(_app.exec())
