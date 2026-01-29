"""Base classes for AI providers."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from PIL import Image

from app.models import StyleConfig


class BaseImageProvider(ABC):
    """Base class for image generation providers."""
    
    name: str = "base"
    
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        style: Optional[StyleConfig] = None,
        variations: int = 1,
        reference_images: Optional[list[Image.Image]] = None,
    ) -> list[Image.Image]:
        """Generate images from a prompt.
        
        Args:
            prompt: The text prompt for generation
            style: Style configuration (aspect ratio, size, etc.)
            variations: Number of variations to generate
            reference_images: Optional reference images for style/content
            
        Returns:
            List of generated PIL Images
        """
        pass
    
    @abstractmethod
    async def edit(
        self,
        image: Image.Image,
        prompt: str,
        style: Optional[StyleConfig] = None,
    ) -> Image.Image:
        """Edit an existing image based on a prompt.
        
        Args:
            image: The image to edit
            prompt: Instructions for editing
            style: Style configuration
            
        Returns:
            The edited PIL Image
        """
        pass
    
    def build_prompt(self, base_prompt: str, style: Optional[StyleConfig] = None) -> str:
        """Build the full prompt including style modifiers."""
        if not style:
            return base_prompt
            
        parts = []
        if style.global_prompt_prefix:
            parts.append(style.global_prompt_prefix)
        parts.append(base_prompt)
        if style.global_prompt_suffix:
            parts.append(style.global_prompt_suffix)
            
        return ", ".join(parts)


class BaseTextProvider(ABC):
    """Base class for text generation providers."""
    
    name: str = "base"
    
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> str:
        """Generate text from a prompt.
        
        Args:
            prompt: The text prompt
            system_prompt: Optional system/context prompt
            max_tokens: Maximum tokens to generate
            
        Returns:
            Generated text string
        """
        pass
    
    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        schema: dict,
        system_prompt: Optional[str] = None,
    ) -> dict:
        """Generate structured JSON output.
        
        Args:
            prompt: The text prompt
            schema: JSON schema for the output
            system_prompt: Optional system/context prompt
            
        Returns:
            Parsed JSON dict
        """
        pass


class BaseResearchProvider(ABC):
    """Base class for research/search providers."""
    
    name: str = "base"
    
    @abstractmethod
    async def research(
        self,
        query: str,
        max_results: int = 5,
    ) -> dict:
        """Research a topic and return structured results.
        
        Args:
            query: The research query
            max_results: Maximum number of sources to return
            
        Returns:
            Dict with 'summary' and 'sources' keys
        """
        pass
