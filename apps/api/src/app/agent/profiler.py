import json
from dataclasses import dataclass, field

from app.github.client import GitHubClient
from app.github.utils import safe_fetch_file


@dataclass
class RepoProfile:
    frameworks: list[str] = field(default_factory=list)
    conventions: dict[str, str] = field(default_factory=dict)


async def profile_repo(gh: GitHubClient, owner: str, repo: str, ref: str) -> RepoProfile:
    # Import here to avoid circular imports at module load time
    from app.agent.profiler_cache import get_cached_repo_profile, set_cached_repo_profile

    cached = await get_cached_repo_profile(owner, repo, ref)
    if cached is not None:
        return cached

    profile = RepoProfile()
    await _profile_package_json(gh, owner, repo, ref, profile)
    await _profile_pyproject(gh, owner, repo, ref, profile)
    await _profile_by_file_presence(gh, owner, repo, ref, profile)
    profile.frameworks = sorted(set(profile.frameworks))

    await set_cached_repo_profile(owner, repo, ref, profile)
    return profile


async def _profile_package_json(
    gh: GitHubClient,
    owner: str,
    repo: str,
    ref: str,
    profile: RepoProfile,
) -> None:
    package_json = await safe_fetch_file(gh, owner, repo, "package.json", ref)
    if package_json is None:
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
    raw = await safe_fetch_file(gh, owner, repo, "pyproject.toml", ref)
    if raw is None:
        return
    pyproject = raw.lower()
    if "fastapi" in pyproject:
        profile.frameworks.append("fastapi")
    if "django" in pyproject:
        profile.frameworks.append("django")


async def _repo_has_file(gh: GitHubClient, owner: str, repo: str, path: str, ref: str) -> bool:
    return await safe_fetch_file(gh, owner, repo, path, ref) is not None


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
        if not await _repo_has_file(gh, owner, repo, path, ref):
            continue
        profile.frameworks.append(framework)
        if convention_key and convention_value:
            profile.conventions[convention_key] = convention_value
