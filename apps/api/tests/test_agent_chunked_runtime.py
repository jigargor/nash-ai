from __future__ import annotations

from app.agent.chunked_runtime import chunk_state_key


def test_chunk_state_key_is_deterministic_and_hides_raw_values() -> None:
    context = {
        "repo": "acme/private-repo",
        "pr_number": 123,
        "head_sha": "deadbeef" * 5,
        "chunking_config_hash": "cfg-hash",
    }
    left = chunk_state_key(context)
    right = chunk_state_key(dict(context))

    assert left == right
    assert left.startswith("chunking:")
    assert len(left.split(":", 1)[1]) == 64
    assert "private-repo" not in left
    assert context["head_sha"] not in left


def test_chunk_state_key_changes_when_inputs_change() -> None:
    base = chunk_state_key(
        {
            "repo": "acme/repo",
            "pr_number": 1,
            "head_sha": "a" * 40,
            "chunking_config_hash": "cfg-a",
        }
    )
    changed = chunk_state_key(
        {
            "repo": "acme/repo",
            "pr_number": 1,
            "head_sha": "b" * 40,
            "chunking_config_hash": "cfg-a",
        }
    )
    assert base != changed
