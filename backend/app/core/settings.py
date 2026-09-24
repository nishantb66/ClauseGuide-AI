from functools import lru_cache
from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="ClauseGuide AI")
    api_prefix: str = Field(default="/api")
    env: str = Field(default="dev")
    log_level: str = Field(default="INFO")

    mongodb_uri: str | None = Field(default=None)
    mongodb_database: str = Field(default="csi")
    mongodb_collection: str = Field(default="clauseguide_ai")
    max_upload_mb: int = Field(default=25)

    embedding_dim: int = Field(default=384)
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5")
    use_sentence_transformers: bool = Field(default=False)
    use_cross_encoder_reranker: bool = Field(default=False)
    reranker_model: str = Field(default="cross-encoder/ms-marco-MiniLM-L-6-v2")
    retrieval_min_score_threshold: float = Field(default=0.16)
    retrieval_min_citation_score: float = Field(default=0.72)
    bm25_k1: float = Field(default=1.4)
    bm25_b: float = Field(default=0.75)

    groq_api_key: str | None = Field(default=None)
    groq_base_url: str = Field(default="https://api.groq.com/openai/v1")
    groq_model: str = Field(default="openai/gpt-oss-20b")
    request_timeout_seconds: int = Field(default=30)
    llm_max_retries: int = Field(default=2)
    llm_retry_backoff_seconds: float = Field(default=1.1)
    llm_context_chunk_chars: int = Field(default=1400)
    llm_max_context_chunks: int = Field(default=6)

    jwt_secret: str = Field(default="change-me-in-production")
    jwt_issuer: str = Field(default="clauseguide-ai")
    jwt_access_token_minutes: int = Field(default=720)

    otp_secret: str = Field(default="change-me-otp-secret")
    otp_expiry_minutes: int = Field(default=10)
    otp_max_attempts: int = Field(default=5)

    smtp_enabled: bool = Field(default=True)
    smtp_host: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=465)
    smtp_username: str | None = Field(default=None)
    smtp_app_password: str | None = Field(default=None)
    smtp_from_email: str | None = Field(default=None)

    google_client_id: str | None = Field(default=None)
    google_client_secret: str | None = Field(default=None)
    google_redirect_uri: str = Field(default="http://localhost:5173/google/callback/")
    google_auto_signup_enabled: bool = Field(default=False)
    cors_origin_csv: str = Field(default="http://localhost:5173,http://127.0.0.1:5173")

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    @property
    def allowed_extensions(self) -> set[str]:
        return {".pdf", ".docx", ".txt"}

    @computed_field
    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origin_csv.split(",") if origin.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings()
