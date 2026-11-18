"""N.E.X.U.S. Remote Control Protocol Specification.
Strongly-typed message structures, message types, and action definitions.
"""

import time
import uuid
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional


class MessageType(str, Enum):
    HELLO = "HELLO"
    PAIR_REQUEST = "PAIR_REQUEST"
    PAIR_CONFIRM = "PAIR_CONFIRM"
    AUTH = "AUTH"
    AUTH_SUCCESS = "AUTH_SUCCESS"
    AUTH_FAILED = "AUTH_FAILED"
    COMMAND = "COMMAND"
    COMMAND_ACK = "COMMAND_ACK"
    TELEMETRY = "TELEMETRY"
    HEARTBEAT = "HEARTBEAT"
    DISCONNECT = "DISCONNECT"
    ERROR = "ERROR"


class CommandAction(str, Enum):
    # Mouse & Touchpad
    MOUSE_MOVE = "MOUSE_MOVE"
    CLICK = "CLICK"
    MOUSE_DOWN = "MOUSE_DOWN"
    MOUSE_UP = "MOUSE_UP"
    SCROLL = "SCROLL"

    # Keyboard
    KEY_PRESS = "KEY_PRESS"
    TYPE_TEXT = "TYPE_TEXT"

    # Audio & System
    VOLUME_SET = "VOLUME_SET"
    VOLUME_UP = "VOLUME_UP"
    VOLUME_DOWN = "VOLUME_DOWN"
    MUTE_AUDIO = "MUTE_AUDIO"
    SWITCH_WINDOW = "SWITCH_WINDOW"
    LAUNCH_APP = "LAUNCH_APP"

    # AI Chat
    AI_QUERY = "AI_QUERY"

    # Modes & Safety
    SET_MODE = "SET_MODE"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    PAUSE = "PAUSE"
    RESUME = "RESUME"


@dataclass
class ProtocolMessage:
    msg_type: MessageType
    payload: Dict[str, Any] = field(default_factory=dict)
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    nonce: int = 0
    token: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["msg_type"] = self.msg_type.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProtocolMessage":
        m_type = MessageType(data.get("msg_type", MessageType.ERROR.value))
        return cls(
            msg_type=m_type,
            payload=data.get("payload", {}),
            msg_id=data.get("msg_id", str(uuid.uuid4())),
            timestamp=float(data.get("timestamp", time.time())),
            nonce=int(data.get("nonce", 0)),
            token=data.get("token")
        )
