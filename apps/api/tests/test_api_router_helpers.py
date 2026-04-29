"""Unit tests for pure functions in app.api.router.

These tests have no DB dependencies and no async requirements — they run fast
and serve as a stable baseline that is immune to Python-version coverage
instrumentation differences.

Endpoint integration tests live in test_api_router.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml
from fastapi import HTTPException

from app.agent.review_config import ReviewConfig
from app.api import router as api_router
from app.api.auth import CurrentDashboardUser
from app.db.models import Installation
from app.db.models import Review


# ---------------------------------------------------------------------------
# _findings_count_from_review_row
# ---------------------------------------------------------------------------


def test_findings_count_returns_count() -> None:
    review = SimpleNamespace(findings={"findings": [{"severity": "high"}, {"severity": "low"}]})
    assert api_router._findings_count_from_review_row(review) == 2  # type: ignore[attr-defined]


def test_findings_count_none_findings() -> None:
    assert api_router._findings_count_from_review_row(SimpleNamespace(findings=None)) == 0  # type: ignore[attr-defined]


def test_findings_count_non_dict() -> None:
    assert api_router._findings_count_from_review_row(SimpleNamespace(findings="bad")) == 0  # type: ignore[attr-defined]


def test_findings_count_non_list_value() -> None:
    review = SimpleNamespace(findings={"findings": "not-a-list"})
    assert api_router._findings_count_from_review_row(review) == 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _as_int_or_none
# ---------------------------------------------------------------------------


def test_as_int_or_none_int() -> None:
    assert api_router._as_int_or_none(42) == 42  # type: ignore[attr-defined]


def test_as_int_or_none_whole_float() -> None:
    assert api_router._as_int_or_none(3.0) == 3  # type: ignore[attr-defined]


def test_as_int_or_none_fractional_float() -> None:
    assert api_router._as_int_or_none(3.5) is None  # type: ignore[attr-defined]


def test_as_int_or_none_bool() -> None:
    assert api_router._as_int_or_none(True) is None  # type: ignore[attr-defined]


def test_as_int_or_none_string() -> None:
    assert api_router._as_int_or_none("42") is None  # type: ignore[attr-defined]


def test_as_int_or_none_none() -> None:
    assert api_router._as_int_or_none(None) is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# status filter helpers
# ---------------------------------------------------------------------------


def test_normalize_review_status_filter_maps_all_to_none() -> None:
    assert api_router._normalize_review_status_filter("all") is None  # type: ignore[attr-defined]


def test_normalize_review_status_filter_lowercases() -> None:
    assert api_router._normalize_review_status_filter(" RUNNING ") == "running"  # type: ignore[attr-defined]


def test_status_clause_running_matches_queued_or_running() -> None:
    clause = api_router._status_clause("running")  # type: ignore[attr-defined]
    compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
    assert "reviews.status = 'queued'" in compiled
    assert "reviews.status = 'running'" in compiled


# ---------------------------------------------------------------------------
# _diff_stats_from_debug_artifacts
# ---------------------------------------------------------------------------


def test_diff_stats_returns_values() -> None:
    review = SimpleNamespace(debug_artifacts={
        "fast_path_decision": {"changed_file_count": 5, "changed_line_count": 120}
    })
    files, lines = api_router._diff_stats_from_debug_artifacts(review)  # type: ignore[attr-defined]
    assert files == 5
    assert lines == 120


def test_diff_stats_none_artifacts() -> None:
    files, lines = api_router._diff_stats_from_debug_artifacts(SimpleNamespace(debug_artifacts=None))  # type: ignore[attr-defined]
    assert files is None and lines is None


def test_diff_stats_empty_artifacts() -> None:
    files, lines = api_router._diff_stats_from_debug_artifacts(SimpleNamespace(debug_artifacts={}))  # type: ignore[attr-defined]
    assert files is None and lines is None


def test_diff_stats_non_dict_fast_path() -> None:
    review = SimpleNamespace(debug_artifacts={"fast_path_decision": "bad"})
    files, lines = api_router._diff_stats_from_debug_artifacts(review)  # type: ignore[attr-defined]
    assert files is None and lines is None


# ---------------------------------------------------------------------------
# _validate_repo_segment
# ---------------------------------------------------------------------------


def test_validate_repo_segment_valid() -> None:
    result = api_router._validate_repo_segment("acme-org", "owner")  # type: ignore[attr-defined]
    assert result == "acme-org"


def test_validate_repo_segment_invalid_slash() -> None:
    from fastapi import HTTPException
    import pytest
    with pytest.raises(HTTPException) as exc_info:
        api_router._validate_repo_segment("bad/segment", "owner")  # type: ignore[attr-defined]
    assert exc_info.value.status_code == 400


def test_validate_repo_segment_empty() -> None:
    from fastapi import HTTPException
    import pytest
    with pytest.raises(HTTPException):
        api_router._validate_repo_segment("  ", "owner")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _extract_yaml_payload
# ---------------------------------------------------------------------------


def test_extract_yaml_strips_fenced_block() -> None:
    raw = "```yaml\nkey: value\n```"
    assert api_router._extract_yaml_payload(raw) == "key: value"  # type: ignore[attr-defined]


def test_extract_yaml_strips_yml_fence() -> None:
    raw = "```yml\nfoo: bar\n```"
    assert api_router._extract_yaml_payload(raw) == "foo: bar"  # type: ignore[attr-defined]


def test_extract_yaml_plain_text() -> None:
    raw = "key: value"
    assert api_router._extract_yaml_payload(raw) == "key: value"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _normalize_generated_config
# ---------------------------------------------------------------------------


def test_normalize_generated_config_defaults() -> None:
    config = api_router._normalize_generated_config({})  # type: ignore[attr-defined]
    assert isinstance(config, ReviewConfig)
    assert config.prompt_additions is None


def test_normalize_generated_config_with_fields() -> None:
    config = api_router._normalize_generated_config({  # type: ignore[attr-defined]
        "confidence_threshold": 90,
        "severity_threshold": "high",
        "categories": ["security", "correctness"],
    })
    assert config.confidence_threshold == 90
    assert config.severity_threshold == "high"
    assert "security" in config.categories


def test_normalize_generated_config_empty_prompt_additions() -> None:
    # Empty string prompt_additions should become None
    config = api_router._normalize_generated_config({"prompt_additions": ""})  # type: ignore[attr-defined]
    assert config.prompt_additions is None


def test_normalize_generated_config_whitespace_prompt_additions() -> None:
    config = api_router._normalize_generated_config({"prompt_additions": "   "})  # type: ignore[attr-defined]
    assert config.prompt_additions is None


def test_normalize_generated_config_with_prompt_additions() -> None:
    config = api_router._normalize_generated_config({"prompt_additions": "  focus on SQL  "})  # type: ignore[attr-defined]
    assert config.prompt_additions == "focus on SQL"


def test_normalize_generated_config_non_string_prompt_additions() -> None:
    # Non-string prompt_additions should become None (not isinstance str)
    config = api_router._normalize_generated_config({"prompt_additions": 42})  # type: ignore[attr-defined]
    assert config.prompt_additions is None


# ---------------------------------------------------------------------------
# _serialize_review_config_yaml
# ---------------------------------------------------------------------------


def test_serialize_review_config_yaml_roundtrips() -> None:
    config = ReviewConfig()
    text = api_router._serialize_review_config_yaml(config)  # type: ignore[attr-defined]
    parsed = yaml.safe_load(text)
    assert isinstance(parsed, dict)
    assert "confidence_threshold" in parsed
    assert "severity_threshold" in parsed


def test_serialize_review_config_yaml_decimal_as_float() -> None:
    config = ReviewConfig()
    text = api_router._serialize_review_config_yaml(config)  # type: ignore[attr-defined]
    parsed = yaml.safe_load(text)
    # Decimal fields converted to float so YAML doesn't emit !!python/object
    assert isinstance(parsed["model"]["input_per_1m_usd"], float)
    assert isinstance(parsed["model"]["output_per_1m_usd"], float)


def test_require_installation_access_raises_for_unlinked() -> None:
    with pytest.raises(HTTPException) as exc_info:
        api_router._require_installation_access({1, 2}, 3)  # type: ignore[attr-defined]
    assert exc_info.value.status_code == 404


def test_require_installation_access_allows_linked() -> None:
    api_router._require_installation_access({3, 4}, 3)  # type: ignore[attr-defined]


class _FakeGitHub:
    def __init__(self, payloads: dict[str, dict[str, object]]) -> None:
        self._payloads = payloads

    async def get_json(self, path: str) -> dict[str, object]:
        return self._payloads[path]


@pytest.mark.anyio
async def test_resolve_repo_head_sha_returns_sha() -> None:
    gh = _FakeGitHub(
        {
            "/repos/acme/repo": {"default_branch": "main"},
            "/repos/acme/repo/branches/main": {"commit": {"sha": "deadbeef"}},
        }
    )
    sha = await api_router._resolve_repo_head_sha(gh, "acme", "repo")  # type: ignore[attr-defined]
    assert sha == "deadbeef"


@pytest.mark.anyio
async def test_resolve_repo_head_sha_falls_back_to_branch_name() -> None:
    gh = _FakeGitHub(
        {
            "/repos/acme/repo": {"default_branch": "trunk"},
            "/repos/acme/repo/branches/trunk": {"commit": {}},
        }
    )
    sha = await api_router._resolve_repo_head_sha(gh, "acme", "repo")  # type: ignore[attr-defined]
    assert sha == "trunk"


@pytest.mark.anyio
async def test_list_installation_rows_returns_empty_when_filter_empty() -> None:
    session = _FakeSessionForListRows([])
    rows = await api_router._list_installation_rows(  # type: ignore[attr-defined]
        session,  # type: ignore[arg-type]
        installation_ids=set(),
    )
    assert rows == []


class _FakeScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeExecuteResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self._values)


class _FakeSessionForListRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    async def scalars(self, _stmt: object) -> _FakeScalarResult:
        return _FakeScalarResult(self._rows)


class _FakeSessionForAllowedInstallations:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    async def execute(self, _stmt: object) -> _FakeExecuteResult:
        return _FakeExecuteResult(self._values)


@pytest.mark.anyio
async def test_list_installation_rows_includes_rows_when_allowed() -> None:
    installation = Installation(
        installation_id=int(str(uuid4().int)[:9]),
        account_login="acme-suspended",
        account_type="Organization",
        suspended_at=datetime.now(timezone.utc),
    )
    session = _FakeSessionForListRows([installation])
    rows = await api_router._list_installation_rows(  # type: ignore[attr-defined]
        session,  # type: ignore[arg-type]
        installation_ids={int(installation.installation_id)},
        active_only=False,
    )
    assert len(rows) == 1
    assert int(rows[0].installation_id) == int(installation.installation_id)


@pytest.mark.anyio
async def test_allowed_installation_ids_casts_results_to_ints() -> None:
    session = _FakeSessionForAllowedInstallations([123, 456])
    allowed = await api_router._allowed_installation_ids(  # type: ignore[attr-defined]
        session,  # type: ignore[arg-type]
        CurrentDashboardUser(github_id=1, login="tester"),
    )
    assert allowed == {123, 456}


class _FakeSessionContext:
    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        return None


@pytest.mark.anyio
async def test_list_installations_direct_formats_output(monkeypatch: pytest.MonkeyPatch) -> None:
    session = object()
    monkeypatch.setattr(api_router, "AsyncSessionLocal", lambda: _FakeSessionContext(session))

    async def _fake_allowed(_session: object, _user: CurrentDashboardUser) -> set[int]:
        return {123}

    now = datetime.now(timezone.utc)

    async def _fake_list_rows(_session: object, **_kwargs: object) -> list[Installation]:
        return [
            Installation(
                installation_id=123,
                account_login="acme",
                account_type="Organization",
                suspended_at=None,
            ),
            Installation(
                installation_id=124,
                account_login="old-acme",
                account_type="Organization",
                suspended_at=now,
            ),
        ]

    monkeypatch.setattr(api_router, "_allowed_installation_ids", _fake_allowed)
    monkeypatch.setattr(api_router, "_list_installation_rows", _fake_list_rows)

    result = await api_router.list_installations(
        active_only=True,
        limit=50,
        current_user=CurrentDashboardUser(github_id=1, login="tester")
    )
    assert result[0]["installation_id"] == 123
    assert "active" in result[0]


class _FakeReviewSession:
    async def scalars(self, _stmt: object) -> _FakeScalarResult:
        review = Review(
            installation_id=321,
            repo_full_name="acme/repo",
            pr_number=9,
            pr_head_sha="a" * 40,
            status="done",
            model_provider="anthropic",
            model="claude-sonnet-4-5",
            findings={"findings": []},
            debug_artifacts={"fast_path_decision": {"changed_file_count": 3, "changed_line_count": 42}},
            tokens_used=10,
            cost_usd=0.01,
        )
        review.id = 99
        review.created_at = datetime.now(timezone.utc)
        review.completed_at = datetime.now(timezone.utc)
        return _FakeScalarResult([review])


class _FakeEmptyRepoSession:
    async def scalars(self, _stmt: object) -> _FakeScalarResult:
        return _FakeScalarResult([])


@pytest.mark.anyio
async def test_list_reviews_direct_installation_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeReviewSession()
    monkeypatch.setattr(api_router, "AsyncSessionLocal", lambda: _FakeSessionContext(session))

    async def _fake_allowed(_session: object, _user: CurrentDashboardUser) -> set[int]:
        return {321}

    async def _fake_set_ctx(_session: object, _installation_id: int) -> None:
        return None

    monkeypatch.setattr(api_router, "_allowed_installation_ids", _fake_allowed)
    monkeypatch.setattr(api_router, "set_installation_context", _fake_set_ctx)

    result = await api_router.list_reviews(
        installation_id=321,
        limit=50,
        current_user=CurrentDashboardUser(github_id=1, login="tester"),
    )
    assert len(result) == 1
    assert result[0]["id"] == 99


@pytest.mark.anyio
async def test_list_repos_direct_installation_branch_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeEmptyRepoSession()
    monkeypatch.setattr(api_router, "AsyncSessionLocal", lambda: _FakeSessionContext(session))

    async def _fake_allowed(_session: object, _user: CurrentDashboardUser) -> set[int]:
        return {321}

    async def _fake_set_ctx(_session: object, _installation_id: int) -> None:
        return None

    monkeypatch.setattr(api_router, "_allowed_installation_ids", _fake_allowed)
    monkeypatch.setattr(api_router, "set_installation_context", _fake_set_ctx)

    result = await api_router.list_repos(
        installation_id=321,
        limit=10,
        current_user=CurrentDashboardUser(github_id=1, login="tester"),
    )
    assert result == []
