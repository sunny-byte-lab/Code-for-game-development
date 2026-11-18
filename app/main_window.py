"""N.E.X.U.S. Cinematic Main Window.
Neural Experience & Unified System -- Futuristic Holographic AI Laboratory.
All components are wired directly to actual OpenCV, MediaPipe, PyAutoGUI, and Pycaw engines.
"""

import os
import sys
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from app import qt_bootstrap
from PySide6.QtCore import Qt, QTimer, Slot, QRectF, QPointF, QThread, QCoreApplication
from PySide6.QtGui import (
    QImage, QKeySequence, QShortcut, QPainter, QColor, QPen, QBrush, QLinearGradient
)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QStackedWidget, QFrame, QProgressBar,
    QSizePolicy, QScrollArea, QTabWidget
)

from app.theme import (
    NEXUS_STYLESHEET, ACCENT_CYAN, ACCENT_ICY_BLUE, ACCENT_BLUE,
    ACCENT_GOLD, ACCENT_GREEN, ACCENT_RED, TEXT_PRIMARY, TEXT_MUTED,
    BG_BLACK, BG_MIDNIGHT, BG_PANEL
)
from app.settings_manager import SettingsManager
from app.safety_controller import SafetyController, SystemState, ControlMode
from app.hand_tracker import HandTracker, HandLandmarkData
from app.gesture_recognizer import GestureRecognizer, GestureType, GestureState
from app.virtual_mouse import VirtualMouse
from app.system_controls import SystemControls
from app.app_launcher import AppLauncher
from app.camera_worker import CameraWorker, ControlPipelineStatus
from app.settings_dialog import SettingsDialog
from app.voice_commander import VoiceCommander
from app.hud_widgets import (
    NexusLogoWidget, NexusCoreWidget, GlowCard,
    WebcamHUDWidget, AudioLevelMeter, TerminalLogView,
    HolographicGlobeWidget, AIAssistantWidget,
    ArmorTelemetryWidget, GestureGuideWidget
)
from app.holographic_keyboard import HolographicKeyboardWidget
from app.startup_screen import NexusStartupScreen, JarvisStartupScreen
from app.calibration_wizard import NexusCalibrationWizard, JarvisCalibrationWizard
from app.diagnostics_dialog import NexusDiagnosticsDialog, JarvisDiagnosticsDialog
from app.camera_device_utils import open_windows_camera_settings
from app.logger import register_log_listener, unregister_log_listener, log_bridge, get_log_bridge
from app.scroll_controller import ScrollDiagnosticWidget, ScrollTelemetry

logger = logging.getLogger("NEXUS.MainWindow")


# ============================================================================
# TOP HEADER BAR
# ============================================================================
class _HeaderBar(QWidget):
    """
    Top Header Bar:
    - N.E.X.U.S. animated emblem and branding
    - Navigation tabs: Vision | Control | Automation | 3D Lab | AI Assistant | System
    - Live digital clock and date
    - Real-time status pills: Camera, Gesture, System status
    - System Configuration access button
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(54)
        self.setObjectName("HeaderWidget")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(10)

        # Logo emblem
        self.logo = NexusLogoWidget(self, size=38)
        layout.addWidget(self.logo)

        # Title block
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        lbl_title = QLabel("N.E.X.U.S.")
        lbl_title.setStyleSheet(
            f"font-size: 17px; font-weight: 900; letter-spacing: 6px; color: {ACCENT_CYAN};"
        )
        lbl_sub = QLabel("HOLOGRAPHIC AI LABORATORY")
        lbl_sub.setStyleSheet(
            f"font-size: 7px; font-weight: 700; letter-spacing: 2.5px; color: {TEXT_MUTED};"
        )
        title_col.addWidget(lbl_title)
        title_col.addWidget(lbl_sub)
        layout.addLayout(title_col)

        layout.addSpacing(12)

        # Navigation pill buttons
        self.nav_buttons: Dict[str, QPushButton] = {}
        nav_items = ["VISION", "CONTROL", "AUTOMATION", "3D LAB", "PRESENTATION", "KEYBOARD", "AI ASSISTANT", "SYSTEM"]
        for item in nav_items:
            b = QPushButton(item)
            b.setFixedHeight(26)
            b.setStyleSheet(
                f"QPushButton {{ background: rgba(8,18,44,0.6); border: 1px solid rgba(0,200,255,0.18); "
                f"color: {TEXT_MUTED}; font-size: 8px; font-weight: 700; padding: 2px 8px; "
                f"letter-spacing: 0.8px; border-radius: 2px; }}"
                f"QPushButton:hover {{ background: rgba(0,140,240,0.25); border: 1px solid {ACCENT_CYAN}; color: #fff; }}"
                f"QPushButton[active='true'] {{ background: rgba(0,180,255,0.3); border: 1px solid {ACCENT_CYAN}; color: #fff; }}"
            )
            self.nav_buttons[item] = b
            layout.addWidget(b)

        layout.addStretch()

        # Live digital clock
        self.lbl_clock = QLabel()
        self.lbl_clock.setStyleSheet(
            f"font-family: Consolas, monospace; font-size: 9px; font-weight: bold; "
            f"color: {ACCENT_ICY_BLUE}; padding: 3px 10px; "
            f"background: rgba(8,18,44,0.8); border: 1px solid rgba(0,200,255,0.2); "
            f"border-radius: 3px; letter-spacing: 1px;"
        )
        self._update_clock()
        layout.addWidget(self.lbl_clock)
        self._clock_t = QTimer(self)
        self._clock_t.timeout.connect(self._update_clock)
        self._clock_t.start(1000)

        # Status pills
        self.lbl_cam = _StatusPill("CAM OFFLINE", ACCENT_GOLD)
        layout.addWidget(self.lbl_cam)

        self.lbl_gest = _StatusPill("GESTURE: NONE", ACCENT_ICY_BLUE)
        layout.addWidget(self.lbl_gest)

        self.lbl_state = _StatusPill("WAITING FOR HAND", ACCENT_GOLD)
        layout.addWidget(self.lbl_state)

        layout.addSpacing(6)

        # Header utility buttons
        for label, tip, cb_name in [
            ("CALIBRATE", "Open Calibration Wizard", "calibrate"),
            ("SENSOR 0", "Cycle Camera Device", "sensor"),
            ("CONFIG", "Open System Configuration", "config"),
            ("DIAGNOSTICS", "Open Diagnostics & Telemetry", "diag"),
        ]:
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.setFixedHeight(28)
            btn.setStyleSheet(
                f"font-size: 8px; font-weight: 700; letter-spacing: 0.5px; "
                f"padding: 2px 10px; background: rgba(8,18,44,0.7); "
                f"border: 1px solid rgba(0,200,255,0.2); color: {ACCENT_ICY_BLUE}; border-radius:2px;"
            )
            setattr(self, f"btn_{cb_name}", btn)
            layout.addWidget(btn)

    def _update_clock(self):
        self.lbl_clock.setText(datetime.now().strftime("%d %b %Y  %H:%M:%S"))

    def set_cam_state(self, online: bool):
        if online:
            self.lbl_cam.setText("CAM ONLINE")
            self.lbl_cam.setStyleSheet(
                f"background: rgba(8,18,44,0.7); border: 1px solid rgba(16,185,129,0.4); "
                f"border-radius: 8px; color: {ACCENT_GREEN}; font-size: 8px; font-weight: 700; "
                f"padding: 2px 8px; letter-spacing: 0.5px;"
            )
        else:
            self.lbl_cam.setText("CAM OFFLINE")
            self.lbl_cam.setStyleSheet(
                f"background: rgba(8,18,44,0.7); border: 1px solid rgba(245,158,11,0.4); "
                f"border-radius: 8px; color: {ACCENT_GOLD}; font-size: 8px; font-weight: 700; "
                f"padding: 2px 8px; letter-spacing: 0.5px;"
            )

    def set_gesture_text(self, text: str):
        self.lbl_gest.setText(f"GESTURE: {text[:14]}")

    def set_control_state(self, text: str, color: str):
        self.lbl_state.setText(text)
        self.lbl_state.setStyleSheet(
            f"background: rgba(8,18,44,0.7); border: 1px solid rgba(0,200,255,0.22); "
            f"border-radius: 8px; color: {color}; font-size: 8px; font-weight: 700; "
            f"padding: 2px 10px; letter-spacing: 0.5px;"
        )

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(4, 10, 26, 240))
        grad = QLinearGradient(0, h - 1, w, h - 1)
        grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad.setColorAt(0.2, QColor(0, 240, 255, 90))
        grad.setColorAt(0.8, QColor(0, 240, 255, 90))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, h - 1, w, 1, QBrush(grad))


class _StatusPill(QLabel):
    def __init__(self, text="", color=ACCENT_CYAN, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(
            f"background: rgba(8,18,44,0.7); border: 1px solid rgba(0,200,255,0.22); "
            f"border-radius: 8px; color: {color}; font-size: 8px; font-weight: 700; "
            f"padding: 2px 8px; letter-spacing: 0.5px;"
        )


# ============================================================================
# BOTTOM CONTROL DOCK
# ============================================================================
class _ControlDock(QWidget):
    """Floating bottom control dock with mode switcher and master safety controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 4, 16, 4)
        layout.setSpacing(6)

        # Mode label
        lbl = QLabel("MODE:")
        lbl.setStyleSheet(f"font-size: 8px; font-weight: 700; color: {TEXT_MUTED}; letter-spacing: 1px;")
        layout.addWidget(lbl)

        # Mode buttons
        self.btn_mouse    = self._mode_btn("DESKTOP")
        self.btn_app      = self._mode_btn("APP LAUNCHER")
        self.btn_sys      = self._mode_btn("SYSTEM CONTROL")
        self.btn_3d       = self._mode_btn("3D LAB")
        self.btn_pres     = self._mode_btn("PRESENTATION")
        self.btn_keyboard = self._mode_btn("KEYBOARD")
        for b in (self.btn_mouse, self.btn_app, self.btn_sys, self.btn_3d, self.btn_pres, self.btn_keyboard):
            layout.addWidget(b)

        layout.addSpacing(10)
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setFixedHeight(24)
        sep.setStyleSheet("background: rgba(0,240,255,0.18);")
        layout.addWidget(sep)
        layout.addSpacing(10)

        # Utility buttons
        self.btn_alttab    = self._util_btn("ALT+TAB")
        self.btn_minimize  = self._util_btn("MINIMIZE")
        self.btn_desktop   = self._util_btn("WIN+D")
        self.btn_files     = self._util_btn("FILES")
        self.btn_fine_ctrl = self._util_btn("FINE CTRL")
        self.btn_recenter  = self._util_btn("RECENTER")
        self.btn_settings  = self._util_btn("SETTINGS")
        self.btn_reset_3d  = self._util_btn("RESET 3D")
        self.btn_toggle_kb = self._util_btn("HOLO KB")
        self.btn_calibrate = self._util_btn("CALIBRATE")
        for b in (self.btn_alttab, self.btn_minimize, self.btn_desktop, self.btn_files, self.btn_fine_ctrl, self.btn_recenter, self.btn_settings, self.btn_reset_3d, self.btn_toggle_kb, self.btn_calibrate):
            layout.addWidget(b)

        layout.addStretch()

        # Master safety controls
        self.btn_enable = QPushButton("ENABLE CONTROL")
        self.btn_enable.setObjectName("EnableBtn")
        self.btn_enable.setFixedHeight(32)
        layout.addWidget(self.btn_enable)

        self.btn_pause = QPushButton("PAUSE")
        self.btn_pause.setFixedHeight(32)
        self.btn_pause.setStyleSheet(
            f"background: rgba(10,22,52,0.7); border: 1px solid rgba(0,200,255,0.25); "
            f"color: {ACCENT_ICY_BLUE}; font-weight: 700; font-size: 9px; padding: 3px 12px;"
        )
        layout.addWidget(self.btn_pause)

        self.btn_emergency = QPushButton("EMERGENCY STOP [ESC]")
        self.btn_emergency.setObjectName("EmergencyBtn")
        self.btn_emergency.setFixedHeight(32)
        layout.addWidget(self.btn_emergency)

    def _mode_btn(self, label):
        b = QPushButton(label)
        b.setProperty("class", "ModeBtn")
        b.setFixedHeight(30)
        b.setStyleSheet(
            f"QPushButton {{ background: rgba(8,16,38,0.6); border: 1px solid rgba(0,150,200,0.2); "
            f"color: {TEXT_MUTED}; padding: 4px 10px; font-size: 8px; font-weight: 700; "
            f"letter-spacing: 0.8px; border-radius: 2px; }}"
            f"QPushButton:hover {{ border: 1px solid {ACCENT_CYAN}; color: #fff; "
            f"background: rgba(0,100,200,0.2); }}"
            f"QPushButton[active='true'] {{ border: 1px solid {ACCENT_CYAN}; color: #fff; "
            f"background: rgba(0,100,200,0.28); }}"
        )
        return b

    def _util_btn(self, label):
        b = QPushButton(label)
        b.setFixedHeight(30)
        b.setStyleSheet(
            f"background: rgba(8,18,44,0.6); border: 1px solid rgba(0,200,255,0.15); "
            f"color: {TEXT_MUTED}; padding: 4px 8px; font-size: 8px; font-weight: 600; letter-spacing: 0.5px;"
        )
        return b

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(2, 7, 18, 240))
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad.setColorAt(0.3, QColor(0, 240, 255, 60))
        grad.setColorAt(0.7, QColor(0, 240, 255, 60))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, w, 1, QBrush(grad))


