from pydantic import BaseModel, ConfigDict, Field, field_validator


class GitHubInstallationAccount(BaseModel):
    login: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=100)


class GitHubInstallation(BaseModel):
    id: int = Field(ge=1)
    account: GitHubInstallationAccount | None = None


class GitHubRepositoryOwner(BaseModel):
    login: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=100)


class GitHubRepository(BaseModel):
    full_name: str = Field(min_length=3, max_length=255, pattern=r"^[^/]+/[^/]+$")
    owner: GitHubRepositoryOwner


class GitHubPullRequestHead(BaseModel):
    sha: str = Field(min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$")

    @field_validator("sha", mode="before")
    @classmethod
    def normalize_head_sha(cls, value: object) -> object:
        if isinstance(value, str):
            return value.lower()
        return value


class GitHubPullRequest(BaseModel):
    number: int = Field(ge=1)
    head: GitHubPullRequestHead
    draft: bool = False


class GitHubPullRequestWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str = Field(min_length=1, max_length=50)
    installation: GitHubInstallation
    repository: GitHubRepository
    pull_request: GitHubPullRequest


class GitHubInstallationWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str = Field(min_length=1, max_length=50)
    installation: GitHubInstallation
