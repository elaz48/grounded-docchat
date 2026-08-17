from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # pydantic-settings 2.x style: class Config is the deprecated v1 shape and
    # is only honoured for backwards compatibility. extra="ignore" because the
    # .env is shared with docker compose and tooling, so it carries keys this
    # app has no field for; forbidding them would fail startup on a comment.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    database_url: str = "postgresql://docchat:docchat@localhost:5432/docchat"
    chunk_target_chars: int = 1200
    chunk_overlap_chars: int = 150
    retrieval_k: int = 6
    grounding_min_score: float = 0.015


settings = Settings()
