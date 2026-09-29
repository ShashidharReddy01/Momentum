"""Momentum's own code-backed agents (ADR-0009 handlers shipped with Momentum). Their names
start with ``momentum.``; a host's handler can't replace them."""

from __future__ import annotations

from momentum.agents import herald, nudge, pulse
from momentum.agents.extensions import Handler

BUILTIN_HANDLERS: dict[str, Handler] = {
    pulse.HANDLER: pulse.daily_digest,
    herald.HANDLER: herald.status_reporter,
    nudge.HANDLER: nudge.nudger,
}
