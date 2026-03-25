"""Tests for configuration"""

import os
from unittest.mock import patch

from src.config import Settings, get_settings


class TestSettings:
    """Tests for Settings class"""

    def test_default_values(self):
        """Test that default values are set correctly"""
        # Create Settings without loading from .env by clearing env vars first
        env_backup = {}
        keys_to_clear = ["TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "WHISPER_MODEL",
                         "LOG_LEVEL", "WHISPER_DEVICE", "WHISPER_COMPUTE_TYPE"]
        for key in keys_to_clear:
            env_backup[key] = os.environ.pop(key, None)

        try:
            settings = Settings(_env_file=None)

            assert settings.twitch_client_id == ""
            assert settings.twitch_client_secret == ""
            assert settings.log_level == "INFO"
            assert settings.whisper_model == "base"
            assert settings.whisper_device == "cpu"
            assert settings.whisper_compute_type == "int8"
        finally:
            # Restore env vars
            for key, value in env_backup.items():
                if value is not None:
                    os.environ[key] = value

    def test_loads_from_env(self):
        """Test that settings are loaded from environment variables"""
        with patch.dict(os.environ, {
            "TWITCH_CLIENT_ID": "test_id",
            "TWITCH_CLIENT_SECRET": "test_secret",
            "WHISPER_MODEL": "large",
            "LOG_LEVEL": "DEBUG",
        }, clear=False):
            # Clear the .env file loading by using _env_file
            settings = Settings(_env_file=None)

            assert settings.twitch_client_id == "test_id"
            assert settings.twitch_client_secret == "test_secret"
            assert settings.whisper_model == "large"
            assert settings.log_level == "DEBUG"

    def test_uses_defaults_for_missing_env(self):
        """Test that defaults are used when env vars are not set"""
        # Save current env values
        env_backup = {}
        keys_to_clear = ["TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "WHISPER_MODEL", "LOG_LEVEL"]
        for key in keys_to_clear:
            env_backup[key] = os.environ.pop(key, None)

        try:
            settings = Settings(_env_file=None)

            assert settings.twitch_client_id == ""
            assert settings.twitch_client_secret == ""
            assert settings.whisper_model == "base"
        finally:
            # Restore env vars
            for key, value in env_backup.items():
                if value is not None:
                    os.environ[key] = value


class TestGetSettings:
    """Tests for get_settings function"""

    def test_returns_settings_instance(self):
        """Test that Settings instance is returned"""
        # Clear the cache
        get_settings.cache_clear()

        settings = get_settings()

        assert isinstance(settings, Settings)

    def test_returns_cached_instance(self):
        """Test that the same instance is returned on subsequent calls"""
        # Clear the cache
        get_settings.cache_clear()

        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2

    def test_cache_respects_lru_cache(self):
        """Test that lru_cache is being used"""
        # Clear the cache
        get_settings.cache_clear()

        # Get settings multiple times
        settings1 = get_settings()
        settings2 = get_settings()
        settings3 = get_settings()

        # All should be the same instance due to caching
        assert settings1 is settings2 is settings3
