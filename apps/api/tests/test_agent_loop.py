from types import SimpleNamespace

import pytest

from app.agent import loop


class _FakeMessagesApi:
    def __init__(self, responses: list[object]) -> None:
        self._responses = responses
        self._index = 0
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = self._responses[self._index]
        self._index += 1
        return response


class _FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.messages = _FakeMessagesApi(responses)


def _response(
    stop_reason: str, content: list[object], input_tokens: int = 10, output_tokens: int = 5
) -> object:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=content,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _fake_provider_api_key(
    _provider: object, *, user_key_override: str | None = None
) -> str:
    return user_key_override or "test-api-key"


@pytest.mark.anyio
async def test_run_agent_end_turn_records_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    context: dict[str, object] = {}
    monkeypatch.setattr(loop, "get_provider_api_key", _fake_provider_api_key)
    monkeypatch.setattr(
        loop,
        "create_async_anthropic_client",
        lambda _api_key: _FakeClient([_response("end_turn", [])]),
    )

    messages = await loop.run_agent("system", "user", context)

    assert len(messages) == 2
    assert context["tokens_used"] == 15
    assert context["agent_metrics"]["turn_count"] == 1
    assert context["agent_metrics"]["fetch_file_content_calls"] == 0
    assert context["agent_metrics"]["first_model_call_latency_ms"] >= 0
    assert context["agent_metrics"]["tool_result_tokens_total"] == 0


@pytest.mark.anyio
async def test_run_agent_tool_use_executes_tools_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_block = SimpleNamespace(
        type="tool_use", name="fetch_file_content", id="tool-1", input={"path": "a.py"}
    )
    responses = [
        _response("tool_use", [tool_block]),
        _response("end_turn", []),
    ]
    context: dict[str, object] = {}
    monkeypatch.setattr(loop, "get_provider_api_key", _fake_provider_api_key)
    monkeypatch.setattr(
        loop, "create_async_anthropic_client", lambda _api_key: _FakeClient(responses)
    )

    async def fake_execute_tool(name: str, tool_input: dict, _context: dict) -> str:
        assert name == "fetch_file_content"
        assert tool_input["path"] == "a.py"
        return "file-content"

    monkeypatch.setattr(loop, "execute_tool", fake_execute_tool)
    messages = await loop.run_agent("system", "user", context)

    assert len(messages) == 4
    assert messages[2]["role"] == "user"
    assert context["tokens_used"] == 30
    assert context["agent_metrics"]["turn_count"] == 2
    assert context["agent_metrics"]["fetch_file_content_calls"] == 1
    assert context["agent_metrics"]["first_model_call_latency_ms"] >= 0
    assert context["agent_metrics"]["tool_result_calls_by_tool"]["fetch_file_content"] == 1
    assert context["agent_metrics"]["tool_result_tokens_total"] > 0


