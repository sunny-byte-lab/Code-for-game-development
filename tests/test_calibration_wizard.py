"""Unit tests for the Interactive Calibration Wizard dialog."""

import os
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from app.settings_manager import SettingsManager
from app.camera_worker import CameraWorker
from app.calibration_wizard import JarvisCalibrationWizard


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_calibration_wizard_lifecycle(qapp):
    from unittest.mock import MagicMock
    settings = SettingsManager("config.json")
    worker = CameraWorker(tracker=MagicMock())
    wizard = JarvisCalibrationWizard(settings, worker)

    assert wizard is not None
    assert wizard.pages.count() == 5
    assert wizard.pages.currentIndex() == 0

    # Step through pages
    wizard._next_page()
    assert wizard.pages.currentIndex() == 1

    # Test ROI preset application
    wizard._set_roi_preset(0.20, 0.20, 0.80, 0.80)
    assert wizard.working_roi_left == 0.20
    assert wizard.working_roi_right == 0.80

    # Move to Step 3 (Sandbox)
    wizard._next_page()
    assert wizard.pages.currentIndex() == 2

    # Move to Step 4 (Pinch)
    wizard._next_page()
    assert wizard.pages.currentIndex() == 3

    # Move to Step 5 (Review)
    wizard._next_page()
    assert wizard.pages.currentIndex() == 4

    # Save and apply
    wizard._save_and_apply()
    assert settings.get("mouse", "roi_left") == 0.20

    wizard.close()
    wizard.deleteLater()
    qapp.processEvents()
    if worker.tracker and hasattr(worker.tracker, "close"):
        worker.tracker.close()
