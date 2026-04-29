from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JudgeGateMetrics:
    is_available: bool = False
    provider_independent: bool = False
    sample_size: int = 0
    false_negative_rate: float | None = None
    false_positive_rate: float | None = None
    inconclusive_rate: float | None = None
    reliability_score: float | None = None