# ============================================================================
# LEFT PANEL: 3D PLANETARY LAB + COMPACT LIVE OPTICAL HUD
# ============================================================================
class _LeftPanel(QWidget):
    """
    Left-side holographic lab containing:
    - Top: Interactive 3D Planetary Model (HolographicGlobeWidget)
    - Bottom: Compact Live Optical Sensor Viewport (WebcamHUDWidget)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # 1. 3D Holographic Planetary Lab
        self.globe_view = HolographicGlobeWidget(self)
        self.globe_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.globe_view, stretch=3)

        # 2. Compact Live Optical Sensor Viewport (kept small in bottom-left)
        optical_card = GlowCard("OPTICAL TRACKING SENSOR")
        op_layout = QVBoxLayout(optical_card)
        op_layout.setContentsMargins(4, 20, 4, 4)

        self.webcam_view = WebcamHUDWidget(optical_card)
        self.webcam_view.setMinimumHeight(180)
        self.webcam_view.setMaximumHeight(240)
        self.webcam_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        op_layout.addWidget(self.webcam_view)

        layout.addWidget(optical_card, stretch=2)


# ============================================================================
# RIGHT PANEL: SYSTEM TELEMETRY, AI ASSISTANT, ROBOTIC ARMOR, APP DOCK
# ============================================================================
class _RightPanel(QWidget):
    """
    Right-side modular panel containing:
    - AI Assistant & Robotic Armor Blueprint
    - Holographic Application Dock (2-column geometric tiles)
    - Audio & Hardware Telemetry (Volume LED meter, CPU, RAM)
    - Gesture Guide Reference Matrix
    - Monospace Event Stream Log
    """

    def __init__(self, launcher: AppLauncher, system_ctrl: SystemControls, on_launch_callback=None, parent=None):
        super().__init__(parent)
        self.launcher = launcher
        self.system_ctrl = system_ctrl
        self.on_launch_callback = on_launch_callback

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Sub-tab selector for upper right section
        self.tabs = QTabWidget(self)
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid rgba(0, 200, 255, 0.18); background: rgba(4, 10, 24, 0.7); }
            QTabBar::tab { background: rgba(8, 18, 42, 0.6); color: #6a90b8; padding: 4px 8px; font-size: 8px; font-weight: bold; border: 1px solid rgba(0, 200, 255, 0.12); }
            QTabBar::tab:selected { background: rgba(0, 100, 200, 0.35); color: #00f0ff; border-top: 1px solid #00f0ff; }
        """)

        # Tab 1: AI Assistant & Armor Telemetry
        ai_tab = QWidget()
        ai_layout = QVBoxLayout(ai_tab)
        ai_layout.setContentsMargins(2, 2, 2, 2)
        ai_layout.setSpacing(4)
        self.ai_view = AIAssistantWidget(ai_tab)
        self.armor_view = ArmorTelemetryWidget(ai_tab)
        ai_layout.addWidget(self.ai_view)
        ai_layout.addWidget(self.armor_view)
        self.tabs.addTab(ai_tab, "AI & ARMOR")

        # Tab 2: Application Dock (2-Column Grid)
        app_tab = QWidget()
        app_layout = QVBoxLayout(app_tab)
        app_layout.setContentsMargins(6, 6, 6, 6)
        self.app_grid_widget = QWidget()
        self.app_grid_layout = QGridLayout(self.app_grid_widget)
        self.app_grid_layout.setContentsMargins(0, 0, 0, 0)
        self.app_grid_layout.setSpacing(4)
        app_layout.addWidget(self.app_grid_widget)
        self.tabs.addTab(app_tab, "APPS")

        # Tab 3: Audio & System Telemetry
        telem_tab = QWidget()
        tl = QVBoxLayout(telem_tab)
        tl.setContentsMargins(8, 8, 8, 8)
        tl.setSpacing(4)

        # Audio subsystem
        vol_row = QHBoxLayout()
        self.lbl_vol = QLabel(f"VOLUME: {self.system_ctrl.get_volume()}%")
        self.lbl_vol.setStyleSheet(f"font-size: 9px; font-weight: 700; color: {ACCENT_CYAN};")
        vol_row.addWidget(self.lbl_vol)
        vol_row.addStretch()

        btn_style = (
            f"background: rgba(8,18,44,0.7); border: 1px solid rgba(0,200,255,0.2); "
            f"color: {ACCENT_ICY_BLUE}; font-size: 8px; font-weight: 700; padding: 2px 6px;"
        )
        self.btn_vdn = QPushButton("VOL -")
        self.btn_vup = QPushButton("VOL +")
        self.btn_mute = QPushButton("MUTE")
        for b in (self.btn_vdn, self.btn_vup, self.btn_mute):
            b.setStyleSheet(btn_style)
            b.setFixedHeight(20)
            vol_row.addWidget(b)
        tl.addLayout(vol_row)

        self.audio_meter = AudioLevelMeter()
        self.audio_meter.set_level(self.system_ctrl.get_volume())
        tl.addWidget(self.audio_meter)

        tl.addSpacing(6)

        # Telemetry metrics rows
        self._telem_rows = {}
        for key, lbl_text in [
            ("mouse_mode",  "MOUSE MODE"),
            ("cam_st",      "CAMERA SENSOR"),
            ("hand",        "TRACKING"),
            ("gesture",     "GESTURE"),
            ("move_st",     "MOUSE MOVE"),
            ("scroll_st",   "SCROLL STATUS"),
            ("click_st",    "CLICK STATE"),
            ("action",      "LAST ACTION"),
            ("input_api",   "INPUT API"),
            ("gate",        "SAFETY GATE"),
            ("coord",       "CURSOR"),
            ("sens",        "SENSITIVITY"),
            ("fine_ctrl",   "FINE CTRL"),
            ("stabilized",  "STABILIZED"),
            ("confidence",  "CONFIDENCE"),
            ("two_fg_st",   "TWO-FINGER ST"),
            ("idx_fg",      "INDEX FINGER"),
            ("mid_fg",      "MIDDLE FINGER"),
            ("ring_fg",     "RING FINGER"),
            ("pinky_fg",    "LITTLE FINGER"),
            ("cpu",         "CPU LOAD"),
            ("ram",         "MEMORY"),
        ]:
            row = QHBoxLayout()
            k_lbl = QLabel(lbl_text + ":")
            k_lbl.setStyleSheet(f"font-size: 8px; font-weight: 700; color: {TEXT_MUTED}; letter-spacing: 0.8px;")
            k_lbl.setFixedWidth(74)
            v_lbl = QLabel("--")
            v_lbl.setStyleSheet(f"font-family: Consolas; font-size: 8px; color: {ACCENT_CYAN};")
            row.addWidget(k_lbl)
            row.addWidget(v_lbl)
            row.addStretch()
            tl.addLayout(row)
            self._telem_rows[key] = v_lbl

        # Pinch proximity
        pinch_row = QHBoxLayout()
        pinch_lbl = QLabel("PINCH:")
        pinch_lbl.setStyleSheet(f"font-size: 8px; font-weight: 700; color: {TEXT_MUTED}; letter-spacing: 0.8px;")
        pinch_lbl.setFixedWidth(74)
        self.pinch_progress = QProgressBar()
        self.pinch_progress.setRange(0, 100)
        self.pinch_progress.setValue(0)
        self.pinch_progress.setFixedHeight(6)
        self.pinch_progress.setTextVisible(False)
        pinch_row.addWidget(pinch_lbl)
        pinch_row.addWidget(self.pinch_progress)
        tl.addLayout(pinch_row)

        self.tabs.addTab(telem_tab, "TELEMETRY")

        # Tab 4: Gesture Guide
        self.gesture_guide = GestureGuideWidget()
        self.tabs.addTab(self.gesture_guide, "GESTURES")

        # Tab 5: Dedicated Scroll Diagnostic & Calibration Overlay
        self.scroll_diag = ScrollDiagnosticWidget(controller=None, parent=self)
        self.tabs.addTab(self.scroll_diag, "SCROLL")

        layout.addWidget(self.tabs, stretch=3)

        # Bottom Event Stream Log
        log_card = GlowCard("EVENT STREAM")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(6, 22, 6, 6)
        self.terminal_view = TerminalLogView()
        self.terminal_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout.addWidget(self.terminal_view)
        layout.addWidget(log_card, stretch=2)

    def set_telemetry(self, key: str, text: str, color: str = ACCENT_CYAN):
        if key in self._telem_rows:
            lbl = self._telem_rows[key]
            if lbl.text() != text:
                lbl.setText(text)
            if getattr(lbl, "_cached_color", None) != color:
                lbl._cached_color = color
                lbl.setStyleSheet(f"font-family: Consolas; font-size: 8px; color: {color};")

    def populate_app_buttons(self):
        while self.app_grid_layout.count():
            item = self.app_grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        apps = self.launcher.get_enabled_apps()
        row, col = 0, 0
        for app in apps:
            name = app.get("name", "App")
            btn = QPushButton(name.upper())
            btn.setFixedHeight(30)
            btn.setProperty("class", "AppTile")
            btn.setStyleSheet(
                f"QPushButton {{ background: rgba(8,18,42,0.75); border: 1px solid rgba(0,200,255,0.18); "
                f"border-radius: 3px; color: {ACCENT_ICY_BLUE}; font-size: 8px; font-weight: 700; "
                f"letter-spacing: 0.5px; padding: 2px 4px; }}"
                f"QPushButton:hover {{ background: rgba(0,120,200,0.28); border: 1px solid {ACCENT_CYAN}; color:#fff; }}"
            )
            btn.clicked.connect(lambda _, a=app: self._trigger_app_launch(a))
            self.app_grid_layout.addWidget(btn, row, col)
            col += 1
            if col >= 2:
                col = 0
                row += 1

    def _trigger_app_launch(self, app_info: dict) -> None:
        name = app_info.get("name", "App")
        ok = self.launcher.launch_app(app_info)
        if self.on_launch_callback:
            self.on_launch_callback(name, ok)


