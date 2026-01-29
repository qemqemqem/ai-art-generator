"""LiteLLM provider for text generation with structured output."""

import logging
from typing import Optional, Type, TypeVar

from pydantic import BaseModel, Field

from app.config import get_config
from .base import BaseTextProvider

logger = logging.getLogger(__name__)

# Type variable for generic Pydantic model support
T = TypeVar("T", bound=BaseModel)


# ============================================================================
# Structured Output Models
# ============================================================================

class GeneratedName(BaseModel):
    """A generated name with optional reasoning."""
    name: str = Field(description="The generated name")
    reasoning: Optional[str] = Field(default=None, description="Brief explanation of why this name fits")


class GeneratedDescription(BaseModel):
    """A generated description or flavor text."""
    text: str = Field(description="The generated text content")


class GeneratedFlavorText(BaseModel):
    """Flavor text for a game card or similar."""
    text: str = Field(description="The flavor text, evocative and atmospheric")
    tone: Optional[str] = Field(default=None, description="The emotional tone (e.g., 'mysterious', 'heroic')")


class GeneratedAbilities(BaseModel):
    """Generated game abilities or stats."""
    abilities: list[str] = Field(description="List of ability descriptions")
    
    
class GeneratedTags(BaseModel):
    """Generated tags or categories."""
    tags: list[str] = Field(description="List of relevant tags")


class GeneratedMultipleOptions(BaseModel):
    """Multiple text options for the user to choose from."""
    options: list[str] = Field(description="List of generated options")


# Mapping from step type hints to response models
STEP_TYPE_MODELS: dict[str, Type[BaseModel]] = {
    "name": GeneratedName,
    "generate_name": GeneratedName,
    "description": GeneratedDescription,
    "generate_text": GeneratedDescription,
    "flavor": GeneratedFlavorText,
    "flavor_text": GeneratedFlavorText,
    "abilities": GeneratedAbilities,
    "tags": GeneratedTags,
}


def get_response_model_for_step(step_type: str) -> Type[BaseModel]:
    """Get the appropriate response model for a step type."""
    return STEP_TYPE_MODELS.get(step_type, GeneratedDescription)


