from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str | None = None
    claude_model: str = "claude-sonnet-4-5"
    target_url: str = "http://127.0.0.1:8001"
    platform_url: str = "http://127.0.0.1:8000"
    headless: bool = False
    max_discovery_steps: int = 20
    artifact_dir: Path = Path("artifacts")
    evidence_dir: Path = Path("evidence")


settings = Settings()