# ============================================================================
# CENTRAL ZONE: HOLOGRAPHIC ENERGY REACTOR & KEYBOARD VIEWPORT
# ============================================================================
class _CenterZone(QWidget):
    """The central luminous cyan holographic energy core & holographic keyboard viewport."""

    def __init__(self, parent=None):
        super().__init__(parent)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.stack = QStackedWidget(self)

        # -------------------------------------------------------------
        # PAGE 0: Central Luminous Energy Reactor Core
        # -------------------------------------------------------------
        self.reactor_page = QWidget()
        layout = QVBoxLayout(self.reactor_page)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignHCenter)

        # Top Neural HUD Header
        top_hud = QHBoxLayout()
        top_hud.setContentsMargins(12, 0, 12, 0)
        self.lbl_neural_status = QLabel("NEURAL INTERFACE: OPTICAL SYNC ONLINE")
        self.lbl_neural_status.setStyleSheet(
            f"font-family: Consolas; font-size: 8px; font-weight: bold; color: {ACCENT_CYAN}; letter-spacing: 1.5px;"
        )
        self.lbl_neural_rate = QLabel("SYNC: 99.4%")
        self.lbl_neural_rate.setStyleSheet(
            f"font-family: Consolas; font-size: 8px; font-weight: bold; color: {ACCENT_GREEN}; letter-spacing: 1px;"
        )
        top_hud.addWidget(self.lbl_neural_status)
        top_hud.addStretch()
        top_hud.addWidget(self.lbl_neural_rate)
        layout.addLayout(top_hud)

        # Central luminous energy core (occupies prominent central area)
        self.nexus_core = NexusCoreWidget(self.reactor_page, size=320)
        self.nexus_core.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.nexus_core, stretch=4, alignment=Qt.AlignCenter)

        # State info box directly beneath the reactor
        info_box = QFrame()
        info_box.setStyleSheet("background: rgba(6,14,34,0.7); border-top: 1px solid rgba(0,200,255,0.12); border-radius: 4px;")
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(14, 6, 14, 6)
        info_layout.setSpacing(3)

        self.lbl_core_state = QLabel("CORE STATE: STANDBY")
        self.lbl_core_state.setAlignment(Qt.AlignCenter)
        self.lbl_core_state.setStyleSheet(
            f"font-family: Consolas; font-weight: 900; font-size: 11px; "
            f"color: {ACCENT_GOLD}; letter-spacing: 2px;"
        )
        info_layout.addWidget(self.lbl_core_state)

        self.lbl_mode = QLabel("MODE: MOUSE CONTROL")
        self.lbl_mode.setAlignment(Qt.AlignCenter)
        self.lbl_mode.setStyleSheet(
            f"font-size: 9px; font-weight: 700; color: {ACCENT_CYAN}; letter-spacing: 1.5px;"
        )
        info_layout.addWidget(self.lbl_mode)

        self.lbl_interlock = QLabel("SAFETY INTERLOCK: ARMED")
        self.lbl_interlock.setAlignment(Qt.AlignCenter)
        self.lbl_interlock.setStyleSheet(
            f"font-size: 8px; color: {ACCENT_GREEN}; letter-spacing: 1px;"
        )
        info_layout.addWidget(self.lbl_interlock)

        layout.addWidget(info_box, stretch=0)
        self.stack.addWidget(self.reactor_page)

        # -------------------------------------------------------------
        # PAGE 1: 3D Holographic Virtual Keyboard & Text Editor
        # -------------------------------------------------------------
        self.holo_keyboard = HolographicKeyboardWidget(self)
        self.stack.addWidget(self.holo_keyboard)

        main_layout.addWidget(self.stack)

    def show_keyboard(self) -> None:
        self.stack.setCurrentIndex(1)

    def show_reactor(self) -> None:
        self.stack.setCurrentIndex(0)

    def toggle_keyboard(self) -> bool:
        if self.stack.currentIndex() == 1:
            self.show_reactor()
            return False
        else:
            self.show_keyboard()
            return True


