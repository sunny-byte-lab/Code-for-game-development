"""Unit tests for JARVIS camera device utilities and privacy permission checking."""

import pytest
import numpy as np
from app.camera_device_utils import (
    probe_camera_devices,
    check_camera_permission,
    generate_privacy_blocked_frame,
    open_windows_camera_settings,
    get_best_camera_index
)


def test_probe_camera_devices_returns_list():
    devs = probe_camera_devices()
    assert isinstance(devs, list)
    if devs:
        first = devs[0]
        assert "index" in first
        assert "name" in first
        assert "is_accessible" in first
        assert "is_permission_denied" in first
        assert "is_virtual" in first


def test_check_camera_permission():
    has_perm, reason = check_camera_permission(0)
    assert isinstance(has_perm, bool)
    assert isinstance(reason, str)


def test_generate_privacy_blocked_frame():
    frame = generate_privacy_blocked_frame(width=640, height=480, frame_count=5)
    assert isinstance(frame, np.ndarray)
    assert frame.shape == (480, 640, 3)
    # Check that frame contains non-zero drawing pixels
    assert np.count_nonzero(frame) > 1000


def test_get_best_camera_index_prioritizes_physical(monkeypatch):
    mock_devices = [
        {"index": 0, "name": "Integrated Camera", "is_accessible": True, "is_virtual": False},
        {"index": 1, "name": "vivo Virtual Camera", "is_accessible": True, "is_virtual": True},
    ]
    monkeypatch.setattr("app.camera_device_utils.probe_camera_devices", lambda: mock_devices)

    # Even if virtual camera index 1 is requested, best index should be physical camera 0
    assert get_best_camera_index(preferred_index=1) == 0
    assert get_best_camera_index(preferred_index=0) == 0


def test_get_best_camera_index_falls_back_to_virtual_when_no_physical_exists(monkeypatch):
    mock_devices = [
        {"index": 1, "name": "vivo Virtual Camera", "is_accessible": True, "is_virtual": True},
    ]
    monkeypatch.setattr("app.camera_device_utils.probe_camera_devices", lambda: mock_devices)

    # When no physical camera is present, virtual camera is used
    assert get_best_camera_index(preferred_index=1) == 1
    assert get_best_camera_index(preferred_index=0) == 1


