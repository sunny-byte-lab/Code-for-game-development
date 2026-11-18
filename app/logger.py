"""N.E.X.U.S. System Logging Module.
Provides centralized logging to console, local log file, and GUI listeners.
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from typing import Callable, List, Optional

# Qt Bridge for thread-safe GUI log signal dispatch (lazily instantiated when QApplication exists)
_log_bridge = None


def get_log_bridge():
    """Returns or creates the thread-safe Qt LogBridge object attached to QApplication."""
    global _log_bridge
    if _log_bridge is None:
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import QObject, Signal
            if QApplication.instance() is None:
                return None
            class _LogBridge(QObject):
                log_signal = Signal(str, str)
            _log_bridge = _LogBridge()
        except Exception:
            _log_bridge = None
    return _log_bridge


class _LogBridgeProxy:
    """Proxy object allowing module-level 'log_bridge' access without creating QObject before QApplication."""
    def __getattr__(self, name):
        bridge = get_log_bridge()
        if bridge is not None:
            return getattr(bridge, name)
        return None


log_bridge = _LogBridgeProxy()

# In-memory listeners for live GUI streaming
_gui_log_listeners: List[Callable[[str, str], None]] = []

class NexusLogHandler(logging.Handler):
    """Custom logging handler to broadcast records to UI listeners."""
    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            level = record.levelname

            # 1. Thread-safe Qt signal emission across worker thread boundaries
            bridge = get_log_bridge()
            if bridge is not None:
                try:
                    bridge.log_signal.emit(level, msg)
                except Exception:
                    pass

            # 2. Legacy direct listeners (for synchronous testing)
            for listener in list(_gui_log_listeners):
                try:
                    listener(level, msg)
                except Exception:
                    pass
        except Exception:
            self.handleError(record)

JarvisLogHandler = NexusLogHandler

def register_log_listener(callback: Callable[[str, str], None]) -> None:
    """Register a callback (level, message) -> None to receive log messages."""
    if callback not in _gui_log_listeners:
        _gui_log_listeners.append(callback)

def unregister_log_listener(callback: Callable[[str, str], None]) -> None:
    """Unregister a log listener."""
    if callback in _gui_log_listeners:
        _gui_log_listeners.remove(callback)

def setup_logger(log_file: str = "nexus.log", log_level: int = logging.INFO) -> logging.Logger:
    """Configures and returns the N.E.X.U.S. root application logger."""
    logger = logging.getLogger("NEXUS")
    logger.setLevel(log_level)

    # Avoid duplicate handlers if setup is called multiple times
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    # Rotating file handler (up to 5 MB per file, max 3 backups)
    try:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        sys.stderr.write(f"Warning: Could not open log file '{log_file}': {e}\n")

    # Console output handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # GUI broadcaster handler
    gui_handler = NexusLogHandler()
    gui_handler.setLevel(log_level)
    gui_formatter = logging.Formatter(
        fmt="[%(asctime)s] %(message)s",
        datefmt="%H:%M:%S"
    )
    gui_handler.setFormatter(gui_formatter)
    logger.addHandler(gui_handler)

    logger.info("N.E.X.U.S. Neural Core Logger initialized.")
    return logger

# Module-level default logger instance
logger = setup_logger()
