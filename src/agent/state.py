"""Shared agent data structures: trace events (what the agents did) and results."""
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from src.utils.helpers import now_iso


@dataclass
class TraceEvent:
    agent: str
    kind: str            # info | thought | action | observation | final | error | warning
    text: str
    ts: str = field(default_factory=now_iso)
    data: Any = None


class Trace:
    """Collects events, forwards them live (UI) and persists them (audit)."""

    def __init__(self, run_id="chat", store=None, callback: Optional[Callable[[TraceEvent], None]] = None):
        self.run_id, self.store, self.callback = run_id, store, callback
        self.events: List[TraceEvent] = []

    def emit(self, agent, kind, text, data=None):
        ev = TraceEvent(agent, kind, str(text), data=data)
        self.events.append(ev)
        if self.store is not None:
            try:
                self.store.add_trace(self.run_id, agent, kind, ev.text[:2000], data)
            except Exception:           # tracing must never break the agent
                pass
        if self.callback:
            try:
                self.callback(ev)
            except Exception:
                pass
        return ev


@dataclass
class AgentResult:
    status: str                  # final | done | max_steps | llm_error | parse_error
    output: Any = None
    steps: int = 0
    error: Optional[str] = None
