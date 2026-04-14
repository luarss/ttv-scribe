"""Application configuration"""

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Required settings
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    youtube_api_key: str = ""

    # Optional settings
    log_level: str = "INFO"
    whisper_model: str = "base"
    audio_output_dir: str = "/tmp/ttv-scribe-audio"
    state_file_dir: str = "./state"
    transcript_dir: str = "./transcripts"

    # Legacy (ignored)
    database_url: str = ""

    # Local Whisper settings (for faster-whisper)
    whisper_device: str = "cpu"  # cpu or cuda (for GPU)
    whisper_compute_type: str = "int8"  # int8, float16, float32

    # Transcription optimization settings
    whisper_beam_size: int = 5  # Beam size for decoding (lower = faster)
    whisper_vad_min_silence_ms: int = 500  # VAD min silence duration in ms

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
