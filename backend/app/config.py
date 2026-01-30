"""Configuration management for AI Art Generator."""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field


def load_env_file(env_path: Optional[str] = None) -> Path | None:
    """Load environment file from specified path or search common locations.
    
    Priority:
    1. Explicitly provided path (CLI flag or ARTGEN_ENV_FILE)
    2. .env.local in current directory
    3. .env in current directory
    4. .env.local in tool directory (ai-art-generator/)
    5. .env in tool directory
    """
    # Check for explicit path first
    explicit_path = env_path or os.getenv("ARTGEN_ENV_FILE")
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if path.exists():
            load_dotenv(path)
            return path
        else:
            print(f"Warning: Specified env file not found: {path}")
    
    # Search locations
    cwd = Path.cwd()
    tool_dir = Path(__file__).parent.parent.parent  # ai-art-generator/
    
    search_paths = [
        cwd / ".env.local",
        cwd / ".env",
        tool_dir / ".env.local",
        tool_dir / ".env",
    ]
    
    for path in search_paths:
        if path.exists():
            load_dotenv(path)
            return path
    
    # Fallback to default dotenv behavior
    load_dotenv()
    return None


# Load env on module import (can be re-called with explicit path)
_loaded_env_path = load_env_file()


def _get_google_api_key() -> Optional[str]:
    """Get Google API key from environment, checking multiple variable names."""
    return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")


class ProviderConfig(BaseModel):
    """Configuration for AI providers."""
    
    # Google/Gemini (default image generator)
    # Supports both GOOGLE_API_KEY and GEMINI_API_KEY
    google_api_key: Optional[str] = Field(default_factory=_get_google_api_key)
    gemini_model: str = "gemini-2.5-flash-image"
    gemini_pro_model: str = "gemini-3-pro-image-preview"
    
    # OpenAI (DALL-E, text generation)
    openai_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    dalle_model: str = "dall-e-3"
    
    # Anthropic (text generation)
    anthropic_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    claude_model: str = "claude-sonnet-4-20250514"
    
    # Tavily (research)
    tavily_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("TAVILY_API_KEY"))
    
    # PixelLab (pixel art)
    pixellab_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("PIXELLAB_API_KEY"))


class AppConfig(BaseModel):
    """Main application configuration."""
    
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = Field(default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true")
    
    # Env file that was loaded
    env_file: Optional[str] = Field(default_factory=lambda: str(_loaded_env_path) if _loaded_env_path else None)
    
    # Provider configuration
    providers: ProviderConfig = Field(default_factory=ProviderConfig)
    
    # Default generation settings
    default_image_provider: str = "gemini"
    default_text_provider: str = "gemini"
    default_research_provider: str = "tavily"
    default_variations: int = 4


def get_config() -> AppConfig:
    """Get the application configuration."""
    return AppConfig()


def reload_config(env_path: Optional[str] = None) -> AppConfig:
    """Reload configuration with a new env file path."""
    global _loaded_env_path
    _loaded_env_path = load_env_file(env_path)
    return get_config()
