"""Unit test for PySide6 GUI initialization using offscreen platform."""

import os
import sys
import pytest

# Ensure offscreen platform so tests run cleanly in headless/sandbox environments
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["MPLCONFIGDIR"] = os.path.join(os.path.dirname(__file__), ".test_mpl")

from PySide6.QtWidgets import QApplication
from app.main_window import JarvisMainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_main_window_instantiation(qapp):
    """Verifies that the entire JARVIS main window and all HUD widgets construct without error."""
    window = JarvisMainWindow("config.json")
    assert window is not None
    assert window.safety.is_enabled is False

    # Simulate transition to dashboard
    window._on_startup_completed()
    assert window.stack.currentWidget() == window.dashboard

    # Verify buttons and widgets exist
    assert window.btn_enable is not None
    assert window.btn_mode_mouse is not None
    assert window.arc_reactor is not None
    assert window.webcam_view is not None
    assert window.btn_switch_cam is not None
    assert window.btn_diag is not None
    assert window.lbl_gate_status is not None
    assert window.lbl_last_action is not None

    # Test quick camera toggle
    initial_cam = window.camera_worker.camera_index
    window._toggle_quick_camera()
    assert window.camera_worker.camera_index != initial_cam or window.btn_switch_cam.text().startswith("SENSOR")

    # Test toggles
    window._toggle_enable()
    assert window.safety.is_enabled is True
    window._toggle_enable()
    assert window.safety.is_enabled is False

    # Clean close
    if hasattr(window, "telemetry_timer"):
        window.telemetry_timer.stop()
    if window.camera_worker:
        window.camera_worker.stop()
        window.camera_worker.wait(2000)
    if window.tracker:
        window.tracker.close()
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_camera_worker_enumeration_and_cycle():
    """Verifies that available cameras always include index 0 and cycle_camera functions correctly."""
    from app.camera_worker import CameraWorker
    cams = CameraWorker.get_available_cameras()
    assert 0 in cams
    worker = CameraWorker(camera_index=0)
    assert worker.camera_index == 0
    next_idx = worker.cycle_camera()
    assert worker.camera_index == next_idx


def test_qt_bootstrap_sanitizes_ambient_variables():
    """Verifies that qt_bootstrap removes foreign or invalid Qt platform plugin environment paths."""
    from app import qt_bootstrap

    # Simulate foreign Qt environment variable injected by third-party software (e.g., Anaconda/OBS)
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = "C:\\InvalidPath\\platforms"
    qt_bootstrap.setup_qt_environment()

    # Must be stripped or sanitized so it does not hijack PySide6
    assert os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH") != "C:\\InvalidPath\\platforms"