class LiteLLMTextProvider(BaseTextProvider):
    """LiteLLM-based text provider with structured output support."""
    
    name = "litellm"
    
    def __init__(self, model: str = "gemini/gemini-2.5-flash"):
        """Initialize the LiteLLM provider.
        
        Args:
            model: The model to use (in litellm format, e.g., "gemini/gemini-2.5-flash")
        """
        self.model = model
        self._initialized = False
        
    def _ensure_init(self):
        """Ensure litellm is configured with API keys."""
        if self._initialized:
            return
            
        import litellm
        config = get_config()
        
        # Set API keys for various providers
        if config.providers.google_api_key:
            litellm.api_key = config.providers.google_api_key
            # Also set as env var for Gemini
            import os
            os.environ["GEMINI_API_KEY"] = config.providers.google_api_key
            
        if config.providers.openai_api_key:
            import os
            os.environ["OPENAI_API_KEY"] = config.providers.openai_api_key
            
        self._initialized = True
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> str:
        """Generate text using litellm (falls back to unstructured for simple cases)."""
        import litellm
        self._ensure_init()
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = await litellm.acompletion(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
        )
        
        return response.choices[0].message.content or ""
    
    async def generate_structured(
        self,
        prompt: str,
        schema: dict,
        system_prompt: Optional[str] = None,
    ) -> dict:
        """Generate structured JSON output."""
        import json
        import litellm
        self._ensure_init()
        
        # Add JSON instruction to prompt
        json_prompt = f"{prompt}\n\nRespond with valid JSON matching this schema:\n{json.dumps(schema, indent=2)}"
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": json_prompt})
        
        response = await litellm.acompletion(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        
        return json.loads(response.choices[0].message.content or "{}")
    
    async def generate_with_model(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
    ) -> T:
        """Generate structured output using a Pydantic model.
        
        This is the preferred method for text generation as it ensures
        clean, structured output.
        
        Args:
            prompt: The generation prompt
            response_model: Pydantic model class defining the expected output
            system_prompt: Optional system context
            
        Returns:
            Instance of the response_model with generated content
        """
        import json
        import litellm
        self._ensure_init()
        
        # Build the schema from the Pydantic model
        schema = response_model.model_json_schema()
        
        # Create a prompt that explicitly requests JSON output
        json_instruction = (
            f"You must respond with ONLY a valid JSON object matching this schema:\n"
            f"{json.dumps(schema, indent=2)}\n\n"
            f"Do NOT include any text before or after the JSON. "
            f"Do NOT include markdown code blocks. "
            f"Output ONLY the raw JSON object."
        )
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": f"{system_prompt}\n\n{json_instruction}"})
        else:
            messages.append({"role": "system", "content": json_instruction})
        messages.append({"role": "user", "content": prompt})
        
        logger.info(f"Generating structured output with model {response_model.__name__}")
        
        response = await litellm.acompletion(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        
        # Parse the response into the Pydantic model
        content = response.choices[0].message.content
        if isinstance(content, str):
            # Clean up any markdown code blocks if present
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            data = json.loads(content)
            return response_model.model_validate(data)
        elif isinstance(content, dict):
            return response_model.model_validate(content)
        else:
            # litellm may return the parsed model directly
            return content

    async def generate_text_for_step(
        self,
        prompt: str,
        step_type: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Generate text for a specific step type, using appropriate structured output.
        
        Args:
            prompt: The generation prompt
            step_type: The type of step (e.g., "name", "flavor", "description")
            system_prompt: Optional system context
            
        Returns:
            The generated text content (extracted from structured output)
        """
        response_model = get_response_model_for_step(step_type)
        
        # Build a system prompt that enforces structured output
        structured_system = self._get_structured_system_prompt(step_type)
        if system_prompt:
            structured_system = f"{system_prompt}\n\n{structured_system}"
        
        try:
            result = await self.generate_with_model(
                prompt,
                response_model,
                structured_system,
            )
            
            # Extract the text content from the structured response
            if hasattr(result, "name"):
                return result.name
            elif hasattr(result, "text"):
                return result.text
            elif hasattr(result, "options"):
                return result.options[0] if result.options else ""
            elif hasattr(result, "abilities"):
                return "\n".join(result.abilities)
            elif hasattr(result, "tags"):
                return ", ".join(result.tags)
            else:
                return str(result)
        except Exception as e:
            logger.warning(f"Structured generation failed, falling back to simple: {e}")
            # Fall back to simple generation with explicit instructions
            return await self._generate_simple_for_step(prompt, step_type)
    
    def _get_structured_system_prompt(self, step_type: str) -> str:
        """Get a system prompt that enforces structured output for the step type."""
        prompts = {
            "name": (
                "You are a creative name generator for fantasy games. "
                "Generate ONE unique, evocative name. "
                "The name should be memorable and fit the subject."
            ),
            "generate_name": (
                "You are a creative name generator for fantasy games. "
                "Generate ONE unique, evocative name. "
                "The name should be memorable and fit the subject."
            ),
            "flavor": (
                "You are a flavor text writer for trading card games. "
                "Write short (1-2 sentences), evocative flavor text. "
                "The text should be atmospheric and hint at lore without being explicit."
            ),
            "flavor_text": (
                "You are a flavor text writer for trading card games. "
                "Write short (1-2 sentences), evocative flavor text. "
                "The text should be atmospheric and hint at lore without being explicit."
            ),
            "description": (
                "You are a description writer. "
                "Write a clear, vivid description."
            ),
            "generate_text": (
                "You are a creative text generator. "
                "Generate the requested content directly without preamble."
            ),
        }
        return prompts.get(step_type, prompts["generate_text"])
    
    async def _generate_simple_for_step(self, prompt: str, step_type: str) -> str:
        """Fallback to simple text generation with explicit instructions."""
        instructions = {
            "name": "Generate ONE creative name. Output ONLY the name, nothing else.",
            "generate_name": "Generate ONE creative name. Output ONLY the name, nothing else.",
            "flavor": "Write short, evocative flavor text. Output ONLY the flavor text.",
            "flavor_text": "Write short, evocative flavor text. Output ONLY the flavor text.",
            "description": "Write a description. Output ONLY the description text.",
            "generate_text": "Generate the requested text. Output ONLY the text content.",
        }
        
        instruction = instructions.get(step_type, instructions["generate_text"])
        enhanced_prompt = f"{instruction}\n\n{prompt}"
        
        return await self.generate(enhanced_prompt)
