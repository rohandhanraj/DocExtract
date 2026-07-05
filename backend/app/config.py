"""Application configuration via environment variables."""

import os
from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache

# Project root: 2 levels up from this file (backend/app/config.py → project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_path(p: str) -> str:
    """Resolve relative paths against PROJECT_ROOT, leave absolute paths as-is."""
    path = Path(p)
    if path.is_absolute():
        return str(path)
    return str((PROJECT_ROOT / path).resolve())


def _find_env_file() -> str:
    """Use .env.local for local dev, fall back to .env."""
    local = PROJECT_ROOT / ".env.local"
    if local.exists():
        return str(local)
    default = PROJECT_ROOT / ".env"
    if default.exists():
        return str(default)
    return ".env"


class Settings(BaseSettings):
    """All settings are loaded from environment variables or .env file."""

    # File handling
    upload_dir: str = "./data/uploads"
    max_file_size_mb: int = 50
    allowed_extensions: list[str] = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".docx"]

    # Model cache — maps to ./models volume in Docker
    model_cache_dir: str = "./models"

    # VLM Configuration (OpenAI-compatible endpoint)
    vlm_base_url: str = "http://localhost:11434/v1"
    vlm_model: str = "qwen2.5-vl:7b"
    vlm_api_key: str = "not-needed"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Page rendering
    page_dpi: int = 200

    model_config = {"env_file": _find_env_file(), "extra": "ignore"}

    def resolve_paths(self) -> None:
        """Convert relative paths to absolute using project root."""
        self.upload_dir = _resolve_path(self.upload_dir)
        self.model_cache_dir = _resolve_path(self.model_cache_dir)

    def configure_model_cache(self) -> None:
        """Set all model-related cache directories to the shared volume."""
        cache = self.model_cache_dir
        os.makedirs(cache, exist_ok=True)
        os.environ.setdefault("HF_HOME", f"{cache}/huggingface")
        os.environ.setdefault("TORCH_HOME", f"{cache}/torch")
        os.environ.setdefault("DOCLING_CACHE_DIR", f"{cache}/docling")
        os.environ.setdefault("SURYA_CACHE_DIR", f"{cache}/surya")
        # Ensure subdirectories exist
        for subdir in ["huggingface", "torch", "docling", "surya"]:
            os.makedirs(f"{cache}/{subdir}", exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Cached singleton for settings."""
    settings = Settings()
    settings.resolve_paths()
    settings.configure_model_cache()
    return settings
