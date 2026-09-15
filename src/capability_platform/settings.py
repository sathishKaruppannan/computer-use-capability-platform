from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str | None = None
    claude_model: str = "claude-sonnet-4-5"
    # Optional fallback used mid-discovery if a single Anthropic call errors — not a default
    # provider swap. See agent/discovery.py's per-call fallback in _decide().
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    target_url: str = "http://127.0.0.1:8001"
    platform_url: str = "http://127.0.0.1:8000"
    headless: bool = False
    max_discovery_steps: int = 20
    artifact_dir: Path = Path("artifacts")
    evidence_dir: Path = Path("evidence")
    credential_dir: Path = Path("data/credentials")
    tracking_dir: Path = Path("data/tracking")
    system_registry_path: Path = Path("config/system_registry.json")


settings = Settings()
