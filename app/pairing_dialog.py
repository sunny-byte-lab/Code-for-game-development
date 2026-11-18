"""N.E.X.U.S. Mobile Pairing & Remote Authentication Dialog.
Provides a secure HUD interface to display 6-digit pairing PIN,
server connection parameters, active device sessions, and remote killswitch.
"""

import time
import socket
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QMessageBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from app.theme import (
    BG_PANEL, BG_MIDNIGHT, ACCENT_CYAN, ACCENT_ICY_BLUE,
    ACCENT_GOLD, ACCENT_RED, TEXT_PRIMARY,
    TEXT_MUTED, NEXUS_STYLESHEET
)


def get_local_lan_ip() -> str:
    """Discovers primary local area network IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class NexusPairingDialog(QDialog):
    """Holographic dialog for pairing mobile companion devices to N.E.X.U.S."""

    def __init__(self, remote_server, parent=None):
        super().__init__(parent)
        self.server = remote_server
        self.setWindowTitle("N.E.X.U.S. // MOBILE REMOTE PAIRING")
        self.setFixedSize(540, 480)
        self.setStyleSheet(NEXUS_STYLESHEET)

        self._init_ui()

        # Refresh timer (1 Hz) for PIN expiration and connection status
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start(1000)

        # Ensure a PIN exists on dialog open
        if self.server:
            if not self.server.security.get_active_pin():
                self.server.security.generate_pairing_pin()
        self._refresh_status()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Header Title
        title_box = QVBoxLayout()
        lbl_head = QLabel("MOBILE DEVICE PAIRING PROTOCOL")
        lbl_head.setStyleSheet(f"font-size: 14px; font-weight: 900; letter-spacing: 2px; color: {ACCENT_CYAN};")
        lbl_sub = QLabel("AUTHENTICATED CROSS-PLATFORM CONTROL GATEWAY")
        lbl_sub.setStyleSheet(f"font-size: 8px; font-weight: 700; letter-spacing: 1.5px; color: {TEXT_MUTED};")
        title_box.addWidget(lbl_head)
        title_box.addWidget(lbl_sub)
        layout.addLayout(title_box)

        # Server Status Card
        card_server = QFrame()
        card_server.setStyleSheet(f"background: {BG_PANEL}; border: 1px solid rgba(0, 200, 255, 0.25); border-radius: 4px; padding: 10px;")
        card_layout = QVBoxLayout(card_server)
        card_layout.setSpacing(4)

        lan_ip = get_local_lan_ip()
        port = self.server.port if self.server else 8765
        is_running = self.server.is_running if self.server else False

        self.lbl_server_status = QLabel(
            f"SERVER STATUS: {'ONLINE (READY FOR CONNECTIONS)' if is_running else 'STANDBY / DISABLED'}"
        )
        self.lbl_server_status.setStyleSheet(f"font-size: 9px; font-weight: bold; color: {ACCENT_CYAN if is_running else ACCENT_GOLD};")
        card_layout.addWidget(self.lbl_server_status)

        self.lbl_endpoint = QLabel(f"HOST ENDPOINT:  {lan_ip} : {port}")
        self.lbl_endpoint.setStyleSheet(f"font-size: 10px; font-family: Consolas, monospace; color: {ACCENT_ICY_BLUE};")
        card_layout.addWidget(self.lbl_endpoint)

        layout.addWidget(card_server)

        # Big PIN Card
        card_pin = QFrame()
        card_pin.setStyleSheet(f"background: rgba(0, 30, 60, 0.6); border: 2px solid {ACCENT_CYAN}; border-radius: 6px; padding: 16px;")
        pin_layout = QVBoxLayout(card_pin)
        pin_layout.setAlignment(Qt.AlignCenter)
        pin_layout.setSpacing(8)

        lbl_pin_prompt = QLabel("ONE-TIME PAIRING PIN")
        lbl_pin_prompt.setStyleSheet(f"font-size: 9px; font-weight: bold; letter-spacing: 1.5px; color: {TEXT_MUTED};")
        lbl_pin_prompt.setAlignment(Qt.AlignCenter)
        pin_layout.addWidget(lbl_pin_prompt)

        self.lbl_pin = QLabel("------")
        self.lbl_pin.setStyleSheet(
            f"font-size: 38px; font-weight: 900; letter-spacing: 10px; color: #ffffff; "
            f"background: rgba(0, 15, 30, 0.8); border: 1px solid rgba(0, 200, 255, 0.4); "
            f"padding: 10px 24px; border-radius: 4px;"
        )
        self.lbl_pin.setAlignment(Qt.AlignCenter)
        pin_layout.addWidget(self.lbl_pin)

        self.lbl_countdown = QLabel("PIN expires in: -- s")
        self.lbl_countdown.setStyleSheet(f"font-size: 9px; color: {ACCENT_GOLD}; font-family: Consolas, monospace;")
        self.lbl_countdown.setAlignment(Qt.AlignCenter)
        pin_layout.addWidget(self.lbl_countdown)

        layout.addWidget(card_pin)

        # Instructions
        lbl_instruct = QLabel(
            "Instructions:\n"
            "1. Connect your Android or iOS device to the same Wi-Fi network.\n"
            "2. Open N.E.X.U.S. Companion and enter the 6-digit PIN above.\n"
            "3. Once paired, cryptographic tokens securely authenticate every command."
        )
        lbl_instruct.setStyleSheet(f"font-size: 9px; color: {TEXT_MUTED}; line-height: 140%;")
        layout.addWidget(lbl_instruct)

        # Active Session Count
        self.lbl_sessions = QLabel("CONNECTED SESSIONS: 0")
        self.lbl_sessions.setStyleSheet(f"font-size: 9px; font-weight: bold; color: {ACCENT_ICY_BLUE};")
        layout.addWidget(self.lbl_sessions)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_new_pin = QPushButton("🔑 GENERATE NEW PIN")
        self.btn_new_pin.setFixedHeight(32)
        self.btn_new_pin.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0, 140, 240, 0.2);
                border: 1px solid {ACCENT_CYAN};
                color: #ffffff;
                font-weight: bold;
                font-size: 9px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background: rgba(0, 180, 255, 0.4);
            }}
        """)
        self.btn_new_pin.clicked.connect(self._generate_new_pin)
        btn_layout.addWidget(self.btn_new_pin)

        self.btn_killswitch = QPushButton("⚡ DISCONNECT ALL (KILLSWITCH)")
        self.btn_killswitch.setFixedHeight(32)
        self.btn_killswitch.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 60, 60, 0.15);
                border: 1px solid {ACCENT_RED};
                color: #ff9999;
                font-weight: bold;
                font-size: 9px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background: rgba(255, 60, 60, 0.35);
                color: #ffffff;
            }}
        """)
        self.btn_killswitch.clicked.connect(self._disconnect_all_devices)
        btn_layout.addWidget(self.btn_killswitch)

        btn_close = QPushButton("CLOSE")
        btn_close.setFixedHeight(32)
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

    def _generate_new_pin(self) -> None:
        if self.server:
            new_pin = self.server.security.generate_pairing_pin()
            self._refresh_status()

    def _disconnect_all_devices(self) -> None:
        if self.server:
            self.server.security.revoke_all_sessions()
            self._refresh_status()
            QMessageBox.information(
                self, "Sessions Terminated",
                "All authenticated mobile sessions have been revoked.\nAny connected devices must re-pair to send commands."
            )

    def _refresh_status(self) -> None:
        if not self.server:
            self.lbl_pin.setText("OFFLINE")
            self.lbl_countdown.setText("Protocol Server not active")
            self.lbl_sessions.setText("CONNECTED SESSIONS: 0")
            return

        active_pin = self.server.security.get_active_pin()
        if active_pin:
            formatted_pin = f"{active_pin[:3]} {active_pin[3:]}"
            self.lbl_pin.setText(formatted_pin)
            rem = max(0, int(self.server.security._pin_expires_at - time.time()))
            self.lbl_countdown.setText(f"PIN expires in: {rem} seconds")
            self.lbl_countdown.setStyleSheet(f"font-size: 9px; color: {ACCENT_CYAN if rem > 30 else ACCENT_RED}; font-family: Consolas, monospace;")
        else:
            self.lbl_pin.setText("EXPIRED")
            self.lbl_countdown.setText("PIN Expired - Click 'Generate New PIN'")
            self.lbl_countdown.setStyleSheet(f"font-size: 9px; color: {ACCENT_RED}; font-family: Consolas, monospace;")

        count = self.server.security.active_session_count
        self.lbl_sessions.setText(f"CONNECTED SESSIONS: {count}")
        if count > 0:
            self.lbl_sessions.setStyleSheet(f"font-size: 9px; font-weight: bold; color: {ACCENT_CYAN};")
        else:
            self.lbl_sessions.setStyleSheet(f"font-size: 9px; font-weight: bold; color: {TEXT_MUTED};")
