import os
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """
    Konfigurasi environment variables menggunakan pydantic-settings.
    Akan otomatis membaca dari file .env di root directory.
    """
    app_name: str = Field("FastAPI AI Chatbot", alias="APP_NAME")
    app_env: str = Field("development", alias="APP_ENV")
    debug: bool = Field(True, alias="DEBUG")
    port: int = Field(8000, alias="PORT")
    
    # Keamanan & CORS
    allowed_origins_raw: str = Field("http://localhost:3000,http://localhost:8000,http://127.0.0.1:8000", alias="ALLOWED_ORIGINS")
    internal_api_key: Optional[str] = Field(None, alias="INTERNAL_API_KEY")
    
    # OpenAI Credentials & Responses API
    openai_api_key: str = Field("sk-your-openai-api-key-here", alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4o-mini", alias="OPENAI_MODEL")
    openai_system_instructions: str = Field(
        "Kamu adalah asisten AI yang ramah dan sangat membantu.", 
        alias="OPENAI_SYSTEM_INSTRUCTIONS"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def allowed_origins(self) -> List[str]:
        """Mengubah string origin terpisahkan koma menjadi daftar/list string."""
        if not self.allowed_origins_raw:
            return ["*"]
        return [origin.strip() for origin in self.allowed_origins_raw.split(",") if origin.strip()]


# Inisialisasi instance settings tunggal (singleton)
settings = Settings()
