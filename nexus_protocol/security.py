"""N.E.X.U.S. Protocol Security & Pairing Engine.
Provides cryptographically secure PIN pairing, session token issuance,
replay protection, and sliding-window rate limiting.
"""

import time
import secrets
import hmac
import hashlib
from typing import Dict, Optional, Tuple, Set


class RateLimiter:
    """Token-bucket rate limiter per device session."""

    def __init__(self, max_rate_hz: int = 60, burst_capacity: int = 120):
        self.rate = max_rate_hz
        self.capacity = burst_capacity
        self.tokens = float(burst_capacity)
        self.last_update = time.time()

    def allow(self) -> bool:
        now = time.time()
        elapsed = now - self.last_update
        self.last_update = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class DeviceSession:
    """Represents an authenticated client session."""

    def __init__(self, device_id: str, device_name: str, token: str, max_rate_hz: int = 60):
        self.device_id = device_id
        self.device_name = device_name
        self.token = token
        self.created_at = time.time()
        self.last_seen = time.time()
        self.last_nonce = 0
        self.rate_limiter = RateLimiter(max_rate_hz=max_rate_hz)

    def is_valid_nonce(self, nonce: int) -> bool:
        """Enforces strictly increasing nonces for replay attack prevention."""
        if nonce > self.last_nonce:
            self.last_nonce = nonce
            return True
        return False


class SecurityManager:
    """Manages PIN-based pairing, session tokens, and connection validation."""

    def __init__(self, pin_timeout_seconds: int = 180, session_timeout_seconds: int = 3600):
        self.pin_timeout_seconds = pin_timeout_seconds
        self.session_timeout_seconds = session_timeout_seconds
        self._current_pin: Optional[str] = None
        self._pin_expires_at: float = 0.0
        self._active_sessions: Dict[str, DeviceSession] = {}  # token -> DeviceSession
        self._paired_devices: Set[str] = set()

    def generate_pairing_pin(self) -> str:
        """Generates a secure, cryptographically random 6-digit PIN."""
        # Avoid simple predictable PINs like 000000
        pin_int = secrets.randbelow(900000) + 100000
        self._current_pin = str(pin_int)
        self._pin_expires_at = time.time() + self.pin_timeout_seconds
        return self._current_pin

    def get_active_pin(self) -> Optional[str]:
        """Returns the active PIN if not expired."""
        if self._current_pin and time.time() < self._pin_expires_at:
            return self._current_pin
        self._current_pin = None
        return None

    def verify_pin_and_create_session(self, submitted_pin: str, device_id: str, device_name: str) -> Tuple[bool, Optional[str], str]:
        """Verifies the submitted PIN and creates an authenticated session token."""
        if not self._current_pin or time.time() > self._pin_expires_at:
            return False, None, "PAIRING_PIN_EXPIRED"

        if not hmac.compare_digest(submitted_pin.strip(), self._current_pin):
            return False, None, "INVALID_PIN"

        # Generate cryptographic session token
        token = secrets.token_hex(32)
        session = DeviceSession(device_id=device_id, device_name=device_name, token=token)
        self._active_sessions[token] = session
        self._paired_devices.add(device_id)

        # Invalidate PIN immediately upon successful pairing
        self._current_pin = None
        self._pin_expires_at = 0.0

        return True, token, "PAIRING_SUCCESS"

    def validate_message(self, token: Optional[str], nonce: int, timestamp: float) -> Tuple[bool, Optional[DeviceSession], str]:
        """Validates message authentication, timestamp freshness, replay nonce, and rate limit."""
        if not token or token not in self._active_sessions:
            return False, None, "UNAUTHORIZED_TOKEN"

        session = self._active_sessions[token]
        now = time.time()

        # Check session expiration
        if now - session.last_seen > self.session_timeout_seconds:
            del self._active_sessions[token]
            return False, None, "SESSION_EXPIRED"

        # Check timestamp freshness (max 5.0 seconds skew to prevent replay)
        if abs(now - timestamp) > 5.0:
            return False, None, "TIMESTAMP_DRIFT_TOO_HIGH"

        # Check replay nonce
        if not session.is_valid_nonce(nonce):
            return False, None, "REPLAY_ATTACK_DETECTED (NONCE NOT INCREASING)"

        # Check rate limiter
        if not session.rate_limiter.allow():
            return False, None, "RATE_LIMIT_EXCEEDED"

        session.last_seen = now
        return True, session, "OK"

    def revoke_all_sessions(self) -> None:
        """Master killswitch: immediately severs all authenticated remote sessions."""
        self._active_sessions.clear()
        self._current_pin = None
        self._pin_expires_at = 0.0

    def revoke_session(self, token: str) -> bool:
        """Revokes a specific session token."""
        if token in self._active_sessions:
            del self._active_sessions[token]
            return True
        return False

    @property
    def active_session_count(self) -> int:
        return len(self._active_sessions)
