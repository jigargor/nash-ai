import asyncio
import httpx

from app.agent.review_config import DEFAULT_CONFIDENCE_THRESHOLD, load_review_config


class FakeGitHubClient:
    def __init__(self, files: dict[str, str]):
        self.files = files

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        if path not in self.files:
            request = httpx.Request("GET", f"https://example.com/{owner}/{repo}/{path}")
            response = httpx.Response(status_code=404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)
        return self.files[path]


def test_load_review_config_uses_defaults_when_file_missing() -> None:
    config = asyncio.run(load_review_config(FakeGitHubClient({}), "acme", "demo", "sha"))
    assert config.confidence_threshold == DEFAULT_CONFIDENCE_THRESHOLD
    assert config.prompt_additions is None


def test_load_review_config_reads_threshold_and_prompt_additions() -> None:
    config = asyncio.run(
        load_review_config(
            FakeGitHubClient(
                {
                    ".codereview.yml": """
                    confidence_threshold: 0.9
                    prompt_additions: |
                      This repo uses generated types.
                    """
                }
            ),
            "acme",
            "demo",
            "sha",
        )
    )
    assert config.confidence_threshold == 0.9
    assert config.prompt_additions == "This repo uses generated types."
