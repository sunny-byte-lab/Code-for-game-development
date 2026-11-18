"""N.E.X.U.S. Core Lifecycle and System States."""

from enum import Enum


class AssistantState(str, Enum):
    INITIALIZING = "INITIALIZING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    SHUTDOWN = "SHUTDOWN"


class AssistantMode(str, Enum):
    MOUSE = "MOUSE"
    KEYBOARD = "KEYBOARD"
    AIR_TYPING = "AIR_TYPING"
    APP_LAUNCH = "APP_LAUNCH"
    SYSTEM_CONTROL = "SYSTEM_CONTROL"
    PRESENTATION = "PRESENTATION"
    LAB_3D = "LAB_3D"
