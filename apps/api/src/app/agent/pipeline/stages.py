"""Stage protocol used by review_pipeline and (progressively) runner."""

from __future__ import annotations

from typing import Any, Protocol

from app.agent.pipeline.isolation import with_isolation


class Stage(Protocol):
    name: str

    async def run(self, context: dict[str, Any]) -> dict[str, Any]: ...


async def run_stage(
    stage: Stage,
    context: dict[str, Any],
    *,
    errors_out: list[str] | None = None,
    timeout_s: float | None = None,
    reraise: bool = False,
) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        return await stage.run(context)

    return await with_isolation(
        stage.name,
        _run,
        fallback=context,
        errors_out=errors_out,
        reraise=reraise,
        timeout_s=timeout_s,
    )
