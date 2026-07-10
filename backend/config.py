from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    # Supabase project URL, e.g. https://xxxxxxxx.supabase.co
    supabase_url: str = ""

    # Service role key (server-side only, never expose to the browser).
    supabase_service_key: str = ""

    # Direct Postgres connection string for pgvector / RAG queries.
    # e.g. postgresql://postgres:<password>@db.xxxx.supabase.co:5432/postgres
    database_url: str = ""

    # Comma-separated list of allowed CORS origins for the frontend.
    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
