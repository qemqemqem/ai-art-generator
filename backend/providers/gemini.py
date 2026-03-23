"""Google Gemini provider for image and text generation."""

import base64
import io
import logging
from io import BytesIO
from typing import Optional

from PIL import Image

from app.config import get_config
from app.models import StyleConfig
from pipeline.retry import rate_limited_call

from .base import BaseImageProvider, BaseTextProvider

logger = logging.getLogger(__name__)


def _genai_to_pil(genai_image) -> Image.Image:
    """Convert a google.genai.types.Image to PIL Image."""
    return Image.open(BytesIO(genai_image.image_bytes))


_SIZE_TO_GEMINI = {"512": "512", "1024": "1K", "1k": "1K", "2048": "2K", "2k": "2K", "4096": "4K", "4k": "4K"}


def _normalize_image_size(raw: str | None) -> str | None:
    """Convert numeric/lowercase sizes to Gemini's format (512, 1K, 2K, 4K)."""
    if not raw:
        return None
    return _SIZE_TO_GEMINI.get(raw, raw)


class GeminiImageProvider(BaseImageProvider):
    """Gemini/Nano Banana image generation provider."""
    
    name = "gemini"
    
    def __init__(self, use_pro: bool = False, model_override: str | None = None):
        """Initialize the Gemini provider.
        
        Args:
            use_pro: If True, use gemini-3-pro-image-preview for higher quality
            model_override: Explicit model string that takes precedence over config defaults
        """
        self.use_pro = use_pro
        self._model_override = model_override
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
        if self._model_override:
            return self._model_override
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
            # Gemini 3.x models accept (and may require) an explicit image_size;
            # Gemini 2.5 Flash Image does not support it.
            if "gemini-3" in self.model:
                size = _normalize_image_size(style.image_size)
                if size:
                    image_config.image_size = size
        
        gen_config = types.GenerateContentConfig(
            response_modalities=['TEXT', 'IMAGE'],
            image_config=image_config,
        )
        
        # Generate images (Gemini generates one at a time, so loop for variations)
        images = []
        for _ in range(variations):
            async def _call():
                try:
                    return self.client.models.generate_content(
                        model=self.model,
                        contents=contents,
                        config=gen_config,
                    )
                except Exception as e:
                    logger.warning(
                        "Gemini image API error: %s\n"
                        "  model=%s\n"
                        "  aspect_ratio=%s\n"
                        "  image_size=%s\n"
                        "  response_modalities=%s\n"
                        "  prompt_length=%d\n"
                        "  prompt_preview=%.300s",
                        e,
                        self.model,
                        getattr(image_config, 'aspect_ratio', None),
                        getattr(image_config, 'image_size', None),
                        gen_config.response_modalities,
                        len(full_prompt),
                        full_prompt,
                    )
                    raise
            
            response = await rate_limited_call("gemini", _call)
            
            # Defend against blocked/empty responses
            if response.parts is None:
                block_reason = getattr(response, 'prompt_feedback', None)
                candidates = getattr(response, 'candidates', None)
                finish_reason = None
                if candidates and len(candidates) > 0:
                    finish_reason = getattr(candidates[0], 'finish_reason', None)
                raise RuntimeError(
                    f"Gemini returned no content. "
                    f"Finish reason: {finish_reason}, "
                    f"Prompt feedback: {block_reason}"
                )
            
            for part in response.parts:
                if part.inline_data is not None:
                    genai_img = part.as_image()
                    # Convert Gemini Image to PIL Image
                    pil_img = _genai_to_pil(genai_img)
                    images.append(pil_img)
                    break  # One image per response
        
        if not images:
            raise RuntimeError(
                f"Gemini generated 0 images for {variations} requested. "
                f"Response contained no image data — the prompt may have been filtered."
            )
        
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
            if "gemini-3" in self.model:
                size = _normalize_image_size(style.image_size)
                if size:
                    image_config.image_size = size
        
        config = types.GenerateContentConfig(
            response_modalities=['TEXT', 'IMAGE'],
            image_config=image_config,
        )
        
        async def _call():
            return self.client.models.generate_content(
                model=self.model,
                contents=[image, full_prompt],
                config=config,
            )
        
        response = await rate_limited_call("gemini", _call)
        
        # Defend against blocked/empty responses
        if response.parts is None:
            block_reason = getattr(response, 'prompt_feedback', None)
            candidates = getattr(response, 'candidates', None)
            finish_reason = None
            if candidates and len(candidates) > 0:
                finish_reason = getattr(candidates[0], 'finish_reason', None)
            raise RuntimeError(
                f"Gemini edit returned no content. "
                f"Finish reason: {finish_reason}, "
                f"Prompt feedback: {block_reason}"
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
        
        async def _call():
            return self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[full_prompt],
                config=config,
            )
        
        response = await rate_limited_call("gemini", _call)
        
        # Defend against blocked/empty responses
        if response.parts is None:
            block_reason = getattr(response, 'prompt_feedback', None)
            candidates = getattr(response, 'candidates', None)
            finish_reason = None
            if candidates and len(candidates) > 0:
                finish_reason = getattr(candidates[0], 'finish_reason', None)
            raise RuntimeError(
                f"Gemini text generation returned no content. "
                f"Finish reason: {finish_reason}, "
                f"Prompt feedback: {block_reason}"
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
        
        async def _call():
            return self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config=config,
            )
        
        response = await rate_limited_call("gemini", _call)
        
        return json.loads(response.text)
