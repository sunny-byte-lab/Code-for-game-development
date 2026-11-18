"""N.E.X.U.S. Unified Command Router.
Authoritatively validates and dispatches intents from Gestures, Voice, and Mobile Remote devices.
"""

import logging
from typing import Dict, Any, Tuple, Optional, Callable
from nexus_protocol.spec import CommandAction
from nexus_core.lifecycle import AssistantState, AssistantMode
from nexus_core.event_bus import EventBus

logger = logging.getLogger("NEXUS.Core.Router")


class CommandRouter:
    """Central authoritative command dispatcher enforcing safety gates."""

    def __init__(self,
                 event_bus: Optional[EventBus] = None,
                 input_controller: Optional[Any] = None,
                 audio_controller: Optional[Any] = None,
                 app_launcher: Optional[Any] = None,
                 ai_service: Optional[Any] = None):
        self.bus = event_bus or EventBus()
        self.input_ctrl = input_controller
        self.audio_ctrl = audio_controller
        self.launcher = app_launcher
        self.ai_service = ai_service

        self.state = AssistantState.ACTIVE
        self.mode = AssistantMode.MOUSE

    def set_state(self, state: AssistantState) -> None:
        self.state = state
        self.bus.publish("state_changed", state.value)
        logger.info(f"[CORE STATE] Changed to: {state.value}")

    def set_mode(self, mode: AssistantMode) -> None:
        self.mode = mode
        self.bus.publish("mode_changed", mode.value)
        logger.info(f"[CORE MODE] Changed to: {mode.value}")

    def route_command(self, action: CommandAction, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """Routes a validated CommandAction to the registered subsystem."""
        # 1. Global Safety Interlocks
        if self.state == AssistantState.EMERGENCY_STOP and action != CommandAction.RESUME:
            return False, "SAFETY_INTERLOCK_ACTIVE: System in EMERGENCY_STOP"

        if self.state == AssistantState.PAUSED and action not in (CommandAction.RESUME, CommandAction.EMERGENCY_STOP):
            return False, "SYSTEM_PAUSED"

        # 2. Lifecycle Commands
        if action == CommandAction.EMERGENCY_STOP:
            self.set_state(AssistantState.EMERGENCY_STOP)
            if self.input_ctrl and hasattr(self.input_ctrl, "release_all_buttons"):
                self.input_ctrl.release_all_buttons()
            return True, "EMERGENCY_STOP_ENGAGED"

        if action == CommandAction.PAUSE:
            self.set_state(AssistantState.PAUSED)
            if self.input_ctrl and hasattr(self.input_ctrl, "release_all_buttons"):
                self.input_ctrl.release_all_buttons()
            return True, "SYSTEM_PAUSED"

        if action == CommandAction.RESUME:
            self.set_state(AssistantState.ACTIVE)
            return True, "SYSTEM_RESUMED"

        if action == CommandAction.SET_MODE:
            target_mode = AssistantMode(payload.get("mode", AssistantMode.MOUSE.value))
            self.set_mode(target_mode)
            return True, f"MODE_SET_{target_mode.value}"

        # 3. Mouse / Touchpad Commands
        if action == CommandAction.MOUSE_MOVE:
            dx = payload.get("dx", 0.0)
            dy = payload.get("dy", 0.0)
            if self.input_ctrl and hasattr(self.input_ctrl, "move_relative"):
                self.input_ctrl.move_relative(dx, dy)
                return True, f"MOVED_RELATIVE({dx}, {dy})"
            return True, f"SIMULATED_MOUSE_MOVE({dx}, {dy})"

        if action in (CommandAction.CLICK, CommandAction.MOUSE_DOWN, CommandAction.MOUSE_UP):
            btn = payload.get("button", "left")
            if self.input_ctrl:
                if action == CommandAction.CLICK and hasattr(self.input_ctrl, "click"):
                    self.input_ctrl.click(btn)
                elif action == CommandAction.MOUSE_DOWN and hasattr(self.input_ctrl, "mouse_down"):
                    self.input_ctrl.mouse_down(btn)
                elif action == CommandAction.MOUSE_UP and hasattr(self.input_ctrl, "mouse_up"):
                    self.input_ctrl.mouse_up(btn)
                return True, f"MOUSE_{action.value}({btn})"
            return True, f"SIMULATED_{action.value}({btn})"

        if action == CommandAction.SCROLL:
            delta = payload.get("delta", 0)
            if self.input_ctrl and hasattr(self.input_ctrl, "scroll"):
                self.input_ctrl.scroll(delta)
                return True, f"SCROLLED({delta})"
            return True, f"SIMULATED_SCROLL({delta})"

        # 4. Keyboard Commands
        if action == CommandAction.KEY_PRESS:
            key_id = payload.get("key_id", "")
            char = payload.get("char", "")
            if self.input_ctrl and hasattr(self.input_ctrl, "press_key"):
                self.input_ctrl.press_key(key_id, char)
            return True, f"KEY_PRESSED({key_id or char})"

        if action == CommandAction.TYPE_TEXT:
            text = payload.get("text", "")
            if self.input_ctrl and hasattr(self.input_ctrl, "type_string"):
                self.input_ctrl.type_string(text)
            return True, f"TYPED_TEXT({len(text)} chars)"

        # 5. Audio Commands
        if action == CommandAction.VOLUME_UP:
            step = payload.get("step", 5)
            if self.audio_ctrl and hasattr(self.audio_ctrl, "volume_up"):
                val = self.audio_ctrl.volume_up(step)
                return True, f"VOLUME_UP({val}%)"
            return True, "VOLUME_UP_SIMULATED"

        if action == CommandAction.VOLUME_DOWN:
            step = payload.get("step", 5)
            if self.audio_ctrl and hasattr(self.audio_ctrl, "volume_down"):
                val = self.audio_ctrl.volume_down(step)
                return True, f"VOLUME_DOWN({val}%)"
            return True, "VOLUME_DOWN_SIMULATED"

        if action == CommandAction.VOLUME_SET:
            pct = payload.get("percent", 50)
            if self.audio_ctrl and hasattr(self.audio_ctrl, "set_volume"):
                self.audio_ctrl.set_volume(pct)
                return True, f"VOLUME_SET({pct}%)"
            return True, f"VOLUME_SET_SIMULATED({pct}%)"

        if action == CommandAction.MUTE_AUDIO:
            if self.audio_ctrl and hasattr(self.audio_ctrl, "toggle_mute"):
                self.audio_ctrl.toggle_mute()
                return True, "AUDIO_MUTE_TOGGLED"
            return True, "MUTE_AUDIO_SIMULATED"

        # 6. App Launcher
        if action == CommandAction.LAUNCH_APP:
            app_id = payload.get("app_id", "")
            if self.launcher and hasattr(self.launcher, "launch_by_id"):
                ok = self.launcher.launch_by_id(app_id)
                return ok, f"LAUNCHED_APP_{app_id}" if ok else f"FAILED_TO_LAUNCH_{app_id}"
            return True, f"SIMULATED_LAUNCH_{app_id}"

        # 7. AI Chat
        if action == CommandAction.AI_QUERY:
            query = payload.get("query", "")
            if self.ai_service and hasattr(self.ai_service, "send_user_message"):
                resp = self.ai_service.send_user_message(query)
                return True, resp.content
            return True, f"SIMULATED_AI_RESPONSE for: '{query}'"

        return False, f"UNHANDLED_COMMAND: {action.value}"