# ============================================================================
# NEXUS MAIN WINDOW
# ============================================================================
class NexusMainWindow(QMainWindow):
    """Cinematic N.E.X.U.S. holographic AI laboratory desktop command interface."""

    def __init__(self, settings_path: str = "config.json"):
        super().__init__()
        self.setWindowTitle("N.E.X.U.S. // GESTURE INTELLIGENCE SYSTEM")
        self.resize(1380, 880)
        self.setMinimumSize(1080, 720)

        self._last_fps_str = "0.0"
        self._auto_enabled = False
        self._prev_3d_x = 0.5
        self._prev_3d_y = 0.5

        # Backend engines
        self.settings = SettingsManager(settings_path)
        self.safety   = SafetyController()
        self.tracker  = HandTracker(
            detection_confidence=self.settings.get("tracking", "detection_confidence", default=0.7),
            tracking_confidence=self.settings.get("tracking", "tracking_confidence", default=0.7),
        )
        self.recognizer = GestureRecognizer(
            pinch_threshold=self.settings.get("mouse", "pinch_threshold", default=0.38),
            pinch_release_threshold=self.settings.get("mouse", "pinch_release_threshold", default=0.50),
            click_cooldown=self.settings.get("mouse", "click_cooldown", default=0.20),
            tracking_landmark=self.settings.get("mouse", "tracking_landmark", default="index_tip"),
            pinch_normalized=self.settings.get("mouse", "pinch_normalized", default=True),
            right_click_gesture=self.settings.get("mouse", "right_click_gesture", default="thumb_middle_pinch"),
        )
        self.mouse = VirtualMouse(
            sensitivity=self.settings.get("mouse", "sensitivity", default=1.2),
            sensitivity_x=self.settings.get("mouse", "sensitivity_x", default=1.2),
            sensitivity_y=self.settings.get("mouse", "sensitivity_y", default=1.2),
            fine_control_mode=self.settings.get("mouse", "fine_control_mode", default=True),
            fine_control_scale=self.settings.get("mouse", "fine_control_scale", default=0.40),
            smoothing=self.settings.get("mouse", "smoothing", default=0.65),
            smoothing_type=self.settings.get("mouse", "smoothing_type", default="one_euro"),
            one_euro_min_cutoff=self.settings.get("mouse", "one_euro_min_cutoff", default=1.0),
            one_euro_beta=self.settings.get("mouse", "one_euro_beta", default=0.02),
            deadzone_radius=self.settings.get("mouse", "deadzone_radius", default=8.0),
            active_margin_x=self.settings.get("mouse", "active_margin_x", default=0.16),
            active_margin_y=self.settings.get("mouse", "active_margin_y", default=0.16),
            roi_bounds=(
                self.settings.get("mouse", "roi_left",   default=0.16),
                self.settings.get("mouse", "roi_top",    default=0.16),
                self.settings.get("mouse", "roi_right",  default=0.84),
                self.settings.get("mouse", "roi_bottom", default=0.84),
            ),
            scroll_speed=self.settings.get("mouse", "scroll_speed", default=35.0),
            invert_x=self.settings.get("mouse", "invert_x", default=False),
            cursor_mode=self.settings.get("mouse", "cursor_mode", default="absolute"),
            relative_speed=self.settings.get("mouse", "relative_speed", default=4.0),
            relative_deadzone=self.settings.get("mouse", "relative_deadzone", default=0.03),
            click_stabilization=self.settings.get("mouse", "click_stabilization", default=True),
            click_stabilization_ms=self.settings.get("mouse", "click_stabilization_ms", default=160),
            pinch_threshold=self.settings.get("mouse", "pinch_threshold", default=0.28),
            pinch_release_threshold=self.settings.get("mouse", "pinch_release_threshold", default=0.40),
            click_cooldown=self.settings.get("mouse", "click_cooldown", default=0.20),
        )
        self.system_ctrl = SystemControls()
        self.launcher    = AppLauncher(self.settings.get("applications", default=[]))

        # Camera worker setup
        init_cam_idx = self.settings.get("camera", "index", default=0)
        try:
            from app.camera_device_utils import get_best_camera_index
            best_idx = get_best_camera_index(init_cam_idx)
            if best_idx != init_cam_idx:
                logger.info(f"Auto-selected accessible camera index {best_idx} (configured: {init_cam_idx}).")
                init_cam_idx = best_idx
                self.settings.set("camera", "index", best_idx)
                self.settings.save()
        except Exception:
            pass

        self.camera_worker = CameraWorker(
            camera_index=init_cam_idx,
            tracker=self.tracker,
            recognizer=self.recognizer,
            mouse=self.mouse,
            safety=self.safety,
            launcher=self.launcher,
            system_ctrl=self.system_ctrl,
            mirror=self.settings.get("camera", "mirror", default=True),
            show_hud=self.settings.get("interface", "show_hud_overlays", default=True),
            active_margins=(
                self.settings.get("mouse", "active_margin_x", default=0.16),
                self.settings.get("mouse", "active_margin_y", default=0.16),
            ),
        )
        self.voice_commander: Optional[VoiceCommander] = None
        if self.settings.get("voice", "enabled", default=False):
            self.voice_commander = VoiceCommander(self._handle_voice_command)

        # UI Stack setup
        self.setStyleSheet(NEXUS_STYLESHEET)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.startup_screen = NexusStartupScreen()
        self.startup_screen.initialization_completed.connect(self._on_startup_completed)
        self.stack.addWidget(self.startup_screen)

        self.dashboard = QWidget()
        self.dashboard.setStyleSheet("background-color: #020810;")
        self._build_dashboard(self.dashboard)
        self.stack.addWidget(self.dashboard)

        # Safety controller listeners
        self.safety.register_mode_listener(self._on_mode_changed)
        self.safety.register_enable_listener(self._on_enable_state_changed)
        self.safety.register_state_listener(self._on_state_changed)

        # Worker signal connections (strictly QueuedConnection for GUI thread safety)
        self.camera_worker.frame_ready.connect(self._on_frame_ready, Qt.ConnectionType.QueuedConnection)
        self.camera_worker.multi_hands_ready.connect(self._on_multi_hands_ready, Qt.ConnectionType.QueuedConnection)
        self.camera_worker.fps_measured.connect(self._on_fps_measured, Qt.ConnectionType.QueuedConnection)
        self.camera_worker.status_changed.connect(self._on_camera_status, Qt.ConnectionType.QueuedConnection)
        self.camera_worker.camera_error.connect(self._on_camera_error, Qt.ConnectionType.QueuedConnection)
        self.camera_worker.camera_permission_blocked.connect(self._on_camera_permission_blocked, Qt.ConnectionType.QueuedConnection)
        self.camera_worker.pipeline_updated.connect(self._on_pipeline_updated, Qt.ConnectionType.QueuedConnection)

        # Scroll telemetry and diagnostic connection
        self.sys_panel.scroll_diag.controller = self.camera_worker.scroll_controller
        self.camera_worker.scroll_telemetry_ready.connect(self.sys_panel.scroll_diag.update_telemetry, Qt.ConnectionType.QueuedConnection)

        # Emergency shortcuts
        self.emergency_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.emergency_shortcut.activated.connect(self._toggle_emergency_stop)
        QShortcut(QKeySequence(Qt.Key_Space), self).activated.connect(self._toggle_enable)
        QShortcut(QKeySequence("Ctrl+E"), self).activated.connect(self._toggle_enable)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._toggle_fine_control)
        QShortcut(QKeySequence(Qt.Key_F), self).activated.connect(self._toggle_fine_control)
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(self._recalibrate_hand_position)
        QShortcut(QKeySequence("Ctrl+K"), self).activated.connect(self._toggle_keyboard_mode)
        QShortcut(QKeySequence("Ctrl+M"), self).activated.connect(self._toggle_virtual_mouse)

        # Hardware Telemetry Timer (CPU & RAM via psutil)
        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.timeout.connect(self._update_hardware_telemetry)
        self.telemetry_timer.start(1500)

        # Thread-safe log dispatch
        bridge = get_log_bridge()
        if bridge is not None:
            bridge.log_signal.connect(self._on_log_message, Qt.QueuedConnection)
        else:
            register_log_listener(self._on_log_message)
        self.stack.setCurrentWidget(self.startup_screen)

    # -- Dashboard construction --
    def _build_dashboard(self, container: QWidget) -> None:
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top Header Bar
        self.header = _HeaderBar(container)
        self.header.btn_calibrate.clicked.connect(self._open_calibration)
        self.header.btn_sensor.clicked.connect(self._toggle_quick_camera)
        self.header.btn_config.clicked.connect(self._open_settings)
        self.header.btn_diag.clicked.connect(self._open_diagnostics)

        # Connect navigation tabs
        self.header.nav_buttons["VISION"].clicked.connect(lambda: self._select_nav("VISION"))
        self.header.nav_buttons["CONTROL"].clicked.connect(lambda: self._select_nav("CONTROL"))
        self.header.nav_buttons["AUTOMATION"].clicked.connect(lambda: self._select_nav("AUTOMATION"))
        self.header.nav_buttons["3D LAB"].clicked.connect(lambda: self._select_nav("3D LAB"))
        self.header.nav_buttons["PRESENTATION"].clicked.connect(lambda: self._select_nav("PRESENTATION"))
        self.header.nav_buttons["KEYBOARD"].clicked.connect(lambda: self._select_nav("KEYBOARD"))
        self.header.nav_buttons["AI ASSISTANT"].clicked.connect(lambda: self._select_nav("AI ASSISTANT"))
        self.header.nav_buttons["SYSTEM"].clicked.connect(lambda: self._select_nav("SYSTEM"))
        root.addWidget(self.header)

        # Main Workspace Area (3 Columns: Left Lab, Center Core, Right Panels)
        main_area = QWidget()
        main_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        area_layout = QHBoxLayout(main_area)
        area_layout.setContentsMargins(8, 6, 8, 4)
        area_layout.setSpacing(8)

        # COLUMN 1: LEFT HOLOGRAPHIC LAB (3D Globe + Compact Optical Viewport)
        self.left_panel = _LeftPanel(main_area)
        self.left_panel.setMinimumWidth(320)
        self.globe_view = self.left_panel.globe_view
        self.webcam_view = self.left_panel.webcam_view
        area_layout.addWidget(self.left_panel, stretch=3)

        # COLUMN 2: CENTER ZONE (Large Luminous Cyan Energy Reactor)
        self.center_zone = _CenterZone(main_area)
        self.center_zone.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.nexus_core = self.center_zone.nexus_core
        self.arc_reactor = self.nexus_core  # Compatibility alias
        self.holo_keyboard = self.center_zone.holo_keyboard
        self.holo_keyboard.closed.connect(lambda: self.safety.switch_mode(ControlMode.MOUSE))

        # Wire global keyboard overlay & configure external typing from settings
        try:
            from app.global_keyboard_overlay import GlobalKeyboardOverlay
            self.global_overlay = GlobalKeyboardOverlay(self.holo_keyboard, self)
            self.holo_keyboard.global_overlay = self.global_overlay
        except Exception as e:
            logger.warning(f"GlobalKeyboardOverlay initialization skipped: {e}")
            self.global_overlay = None

        # Wire settings manager to keyboard
        self.holo_keyboard.settings_manager = self.settings

        ext_typing = self.settings.get("air_typing", "external_typing", default=True)
        if ext_typing:
            self.holo_keyboard.external_typing_enabled = True
            self.holo_keyboard.global_typing_enabled = True
            self.holo_keyboard.test_mode = False

        typing_mode = self.settings.get("air_typing", "typing_mode", default="DWELL")
        dwell_dur = self.settings.get("air_typing", "dwell_duration", default=0.50)
        cooldown = self.settings.get("air_typing", "keypress_cooldown", default=0.20)
        jitter_tol = self.settings.get("air_typing", "dwell_jitter_tolerance", default=25.0)

        self.holo_keyboard.press_detection_mode = typing_mode
        self.holo_keyboard.hover_dwell_time = max(0.30, min(1.0, float(dwell_dur)))
        self.holo_keyboard.keypress_cooldown = max(0.05, min(1.0, float(cooldown)))
        self.holo_keyboard.dwell_jitter_tolerance = max(5.0, min(60.0, float(jitter_tol)))
        area_layout.addWidget(self.center_zone, stretch=4)

        # COLUMN 3: RIGHT PANEL (AI Assistant, Armor Blueprint, App Dock, Telemetry)
        self.sys_panel = _RightPanel(
            self.launcher,
            self.system_ctrl,
            on_launch_callback=self._on_app_launched_event,
            parent=main_area
        )
        self.sys_panel.setMinimumWidth(280)
        self.sys_panel.setMaximumWidth(360)
        self.sys_panel.btn_vdn.clicked.connect(self._on_vol_down)
        self.sys_panel.btn_vup.clicked.connect(self._on_vol_up)
        self.sys_panel.btn_mute.clicked.connect(self._on_toggle_mute)
        self.sys_panel.populate_app_buttons()

        self.terminal_view = self.sys_panel.terminal_view
        self.pinch_progress = self.sys_panel.pinch_progress
        area_layout.addWidget(self.sys_panel, stretch=3)

        root.addWidget(main_area, stretch=1)

        # Bottom Control Dock
        self.dock = _ControlDock(container)
        self.dock.btn_mouse.clicked.connect(lambda: self.safety.switch_mode(ControlMode.MOUSE))
        self.dock.btn_app.clicked.connect(lambda: self.safety.switch_mode(ControlMode.APP_LAUNCH))
        self.dock.btn_sys.clicked.connect(lambda: self.safety.switch_mode(ControlMode.SYSTEM_CONTROL))
        self.dock.btn_3d.clicked.connect(lambda: self.safety.switch_mode(ControlMode.LAB_3D))
        self.dock.btn_pres.clicked.connect(lambda: self.safety.switch_mode(ControlMode.PRESENTATION))
        self.dock.btn_keyboard.clicked.connect(lambda: self.safety.switch_mode(ControlMode.KEYBOARD))

        self.dock.btn_alttab.clicked.connect(self.system_ctrl.switch_window)
        self.dock.btn_minimize.clicked.connect(self.system_ctrl.minimize_active_window)
        self.dock.btn_desktop.clicked.connect(self.system_ctrl.show_desktop)
        self.dock.btn_files.clicked.connect(self.system_ctrl.open_file_explorer)
        self.dock.btn_fine_ctrl.clicked.connect(self._toggle_fine_control)
        self.dock.btn_recenter.clicked.connect(self._recalibrate_hand_position)
        self.dock.btn_settings.clicked.connect(self.system_ctrl.open_settings)
        self.dock.btn_calibrate.clicked.connect(self._open_calibration)
        self.dock.btn_reset_3d.clicked.connect(self.globe_view.reset_view)
        self.dock.btn_toggle_kb.clicked.connect(self._toggle_keyboard_mode)

        self.dock.btn_enable.clicked.connect(self._toggle_enable)
        self.dock.btn_pause.clicked.connect(self._toggle_pause)
        self.dock.btn_emergency.clicked.connect(self._toggle_emergency_stop)

        # Backward compatibility aliases for tests
        self.btn_enable = self.dock.btn_enable
        self.btn_pause  = self.dock.btn_pause
        self.btn_mode_mouse  = self.dock.btn_mouse
        self.btn_mode_app    = self.dock.btn_app
        self.btn_mode_system = self.dock.btn_sys
        self.btn_mode_pres   = self.dock.btn_pres
        self.btn_mode_keyboard = self.dock.btn_keyboard
        self.btn_switch_cam  = self.header.btn_sensor
        self.btn_diag        = self.header.btn_diag
        self.lbl_gate_status  = self.sys_panel._telem_rows["gate"]
        self.lbl_last_action  = self.sys_panel._telem_rows["action"]
        self.lbl_cursor_coords = self.sys_panel._telem_rows["coord"]
        self.lbl_hand_status  = self.sys_panel._telem_rows["hand"]
        self.lbl_gesture      = self.sys_panel._telem_rows["gesture"]
        self.lbl_fps_head     = QLabel()
        self.lbl_mode_head    = QLabel()

        root.addWidget(self.dock)

    def _select_nav(self, nav_name: str) -> None:
        """Handles header navigation tab selection."""
        for name, btn in self.header.nav_buttons.items():
            btn.setProperty("active", "true" if name == nav_name else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if nav_name == "3D LAB":
            self.safety.switch_mode(ControlMode.LAB_3D)
        elif nav_name == "CONTROL":
            self.safety.switch_mode(ControlMode.MOUSE)
        elif nav_name == "PRESENTATION":
            self.safety.switch_mode(ControlMode.PRESENTATION)
        elif nav_name == "KEYBOARD":
            self.safety.switch_mode(ControlMode.KEYBOARD)
        elif nav_name == "AUTOMATION":
            self.safety.switch_mode(ControlMode.APP_LAUNCH)
            self.sys_panel.tabs.setCurrentIndex(1)  # App tab
        elif nav_name == "AI ASSISTANT":
            self.sys_panel.tabs.setCurrentIndex(0)  # AI tab
        elif nav_name == "SYSTEM":
            self.safety.switch_mode(ControlMode.SYSTEM_CONTROL)
            self.sys_panel.tabs.setCurrentIndex(2)  # Telemetry tab

    def _toggle_keyboard_mode(self) -> None:
        if self.safety.current_mode in (ControlMode.KEYBOARD, ControlMode.HOLO_KEYBOARD):
            self.safety.switch_mode(ControlMode.MOUSE)
        else:
            self.safety.switch_mode(ControlMode.KEYBOARD)

    def _update_hardware_telemetry(self) -> None:
        """Polls real CPU and RAM telemetry via psutil and updates telemetry cards."""
        if PSUTIL_AVAILABLE:
            try:
                cpu = psutil.cpu_percent()
                ram = psutil.virtual_memory().percent
                self.sys_panel.set_telemetry("cpu", f"{cpu:.1f}%", ACCENT_CYAN if cpu < 80 else ACCENT_RED)
                self.sys_panel.set_telemetry("ram", f"{ram:.1f}%", ACCENT_CYAN if ram < 85 else ACCENT_GOLD)
            except Exception:
                pass

    def _on_app_launched_event(self, app_name: str, success: bool) -> None:
        """Invoked when an application is launched via the dock or gesture."""
        self.nexus_core.set_app_launch(app_name, success)
        status_msg = f"LAUNCH: {app_name}" if success else f"FAILED: {app_name}"
        self.sys_panel.set_telemetry("action", status_msg, ACCENT_GREEN if success else ACCENT_RED)
        self.sys_panel.ai_view.set_command(f"LAUNCH {app_name}", "Application execution acknowledged.")

    # -- Slots & Event Handlers --
    @Slot(QImage, object, object)
    def _on_frame_ready(self, image: QImage, hand: Optional[HandLandmarkData], state: GestureState) -> None:
        try:
            mode_name = self.safety.current_mode.value
            fps_str = getattr(self, "_last_fps_str", "0.0")
            fps_val = float(fps_str) if fps_str.replace(".", "", 1).isdigit() else 0.0
            self.webcam_view.update_frame(image, mode_name, state.gesture.value, fps_val)
            self._last_primary_hand = hand

            if hand:
                # AUTOMATIC HAND CONTROL ON STARTUP
                if not self._auto_enabled and self.safety.system_state == SystemState.DISABLED:
                    # Validate tracking region calibration
                    roi_valid = (self.mouse.roi_right > self.mouse.roi_left + 0.1) and (self.mouse.roi_bottom > self.mouse.roi_top + 0.1)
                    if not roi_valid:
                        self.header.set_control_state("CALIBRATION REQUIRED", ACCENT_GOLD)
                        logger.warning("[NEXUS] Tracking ROI invalid -- calibration required.")
                    else:
                        self.header.set_control_state("HAND DETECTED", ACCENT_ICY_BLUE)
                        self._auto_enabled = True
                        self.safety.enable_control()
                        self.safety.on_hand_detected()
                        self.header.set_control_state("GESTURE CONTROL ACTIVE", ACCENT_GREEN)
                        logger.info("[NEXUS] Hand detected and tracking region calibrated -- automatically engaged GESTURE CONTROL ACTIVE.")

                nx, ny = hand.get_tracking_point(self.recognizer.tracking_landmark)
                self.nexus_core.set_hand_presence(True, nx, ny, hand.handedness)
                self.sys_panel.set_telemetry("hand", f"HAND DETECTED ({hand.handedness.upper()})", ACCENT_GREEN)

                th = self.recognizer.pinch_threshold
                use_norm = self.recognizer.pinch_normalized or (th > 0.18)
                dist = hand.norm_pinch_distance if use_norm else hand.pinch_distance
                pct = max(0, min(100, int((1.0 - (dist / (max(0.01, th) * 1.8))) * 100)))
                self.pinch_progress.setValue(pct)

                # Reactor pulses on discrete clicks
                if state.gesture == GestureType.PINCH_LEFT_CLICK:
                    self.nexus_core.trigger_pulse(QColor(0, 240, 255))
                elif state.gesture == GestureType.PINCH_RIGHT_CLICK:
                    self.nexus_core.trigger_pulse(QColor(245, 158, 11))
                elif state.gesture == GestureType.TWO_FINGER_SCROLL:
                    self.nexus_core.trigger_pulse()

                self.nexus_core.set_gesture_telemetry(state.gesture.value, scroll_dy=state.scroll_dy)

                # Interactive 3D Lab gesture manipulation
                if self.safety.current_mode in (ControlMode.LAB_3D, ControlMode.HOLOGRAM_CONTROL, ControlMode.HOLOGRAM):
                    if state.cursor_coords:
                        cx, cy = state.cursor_coords
                        dx = cx - self._prev_3d_x
                        dy = cy - self._prev_3d_y
                        if abs(dx) > 0.002 or abs(dy) > 0.002:
                            self.globe_view.rotate_by(dx * 160.0, dy * 160.0)
                        self._prev_3d_x, self._prev_3d_y = cx, cy

                    if abs(state.scroll_dy) > 0.01:
                        self.globe_view.zoom_by(-state.scroll_dy * 1.5)

                    if state.gesture == GestureType.PINCH_LEFT_CLICK:
                        self.globe_view.toggle_select()
                    elif state.gesture == GestureType.SWIPE_RIGHT:
                        self.globe_view.next_scene()
                    elif state.gesture == GestureType.SWIPE_LEFT:
                        self.globe_view.prev_scene()
                    elif state.gesture == GestureType.INDEX_POINT:
                        self.globe_view.highlight_object(True)

                # (Air Typing is authoritatively handled in _on_multi_hands_ready to prevent dual-call conflicts)
            else:
                self.nexus_core.set_hand_presence(False)
                self.sys_panel.set_telemetry("hand", "TRACKING LOST", ACCENT_GOLD)
                if self.safety.system_state == SystemState.READY:
                    self.header.set_control_state("TRACKING LOST: AWAITING HAND", ACCENT_GOLD)
                self.pinch_progress.setValue(0)
                self.nexus_core.set_gesture_telemetry("NONE")

            self.sys_panel.set_telemetry("gesture", state.gesture.value)
            self.header.set_gesture_text(state.gesture.value)

            if state.cursor_coords:
                tx, ty = self.mouse.map_to_screen(state.cursor_coords[0], state.cursor_coords[1])
                self.sys_panel.set_telemetry("coord", f"X:{int(tx)} Y:{int(ty)}")
        except Exception as e:
            logger.debug(f"[FRAME ERROR] {e}")

    @Slot(list)
    def _on_multi_hands_ready(self, hands: list) -> None:
        """Dispatches multi-hand tracking landmarks to Two-Hand Air Typing engine."""
        try:
            # Forward telemetry from camera_worker to holographic keyboard HUD
            if hasattr(self, "camera_worker"):
                self.holo_keyboard.detected_hand_count = getattr(self.camera_worker, "detected_hand_count", len(hands))
                dh_st = getattr(self.camera_worker, "dual_hand_state", None)
                if dh_st is not None:
                    self.holo_keyboard.dual_hand_mode_state = dh_st.value if hasattr(dh_st, "value") else str(dh_st)
                self.holo_keyboard.mode_switch_countdown = getattr(self.camera_worker, "switching_countdown", 0.0)
                self.holo_keyboard.last_mode_transition_reason = getattr(self.camera_worker, "last_mode_transition_reason", "")

            is_kb_active = (
                self.safety.current_mode in (ControlMode.KEYBOARD, ControlMode.HOLO_KEYBOARD, ControlMode.AIR_TYPING) or
                getattr(self.safety, "is_global_keyboard", False) or
                (hasattr(self, "center_zone") and self.center_zone.stack.currentIndex() == 1)
            )
            if is_kb_active:
                self.holo_keyboard.process_multi_hands(hands)
                if hasattr(self, "global_overlay") and self.global_overlay and self.global_overlay.isVisible():
                    self.global_overlay.update()
        except Exception as e:
            logger.debug(f"[MULTI HAND ERROR] {e}")

    @Slot(object)
    def _on_pipeline_updated(self, status: ControlPipelineStatus) -> None:
        try:
            if status is None:
                return
            if status.action_permitted:
                self.sys_panel.set_telemetry("gate", "ENGAGED", ACCENT_GREEN)
            else:
                self.sys_panel.set_telemetry("gate", status.permission_reason[:20], ACCENT_GOLD)

            self.sys_panel.set_telemetry(
                "action",
                status.last_action[:24],
                ACCENT_CYAN if status.last_action_success else ACCENT_RED
            )
            if status.cursor_coords:
                cx, cy = status.cursor_coords
                self.sys_panel.set_telemetry("coord", f"X:{cx} Y:{cy}")
            if hasattr(status, "cursor_sensitivity"):
                fine_txt = " [FINE]" if getattr(status, "fine_control_mode", False) else ""
                self.sys_panel.set_telemetry("sens", f"{status.cursor_sensitivity:.2f}x{fine_txt}", ACCENT_CYAN if not getattr(status, "fine_control_mode", False) else ACCENT_GREEN)
            if hasattr(status, "fine_control_mode"):
                self.sys_panel.set_telemetry("fine_ctrl", "ON (0.40x)" if status.fine_control_mode else "OFF (1.00x)", ACCENT_GREEN if status.fine_control_mode else TEXT_MUTED)
            if hasattr(status, "click_state"):
                c_color = ACCENT_GREEN if "CONFIRMED" in status.click_state or "CLICK" in status.click_state else (ACCENT_GOLD if "LOCKED" in status.click_state or "CANDIDATE" in status.click_state else ACCENT_CYAN)
                self.sys_panel.set_telemetry("click_st", status.click_state, c_color)
            if hasattr(status, "is_cursor_stabilized"):
                stab_txt = "LOCKED" if status.is_cursor_stabilized else "FREE"
                self.sys_panel.set_telemetry("stabilized", stab_txt, ACCENT_GOLD if status.is_cursor_stabilized else ACCENT_CYAN)
            if hasattr(status, "tracking_confidence"):
                self.sys_panel.set_telemetry("confidence", f"{int(status.tracking_confidence * 100)}%", ACCENT_GREEN if status.tracking_confidence > 0.8 else ACCENT_GOLD)
            if hasattr(status, "index_finger_state"):
                c_idx = ACCENT_GREEN if status.index_finger_state == "EXTENDED" else TEXT_MUTED
                self.sys_panel.set_telemetry("idx_fg", status.index_finger_state, c_idx)
            if hasattr(status, "middle_finger_state"):
                c_mid = ACCENT_GREEN if status.middle_finger_state == "EXTENDED" else TEXT_MUTED
                self.sys_panel.set_telemetry("mid_fg", status.middle_finger_state, c_mid)
            if hasattr(status, "ring_finger_state"):
                c_ring = ACCENT_GREEN if status.ring_finger_state == "EXTENDED" else TEXT_MUTED
                self.sys_panel.set_telemetry("ring_fg", status.ring_finger_state, c_ring)
            if hasattr(status, "pinky_finger_state"):
                c_pinky = ACCENT_GREEN if status.pinky_finger_state == "EXTENDED" else TEXT_MUTED
                self.sys_panel.set_telemetry("pinky_fg", status.pinky_finger_state, c_pinky)
            if hasattr(status, "two_finger_status"):
                c_two = ACCENT_GREEN if status.two_finger_status == "STABLE" else (ACCENT_GOLD if status.two_finger_status == "EVALUATING" else TEXT_MUTED)
                self.sys_panel.set_telemetry("two_fg_st", status.two_finger_status, c_two)
            if hasattr(status, "input_api"):
                self.sys_panel.set_telemetry("input_api", status.input_api, ACCENT_GREEN)
            if hasattr(status, "mouse_control_mode"):
                mc_mode = status.mouse_control_mode
                if mc_mode == "AIR MOUSE ACTIVE":
                    mc_col = ACCENT_GREEN
                elif mc_mode == "PHYSICAL MOUSE ACTIVE":
                    mc_col = ACCENT_GOLD
                elif mc_mode == "MOUSE PAUSED":
                    mc_col = ACCENT_RED
                else:
                    mc_col = ACCENT_ICY_BLUE
                self.sys_panel.set_telemetry("mouse_mode", mc_mode, mc_col)
            if hasattr(status, "scroll_status"):
                sc_col = ACCENT_GREEN if status.scroll_status in ("UP", "DOWN") else TEXT_MUTED
                self.sys_panel.set_telemetry("scroll_st", status.scroll_status, sc_col)
            if hasattr(status, "mouse_movement_status"):
                mv_col = ACCENT_GREEN if status.mouse_movement_status == "ACTIVE" else (ACCENT_GOLD if status.mouse_movement_status == "LOCKED" else TEXT_MUTED)
                self.sys_panel.set_telemetry("move_st", status.mouse_movement_status, mv_col)
            if hasattr(status, "fps"):
                cam_txt = f"ONLINE ({status.fps:.1f} FPS)" if status.fps > 0 else "OFFLINE"
                cam_col = ACCENT_GREEN if status.fps > 5 else ACCENT_RED
                self.sys_panel.set_telemetry("cam_st", cam_txt, cam_col)
            if hasattr(status, "dual_hand_mode_state") and status.dual_hand_mode_state is not None:
                d_val = status.dual_hand_mode_state.value if hasattr(status.dual_hand_mode_state, "value") else str(status.dual_hand_mode_state)
                d_col = ACCENT_GREEN if d_val == "KEYBOARD_MODE" else (ACCENT_GOLD if d_val == "SWITCHING_TO_MOUSE" else ACCENT_CYAN)
                self.sys_panel.set_telemetry("dual_mode", d_val, d_col)
            if hasattr(status, "detected_hand_count"):
                self.sys_panel.set_telemetry("hands", f"{status.detected_hand_count} DETECTED")
            if status.last_action_error:
                logger.error(f"[PIPELINE] {status.last_action_error}")
        except Exception as e:
            logger.debug(f"[PIPELINE UPDATE ERROR] {e}")

    @Slot(float)
    def _on_fps_measured(self, fps: float) -> None:
        try:
            self._last_fps_str = f"{fps:.1f}"
            self.lbl_fps_head.setText(f"FPS: {fps:.1f}")
        except Exception:
            pass

    @Slot(str)
    def _on_camera_status(self, msg: str) -> None:
        try:
            logger.info(f"[CAMERA] {msg}")
            online = "ONLINE" in msg.upper() or "ACTIVE" in msg.upper()
            self.header.set_cam_state(online)
            idx = getattr(self.camera_worker, "camera_index", 0)
            self.header.btn_sensor.setText(f"SENSOR {idx}")
            if online:
                if self.safety.is_enabled and not self.safety.is_hand_present:
                    self.header.set_control_state("READY: AWAITING HAND", ACCENT_CYAN)
                    self.center_zone.lbl_core_state.setText("CORE STATE: READY")
                    self.center_zone.lbl_interlock.setText("SAFETY INTERLOCK: ARMED")
                    self.nexus_core.set_system_state("READY")
                elif not self._auto_enabled and self.safety.system_state == SystemState.DISABLED:
                    self.header.set_control_state("WAITING FOR HAND", ACCENT_GOLD)
                    self.center_zone.lbl_core_state.setText("CORE STATE: WAITING FOR HAND")
                    self.nexus_core.set_system_state("WAITING_FOR_HAND")
            else:
                self.header.set_control_state("CAMERA OFFLINE", ACCENT_RED)
                self.nexus_core.set_system_state("CAMERA_OFFLINE")
                self.center_zone.lbl_core_state.setText("CORE STATE: OFFLINE")
        except Exception as e:
            logger.debug(f"[CAM STATUS ERROR] {e}")

    def _toggle_quick_camera(self) -> None:
        new_idx = self.camera_worker.cycle_camera()
        self.settings.set("camera", "index", new_idx)
        self.settings.save()
        self.header.btn_sensor.setText(f"SENSOR {new_idx}")
        logger.info(f"[CAMERA] Switched to Camera Device {new_idx}.")

    @Slot(str)
    def _on_camera_error(self, err: str) -> None:
        logger.error(f"[CAMERA ERROR] {err}")
        self.header.set_cam_state(False)
        self.header.set_control_state("CAMERA ERROR", ACCENT_RED)
        self.nexus_core.set_system_state("CAMERA_OFFLINE")

    @Slot(str)
    def _on_camera_permission_blocked(self, err_msg: str) -> None:
        logger.warning(f"[CAMERA PRIVACY] {err_msg}")
        self.header.set_cam_state(False)
        self.header.set_control_state("CAMERA BLOCKED", ACCENT_RED)
        self.nexus_core.set_system_state("CAMERA_OFFLINE")

    def _open_camera_privacy(self) -> None:
        logger.info("[NEXUS] Opening Windows Camera Privacy Settings...")
        open_windows_camera_settings()

    @Slot(object)
    def _on_state_changed(self, state: SystemState) -> None:
        try:
            app = QCoreApplication.instance()
            if app is not None and QThread.currentThread() != self.thread():
                QTimer.singleShot(0, lambda: self._on_state_changed(state))
                return

            mode = self.safety.current_mode
            cz = self.center_zone
            if hasattr(self, "holo_keyboard"):
                # Only pause the holographic keyboard on deliberate pause or emergency stop
                self.holo_keyboard.keyboard_paused = (state in (SystemState.EMERGENCY_STOP, SystemState.PAUSED))

            if state == SystemState.EMERGENCY_STOP:
                self.header.set_control_state("EMERGENCY STOP (PAUSED)", ACCENT_RED)
                self.btn_enable.setText("RESUME")
                self.btn_enable.setStyleSheet(
                    f"background: rgba(4,30,20,0.75); border: 1px solid {ACCENT_GREEN}; color:{ACCENT_GREEN}; font-weight:800;")
                self.dock.btn_emergency.setText("RESUME [ESC]")
                cz.lbl_core_state.setText("CORE STATE: STOPPED")
                cz.lbl_core_state.setStyleSheet(
                    f"font-family:Consolas;font-weight:900;font-size:11px;color:{ACCENT_RED};letter-spacing:2px;")
                cz.lbl_interlock.setText("SAFETY INTERLOCK: STOPPED (PRESS ESC TO RESUME)")
                cz.lbl_interlock.setStyleSheet(f"font-size:8px;color:{ACCENT_RED};letter-spacing:1px;")
                self.nexus_core.set_system_state("EMERGENCY_STOP")

            elif state == SystemState.PAUSED:
                self.dock.btn_emergency.setText("EMERGENCY STOP [ESC]")
                self.header.set_control_state("PAUSED", ACCENT_ICY_BLUE)
                self.btn_pause.setText("RESUME")
                cz.lbl_core_state.setText("CORE STATE: PAUSED")
                cz.lbl_core_state.setStyleSheet(
                    f"font-family:Consolas;font-weight:900;font-size:11px;color:{ACCENT_ICY_BLUE};letter-spacing:2px;")
                self.nexus_core.set_system_state("PAUSED")

            elif state == SystemState.ACTIVE:
                self.dock.btn_emergency.setText("EMERGENCY STOP [ESC]")
                self.header.set_control_state("GESTURE CONTROL ACTIVE", ACCENT_GREEN)
                self.btn_enable.setText("DISABLE")
                self.btn_enable.setStyleSheet(
                    f"background: rgba(30,6,14,0.75); border: 1px solid {ACCENT_RED}; color:{ACCENT_RED}; font-weight:800;")
                self.btn_pause.setText("PAUSE")
                cz.lbl_core_state.setText("CORE STATE: ACTIVE")
                cz.lbl_core_state.setStyleSheet(
                    f"font-family:Consolas;font-weight:900;font-size:11px;color:{ACCENT_CYAN};letter-spacing:2px;")
                cz.lbl_interlock.setText("SAFETY INTERLOCK: ENGAGED")
                cz.lbl_interlock.setStyleSheet(f"font-size:8px;color:{ACCENT_GREEN};letter-spacing:1px;")
                self.nexus_core.set_system_state("ACTIVE")

            elif state == SystemState.READY:
                self.dock.btn_emergency.setText("EMERGENCY STOP [ESC]")
                self.header.set_control_state("READY: AWAITING HAND", ACCENT_CYAN)
                self.btn_enable.setText("DISABLE")
                self.btn_enable.setStyleSheet(
                    f"background: rgba(30,6,14,0.75); border: 1px solid {ACCENT_RED}; color:{ACCENT_RED}; font-weight:800;")
                self.btn_pause.setText("PAUSE")
                cz.lbl_core_state.setText("CORE STATE: READY")
                cz.lbl_core_state.setStyleSheet(
                    f"font-family:Consolas;font-weight:900;font-size:11px;color:{ACCENT_CYAN};letter-spacing:2px;")
                cz.lbl_interlock.setText("SAFETY INTERLOCK: ARMED")
                cz.lbl_interlock.setStyleSheet(f"font-size:8px;color:{ACCENT_GREEN};letter-spacing:1px;")
                self.nexus_core.set_system_state("READY")

            else:  # DISABLED
                self.dock.btn_emergency.setText("EMERGENCY STOP [ESC]")
                self.header.set_control_state("WAITING FOR HAND", TEXT_MUTED)
                self.btn_enable.setText("ENABLE CONTROL")
                self.btn_enable.setStyleSheet(
                    f"background: rgba(4,30,20,0.75); border: 1px solid {ACCENT_GREEN}; color:{ACCENT_GREEN}; font-weight:800;")
                self.btn_pause.setText("PAUSE")
                cz.lbl_core_state.setText("CORE STATE: STANDBY")
                cz.lbl_core_state.setStyleSheet(
                    f"font-family:Consolas;font-weight:900;font-size:11px;color:{ACCENT_GOLD};letter-spacing:2px;")
                cz.lbl_interlock.setText("SAFETY INTERLOCK: STANDBY")
                cz.lbl_interlock.setStyleSheet(f"font-size:8px;color:{ACCENT_GOLD};letter-spacing:1px;")
                self.nexus_core.set_system_state("STANDBY")
        except Exception as e:
            logger.error(f"[MAIN_WINDOW] Error in _on_state_changed: {e}")

    @Slot(object)
    def _on_mode_changed(self, mode: ControlMode) -> None:
        try:
            app = QCoreApplication.instance()
            if app is not None and QThread.currentThread() != self.thread():
                QTimer.singleShot(0, lambda: self._on_mode_changed(mode))
                return

            for btn, m in [(self.dock.btn_mouse, ControlMode.MOUSE),
                           (self.dock.btn_app,   ControlMode.APP_LAUNCH),
                           (self.dock.btn_sys,   ControlMode.SYSTEM_CONTROL),
                           (self.dock.btn_3d,    ControlMode.LAB_3D),
                           (self.dock.btn_pres,  ControlMode.PRESENTATION),
                           (self.dock.btn_keyboard, ControlMode.KEYBOARD)]:
                is_active = (mode == m) or (m == ControlMode.KEYBOARD and mode in (ControlMode.HOLO_KEYBOARD, ControlMode.AIR_TYPING))
                btn.setProperty("active", "true" if is_active else "false")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            self.center_zone.lbl_mode.setText(f"MODE: {mode.value.replace('_', ' ')}")
            if mode in (ControlMode.KEYBOARD, ControlMode.HOLO_KEYBOARD, ControlMode.AIR_TYPING):
                self.center_zone.show_keyboard()
                self.holo_keyboard.keyboard_paused = False
                self.holo_keyboard._recalculate_key_geometry()
                self.holo_keyboard.trigger_activation_animation()
                self.header.set_control_state("AIR TYPING ACTIVE", ACCENT_CYAN)
            else:
                self.center_zone.show_reactor()
                if hasattr(self, "global_overlay") and self.global_overlay:
                    self.global_overlay.hide()
                self.holo_keyboard.reset_all_fingers()
                if hasattr(self.holo_keyboard, "release_all_held_keys"):
                    self.holo_keyboard.release_all_held_keys()
        except Exception as e:
            logger.error(f"[MAIN_WINDOW] Error in _on_mode_changed: {e}")

    @Slot(bool)
    def _on_enable_state_changed(self, enabled: bool) -> None:
        try:
            app = QCoreApplication.instance()
            if app is not None and QThread.currentThread() != self.thread():
                QTimer.singleShot(0, lambda: self._on_enable_state_changed(enabled))
                return
            self._on_state_changed(self.safety.system_state)
        except Exception as e:
            logger.error(f"[MAIN_WINDOW] Error in _on_enable_state_changed: {e}")

    def _toggle_enable(self) -> None:
        if self.safety.system_state == SystemState.EMERGENCY_STOP:
            self.safety.reengage_from_emergency()
        elif self.safety.is_enabled:
            self._auto_enabled = False
            self.safety.disable_control()
        else:
            self._auto_enabled = True
            self.safety.enable_control()

    def _toggle_virtual_mouse(self) -> None:
        """Manually toggles virtual mouse cursor injection on/off."""
        if hasattr(self, "camera_worker"):
            curr = getattr(self.camera_worker, "virtual_mouse_enabled", True)
            self.camera_worker.virtual_mouse_enabled = not curr
            status_txt = "AIR MOUSE ENABLED" if not curr else "AIR MOUSE DISABLED (PHYSICAL ONLY)"
            col = ACCENT_GREEN if not curr else ACCENT_GOLD
            self.header.set_control_state(status_txt, col)
            logger.info(f"[AIR MOUSE TOGGLE] {status_txt}")

    def _toggle_pause(self) -> None:
        if self.safety.system_state == SystemState.PAUSED or getattr(self.safety, "_is_paused", False):
            self.safety.resume_control()
        else:
            self.safety.pause_control()

    def _toggle_emergency_stop(self) -> None:
        """Toggles manual emergency stop via Esc or GUI button with safe button cleanup."""
        if self.safety.system_state == SystemState.EMERGENCY_STOP:
            self.safety.reengage_from_emergency()
        else:
            self.safety.emergency_stop(source="MANUAL [ESC]")

    def _toggle_fine_control(self) -> None:
        """Toggles Fine Control precision mode (reduces cursor speed to 40% for accurate targeting)."""
        active = self.mouse.toggle_fine_control()
        self.settings.set("mouse", "fine_control_mode", active)
        self.settings.save()
        self.dock.btn_fine_ctrl.setStyleSheet(
            f"background: {'rgba(0,255,160,0.25)' if active else 'rgba(8,18,44,0.6)'}; "
            f"border: 1px solid {ACCENT_GREEN if active else 'rgba(0,200,255,0.15)'}; "
            f"color: {ACCENT_GREEN if active else TEXT_MUTED}; padding: 4px 8px; font-size: 8px; font-weight: 700;"
        )
        mode_txt = "FINE CONTROL ON (0.40x SPEED)" if active else "FINE CONTROL OFF (1.00x SPEED)"
        self.header.set_control_state(mode_txt, ACCENT_GREEN if active else ACCENT_CYAN)
        logger.info(f"[FINE CONTROL] Mode toggled: {mode_txt}")

    def _recalibrate_hand_position(self) -> None:
        """Re-centers cursor to screen center and centers active ROI around current hand position."""
        nx, ny = None, None
        if hasattr(self, "_last_primary_hand") and self._last_primary_hand:
            lm_idx = 8  # INDEX_TIP
            if hasattr(self._last_primary_hand, "landmarks_norm") and len(self._last_primary_hand.landmarks_norm) > lm_idx:
                nx = self._last_primary_hand.landmarks_norm[lm_idx][0]
                ny = self._last_primary_hand.landmarks_norm[lm_idx][1]
        self.mouse.recalibrate_position(nx, ny)
        self.header.set_control_state("HAND POSITION RECALIBRATED", ACCENT_GREEN)
        logger.info("[RECALIBRATE] Hand resting position recalibrated and cursor centered.")

    def _on_vol_up(self) -> None:
        v = self.system_ctrl.volume_up()
        self.sys_panel.lbl_vol.setText(f"VOLUME: {v}%")
        self.sys_panel.audio_meter.set_level(v)

    def _on_vol_down(self) -> None:
        v = self.system_ctrl.volume_down()
        self.sys_panel.lbl_vol.setText(f"VOLUME: {v}%")
        self.sys_panel.audio_meter.set_level(v)

    def _on_toggle_mute(self) -> None:
        muted = self.system_ctrl.toggle_mute()
        self.sys_panel.lbl_vol.setText("VOLUME: MUTED" if muted else f"VOLUME: {self.system_ctrl.get_volume()}%")

    @Slot(str, str)
    def _on_log_message(self, level: str, msg: str) -> None:
        if "CURSOR_MOVE_SENT" in msg:
            return  # High-frequency move events are logged to file/console, not flooded to GUI
        if hasattr(self, "terminal_view") and self.terminal_view is not None:
            try:
                self.terminal_view.append_log(level, msg)
            except Exception:
                pass

    def _handle_voice_command(self, cmd: str) -> None:
        logger.info(f"[VOICE] {cmd}")
        self.sys_panel.ai_view.set_command(cmd, "Command processed via neural pipeline.")
        dispatch = {
            "LAUNCH_CHROME":   lambda: self.launcher.launch_by_id("google_chrome"),
            "LAUNCH_VSCODE":   lambda: self.launcher.launch_by_id("visual_studio_code"),
            "LAUNCH_BLENDER":  lambda: self.launcher.launch_by_id("blender_3d"),
            "LAUNCH_GODOT":    lambda: self.launcher.launch_by_id("godot_engine"),
            "LAUNCH_NOTEPAD":  lambda: self.launcher.launch_by_id("notepad"),
            "LAUNCH_EXPLORER": lambda: self.launcher.launch_by_id("file_explorer"),
            "VOLUME_UP":       self._on_vol_up,
            "VOLUME_DOWN":     self._on_vol_down,
            "MUTE_AUDIO":      self._on_toggle_mute,
            "SWITCH_WINDOW":   self.system_ctrl.switch_window,
            "PAUSE_CONTROL":   self.safety.pause_control,
            "RESUME_CONTROL":  self.safety.resume_control,
            "EMERGENCY_STOP":  lambda: self.safety.emergency_stop(source="VOICE"),
        }
        if cmd in dispatch:
            dispatch[cmd]()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self.camera_worker, self)
        dlg.settings_applied.connect(self._apply_settings_updates)
        dlg.exec()

    def _open_calibration(self) -> None:
        wiz = NexusCalibrationWizard(self.settings, self.camera_worker, self)
        wiz.calibration_applied.connect(self._apply_settings_updates)
        wiz.exec()

    def _open_diagnostics(self) -> None:
        dlg = NexusDiagnosticsDialog(self.camera_worker, self.safety, self.mouse, self)
        dlg.exec()

    def _apply_settings_updates(self) -> None:
        logger.info("Applying updated settings to running systems...")
        cam_idx = self.settings.get("camera", "index", default=0)
        self.camera_worker.set_camera_index(cam_idx)
        self.header.btn_sensor.setText(f"SENSOR {cam_idx}")
        self.camera_worker.mirror   = self.settings.get("camera", "mirror", default=True)
        self.camera_worker.show_hud = self.settings.get("interface", "show_hud_overlays", default=True)
        self.camera_worker.auto_activate_duration = self.settings.get("air_typing", "auto_activate_duration", default=0.40)
        self.camera_worker.auto_exit_duration = self.settings.get("air_typing", "auto_exit_duration", default=0.80)

        sx = self.settings.get("mouse", "sensitivity_x", default=2.2)
        sy = self.settings.get("mouse", "sensitivity_y", default=2.2)
        self.mouse.sensitivity_x = sx
        self.mouse.sensitivity_y = sy
        self.mouse.sensitivity   = sx
        self.mouse.smoothing     = self.settings.get("mouse", "smoothing", default=0.65)
        self.mouse.smoothing_type = self.settings.get("mouse", "smoothing_type", default="one_euro")
        self.mouse.one_euro_min_cutoff = self.settings.get("mouse", "one_euro_min_cutoff", default=1.0)
        self.mouse.one_euro_beta = self.settings.get("mouse", "one_euro_beta", default=0.05)
        self.mouse.deadzone_radius = self.settings.get("mouse", "deadzone_radius", default=4.0)
        self.mouse.invert_x = self.settings.get("mouse", "invert_x", default=False)
        self.mouse.cursor_mode = self.settings.get("mouse", "cursor_mode", default="absolute")
        self.mouse.relative_speed = self.settings.get("mouse", "relative_speed", default=4.0)
        self.mouse.relative_deadzone = self.settings.get("mouse", "relative_deadzone", default=0.03)

        self.mouse.set_roi(
            self.settings.get("mouse", "roi_left",   default=0.16),
            self.settings.get("mouse", "roi_top",    default=0.16),
            self.settings.get("mouse", "roi_right",  default=0.84),
            self.settings.get("mouse", "roi_bottom", default=0.84),
        )
        self.recognizer.update_config(
            pinch_th=self.settings.get("mouse", "pinch_threshold", default=0.38),
            release_th=self.settings.get("mouse", "pinch_release_threshold", default=0.50),
            click_cd=self.settings.get("mouse", "click_cooldown", default=0.20),
            tracking_landmark=self.settings.get("mouse", "tracking_landmark", default="index_tip"),
            pinch_normalized=self.settings.get("mouse", "pinch_normalized", default=True),
            right_click_gesture=self.settings.get("mouse", "right_click_gesture", default="thumb_middle_pinch"),
        )
        anim = self.settings.get("interface", "enable_animations", default=True)
        self.nexus_core.set_animations_enabled(anim)

        # Apply Air Keyboard Settings
        if hasattr(self, "holo_keyboard") and self.holo_keyboard:
            self.holo_keyboard.press_detection_mode = self.settings.get("air_typing", "typing_mode", default="DWELL")
            self.holo_keyboard.hover_dwell_time = float(self.settings.get("air_typing", "dwell_duration", default=0.50))
            self.holo_keyboard.dwell_jitter_tolerance = float(self.settings.get("air_typing", "dwell_jitter_tolerance", default=25.0))
            self.holo_keyboard.keypress_cooldown = float(self.settings.get("air_typing", "keypress_cooldown", default=0.20))

        self.launcher.set_apps(self.settings.get("applications", default=[]))
        self.sys_panel.populate_app_buttons()

    def _on_startup_completed(self) -> None:
        logger.info("Startup sequence complete. Engaging N.E.X.U.S. Dashboard.")
        self.stack.setCurrentWidget(self.dashboard)
        self.header.set_control_state("READY: AWAITING HAND", ACCENT_CYAN)
        self.center_zone.lbl_core_state.setText("CORE STATE: READY")
        self.center_zone.lbl_interlock.setText("SAFETY INTERLOCK: ARMED")
        self.nexus_core.set_system_state("READY")
        self.camera_worker.start()
        if self.voice_commander and self.voice_commander.is_available:
            self.voice_commander.start()

    def closeEvent(self, event) -> None:
        logger.info("Shutdown signal received. Releasing resources...")
        bridge = get_log_bridge()
        if bridge is not None:
            try:
                bridge.log_signal.disconnect(self._on_log_message)
            except Exception:
                pass
        unregister_log_listener(self._on_log_message)
        if hasattr(self, "telemetry_timer"):
            self.telemetry_timer.stop()
        if self.voice_commander:
            self.voice_commander.stop()
        if self.camera_worker:
            self.camera_worker.stop()
        if self.tracker:
            self.tracker.close()
        logger.info("N.E.X.U.S. OS shutdown complete.")
        event.accept()


# Backwards compatibility alias
JarvisMainWindow = NexusMainWindow
