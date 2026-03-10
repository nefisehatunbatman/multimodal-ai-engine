import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # -------------------------
    # Database
    # -------------------------
    DB_USER: str | None = os.getenv("DB_USER")
    DB_PASSWORD: str | None = os.getenv("DB_PASSWORD")
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "5433")
    DB_NAME: str | None = os.getenv("DB_NAME")

    # -------------------------
    # OpenRouter
    # -------------------------
    OPENROUTER_API_KEY: str | None = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_MODEL_PRIMARY: str = os.getenv("OPENROUTER_MODEL_PRIMARY", "openai/gpt-4o-mini")
    OPENROUTER_MODEL_FALLBACK: str = os.getenv("OPENROUTER_MODEL_FALLBACK", "google/gemini-1.5-flash")

    # -------------------------
    # WeKnora
    # -------------------------
    WEKNORA_APP_HOST: str = os.getenv("WEKNORA_APP_HOST", "localhost")
    WEKNORA_APP_PORT: int = int(os.getenv("WEKNORA_APP_PORT", "8080"))
    WEKNORA_API_KEY: str | None = os.getenv("WEKNORA_API_KEY") or None
    WEKNORA_KB_ID: str | None = os.getenv("WEKNORA_KB_ID") or None

    # -------------------------
    # App
    # -------------------------
    MAX_HISTORY_MESSAGES: int = int(os.getenv("MAX_HISTORY_MESSAGES", "6"))
    DEFAULT_SYSTEM_PROMPT: str = os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful assistant.")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info")

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql://{self.DB_USER}:"
            f"{self.DB_PASSWORD}@"
            f"{self.DB_HOST}:"
            f"{self.DB_PORT}/"
            f"{self.DB_NAME}"
        )


settings = Settings()