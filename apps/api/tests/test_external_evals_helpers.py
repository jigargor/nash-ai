from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api import external_evals


def test_estimate_cost_applies_floor_and_rounding() -> None:
    estimated_tokens, estimated_cost = external_evals._estimate_cost(file_count=1, total_bytes=100)
    assert estimated_tokens == 1200
    assert str(estimated_cost) == "0.000240"


@pytest.mark.anyio
async def test_resolve_preflight_uses_ttl_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    external_evals._preflight_cache.clear()
    parse_calls = {"count": 0}
    resolve_calls = {"count": 0}
    list_calls = {"count": 0}

    def fake_parse_public_repo_url(repo_url: str) -> tuple[str, str]:
        parse_calls["count"] += 1
        assert repo_url == "https://github.com/acme/repo"
        return "acme", "repo"

    async def fake_resolve_repo_ref(owner: str, repo: str, target_ref: str | None) -> SimpleNamespace:
        resolve_calls["count"] += 1
        assert owner == "acme"
        assert repo == "repo"
        assert target_ref is None
        return SimpleNamespace(ref="main", default_branch="main")

    async def fake_list_repo_files(repo_ref: object) -> list[SimpleNamespace]:
        list_calls["count"] += 1
        assert getattr(repo_ref, "ref", None) == "main"
        return [SimpleNamespace(size_bytes=4000), SimpleNamespace(size_bytes=2000)]

    monkeypatch.setattr(external_evals, "parse_public_repo_url", fake_parse_public_repo_url)
    monkeypatch.setattr(external_evals, "resolve_repo_ref", fake_resolve_repo_ref)
    monkeypatch.setattr(external_evals, "list_repo_files", fake_list_repo_files)

    first = await external_evals._resolve_preflight(
        installation_id=99,
        repo_url="https://github.com/acme/repo",
        target_ref=None,
    )
    second = await external_evals._resolve_preflight(
        installation_id=99,
        repo_url="https://github.com/acme/repo",
        target_ref=None,
    )

    assert first.owner == "acme"
    assert first.repo == "repo"
    assert first.target_ref == "main"
    assert first.file_count == 2
    assert first.total_bytes == 6000
    assert first.estimated_tokens == 1500
    assert str(first.estimated_cost_usd) == "0.000300"
    assert second == first
    assert parse_calls["count"] == 1
    assert resolve_calls["count"] == 1
    assert list_calls["count"] == 1
