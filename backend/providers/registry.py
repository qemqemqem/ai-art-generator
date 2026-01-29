"""Provider registry for managing AI providers."""

from typing import Optional, Type

from app.models import ImageProvider, TextProvider, ResearchProvider

from .base import BaseImageProvider, BaseTextProvider, BaseResearchProvider
from .gemini import GeminiImageProvider, GeminiTextProvider
from .litellm_provider import LiteLLMTextProvider


class ProviderRegistry:
    """Registry for AI providers."""
    
    def __init__(self):
        self._image_providers: dict[str, BaseImageProvider] = {}
        self._text_providers: dict[str, BaseTextProvider] = {}
        self._research_providers: dict[str, BaseResearchProvider] = {}
        
        # Register default providers
        self._register_defaults()
    
    def _register_defaults(self):
        """Register the default providers."""
        # Image providers
        self._image_providers["gemini"] = GeminiImageProvider(use_pro=False)
        self._image_providers["gemini_pro"] = GeminiImageProvider(use_pro=True)
        
        # Text providers - LiteLLM with structured output is preferred
        self._text_providers["litellm"] = LiteLLMTextProvider()
        self._text_providers["gemini"] = LiteLLMTextProvider(model="gemini/gemini-2.5-flash")
        self._text_providers["gemini_legacy"] = GeminiTextProvider()  # Old unstructured
        
        # TODO: Add more providers as needed
        # self._image_providers["dalle"] = DalleImageProvider()
        # self._text_providers["claude"] = LiteLLMTextProvider(model="claude-3-5-sonnet-latest")
        # self._research_providers["tavily"] = TavilyResearchProvider()
    
    def get_image_provider(self, name: str) -> BaseImageProvider:
        """Get an image provider by name."""
        if name not in self._image_providers:
            available = list(self._image_providers.keys())
            raise ValueError(f"Unknown image provider: {name}. Available: {available}")
        return self._image_providers[name]
    
    def get_text_provider(self, name: str) -> BaseTextProvider:
        """Get a text provider by name."""
        if name not in self._text_providers:
            available = list(self._text_providers.keys())
            raise ValueError(f"Unknown text provider: {name}. Available: {available}")
        return self._text_providers[name]
    
    def get_research_provider(self, name: str) -> BaseResearchProvider:
        """Get a research provider by name."""
        if name not in self._research_providers:
            available = list(self._research_providers.keys())
            raise ValueError(f"Unknown research provider: {name}. Available: {available}")
        return self._research_providers[name]
    
    def register_image_provider(self, name: str, provider: BaseImageProvider):
        """Register a custom image provider."""
        self._image_providers[name] = provider
    
    def register_text_provider(self, name: str, provider: BaseTextProvider):
        """Register a custom text provider."""
        self._text_providers[name] = provider
    
    def register_research_provider(self, name: str, provider: BaseResearchProvider):
        """Register a custom research provider."""
        self._research_providers[name] = provider
    
    def list_image_providers(self) -> list[str]:
        """List available image providers."""
        return list(self._image_providers.keys())
    
    def list_text_providers(self) -> list[str]:
        """List available text providers."""
        return list(self._text_providers.keys())
    
    def list_research_providers(self) -> list[str]:
        """List available research providers."""
        return list(self._research_providers.keys())


# Singleton instance
_registry: Optional[ProviderRegistry] = None


def get_provider_registry() -> ProviderRegistry:
    """Get the global provider registry."""
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry
