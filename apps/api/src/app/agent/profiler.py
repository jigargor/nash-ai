import json
from dataclasses import dataclass, field

import httpx

from app.github.client import GitHubClient


@dataclass
class RepoProfile:
    frameworks: list[str] = field(default_factory=list)
    conventions: dict[str, str] = field(default_factory=dict)


async def profile_repo(gh: GitHubClient, owner: str, repo: str, ref: str) -> RepoProfile:
    profile = RepoProfile()

    await _profile_package_json(gh, owner, repo, ref, profile)
    await _profile_pyproject(gh, owner, repo, ref, profile)
    await _profile_by_file_presence(gh, owner, repo, ref, profile)

    profile.frameworks = sorted(set(profile.frameworks))
    return profile


async def _profile_package_json(
    gh: GitHubClient,
    owner: str,
    repo: str,
    ref: str,
    profile: RepoProfile,
) -> None:
    try:
        package_json = await gh.get_file_content(owner, repo, "package.json", ref)
    except httpx.HTTPStatusError:
        return
    except Exception:
        return

    try:
        parsed = json.loads(package_json)
    except json.JSONDecodeError:
        return

    dependencies = {**parsed.get("dependencies", {}), **parsed.get("devDependencies", {})}
    if "next" in dependencies:
        profile.frameworks.append("nextjs")
    if "react" in dependencies:
        profile.frameworks.append("react")
    if "@supabase/supabase-js" in dependencies:
        profile.frameworks.append("supabase")
    if "drizzle-orm" in dependencies:
        profile.frameworks.append("drizzle")
    if "prisma" in dependencies:
        profile.frameworks.append("prisma")
    if "zod" in dependencies:
        profile.conventions["validation"] = "zod"


async def _profile_pyproject(
    gh: GitHubClient,
    owner: str,
    repo: str,
    ref: str,
    profile: RepoProfile,
) -> None:
    try:
        pyproject = (await gh.get_file_content(owner, repo, "pyproject.toml", ref)).lower()
    except httpx.HTTPStatusError:
        return
    except Exception:
        return

    if "fastapi" in pyproject:
        profile.frameworks.append("fastapi")
    if "django" in pyproject:
        profile.frameworks.append("django")


async def _profile_by_file_presence(
    gh: GitHubClient,
    owner: str,
    repo: str,
    ref: str,
    profile: RepoProfile,
) -> None:
    checks = {
        "app/layout.tsx": ("nextjs", "routing", "app-router"),
        "pages/_app.tsx": ("nextjs", "routing", "pages-router"),
        "supabase/config.toml": ("supabase", None, None),
        "prisma/schema.prisma": ("prisma", None, None),
    }
    for path, metadata in checks.items():
        framework, convention_key, convention_value = metadata
        try:
            await gh.get_file_content(owner, repo, path, ref)
        except Exception:
            continue
        profile.frameworks.append(framework)
        if convention_key and convention_value:
            profile.conventions[convention_key] = convention_value
