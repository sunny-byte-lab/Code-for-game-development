"""N.E.X.U.S. Design Theme & Stylesheets.
Cinematic deep-space holographic palette.
"""

# Core Colour Palette
BG_BLACK          = "#020810"
BG_MIDNIGHT       = "#050d1e"
BG_DARK_NAVY      = "#081428"
BG_PANEL          = "#0a1830"
BG_PANEL_TRANSLUCENT = "rgba(8, 18, 40, 0.82)"
BG_PANEL_GLOW     = "rgba(0, 240, 255, 0.03)"

BORDER_CYAN       = "#00f0ff"
BORDER_BLUE       = "#0077ee"
BORDER_DARK       = "#102040"
BORDER_SUBTLE     = "#0e1e38"

ACCENT_CYAN       = "#00f0ff"
ACCENT_ICY_BLUE   = "#38bdf8"
ACCENT_BLUE       = "#0077ee"
ACCENT_GOLD       = "#f59e0b"
ACCENT_GREEN      = "#10b981"
ACCENT_RED        = "#ef4444"

TEXT_PRIMARY      = "#f0f8ff"
TEXT_MUTED        = "#6a90b8"
TEXT_CYAN         = "#00f0ff"
TEXT_ICY          = "#bae6fd"

# Master QSS Stylesheet
NEXUS_STYLESHEET = f"""
QMainWindow {{
    background-color: {BG_BLACK};
}}

QWidget {{
    font-family: 'Segoe UI', 'Consolas', 'Arial', sans-serif;
    color: {TEXT_PRIMARY};
    background-color: transparent;
}}

/* Header / Footer Bars */
QFrame#HeaderBar {{
    background-color: rgba(5, 12, 28, 0.96);
    border-bottom: 1px solid rgba(0, 240, 255, 0.18);
}}
QFrame#FooterBar {{
    background-color: rgba(3, 8, 20, 0.98);
    border-top: 1px solid rgba(0, 240, 255, 0.14);
}}

/* Generic GlowCard */
QFrame#GlowCard {{
    background-color: rgba(8, 18, 40, 0.55);
    border: none;
}}

/* Buttons: default */
QPushButton {{
    background-color: rgba(10, 22, 52, 0.7);
    color: {TEXT_ICY};
    border: 1px solid rgba(0, 200, 255, 0.22);
    border-radius: 3px;
    padding: 5px 12px;
    font-weight: 600;
    font-size: 10px;
    letter-spacing: 0.8px;
}}
QPushButton:hover {{
    background-color: rgba(0, 130, 220, 0.22);
    border: 1px solid {ACCENT_CYAN};
    color: #ffffff;
}}
QPushButton:pressed {{
    background-color: rgba(0, 200, 255, 0.25);
}}

/* Mode Buttons */
QPushButton.ModeBtn {{
    background-color: rgba(8, 16, 38, 0.6);
    border: 1px solid rgba(0, 150, 200, 0.2);
    color: {TEXT_MUTED};
    padding: 6px 14px;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1px;
    border-radius: 2px;
}}
QPushButton.ModeBtn:checked, QPushButton.ModeBtn[active="true"] {{
    background-color: rgba(0, 100, 200, 0.28);
    border: 1px solid {ACCENT_CYAN};
    color: #ffffff;
}}

/* Enable / Disable Control */
QPushButton#EnableBtn {{
    background-color: rgba(4, 30, 20, 0.75);
    border: 1px solid {ACCENT_GREEN};
    color: {ACCENT_GREEN};
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 1px;
}}
QPushButton#EnableBtn:hover {{
    background-color: rgba(10, 60, 40, 0.9);
    color: #ffffff;
    border-color: #34d399;
}}

/* Emergency Stop */
QPushButton#EmergencyBtn {{
    background-color: rgba(40, 6, 16, 0.85);
    border: 1px solid {ACCENT_RED};
    color: {ACCENT_RED};
    font-weight: 900;
    font-size: 10px;
    letter-spacing: 1px;
}}
QPushButton#EmergencyBtn:hover {{
    background-color: {ACCENT_RED};
    color: #ffffff;
}}

/* App Launcher Geometric Tiles */
QPushButton.AppTile {{
    background-color: rgba(8, 18, 42, 0.75);
    border: 1px solid rgba(0, 200, 255, 0.18);
    border-radius: 3px;
    color: {ACCENT_ICY_BLUE};
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 0.6px;
    padding: 4px;
}}
QPushButton.AppTile:hover {{
    background-color: rgba(0, 120, 200, 0.28);
    border: 1px solid {ACCENT_CYAN};
    color: #ffffff;
}}
QPushButton.AppTile[selected="true"] {{
    background-color: rgba(0, 140, 220, 0.35);
    border: 1px solid {ACCENT_CYAN};
    color: #ffffff;
}}

/* Labels */
QLabel.TechHeader {{
    color: {ACCENT_CYAN};
    font-weight: 800;
    font-size: 10px;
    letter-spacing: 2px;
}}
QLabel.MetricValue {{
    color: #ffffff;
    font-weight: 700;
    font-size: 13px;
}}
QLabel.MetricLabel {{
    color: {TEXT_MUTED};
    font-size: 8px;
    letter-spacing: 1.2px;
}}
QLabel.StatusPill {{
    background-color: rgba(0, 60, 100, 0.5);
    border: 1px solid rgba(0, 200, 255, 0.3);
    border-radius: 8px;
    color: {ACCENT_CYAN};
    font-size: 9px;
    font-weight: 700;
    padding: 2px 8px;
    letter-spacing: 0.5px;
}}

/* Terminal Log */
QTextEdit#TerminalLog {{
    background-color: rgba(2, 6, 18, 0.95);
    color: {TEXT_CYAN};
    font-family: Consolas, 'Courier New', monospace;
    font-size: 9px;
    border: none;
    border-top: 1px solid rgba(0, 200, 255, 0.12);
}}

/* Sliders */
QSlider::groove:horizontal {{
    height: 3px;
    background: #0f1e3a;
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT_CYAN};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: #ffffff;
    border: 1px solid {ACCENT_BLUE};
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
}}

/* Scrollbar */
QScrollBar:vertical {{
    border: none;
    background: transparent;
    width: 4px;
}}
QScrollBar::handle:vertical {{
    background: rgba(0, 200, 255, 0.25);
    min-height: 20px;
    border-radius: 2px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QScrollBar:horizontal {{
    border: none;
    background: transparent;
    height: 4px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(0, 200, 255, 0.25);
    min-width: 20px;
    border-radius: 2px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* Progress Bar */
QProgressBar {{
    background-color: #08162c;
    border: 1px solid #143060;
    border-radius: 2px;
}}
QProgressBar::chunk {{
    background-color: {ACCENT_CYAN};
    border-radius: 1px;
}}

/* Combo Box */
QComboBox {{
    background-color: rgba(8, 18, 42, 0.8);
    color: {TEXT_PRIMARY};
    border: 1px solid rgba(0, 200, 255, 0.25);
    border-radius: 3px;
    padding: 4px 8px;
    font-size: 10px;
}}
QComboBox:hover {{ border: 1px solid {ACCENT_CYAN}; }}
QComboBox QAbstractItemView {{
    background-color: {BG_DARK_NAVY};
    color: {TEXT_PRIMARY};
    selection-background-color: rgba(0, 100, 200, 0.4);
    border: 1px solid {BORDER_CYAN};
}}

/* Tab Widget */
QTabWidget::pane {{
    border: 1px solid {BORDER_DARK};
    background-color: {BG_PANEL};
}}
QTabBar::tab {{
    background-color: rgba(6, 14, 30, 0.8);
    color: {TEXT_MUTED};
    border: 1px solid {BORDER_DARK};
    border-bottom: none;
    padding: 6px 16px;
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 0.8px;
}}
QTabBar::tab:selected {{
    background-color: {BG_PANEL};
    color: {ACCENT_CYAN};
    border-top: 1px solid {ACCENT_CYAN};
}}

/* QDialog */
QDialog {{
    background-color: {BG_MIDNIGHT};
    color: {TEXT_PRIMARY};
}}
"""

# Backwards compatibility alias
JARVIS_STYLESHEET = NEXUS_STYLESHEET
