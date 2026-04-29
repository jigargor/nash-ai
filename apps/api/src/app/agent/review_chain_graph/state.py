from __future__ import annotations

from typing import TypedDict


class ReviewChainState(TypedDict, total=False):
    run_id: str
    findings_after_policy: int
    is_light_review: bool
    max_mode_enabled: bool
    should_run_max_mode: bool
    should_run_editor: bool
    chain_short_circuit: bool
