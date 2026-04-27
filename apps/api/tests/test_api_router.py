from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.api import router as api_router
from app.config import settings
from app.db.models import Installation, RepoConfig, Review, ReviewModelAudit
from app.db.session import AsyncSessionLocal, engine, set_installation_context


@dataclass
class _FakeJob:
    job_id: str


class _FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def enqueue_job(self, *args: object, **_kwargs: object) -> _FakeJob:
        self.calls.append(args)
        return _FakeJob(job_id=f"job-{len(self.calls)}")


def _random_installation_id() -> int:
    return int(str(uuid4().int)[:9])


def _auth_headers() -> dict[str, str]:
    if settings.api_access_key:
        return {"X-Api-Key": settings.api_access_key}
    return {}


async def _insert_installation(installation_id: int, *, suspended: bool = False) -> None:
    await engine.dispose()
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            Installation(
                installation_id=installation_id,
                account_login=f"acme-{installation_id}",
                account_type="Organization",
                suspended_at=datetime.now(timezone.utc) if suspended else None,
            )
        )
        await session.commit()


async def _insert_review(
    installation_id: int,
    *,
    repo_full_name: str = "acme/repo",
    status: str = "done",
    findings: dict[str, object] | None = None,
) -> int:
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = Review(
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            pr_number=7,
            pr_head_sha="a" * 40,
            status=status,
            model_provider="anthropic",
            model="claude-sonnet-4-5",
            findings=findings,
            debug_artifacts={},
            tokens_used=123,
            cost_usd=0.25,
        )
        session.add(review)
        await session.flush()
        review_id = int(review.id)
        await session.commit()
    return review_id


@pytest.fixture
def test_app() -> FastAPI:
    application = FastAPI()
    application.include_router(api_router.router)
    application.state.redis = _FakeRedis()
    return application


@pytest.fixture
async def client(test_app: FastAPI) -> httpx.AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


@pytest.mark.anyio
async def test_verify_api_access_allows_when_key_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_access_key", None)

    api_router._verify_api_access(None)


@pytest.mark.anyio
async def test_verify_api_access_rejects_invalid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_access_key", "secret")

    with pytest.raises(api_router.HTTPException) as exc_info:
        api_router._verify_api_access("wrong")
    assert exc_info.value.status_code == 401


