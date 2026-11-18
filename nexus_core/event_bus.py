"""N.E.X.U.S. Core Event Bus.
Thread-safe publisher-subscriber message broker for telemetry and system status.
"""

import threading
import logging
from typing import Dict, List, Callable, Any

logger = logging.getLogger("NEXUS.Core.EventBus")


class EventBus:
    """Thread-safe publish-subscribe event dispatcher."""

    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[Any], None]]] = {}
        self._lock = threading.RLock()

    def subscribe(self, topic: str, callback: Callable[[Any], None]) -> None:
        """Subscribes a callback to an event topic."""
        with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = []
            if callback not in self._subscribers[topic]:
                self._subscribers[topic].append(callback)

    def unsubscribe(self, topic: str, callback: Callable[[Any], None]) -> None:
        """Unsubscribes a callback from a topic."""
        with self._lock:
            if topic in self._subscribers and callback in self._subscribers[topic]:
                self._subscribers[topic].remove(callback)

    def publish(self, topic: str, data: Any = None) -> None:
        """Publishes an event to all registered topic subscribers."""
        with self._lock:
            listeners = list(self._subscribers.get(topic, []))
            wildcard_listeners = list(self._subscribers.get("*", []))

        for cb in listeners + wildcard_listeners:
            try:
                cb(data)
            except Exception as e:
                logger.error(f"Error executing event subscriber for '{topic}': {e}")
