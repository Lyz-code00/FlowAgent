from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "FlowAgent"
    env: str = "development"
    log_level: str = "INFO"
    admin_api_token: str = ""
    config_encryption_key: str = ""
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    database_url: str = "sqlite+aiosqlite:///./flowagent.db"
    auto_create_tables: bool = True
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4.1-mini"
    max_agent_steps: int = 5
    context_turns: int = 10
    tool_timeout_seconds: float = 15
    github_base_url: str = "https://api.github.com"
    github_api_version: str = "2026-03-10"
    github_token: str = ""
    github_owner: str = ""
    github_repo: str = ""
    github_default_labels: list[str] = Field(default_factory=lambda: ["bug"])
    github_default_assignee: str = ""
    member_can_create_issue: bool = False
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    knowledge_chunk_size: int = 1000
    knowledge_chunk_overlap: int = 150
    knowledge_top_k: int = 5
    knowledge_min_score: float = 0.05
    knowledge_max_file_bytes: int = 10 * 1024 * 1024
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_verification_token: str = ""
    feishu_encrypt_key: str = ""
    feishu_bot_open_id: str = ""
    feishu_internal_callback_url: str = (
        "http://127.0.0.1:8001/api/v1/channels/feishu/events"
    )

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_prefix="FLOWAGENT_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