@pytest.mark.anyio
async def test_list_installations_and_repos_include_template_state(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    review_id = await _insert_review(installation_id, repo_full_name="acme/repo")

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            RepoConfig(
                installation_id=installation_id,
                repo_full_name="acme/repo",
                ai_generated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    installation_response = await client.get("/api/v1/installations", headers=_auth_headers())
    assert installation_response.status_code == 200
    assert any(item["installation_id"] == installation_id for item in installation_response.json())

    repos_response = await client.get(
        f"/api/v1/repos?installation_id={installation_id}", headers=_auth_headers()
    )
    assert repos_response.status_code == 200
    payload = repos_response.json()
    assert len(payload) == 1
    assert payload[0]["latest_review_id"] == review_id
    assert payload[0]["ai_template_generated"] is True
    assert payload[0]["ai_template_generated_at"] is not None


@pytest.mark.anyio
async def test_generate_template_success_and_once_limit(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-anthropic-key")
    monkeypatch.setattr(
        api_router,
        "resolve_model_for_role",
        lambda _config, _role: SimpleNamespace(provider="openai", model="gpt-5.5"),
    )

    class _FakeGitHubClient:
        pass

    async def _fake_for_installation(_installation_id: int) -> _FakeGitHubClient:
        return _FakeGitHubClient()

    async def _fake_resolve_head_sha(_gh: object, _owner: str, _repo: str) -> str:
        return "main"

    async def _fake_profile_repo(
        _gh: object, _owner: str, _repo: str, _ref: str
    ) -> SimpleNamespace:
        return SimpleNamespace(frameworks=["fastapi"])

    async def _fake_generate_yaml(**_kwargs: object) -> str:
        return """
confidence_threshold: 0.9
severity_threshold: medium
categories: [security, correctness]
review_drafts: false
max_findings_per_pr: 20
ignore_paths: []
model:
  provider: openai
  name: gpt-5.5
"""

    monkeypatch.setattr(api_router.GitHubClient, "for_installation", _fake_for_installation)
    monkeypatch.setattr(api_router, "_resolve_repo_head_sha", _fake_resolve_head_sha)
    monkeypatch.setattr(api_router, "profile_repo", _fake_profile_repo)
    monkeypatch.setattr(api_router, "_generate_yaml_with_model", _fake_generate_yaml)

    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    first = await client.post(
        f"/api/v1/repos/acme/repo/codereview-template/generate?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert first.status_code == 200
    body = first.json()
    assert body["repo_full_name"] == "acme/repo"
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-5.5"
    assert "confidence_threshold" in body["config_yaml_text"]

    second = await client.post(
        f"/api/v1/repos/acme/repo/codereview-template/generate?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert second.status_code == 429


@pytest.mark.anyio
async def test_generate_template_rejects_malformed_yaml(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-anthropic-key")
    monkeypatch.setattr(
        api_router,
        "resolve_model_for_role",
        lambda _config, _role: SimpleNamespace(provider="openai", model="gpt-5.5"),
    )

    async def _fake_for_installation(_installation_id: int) -> object:
        return object()

    async def _fake_resolve_head_sha(_gh: object, _owner: str, _repo: str) -> str:
        return "main"

    async def _fake_profile_repo(
        _gh: object, _owner: str, _repo: str, _ref: str
    ) -> SimpleNamespace:
        return SimpleNamespace(frameworks=["fastapi"])

    async def _bad_yaml(**_kwargs: object) -> str:
        return "invalid: [yaml"

    monkeypatch.setattr(api_router.GitHubClient, "for_installation", _fake_for_installation)
    monkeypatch.setattr(api_router, "_resolve_repo_head_sha", _fake_resolve_head_sha)
    monkeypatch.setattr(api_router, "profile_repo", _fake_profile_repo)
    monkeypatch.setattr(api_router, "_generate_yaml_with_model", _bad_yaml)

    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    response = await client.post(
        f"/api/v1/repos/acme/repo/codereview-template/generate?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Generated config was malformed YAML."


@pytest.mark.anyio
async def test_telemetry_outcomes_summary_uses_public_summarizer(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)

    async def _fake_summary(
        *, installation_id: int | None = None, repo_full_name: str | None = None
    ) -> dict[str, object]:
        assert installation_id == 777
        assert repo_full_name == "acme/repo"
        return {
            "total_classified": 3,
            "global_metrics": {"useful_rate": 2 / 3},
            "outcomes": {"applied_directly": 2},
        }

    monkeypatch.setattr(api_router, "summarize_finding_outcomes", _fake_summary)

    response = await client.get(
        "/api/v1/telemetry/outcomes/summary?installation_id=777&repo_full_name=acme/repo",
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["installation_id"] == 777
    assert payload["repo_full_name"] == "acme/repo"
    assert payload["total_classified"] == 3
    assert payload["global_metrics"]["useful_rate"] == pytest.approx(2 / 3)


@pytest.mark.anyio
async def test_rerun_review_enqueues_job_and_resets_status(
    client: httpx.AsyncClient,
    test_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-anthropic-key")
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    review_id = await _insert_review(installation_id, status="failed")

    response = await client.post(
        f"/api/v1/reviews/{review_id}/rerun?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["review_id"] == review_id
    assert payload["job_id"] == "job-1"

    redis = test_app.state.redis
    assert isinstance(redis, _FakeRedis)
    assert len(redis.calls) == 1
    assert redis.calls[0][0] == "review_pr"

    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        assert review is not None
        assert review.status == "queued"


@pytest.mark.anyio
async def test_dismiss_finding_is_idempotent(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    review_id = await _insert_review(installation_id, findings={"findings": []})

    first = await client.post(
        f"/api/v1/reviews/{review_id}/findings/3/dismiss?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/v1/reviews/{review_id}/findings/3/dismiss?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert second.status_code == 200

    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        assert review is not None
        assert isinstance(review.debug_artifacts, dict)
        assert review.debug_artifacts.get("dismissed_findings") == [3]


@pytest.mark.anyio
async def test_list_reviews_with_installation_id(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    await _insert_review(installation_id, repo_full_name="acme/listed-repo")

    resp = await client.get(
        f"/api/v1/reviews?installation_id={installation_id}", headers=_auth_headers()
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(item["repo_full_name"] == "acme/listed-repo" for item in data)


@pytest.mark.anyio
async def test_list_reviews_without_installation_id_returns_all(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    await _insert_review(installation_id, repo_full_name="acme/global-repo")

    resp = await client.get("/api/v1/reviews", headers=_auth_headers())
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.anyio
async def test_get_review_returns_review(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    review_id = await _insert_review(installation_id)

    resp = await client.get(
        f"/api/v1/reviews/{review_id}?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == review_id


@pytest.mark.anyio
async def test_get_review_not_found_returns_404(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    await engine.dispose()
    resp = await client.get("/api/v1/reviews/9999999", headers=_auth_headers())
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_review_installation_mismatch_returns_400(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    other_installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    await _insert_installation(other_installation_id)
    review_id = await _insert_review(installation_id)

    resp = await client.get(
        f"/api/v1/reviews/{review_id}?installation_id={other_installation_id}",
        headers=_auth_headers(),
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_validate_repo_segment_rejects_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import router as api_router
    with pytest.raises(api_router.HTTPException) as exc_info:
        api_router._validate_repo_segment("bad/segment", "owner")
    assert exc_info.value.status_code == 400


@pytest.mark.anyio
async def test_extract_yaml_payload_strips_fenced_block() -> None:
    from app.api import router as api_router
    raw = "```yaml\nkey: value\n```"
    assert api_router._extract_yaml_payload(raw) == "key: value"


@pytest.mark.anyio
async def test_stream_review_events_returns_not_found_event(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    await engine.dispose()

    class _MissingSession:
        async def get(self, _model: object, _review_id: int) -> None:
            return None

    class _MissingSessionContext:
        async def __aenter__(self) -> _MissingSession:
            return _MissingSession()

        async def __aexit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
            return None

    monkeypatch.setattr(api_router, "AsyncSessionLocal", lambda: _MissingSessionContext())

    response = await client.get("/api/v1/reviews/999999/stream", headers=_auth_headers())
    assert response.status_code == 200
    assert "Review not found" in response.text


# ---------------------------------------------------------------------------
# Additional endpoint coverage: outcomes, model-audits, codereview-config, list_repos
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_review_outcomes_returns_empty_list(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    review_id = await _insert_review(installation_id, findings={"findings": []})

    resp = await client.get(
        f"/api/v1/reviews/{review_id}/outcomes?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_id"] == review_id
    assert body["finding_outcomes"] == []


@pytest.mark.anyio
async def test_get_review_outcomes_not_found(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    await engine.dispose()
    resp = await client.get("/api/v1/reviews/9999998/outcomes", headers=_auth_headers())
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_review_model_audits_empty(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    review_id = await _insert_review(installation_id)

    resp = await client.get(
        f"/api/v1/reviews/{review_id}/model-audits?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_id"] == review_id
    assert body["model_audits"] == []


@pytest.mark.anyio
async def test_get_review_model_audits_with_data(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    review_id = await _insert_review(installation_id)

    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            ReviewModelAudit(
                review_id=review_id,
                installation_id=installation_id,
                run_id="run-abc",
                stage="primary",
                provider="anthropic",
                model="claude-sonnet-4-5",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                findings_count=2,
            )
        )
        await session.commit()

    resp = await client.get(
        f"/api/v1/reviews/{review_id}/model-audits?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    audits = resp.json()["model_audits"]
    assert len(audits) == 1
    assert audits[0]["stage"] == "primary"
    assert audits[0]["total_tokens"] == 150


@pytest.mark.anyio
async def test_get_review_model_audits_not_found(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    await engine.dispose()
    resp = await client.get("/api/v1/reviews/9999997/model-audits", headers=_auth_headers())
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_list_repos_with_installation_id(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    await _insert_review(installation_id, repo_full_name="acme/repo-list-test")

    resp = await client.get(
        f"/api/v1/repos?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    repos = resp.json()
    assert any(r["repo_full_name"] == "acme/repo-list-test" for r in repos)


@pytest.mark.anyio
async def test_list_repos_failed_review_counted(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    await _insert_review(installation_id, repo_full_name="acme/fail-repo", status="failed")

    resp = await client.get(
        f"/api/v1/repos?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    repo = next(r for r in resp.json() if r["repo_full_name"] == "acme/fail-repo")
    assert repo["failed_review_count"] == 1


@pytest.mark.anyio
async def test_get_repo_codereview_config_not_found(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    async def _fake_for_installation(_iid: int) -> object:
        return object()

    async def _fake_safe_fetch(_gh: object, _o: str, _r: str, _p: str, _ref: str) -> None:
        return None

    monkeypatch.setattr(api_router.GitHubClient, "for_installation", _fake_for_installation)
    monkeypatch.setattr(api_router, "safe_fetch_file", _fake_safe_fetch)

    resp = await client.get(
        f"/api/v1/repos/acme/repo/codereview-config?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["found"] is False
    assert resp.json()["yaml_text"] is None


@pytest.mark.anyio
async def test_get_repo_codereview_config_found(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    async def _fake_for_installation(_iid: int) -> object:
        return object()

    async def _fake_safe_fetch(_gh: object, _o: str, _r: str, _p: str, _ref: str) -> str:
        return "confidence_threshold: 90\nseverity_threshold: high\n"

    monkeypatch.setattr(api_router.GitHubClient, "for_installation", _fake_for_installation)
    monkeypatch.setattr(api_router, "safe_fetch_file", _fake_safe_fetch)

    resp = await client.get(
        f"/api/v1/repos/acme/repo/codereview-config?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["config_json"]["confidence_threshold"] == 90
