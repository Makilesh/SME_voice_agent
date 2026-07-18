"""Central configuration, loaded once from environment (.env)."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class Settings(BaseModel):
    # Gemini
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    model_pro: str = os.getenv("GEMINI_MODEL_PRO", "gemini-3-pro-preview")
    model_flash: str = os.getenv("GEMINI_MODEL_FLASH", "gemini-2.5-flash")
    gemini_live_model: str = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")

    # STT
    stt_backend: str = os.getenv("STT_BACKEND", "local")  # local | gemini_live
    stt_mode: str = os.getenv("STT_MODE", "balanced")     # fast | balanced | accurate

    # Server
    host: str = os.getenv("BACKEND_HOST", "127.0.0.1")
    port: int = int(os.getenv("BACKEND_PORT", "8000"))

    # RAG
    chroma_db_path: str = os.getenv("CHROMA_DB_PATH", "./chroma_db")

    # TTS (off in meeting mode)
    tts_enabled: bool = os.getenv("TTS_ENABLED", "false").lower() == "true"

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
