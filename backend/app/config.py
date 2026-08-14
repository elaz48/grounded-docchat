from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    database_url: str = "postgresql://docchat:docchat@localhost:5432/docchat"
    chunk_target_chars: int = 1200
    chunk_overlap_chars: int = 150
    retrieval_k: int = 6
    grounding_min_score: float = 0.015

    class Config:
        env_file = ".env"


settings = Settings()
