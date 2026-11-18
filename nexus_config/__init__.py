"""N.E.X.U.S. Shared Configuration Package."""

from nexus_config.schema import (
    NexusRootConfig, CameraConfig, TrackingConfig, MouseConfig,
    GesturesEnabledConfig, InterfaceConfig, AirTypingConfig,
    RemoteProtocolConfig, AIConfig, VoiceConfig
)
from nexus_config.manager import ConfigManager

__all__ = [
    "NexusRootConfig",
    "CameraConfig",
    "TrackingConfig",
    "MouseConfig",
    "GesturesEnabledConfig",
    "InterfaceConfig",
    "AirTypingConfig",
    "RemoteProtocolConfig",
    "AIConfig",
    "VoiceConfig",
    "ConfigManager"
]
