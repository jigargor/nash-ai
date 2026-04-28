from __future__ import annotations

from app.agent.external.types import PrepassPlan


def recommended_team_size(plan: PrepassPlan) -> int:
    if plan.service_tier == "high":
        return max(plan.shard_count, 16)
    if plan.service_tier == "balanced":
        return max(plan.shard_count, 8)
    return max(plan.shard_count, 4)


def recommended_model_distribution(plan: PrepassPlan) -> dict[str, int]:
    team_size = recommended_team_size(plan)
    if plan.service_tier == "high":
        return {"economy": max(team_size - 6, 8), "balanced": 4, "high": 2}
    if plan.service_tier == "balanced":
        return {"economy": max(team_size - 3, 4), "balanced": 2, "high": 1}
    return {"economy": max(team_size - 1, 3), "balanced": 1, "high": 0}

