"""Unit tests for nexus_protocol security, validator, and pairing handshake."""

import time
import pytest
from nexus_protocol import (
    SecurityManager,
    CommandValidator,
    CommandAction,
    ProtocolMessage,
    MessageType
)


def test_pin_pairing_flow():
    sec = SecurityManager(pin_timeout_seconds=60)
    pin = sec.generate_pairing_pin()
    assert len(pin) == 6
    assert pin.isdigit()

    # Wrong PIN fails
    fail_ok, _, reason = sec.verify_pin_and_create_session("000000", "dev1", "Phone")
    assert fail_ok is False
    assert reason == "INVALID_PIN"

    # Correct PIN succeeds
    ok, token, reason = sec.verify_pin_and_create_session(pin, "dev1", "Phone")
    assert ok is True
    assert token is not None
    assert reason == "PAIRING_SUCCESS"
    assert sec.active_session_count == 1

    # Re-using PIN fails (one-time use)
    reuse_ok, _, _ = sec.verify_pin_and_create_session(pin, "dev2", "Tablet")
    assert reuse_ok is False


def test_replay_attack_prevention():
    sec = SecurityManager()
    pin = sec.generate_pairing_pin()
    ok, token, _ = sec.verify_pin_and_create_session(pin, "dev1", "Phone")

    t0 = time.time()
    # Message 1 with nonce 1 -> Success
    ok1, _, _ = sec.validate_message(token, nonce=1, timestamp=t0)
    assert ok1 is True

    # Replay Message 1 with nonce 1 -> Rejected
    ok_replay, _, err = sec.validate_message(token, nonce=1, timestamp=t0)
    assert ok_replay is False
    assert "REPLAY_ATTACK_DETECTED" in err

    # Message 2 with nonce 2 -> Success
    ok2, _, _ = sec.validate_message(token, nonce=2, timestamp=t0 + 0.1)
    assert ok2 is True


def test_command_validator_allowlist():
    val = CommandValidator()

    # Valid mouse move
    v_ok, act, payload, _ = val.validate_command("MOUSE_MOVE", {"dx": 15.0, "dy": -20.0})
    assert v_ok is True
    assert act == CommandAction.MOUSE_MOVE
    assert payload["dx"] == 15.0

    # Parameter clamping for safety
    _, _, clamped_payload, _ = val.validate_command("MOUSE_MOVE", {"dx": 99999.0, "dy": -88888.0})
    assert clamped_payload["dx"] == 500.0
    assert clamped_payload["dy"] == -500.0

    # Arbitrary dangerous command rejection
    bad_ok, _, _, bad_err = val.validate_command("EXEC_SHELL", {"cmd": "powershell.exe"})
    assert bad_ok is False
    assert "REJECTED_UNKNOWN_ACTION" in bad_err


def test_master_killswitch_revocation():
    sec = SecurityManager()
    pin = sec.generate_pairing_pin()
    _, token, _ = sec.verify_pin_and_create_session(pin, "dev1", "Phone")
    assert sec.active_session_count == 1

    # Master killswitch
    sec.revoke_all_sessions()
    assert sec.active_session_count == 0

    # Old token is completely unauthorized
    val_ok, _, err = sec.validate_message(token, nonce=1, timestamp=time.time())
    assert val_ok is False
    assert err == "UNAUTHORIZED_TOKEN"
