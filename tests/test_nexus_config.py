"""Unit tests for nexus_config schema, validation, and manager."""

import os
import json
import pytest
from nexus_config import ConfigManager, NexusRootConfig


def test_config_defaults(tmp_path):
    test_json = str(tmp_path / "test_config.json")
    mgr = ConfigManager(test_json)
    assert mgr.get("camera", "width") == 640
    assert mgr.get("tracking", "max_num_hands") == 2
    assert mgr.get("mouse", "sensitivity") == 2.40
    assert mgr.get("remote_protocol", "enabled") is False
    assert os.path.exists(test_json)


def test_config_set_and_sanitization(tmp_path):
    test_json = str(tmp_path / "test_config.json")
    mgr = ConfigManager(test_json)

    # Set within bounds
    mgr.set("mouse", "sensitivity", 3.5)
    assert mgr.get("mouse", "sensitivity") == 3.5

    # Boundary clamping: max sensitivity is 8.0
    mgr.set("mouse", "sensitivity", 99.0)
    assert mgr.get("mouse", "sensitivity") == 8.0

    # Boundary clamping: min sensitivity is 0.2
    mgr.set("mouse", "sensitivity", -5.0)
    assert mgr.get("mouse", "sensitivity") == 0.2


def test_config_persistence_and_reload(tmp_path):
    test_json = str(tmp_path / "test_config.json")
    mgr = ConfigManager(test_json)
    mgr.set("air_typing", "dwell_duration", 0.65, auto_save=True)

    # Reload from disk
    mgr2 = ConfigManager(test_json)
    assert mgr2.get("air_typing", "dwell_duration") == 0.65


def test_config_listener_notifications(tmp_path):
    test_json = str(tmp_path / "test_config.json")
    mgr = ConfigManager(test_json)

    events = []
    mgr.add_listener(lambda k, v: events.append((k, v)))
    mgr.set("camera", "fps_target", 60)

    assert len(events) == 1
    assert events[0] == ("camera.fps_target", 60)
