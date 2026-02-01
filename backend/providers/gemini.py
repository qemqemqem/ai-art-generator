"""Google Gemini provider for image and text generation."""

import base64
import io
from io import BytesIO
from typing import Optional

from PIL import Image

from app.config import get_config
from app.models import StyleConfig

from .base import BaseImageProvider, BaseTextProvider


def _genai_to_pil(genai_image) -> Image.Image:
    """Convert a google.genai.types.Image to PIL Image."""
    return Image.open(BytesIO(genai_image.image_bytes))


class GeminiImageProvider(BaseImageProvider):
    """Gemini/Nano Banana image generation provider."""
    
    name = "gemini"
    
    def __init__(self, use_pro: bool = False):
        """Initialize the Gemini provider.
        
        Args:
            use_pro: If True, use gemini-3-pro-image-preview for higher quality
        """
        self.use_pro = use_pro
        self._client = None
        
    @property
    def client(self):
        """Lazy-load the Gemini client."""
        if self._client is None:
            from google import genai
            config = get_config()
            self._client = genai.Client(api_key=config.providers.google_api_key)
        return self._client
    
    @property
    def model(self) -> str:
        """Get the model name to use."""
        config = get_config()
        return config.providers.gemini_pro_model if self.use_pro else config.providers.gemini_model
    
    async def generate(
        self,
        prompt: str,
        style: Optional[StyleConfig] = None,
        variations: int = 1,
        reference_images: Optional[list[Image.Image]] = None,
    ) -> list[Image.Image]:
        """Generate images using Gemini."""
        from google.genai import types
        
        full_prompt = self.build_prompt(prompt, style)
        
        # Build content list
        contents = [full_prompt]
        
        # Add reference images if provided
        if reference_images:
            for ref_img in reference_images:
                contents.append(ref_img)
        
        # Build config
        image_config = types.ImageConfig()
        if style:
            image_config.aspect_ratio = style.aspect_ratio
            if self.use_pro:
                image_config.image_size = style.image_size
        
        config = types.GenerateContentConfig(
            response_modalities=['IMAGE'],
            image_config=image_config,
        )
        
        # Generate images (Gemini generates one at a time, so loop for variations)
        images = []
        for _ in range(variations):
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )
            
            for part in response.parts:
                if part.inline_data is not None:
                    genai_img = part.as_image()
                    # Convert Gemini Image to PIL Image
                    pil_img = _genai_to_pil(genai_img)
                    images.append(pil_img)
                    break  # One image per response
        
        return images
    
    async def edit(
        self,
        image: Image.Image,
        prompt: str,
        style: Optional[StyleConfig] = None,
    ) -> Image.Image:
        """Edit an image using Gemini's conversational editing."""
        from google.genai import types
        
        full_prompt = self.build_prompt(prompt, style)
        
        # Build config
        image_config = types.ImageConfig()
        if style:
            image_config.aspect_ratio = style.aspect_ratio
            if self.use_pro:
                image_config.image_size = style.image_size
        
        config = types.GenerateContentConfig(
            response_modalities=['IMAGE'],
            image_config=image_config,
        )
        
        response = self.client.models.generate_content(
            model=self.model,
            contents=[image, full_prompt],
            config=config,
        )
        
        for part in response.parts:
            if part.inline_data is not None:
                genai_img = part.as_image()
                return _genai_to_pil(genai_img)
        
        raise RuntimeError("No image returned from Gemini edit")


class GeminiTextProvider(BaseTextProvider):
    """Gemini text generation provider."""
    
    name = "gemini"
    
    def __init__(self):
        self._client = None
        
    @property
    def client(self):
        """Lazy-load the Gemini client."""
        if self._client is None:
            from google import genai
            config = get_config()
            self._client = genai.Client(api_key=config.providers.google_api_key)
        return self._client
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text using Gemini.
        
        Args:
            prompt: The prompt to generate from
            system_prompt: Optional system context
            max_tokens: Maximum output tokens. If None, uses model's default (no limit imposed).
        """
        from google.genai import types
        
        # Build the full prompt with optional system context
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"
        else:
            full_prompt = prompt
        
        # Configure generation - only set max_output_tokens if specified
        config = None
        if max_tokens is not None:
            config = types.GenerateContentConfig(
                max_output_tokens=max_tokens,
            )
        
        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[full_prompt],
            config=config,
        )
        
        # Get text from response
        if response.text:
            return response.text
        
        return ""
    
    async def generate_structured(
        self,
        prompt: str,
        schema: dict,
        system_prompt: Optional[str] = None,
    ) -> dict:
        """Generate structured JSON output using Gemini."""
        import json
        from google.genai import types
        
        # Add JSON instruction to prompt
        json_prompt = f"{prompt}\n\nRespond with valid JSON matching this schema:\n{json.dumps(schema, indent=2)}"
        
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
            contents.append({"role": "model", "parts": [{"text": "Understood."}]})
        contents.append(json_prompt)
        
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
        )
        
        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=config,
        )
        
        return json.loads(response.text)
