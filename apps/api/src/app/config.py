from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    github_app_id: str
    github_webhook_secret: str
    github_private_key_path: Path = Path("private-key.pem")
    github_client_id: str
    github_client_secret: str
    database_url: str
    redis_url: str = "redis://localhost:6379"
    fernet_key: str
    anthropic_api_key: str
    environment: str = "development"

    class Config:
        env_file = ".env"


settings = Settings()  # type: ignore[call-arg]
