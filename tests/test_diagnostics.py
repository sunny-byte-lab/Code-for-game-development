"""Unit tests for Diagnostics & Telemetry dialog and 5-stage pipeline reporting."""

import os
import pytest
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from app.camera_worker import CameraWorker, ControlPipelineStatus
from app.safety_controller import SafetyController, SystemState, ControlMode
from app.virtual_mouse import VirtualMouse
from app.diagnostics_dialog import JarvisDiagnosticsDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_diagnostics_dialog_lifecycle(qapp):
    from unittest.mock import MagicMock
    worker = CameraWorker(tracker=MagicMock())
    safety = SafetyController()
    mouse = VirtualMouse()

    diag = JarvisDiagnosticsDialog(worker, safety, mouse)
    assert diag is not None

    # Emit mock pipeline status
    mock_status = ControlPipelineStatus(
        hand_detected=True,
        hand_landmarks_count=21,
        gesture_name="CURSOR_MOVE",
        system_state="ACTIVE",
        control_mode="MOUSE MODE",
        action_permitted=True,
        permission_reason="PERMITTED",
        last_action="Moved to (960, 540)",
        last_action_success=True,
        last_action_error="",
        cursor_coords=(960, 540),
        fps=30.0,
        camera_index=0
    )
    worker.pipeline_updated.emit(mock_status)
    diag._refresh_display()

    assert "TRACKED" in diag.val_stage1.text()
    assert "CURSOR_MOVE" in diag.val_stage2.text()
    assert "ACTIVE" in diag.val_stage3.text()
    assert "PERMITTED" in diag.val_stage4.text()
    assert "Moved" in diag.val_stage5.text()

    # Test interactive diagnostic test triggers
    diag._test_click()
    diag._test_center()
    diag._rescan_screen()
    assert len(diag.txt_events.toPlainText()) > 0

    diag.close()
    diag.deleteLater()
    qapp.processEvents()
    if worker.tracker and hasattr(worker.tracker, "close"):
        worker.tracker.close()
