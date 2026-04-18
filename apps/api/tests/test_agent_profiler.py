import asyncio
import httpx

from app.agent.profiler import profile_repo


class FakeGitHubClient:
    def __init__(self, files: dict[str, str]):
        self.files = files

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        if path not in self.files:
            request = httpx.Request("GET", f"https://example.com/{owner}/{repo}/{path}")
            response = httpx.Response(status_code=404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)
        return self.files[path]


def test_profile_repo_detects_frameworks_from_dependencies_and_files() -> None:
    fake_gh = FakeGitHubClient(
        files={
            "package.json": """
            {
                "dependencies": {
                    "next": "15.0.0",
                    "react": "19.0.0",
                    "@supabase/supabase-js": "2.0.0",
                    "drizzle-orm": "0.41.0",
                    "prisma": "5.0.0"
                }
            }
            """,
            "pyproject.toml": """
            [project]
            dependencies = ["fastapi>=0.111.0"]
            """,
            "app/layout.tsx": "export default function Layout(){ return null }",
            "prisma/schema.prisma": "model User { id Int @id }",
        }
    )

    profile = asyncio.run(profile_repo(fake_gh, "acme", "demo", "headsha"))

    assert "nextjs" in profile.frameworks
    assert "react" in profile.frameworks
    assert "supabase" in profile.frameworks
    assert "drizzle" in profile.frameworks
    assert "prisma" in profile.frameworks
    assert "fastapi" in profile.frameworks
    assert profile.conventions["routing"] == "app-router"
