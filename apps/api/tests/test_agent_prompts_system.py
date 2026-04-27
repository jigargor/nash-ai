from app.agent.prompts.system import _load_file, build_system_prompt
from pathlib import Path


def test_build_system_prompt_loads_reviewer_assets() -> None:
    prompt = build_system_prompt(frameworks=[], diff="diff --git a/x b/x\n+print('ok')", repo_additions=None)
    assert "You are a senior code reviewer" in prompt


def test_load_file_falls_back_to_filesystem_when_importlib_resource_missing(monkeypatch) -> None:
    def _raise(*_args, **_kwargs):
        raise ModuleNotFoundError("simulated missing package resource")

    monkeypatch.setattr("app.agent.prompts.system.resources.files", _raise)
    content = _load_file("reviewer_system.md")
    assert "You are a senior code reviewer" in content


def test_load_file_uses_embedded_fallback_when_package_and_filesystem_assets_missing(monkeypatch) -> None:
    def _raise_resources(*_args, **_kwargs):
        raise ModuleNotFoundError("simulated missing package resource")

    def _raise_read_text(self: Path, *args, **kwargs):  # noqa: ARG001
        raise FileNotFoundError("simulated missing filesystem resource")

    monkeypatch.setattr("app.agent.prompts.system.resources.files", _raise_resources)
    monkeypatch.setattr(Path, "read_text", _raise_read_text)
    content = _load_file("reviewer_system.md")
    assert "senior code reviewer" in content
