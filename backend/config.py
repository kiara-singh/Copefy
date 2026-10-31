from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    supabase_url: str = ""
    supabase_service_key: str = ""
    database_url: str = ""
    cors_origins: str = "http://localhost:5173"

    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-flash-latest"
    # Comma-separated fallbacks tried in order when the primary model is unavailable.
    gemini_chat_model_fallbacks: str = (
        "gemini-flash-latest,gemini-3-flash-preview,gemini-flash-lite-latest,gemini-3.1-flash-lite-preview"
    )
    # Dedicated paid credential for grounded search. Never falls back to the
    # normal chat key, so billing remains isolated to Path.WEB_SEARCH.
    gemini_web_search_api_key: str = ""
    gemini_web_search_model: str = "gemini-3.1-flash-lite"
    gemini_web_search_enabled: bool = True
    # Google bills Gemini 3 grounding per internal search query and may issue
    # several queries for one request. Reserve ten queries per request and stop
    # below the 5,000-query included monthly allowance.
    gemini_web_search_monthly_query_budget: int = 4500
    gemini_web_search_query_reservation: int = 10
    gemini_web_search_usage_db: str = ".web_search_usage.sqlite3"
    gemini_embed_model: str = "gemini-embedding-2"
    system_prompt_version: str = "v1"

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
