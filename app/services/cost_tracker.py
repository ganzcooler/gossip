"""Thread-safe cost accounting for OpenRouter calls."""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class CostTracker:
    """Aggregate token usage and USD cost for one pipeline run."""

    label: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    def record(self, usage: dict | None) -> None:
        if not usage:
            return
        self.calls += 1
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)
        self.total_tokens += int(usage.get("total_tokens") or 0)
        details = usage.get("completion_tokens_details") or {}
        self.reasoning_tokens += int(details.get("reasoning_tokens") or 0)
        self.cost_usd += float(usage.get("cost") or 0.0)

    def summary(self) -> str:
        return (
            f"{self.label}: calls={self.calls} "
            f"prompt_tokens={self.prompt_tokens} "
            f"completion_tokens={self.completion_tokens} "
            f"reasoning_tokens={self.reasoning_tokens} "
            f"total_tokens={self.total_tokens} "
            f"cost_usd={self.cost_usd:.6f}"
        )


_lock = threading.Lock()
_active: CostTracker | None = None


def start_cost_tracking(label: str) -> CostTracker:
    """Start a new tracker and make it the active accumulator."""
    global _active
    tracker = CostTracker(label=label)
    with _lock:
        _active = tracker
    return tracker


def stop_cost_tracking() -> CostTracker | None:
    """Return and clear the active tracker."""
    global _active
    with _lock:
        tracker = _active
        _active = None
    return tracker


def record_usage(usage: dict | None) -> None:
    """Record usage from any OpenRouter call in the active run."""
    with _lock:
        tracker = _active
        if tracker is not None:
            tracker.record(usage)
