from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    supabase_url: str = ""
    supabase_service_key: str = ""
    database_url: str = ""
    cors_origins: str = "http://localhost:5173"

    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-2.5-flash"
    # Comma-separated fallbacks tried in order when the primary model is unavailable.
    gemini_chat_model_fallbacks: str = (
        "gemini-2.5-flash,gemini-2.0-flash,gemini-2.5-flash-lite,gemini-2.0-flash-lite"
    )
    gemini_embed_model: str = "gemini-embedding-2"

    rag_debug: bool = False
    rag_strategy: str = "mmr"

    agent_router: str = "rule"
    agent_router_model: str = "gemini-flash-latest"
    # Optional: bill routing to a different project than chat/embeddings. Free-tier
    # generateContent quotas are tiny, so a paid key here makes eval runs practical.
    agent_router_api_key: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def gemini_chat_model_fallbacks_list(self) -> list[str]:
        return [
            model.strip()
            for model in self.gemini_chat_model_fallbacks.split(",")
            if model.strip()
        ]


settings = Settings()
