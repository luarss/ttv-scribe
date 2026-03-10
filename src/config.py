"""Application configuration"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Required settings
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    openai_api_key: str = ""
    database_url: str = "sqlite:///./ttv_scribe.db"

    # Optional settings
    log_level: str = "INFO"
    whisper_model: str = "base"
    audio_output_dir: str = "/tmp/ttv-scribe-audio"

    # Local Whisper settings (for faster-whisper)
    whisper_use_local: bool = False  # Set to True to use local transcription
    whisper_device: str = "cpu"  # cpu or cuda (for GPU)
    whisper_compute_type: str = "int8"  # int8, float16, float32

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()