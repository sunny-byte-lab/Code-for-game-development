"""N.E.X.U.S. - Neural Experience & Unified System.
Main Application Entry Point.
"""

import os
import sys
import tempfile
import logging
import warnings
import io

# 1. Guarantee valid streams in windowed/frozen GUI mode on Windows
class _SafeNullStream:
    def write(self, s): pass
    def flush(self): pass
    def isatty(self): return False

if sys.stdout is None:
    sys.stdout = _SafeNullStream()
if sys.stderr is None:
    sys.stderr = _SafeNullStream()

# Enable crash fault handler only when a valid system stream/fileno exists
try:
    import faulthandler
    if hasattr(sys.stderr, "fileno"):
        faulthandler.enable()
except Exception:
    pass

# Suppress Protobuf deprecation warning from MediaPipe
warnings.filterwarnings("ignore", category=UserWarning, module="google.protobuf")

# Ensure cache directories are writable to prevent permission warnings
os.environ["MPLCONFIGDIR"] = os.path.join(tempfile.gettempdir(), "nexus_mpl")
# Suppress noisy OpenCV backend probe warnings in console
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
# Suppress TensorFlow Lite / absl C++ logs
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("GLOG_minloglevel", "3")
os.environ.setdefault("ABSL_LOG_LEVEL", "3")
# Suppress Qt 6 Windows SetProcessDpiAwarenessContext warning
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false;qt.qpa.*=false;*.debug=false")
os.environ.setdefault("QT_WIN_WINDOWS_ARGUMENTS", "dpiawareness=0")

# Add current workspace directory to sys.path
_workspace_dir = os.path.dirname(os.path.abspath(__file__))
if _workspace_dir not in sys.path:
    sys.path.insert(0, _workspace_dir)

# Automatic Python Environment Resolver (Only in source mode, never in frozen .exe):
if not getattr(sys, "frozen", False):
    _venv_python = os.path.join(_workspace_dir, ".venv", "Scripts", "python.exe")
    if os.path.isfile(_venv_python):
        try:
            _curr_exe = os.path.abspath(sys.executable).lower()
            _target_exe = os.path.abspath(_venv_python).lower()
            if _curr_exe != _target_exe:
                import subprocess
                main_script = os.path.join(_workspace_dir, "main.py")
                _clean_env = os.environ.copy()
                sys.exit(subprocess.call([_venv_python, main_script] + sys.argv[1:], cwd=_workspace_dir, env=_clean_env))
        except Exception:
            pass

# Initialize Qt and PySide6 Environment FIRST before importing Qt widgets
from app import qt_bootstrap
qt_bootstrap.setup_qt_environment()

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, qInstallMessageHandler
from app.logger import setup_logger
from app.main_window import NexusMainWindow, JarvisMainWindow

main_window = None


def qt_message_handler(mode, context, message):
    """Logs internal Qt C++ engine events."""
    msg_str = str(message)
    if any(k in msg_str.lower() for k in ("error", "critical", "fatal", "warning")):
        logging.getLogger("NEXUS.Qt").warning(f"[Qt Engine] {msg_str}")


def main() -> int:
    """Initializes and runs the N.E.X.U.S. desktop environment."""
    global main_window
    logger = setup_logger("nexus.log", logging.INFO)
    logger.info("Initializing N.E.X.U.S. // GESTURE INTELLIGENCE SYSTEM...")

    # Global unhandled exception handler
    def excepthook(exc_type, exc_val, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_val, exc_tb)
            return
        logger.critical("Uncaught top-level exception in application loop:", exc_info=(exc_type, exc_val, exc_tb))

    sys.excepthook = excepthook
    qInstallMessageHandler(qt_message_handler)

    # Enable High-DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("N.E.X.U.S. Gesture OS")
    app.setOrganizationName("NexusIntelligence")

    try:
        main_window = NexusMainWindow("config.json")
        main_window.show()
        logger.info("N.E.X.U.S. Main Window displayed successfully.")
        ret = app.exec()
        logger.info(f"N.E.X.U.S. Application Event Loop exited cleanly with code {ret}.")
        return ret
    except Exception as e:
        logger.critical(f"Unhandled exception during execution: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
