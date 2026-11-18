"""N.E.X.U.S. Configuration Schema.
Defines strongly-typed configuration dataclasses with boundary validation and sensible defaults.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional


@dataclass
class CameraConfig:
    index: int = 1
    width: int = 640
    height: int = 480
    fps_target: int = 30
    mirror: bool = True


@dataclass
class TrackingConfig:
    detection_confidence: float = 0.70
    tracking_confidence: float = 0.70
    max_num_hands: int = 2


@dataclass
class MouseConfig:
    sensitivity: float = 2.40
    sensitivity_x: float = 2.40
    sensitivity_y: float = 2.40
    sensitivity_preset: str = "medium"
    fine_control_mode: bool = True
    fine_control_scale: float = 0.40
    smoothing: float = 0.65
    smoothing_type: str = "one_euro"
    one_euro_min_cutoff: float = 1.00
    one_euro_beta: float = 0.02
    deadzone_radius: float = 8.00
    active_margin_x: float = 0.20
    active_margin_y: float = 0.20
    roi_left: float = 0.20
    roi_top: float = 0.20
    roi_right: float = 0.80
    roi_bottom: float = 0.80
    invert_x: bool = False
    cursor_mode: str = "absolute"
    relative_speed: float = 4.00
    relative_deadzone: float = 0.03
    tracking_landmark: str = "index_tip"
    pinch_normalized: bool = True
    pinch_threshold: float = 0.28
    pinch_release_threshold: float = 0.40
    right_click_threshold: float = 0.28
    right_click_gesture: str = "thumb_middle_pinch"
    click_cooldown: float = 0.20
    click_stabilization: bool = True
    click_stabilization_ms: int = 160
    drag_hold_duration: float = 0.45
    scroll_speed: float = 35.0
    scroll_deadzone: float = 0.015


@dataclass
class GesturesEnabledConfig:
    cursor_move: bool = True
    left_click: bool = True
    drag_and_drop: bool = True
    right_click: bool = True
    scroll: bool = True
    open_palm_pause: bool = False
    fist_emergency_stop: bool = False


@dataclass
class InterfaceConfig:
    enable_animations: bool = True
    show_landmarks: bool = True
    show_hud_overlays: bool = True
    show_radar_sweep: bool = True
    theme: str = "iron_man_dark"


@dataclass
class AirTypingConfig:
    typing_mode: str = "DWELL"
    dwell_duration: float = 0.50
    dwell_jitter_tolerance: float = 25.0
    keypress_cooldown: float = 0.20
    auto_activate_duration: float = 0.40
    auto_exit_duration: float = 0.80


@dataclass
class RemoteProtocolConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    require_pairing: bool = True
    pairing_pin_timeout_seconds: int = 180
    session_timeout_seconds: int = 3600
    max_rate_hz: int = 60
    allow_unauthenticated_localhost: bool = False


@dataclass
class AIConfig:
    provider: str = "mock"  # "mock", "gemini", "openai", "local"
    api_key: str = ""
    model_name: str = "gemini-1.5-flash"
    temperature: float = 0.70
    max_tokens: int = 1024
    system_prompt: str = (
        "You are N.E.X.U.S., an advanced holographic tactical AI assistant. "
        "Keep responses concise, confident, structured, and focused on helping the user."
    )


@dataclass
class VoiceConfig:
    enabled: bool = False
    trigger_keyword: str = "nexus"
    language: str = "en-US"
    tts_enabled: bool = False
    tts_voice_rate: int = 180


@dataclass
class ApplicationItem:
    id: str
    name: str
    path: str
    enabled: bool = True


@dataclass
class NexusRootConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    mouse: MouseConfig = field(default_factory=MouseConfig)
    gestures_enabled: GesturesEnabledConfig = field(default_factory=GesturesEnabledConfig)
    interface: InterfaceConfig = field(default_factory=InterfaceConfig)
    air_typing: AirTypingConfig = field(default_factory=AirTypingConfig)
    remote_protocol: RemoteProtocolConfig = field(default_factory=RemoteProtocolConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    applications: List[Dict[str, Any]] = field(default_factory=lambda: [
        {"id": "notepad", "name": "Notepad", "path": "notepad.exe", "enabled": True},
        {"id": "file_explorer", "name": "File Explorer", "path": "explorer.exe", "enabled": True},
        {"id": "windows_settings", "name": "Windows Settings", "path": "ms-settings:", "enabled": True},
        {"id": "google_chrome", "name": "Google Chrome", "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "enabled": True},
        {"id": "visual_studio_code", "name": "Visual Studio Code", "path": "Code.exe", "enabled": True},
        {"id": "blender_3d", "name": "Blender 3D", "path": "blender.exe", "enabled": True},
    ])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
