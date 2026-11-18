"""Pytest configuration and environment fixtures."""

import os
import sys

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set headless Qt platform by default for tests if not set
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Run Qt bootstrap
import app.qt_bootstrap
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def pytest_unconfigure(config):
    """Clean exit hook executed after all reports are printed."""
    # Prevent Windows C++ CRT destructor crash between Qt and MediaPipe threads
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            app.quit()
    except Exception:
        pass
