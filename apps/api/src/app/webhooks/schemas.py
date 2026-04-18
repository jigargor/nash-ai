from pydantic import BaseModel, ConfigDict, Field


class GitHubInstallation(BaseModel):
    id: int = Field(ge=1)


class GitHubRepositoryOwner(BaseModel):
    login: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=100)


class GitHubRepository(BaseModel):
    full_name: str = Field(min_length=3, max_length=255, pattern=r"^[^/]+/[^/]+$")
    owner: GitHubRepositoryOwner


class GitHubPullRequestHead(BaseModel):
    sha: str = Field(min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$")


class GitHubPullRequest(BaseModel):
    number: int = Field(ge=1)
    head: GitHubPullRequestHead


class GitHubPullRequestWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str = Field(min_length=1, max_length=50)
    installation: GitHubInstallation
    repository: GitHubRepository
    pull_request: GitHubPullRequest
