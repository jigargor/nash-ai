from app.agent.prompts.system import _load_file, build_system_prompt


def test_build_system_prompt_loads_reviewer_assets() -> None:
    prompt = build_system_prompt(frameworks=[], diff="diff --git a/x b/x\n+print('ok')", repo_additions=None)
    assert "You are a senior code reviewer" in prompt


def test_load_file_falls_back_to_filesystem_when_importlib_resource_missing(monkeypatch) -> None:
    def _raise(*_args, **_kwargs):
        raise ModuleNotFoundError("simulated missing package resource")

    monkeypatch.setattr("app.agent.prompts.system.resources.files", _raise)
    content = _load_file("reviewer_system.md")
    assert "You are a senior code reviewer" in content
