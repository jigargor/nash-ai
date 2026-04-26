from types import SimpleNamespace

import pytest

from app.agent import loop


class _FakeMessagesApi:
    def __init__(self, responses: list[object]) -> None:
        self._responses = responses
        self._index = 0

    async def create(self, **_: object) -> object:
        response = self._responses[self._index]
        self._index += 1
        return response


class _FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.messages = _FakeMessagesApi(responses)


def _response(stop_reason: str, content: list[object], input_tokens: int = 10, output_tokens: int = 5) -> object:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=content,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


@pytest.mark.anyio
async def test_run_agent_end_turn_records_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    context: dict[str, object] = {}
    monkeypatch.setattr(loop, "create_async_anthropic_client", lambda _api_key: _FakeClient([_response("end_turn", [])]))

    messages = await loop.run_agent("system", "user", context)

    assert len(messages) == 2
    assert context["tokens_used"] == 15
    assert context["agent_metrics"]["turn_count"] == 1
    assert context["agent_metrics"]["fetch_file_content_calls"] == 0
    assert context["agent_metrics"]["first_model_call_latency_ms"] >= 0


@pytest.mark.anyio
async def test_run_agent_tool_use_executes_tools_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_block = SimpleNamespace(type="tool_use", name="fetch_file_content", id="tool-1", input={"path": "a.py"})
    responses = [
        _response("tool_use", [tool_block]),
        _response("end_turn", []),
    ]
    context: dict[str, object] = {}
    monkeypatch.setattr(loop, "create_async_anthropic_client", lambda _api_key: _FakeClient(responses))

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


@pytest.mark.anyio
async def test_run_agent_stops_after_max_iterations(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_block = SimpleNamespace(type="tool_use", name="search_codebase", id="tool-1", input={"pattern": "jwt"})
    monkeypatch.setattr(loop, "MAX_ITERATIONS", 2)
    monkeypatch.setattr(
        loop,
        "create_async_anthropic_client",
        lambda _api_key: _FakeClient([_response("tool_use", [tool_block]), _response("tool_use", [tool_block])]),
    )

    async def fake_execute_tool(*_args: object, **_kwargs: object) -> str:
        return "ok"

    monkeypatch.setattr(loop, "execute_tool", fake_execute_tool)

    context: dict[str, object] = {}
    messages = await loop.run_agent("system", "user", context)

    assert context["agent_metrics"]["turn_count"] == 2
    assert len(messages) >= 3
