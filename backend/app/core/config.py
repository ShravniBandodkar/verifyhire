"""Central configuration. Every value can be overridden with an environment variable."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "VerifyHire"
    ENV: str = "dev"
    DATABASE_URL: str = "sqlite:///./verifyhire.db"
    JWT_SECRET: str = "dev-only-change-me"
    JWT_EXPIRE_MINUTES: int = 60 * 12
    # Master key-encryption-key (KEK) for envelope encryption, base64 32 bytes.
    # Several keys may be supplied comma separated as "v1:<b64>,v2:<b64>" — last is active.
    VAULT_KEKS: str = ""
    BADGE_SIGNING_KEY: str = "dev-badge-key"
    STORAGE_DIR: str = "./storage"
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    CORS_ORIGINS: str = "*"

    # LLM provider: none | anthropic | openai | gemini
    LLM_PROVIDER: str = "none"
    LLM_MODEL: str = ""
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    LLM_TIMEOUT: float = 25.0

    # Sandbox government adapters (mock DigiLocker / NSDL / MCA21 / GSTN / NAD)
    GOV_ADAPTER_MODE: str = "sandbox"
    SANDBOX_OTP: str = "123456"

    RATE_LIMIT_PER_MIN: int = 240
    SCRAPE_PROFILE_VIEWS_PER_MIN: int = 40
    AUTO_SEED: bool = True
    FRONTEND_DIR: str = "../frontend/out"


@lru_cache
def get_settings() -> Settings:
    import os
    s = Settings()
    if s.PUBLIC_BASE_URL == "http://localhost:8000" and os.getenv("RENDER_EXTERNAL_URL"):
        s.PUBLIC_BASE_URL = os.environ["RENDER_EXTERNAL_URL"]
    return s


settings = get_settings()
