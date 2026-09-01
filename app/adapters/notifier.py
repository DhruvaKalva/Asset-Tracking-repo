"""Alert delivery. In-app for the demo; email/push/SMS behind the same call."""
from __future__ import annotations

import logging
from typing import Protocol

from app.adapters.bus import bus

log = logging.getLogger(__name__)


class Notifier(Protocol):
    channel: str

    def send(self, payload: dict) -> None: ...


class InAppNotifier:
    """Pushes onto the SSE stream -- the dashboard toasts it instantly."""

    channel = "in_app"

    def send(self, payload: dict) -> None:
        bus.publish("alert", payload)
        log.info("[ALERT/%s] %s -- %s", payload.get("severity"), payload.get("equipment_id"), payload.get("reason_text"))


class ConsoleNotifier:
    channel = "console"

    def send(self, payload: dict) -> None:
        log.warning("[%s] %s: %s", payload.get("severity"), payload.get("equipment_id"), payload.get("reason_text"))


class EmailNotifier:
    """Production drop-in. Wire an SMTP/SES client here; nothing else changes."""

    channel = "email"

    def send(self, payload: dict) -> None:  # pragma: no cover - not used in demo
        log.info("email notifier not configured; would send: %s", payload)


class FanoutNotifier:
    def __init__(self, notifiers: list[Notifier]) -> None:
        self.notifiers = notifiers
        self.channel = "fanout"

    def send(self, payload: dict) -> None:
        for n in self.notifiers:
            try:
                n.send(payload)
            except Exception:  # a broken channel must not block the others
                log.exception("notifier %s failed", n.channel)


def get_notifier() -> Notifier:
    return FanoutNotifier([InAppNotifier()])
