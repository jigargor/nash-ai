from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.agent import editor as editor_module
from app.agent import fast_path as fast_path_module
from app.agent.diff_parser import FileInDiff, NumberedLine
from app.agent.fast_path import run_fast_path_prepass
from app.agent.review_config import ModelProvider
from app.agent.schema import ReviewResult


class _FakeAdapter:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    async def structured_output(self, *, request: object) -> object:  # noqa: ARG002
        return type("Result", (), {"payload": self.payload})()


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini"])
async def test_run_editor_returns_identical_payload_across_providers(
    monkeypatch: pytest.MonkeyPatch,
    provider: ModelProvider,
) -> None:
    payload = {
        "summary": "Edited summary",
        "findings": [
            {
                "severity": "medium",
                "category": "correctness",
                "message": "Adjusted finding message.",
                "file_path": "apps/api/src/app/main.py",
                "line_start": 1,
                "target_line_content": "pass",
                "confidence": 80,
                "evidence": "diff_visible",
            }
        ],
        "decisions": [{"original_index": 0, "action": "keep", "reason": "valid"}],
    }
    monkeypatch.setattr(
        editor_module, "get_provider_adapter", lambda _provider: _FakeAdapter(payload)
    )
    draft = ReviewResult.model_validate({"summary": "Draft", "findings": payload["findings"]})
    out = await editor_module.run_editor(
        draft=draft,
        pr_context={"title": "T"},
        prior_reviews=[],
        code_acknowledgments=[],
        model_name="model",
        provider=provider,
        context={},
    )
    assert out.summary == "Edited summary"
    assert len(out.findings) == 1
    assert out.decisions[0].action == "keep"


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini"])
async def test_run_fast_path_prepass_returns_identical_payload_across_providers(
    monkeypatch: pytest.MonkeyPatch,
    provider: ModelProvider,
) -> None:
    payload = {
        "decision": "light_review",
        "risk_labels": ["low_risk"],
        "reason": "Small low-risk change.",
        "confidence": 92,
        "review_surface": ["src/app.py"],
        "requires_full_context": False,
    }
    monkeypatch.setattr(
        fast_path_module, "get_provider_adapter", lambda _provider: _FakeAdapter(payload)
    )
    files = [
        FileInDiff(
            path="src/app.py",
            language="Python",
            is_new=False,
            is_deleted=False,
            numbered_lines=[
                NumberedLine(new_line_no=1, old_line_no=1, kind="add", content="print('x')")
            ],
            context_window=[],
        )
    ]
    decision, _, _, _ = await run_fast_path_prepass(
        files_in_diff=files,
        diff_text="diff --git a/src/app.py b/src/app.py\n+print('x')",
        pr={"title": "t", "body": ""},
        commits=[],
        generated_paths=[],
        vendor_paths=[],
        config=fast_path_module.FastPathConfig(),
        context={},
        model_name="model",
        provider=provider,
    )
    assert decision.decision == "light_review"
    assert decision.confidence == 92


def test_callers_do_not_import_provider_specific_clients() -> None:
    finalize_text = Path("src/app/agent/finalize.py").read_text(encoding="utf-8")
    editor_text = Path("src/app/agent/editor.py").read_text(encoding="utf-8")
    fast_path_text = Path("src/app/agent/fast_path.py").read_text(encoding="utf-8")

    for text in (finalize_text, editor_text, fast_path_text):
        assert "create_async_anthropic_client" not in text
        assert "create_openai_compatible_client" not in text
        assert "anthropic_tools_to_openai_tools" not in text