@pytest.mark.anyio
async def test_run_agent_stops_after_max_iterations(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_block = SimpleNamespace(
        type="tool_use", name="search_codebase", id="tool-1", input={"pattern": "jwt"}
    )
    monkeypatch.setattr(loop, "MAX_ITERATIONS", 2)
    monkeypatch.setattr(loop, "get_provider_api_key", _fake_provider_api_key)
    monkeypatch.setattr(
        loop,
        "create_async_anthropic_client",
        lambda _api_key: _FakeClient(
            [_response("tool_use", [tool_block]), _response("tool_use", [tool_block])]
        ),
    )

    async def fake_execute_tool(*_args: object, **_kwargs: object) -> str:
        return "ok"

    monkeypatch.setattr(loop, "execute_tool", fake_execute_tool)

    context: dict[str, object] = {}
    messages = await loop.run_agent("system", "user", context)

    assert context["agent_metrics"]["turn_count"] == 2
    assert len(messages) >= 3


@pytest.mark.anyio
async def test_run_agent_anthropic_calls_use_zero_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient([_response("end_turn", [])])
    monkeypatch.setattr(loop, "get_provider_api_key", _fake_provider_api_key)
    monkeypatch.setattr(loop, "create_async_anthropic_client", lambda _api_key: client)

    await loop.run_agent("system", "user", {})

    assert client.messages.calls[0]["temperature"] == 0
    assert client.messages.calls[0]["max_tokens"] == 4096


@pytest.mark.anyio
async def test_run_agent_max_tokens_breaks_without_executing_truncated_tool_use(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    truncated_tool = SimpleNamespace(
        type="tool_use", name="fetch_file_content", id="tool-1", input={"path": "a.py"}
    )
    text_block = SimpleNamespace(type="text", text="partial analysis")
    client = _FakeClient(
        [
            _response("max_tokens", [text_block, truncated_tool]),
            # A second response must never be requested after truncation.
            _response("end_turn", []),
        ]
    )
    executed: list[str] = []

    async def fake_execute_tool(name: str, *_args: object, **_kwargs: object) -> str:
        executed.append(name)
        return "should-not-run"

    monkeypatch.setattr(loop, "get_provider_api_key", _fake_provider_api_key)
    monkeypatch.setattr(loop, "create_async_anthropic_client", lambda _api_key: client)
    monkeypatch.setattr(loop, "execute_tool", fake_execute_tool)
    context: dict[str, object] = {}

    with caplog.at_level("WARNING", logger=loop.logger.name):
        messages = await loop.run_agent("system", "user", context)

    assert executed == []
    assert len(client.messages.calls) == 1
    assert context["agent_truncated"] is True
    assert context["agent_metrics"]["turn_count"] == 1
    # The cut-off tool_use block is stripped so the transcript has no dangling tool_use.
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == [text_block]
    assert any("max_tokens" in record.getMessage() for record in caplog.records)


@pytest.mark.anyio
async def test_run_agent_max_tokens_with_only_tool_use_drops_assistant_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    truncated_tool = SimpleNamespace(
        type="tool_use", name="fetch_file_content", id="tool-1", input={}
    )
    client = _FakeClient([_response("max_tokens", [truncated_tool])])
    monkeypatch.setattr(loop, "get_provider_api_key", _fake_provider_api_key)
    monkeypatch.setattr(loop, "create_async_anthropic_client", lambda _api_key: client)

    messages = await loop.run_agent("system", "user", {})

    assert [message["role"] for message in messages] == ["user"]


@pytest.mark.anyio
async def test_run_agent_logs_warning_when_max_iterations_is_hit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    tool_block = SimpleNamespace(
        type="tool_use", name="search_codebase", id="tool-1", input={"pattern": "jwt"}
    )
    monkeypatch.setattr(loop, "MAX_ITERATIONS", 2)
    monkeypatch.setattr(loop, "get_provider_api_key", _fake_provider_api_key)
    monkeypatch.setattr(
        loop,
        "create_async_anthropic_client",
        lambda _api_key: _FakeClient(
            [_response("tool_use", [tool_block]), _response("tool_use", [tool_block])]
        ),
    )

    async def fake_execute_tool(*_args: object, **_kwargs: object) -> str:
        return "ok"

    monkeypatch.setattr(loop, "execute_tool", fake_execute_tool)

    with caplog.at_level("WARNING", logger=loop.logger.name):
        await loop.run_agent("system", "user", {})

    assert any("MAX_ITERATIONS" in record.getMessage() for record in caplog.records)


@pytest.mark.anyio
async def test_run_agent_does_not_warn_about_max_iterations_on_normal_finish(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(loop, "get_provider_api_key", _fake_provider_api_key)
    monkeypatch.setattr(
        loop,
        "create_async_anthropic_client",
        lambda _api_key: _FakeClient([_response("end_turn", [])]),
    )

    with caplog.at_level("WARNING", logger=loop.logger.name):
        await loop.run_agent("system", "user", {})

    assert not any("MAX_ITERATIONS" in record.getMessage() for record in caplog.records)


@pytest.mark.anyio
async def test_run_agent_anthropic_attaches_cache_control_to_tools_and_user_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient([_response("end_turn", [])])
    monkeypatch.setattr(loop, "get_provider_api_key", _fake_provider_api_key)
    monkeypatch.setattr(loop, "create_async_anthropic_client", lambda _api_key: client)
    original_last_tool = dict(loop.TOOLS[-1])

    await loop.run_agent("system", "big user prompt", {})

    call = client.messages.calls[0]
    tools = call["tools"]
    assert [tool.get("cache_control") for tool in tools[:-1]] == [None] * (len(tools) - 1)
    assert tools[-1]["cache_control"] == {"type": "ephemeral"}
    # Module-level TOOLS must stay untouched so OpenAI/Gemini conversion is unaffected.
    assert "cache_control" not in loop.TOOLS[-1]
    assert loop.TOOLS[-1] == original_last_tool
    first_message = call["messages"][0]
    assert first_message["content"] == [
        {"type": "text", "text": "big user prompt", "cache_control": {"type": "ephemeral"}}
    ]


@pytest.mark.anyio
async def test_run_agent_anthropic_keeps_empty_user_message_plain_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient([_response("end_turn", [])])
    monkeypatch.setattr(loop, "get_provider_api_key", _fake_provider_api_key)
    monkeypatch.setattr(loop, "create_async_anthropic_client", lambda _api_key: client)

    await loop.run_agent("system", "   ", {})

    # Empty-message guard short-circuits before any API call (no cache_control on empty text).
    assert client.messages.calls == []