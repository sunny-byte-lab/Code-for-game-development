"""Unit tests for system controls, volume calculations, and safety fallbacks."""

import pytest
from app.system_controls import SystemControls


class TestSystemControls:
    def test_volume_clamping(self):
        ctrl = SystemControls()
        # Mock volume interface with dummy scalar
        class DummyVolume:
            def __init__(self):
                self.val = 0.5
                self.muted = False
            def GetMasterVolumeLevelScalar(self):
                return self.val
            def SetMasterVolumeLevelScalar(self, s, _):
                self.val = s
            def GetMute(self):
                return self.muted
            def SetMute(self, m, _):
                self.muted = m

        ctrl._volume_interface = DummyVolume()

        # Set 75%
        ctrl.set_volume(75)
        assert ctrl.get_volume() == 75

        # Set 150% (should clamp to 100)
        ctrl.set_volume(150)
        assert ctrl.get_volume() == 100

        # Set -20% (should clamp to 0)
        ctrl.set_volume(-20)
        assert ctrl.get_volume() == 0

    def test_volume_stepping(self):
        ctrl = SystemControls()
        class DummyVolume:
            def __init__(self):
                self.val = 0.50
            def GetMasterVolumeLevelScalar(self):
                return self.val
            def SetMasterVolumeLevelScalar(self, s, _):
                self.val = s

        ctrl._volume_interface = DummyVolume()
        new_v = ctrl.volume_up(step=10)
        assert new_v == 60

        new_v2 = ctrl.volume_down(step=15)
        assert new_v2 == 45

    def test_mute_toggle(self):
        ctrl = SystemControls()
        class DummyVolume:
            def __init__(self):
                self.muted = False
            def GetMute(self):
                return self.muted
            def SetMute(self, m, _):
                self.muted = m

        ctrl._volume_interface = DummyVolume()
        assert ctrl.toggle_mute() is True
        assert ctrl.toggle_mute() is False
