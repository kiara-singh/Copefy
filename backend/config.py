from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    supabase_url: str = ""
    supabase_service_key: str = ""
    database_url: str = ""
    cors_origins: str = "http://localhost:5173"

    gemini_api_key: str = ""
    # Optional paid/ingest project. Generation eval prefers this over GEMINI_API_KEY.
    gemini_ingest_api_key: str = ""
    gemini_chat_model: str = "gemini-3.5-flash-lite"
    # Comma-separated fallbacks tried in order when the primary model is unavailable.
    # 2.5-flash is last: this project 404s it, and a failed first try still burns eval budget.
    gemini_chat_model_fallbacks: str = (
        "gemini-3.5-flash-lite,gemini-flash-latest,gemini-3.6-flash,gemini-2.5-flash"
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
    # Audio journals: transcribe with generateContent, then reuse text embeddings.
    # Chat already uses 3.5-flash-lite; this project 404s gemini-2.5-flash.
    gemini_transcribe_model: str = "gemini-3.5-flash-lite"
    system_prompt_version: str = "v1"

    rag_debug: bool = False
    # When true, /chat always attaches a metadata-only trace. Retrieved snippet
    # text is never included in HTTP responses.
    rag_strategy: str = "mmr"
    # Journal path only. Calibrated junk reduction on synthetic no-memory
    # searches; not a guarantee that a kept chunk is the right memory.
    journal_min_similarity: float = 0.70
    # Generation prompt only: prior user/assistant exchanges to keep (current user
    # message stays separate). Journal retrieval is unaffected. 6 still drops the
    # in-chat update on long 11-turn state_* fixtures (update at turn 4 of 10 prior);
    # 8 covers those while staying exchange-based.
    chat_history_exchanges: int = 8

    agent_router: str = "rule"
    agent_router_model: str = "gemini-flash-latest"
    # Comma-separated judge/router fallbacks when the primary is 503 or returns empty JSON.
    agent_router_model_fallbacks: str = (
        "gemini-3.5-flash-lite,gemini-flash-latest,gemini-2.5-flash,gemini-3.6-flash"
    )
    # Optional: bill routing to a different project than chat/embeddings. Free-tier
    # generateContent quotas are tiny, so a paid key here makes eval runs practical.
    agent_router_api_key: str = ""

    # Eval and seed scripts only. Chat and auth always use the signed-in user.
    journal_eval_user_id: str = ""
    seed_user_id: str = ""

    # Clinical KB ingest (`python -m rag.ingest`). Embeddings use gemini_embed_model
    # at the same 768 dimensions as query-time search.
    ingest_concurrency: int = 1
    embed_batch_size: int = 8
    embed_delay_seconds: float = 2.0
    embed_concurrency: int = 1
    chunk_max_chars: int = 800
    chunk_overlap: int = 120
    chunk_min_chars: int = 200
    max_chunks_per_doc: int = 40
    max_source_chars: int = 24000
    max_source_chars_pmc: int = 60000
    discovery_bfs_max_depth: int = 6
    discovery_bfs_max_pages: int = 30000
    pmc_max_per_category: int = 1200
    crawl_user_agent: str = (
        "CopefyBot/0.2 (+https://copefy.local; health-education ingest)"
    )

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

    @property
    def agent_router_model_fallbacks_list(self) -> list[str]:
        return [
            model.strip()
            for model in self.agent_router_model_fallbacks.split(",")
            if model.strip()
        ]


settings = Settings()
