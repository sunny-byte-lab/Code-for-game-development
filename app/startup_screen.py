"""N.E.X.U.S. Startup Screen and Boot Sequence Animation.
Renders initialization diagnostics, N.E.X.U.S. core spin-up, and smooth transition into main dashboard.
"""

from typing import Optional
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QColor, QRadialGradient
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QProgressBar, QPushButton, QHBoxLayout
)
from app.hud_widgets import NexusCoreWidget
from app.theme import (
    ACCENT_CYAN, ACCENT_ICY_BLUE, TEXT_PRIMARY, TEXT_MUTED
)


class NexusStartupScreen(QWidget):
    """Futuristic N.E.X.U.S. boot screen with diagnostic readout and Energy Core spin-up."""

    initialization_completed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("StartupScreen")

        self.progress_value = 0
        self.diagnostic_steps = [
            "INITIALIZING NEXUS SYSTEM...",
            "VERIFYING NEURAL COMPUTATION ENGINE...",
            "CALIBRATING OPTICAL VISION SENSORS...",
            "LOADING HIGH-FIDELITY HAND LANDMARK GRAPHS...",
            "INITIALIZING VIRTUAL MOUSE & INPUT MAPPINGS...",
            "SYNCHRONIZING AUDIO ENGINE & SYSTEM CONTROL...",
            "ENGAGING REAL-TIME SAFETY INTERLOCKS...",
            "ALL SYSTEMS READY"
        ]
        self.current_step_idx = 0

        self._init_ui()

        # Step timer for animated boot sequence
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_boot_step)
        self.timer.start(45)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(16)

        # Header Title
        title_label = QLabel("N.E.X.U.S.")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            f"font-size: 40px; font-weight: 900; letter-spacing: 10px; color: {ACCENT_CYAN}; margin-top: 10px;"
        )
        layout.addWidget(title_label)

        full_name_label = QLabel("NEURAL EXPERIENCE & UNIFIED SYSTEM")
        full_name_label.setAlignment(Qt.AlignCenter)
        full_name_label.setStyleSheet(
            f"font-size: 11px; font-weight: 700; letter-spacing: 3.5px; color: {ACCENT_ICY_BLUE};"
        )
        layout.addWidget(full_name_label)

        tagline_label = QLabel("Beyond Touch. Beyond Limits.")
        tagline_label.setAlignment(Qt.AlignCenter)
        tagline_label.setStyleSheet(
            f"font-size: 12px; font-style: italic; letter-spacing: 2px; color: {TEXT_MUTED}; margin-bottom: 8px;"
        )
        layout.addWidget(tagline_label)

        # Center N.E.X.U.S. Core element
        hud_container = QHBoxLayout()
        hud_container.setAlignment(Qt.AlignCenter)
        self.reactor = NexusCoreWidget(self, size=190)
        hud_container.addWidget(self.reactor)
        layout.addLayout(hud_container)

        # Diagnostic Status Readout
        self.status_label = QLabel(self.diagnostic_steps[0])
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet(
            f"font-family: Consolas, monospace; font-size: 11px; font-weight: bold; color: {ACCENT_CYAN}; letter-spacing: 1.5px;"
        )
        layout.addWidget(self.status_label)

        # High-tech progress bar
        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(0)
        self.prog_bar.setFixedHeight(6)
        self.prog_bar.setFixedWidth(380)
        self.prog_bar.setTextVisible(False)
        self.prog_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: #08162e;
                border: 1px solid #143560;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {ACCENT_CYAN};
                border-radius: 2px;
            }}
        """)
        layout.addWidget(self.prog_bar, alignment=Qt.AlignCenter)

        # Fast Skip Button
        self.skip_btn = QPushButton("INITIALIZE NOW")
        self.skip_btn.setFixedWidth(160)
        self.skip_btn.clicked.connect(self._finish_initialization)
        layout.addWidget(self.skip_btn, alignment=Qt.AlignCenter)

    def _on_boot_step(self) -> None:
        self.progress_value += 2
        self.prog_bar.setValue(self.progress_value)

        # Update diagnostic text according to progress
        step = int((self.progress_value / 100.0) * len(self.diagnostic_steps))
        if step < len(self.diagnostic_steps) and step != self.current_step_idx:
            self.current_step_idx = step
            self.status_label.setText(self.diagnostic_steps[step])

        if self.progress_value >= 100:
            self.timer.stop()
            self.status_label.setText("ALL SYSTEMS READY")
            QTimer.singleShot(350, self._finish_initialization)

    def _finish_initialization(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
        self.initialization_completed.emit()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Deep space dark background
        painter.fillRect(self.rect(), QColor(3, 7, 18))

        # Ambient radial background glow behind reactor
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        glow = QRadialGradient(cx, cy, 320)
        glow.setColorAt(0.0, QColor(0, 240, 255, 35))
        glow.setColorAt(0.5, QColor(0, 90, 180, 15))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), glow)


# Backwards compatibility alias
JarvisStartupScreen = NexusStartupScreen
