"""
Text Generation Executors.

Handles text-based steps:
  - research: AI research on a topic
  - generate_text: General text generation
  - generate_name: Name generation
  - generate_prompt: Image prompt generation
"""

from typing import Any

from .base import ExecutorContext, StepExecutor, StepResult
from .registry import register_executor
from ..templates import substitute_template


@register_executor("research")
class ResearchExecutor(StepExecutor):
    """Execute research steps using AI."""
    
    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute a research step.
        
        Config:
            query: The research query
            depth: How deep to research (default: "medium")
        """
        import time
        start = time.time()
        
        query = config.get("query", "")
        
        # Substitute template variables
        query = substitute_template(
            query,
            ctx.context,
            ctx.asset,
            ctx.step_outputs,
        )
        
        # Get text provider
        provider = ctx.providers.get_text_provider("litellm")
        
        prompt = f"""Research the following topic and provide useful background information:

{query}

Provide:
1. A brief summary of the key points
2. Relevant visual elements or characteristics
3. Historical or cultural context if applicable
4. Suggestions for creative interpretation

Be thorough but concise. Focus on details that would help create visual art."""
        
        try:
            result = await provider.generate(prompt)
            
            duration = int((time.time() - start) * 1000)
            
            return StepResult(
                success=True,
                output={"content": result, "query": query},
                duration_ms=duration,
            )
        except Exception as e:
            return StepResult(
                success=False,
                error=str(e),
            )


@register_executor("generate_text")
class GenerateTextExecutor(StepExecutor):
    """Execute text generation steps."""
    
    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute a text generation step.
        
        Config:
            prompt: The generation prompt
            max_length: Maximum output length
            variations: Number of variations to generate
        """
        import time
        start = time.time()
        
        prompt = config.get("prompt", "")
        variations = config.get("variations", 1)
        
        # Substitute template variables
        prompt = substitute_template(
            prompt,
            ctx.context,
            ctx.asset,
            ctx.step_outputs,
        )
        
        # Get text provider
        provider = ctx.providers.get_text_provider("litellm")
        
        try:
            results = []
            for i in range(variations):
                result = await provider.generate(prompt)
                results.append(result)
            
            duration = int((time.time() - start) * 1000)
            
            if len(results) == 1:
                return StepResult(
                    success=True,
                    output={"content": results[0]},
                    variations=results,
                    duration_ms=duration,
                )
            else:
                return StepResult(
                    success=True,
                    output={"content": results[0]},
                    variations=results,
                    duration_ms=duration,
                )
        except Exception as e:
            return StepResult(
                success=False,
                error=str(e),
            )


@register_executor("generate_name")
class GenerateNameExecutor(StepExecutor):
    """Execute name generation steps."""
    
    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute a name generation step.
        
        Config:
            style: Style of name (e.g., "fantasy", "sci-fi")
            constraints: Additional constraints
            variations: Number of name options
        """
        import time
        start = time.time()
        
        style = config.get("style", "creative")
        constraints = config.get("constraints", "")
        variations = config.get("variations", 3)
        
        # Build context for the prompt
        context_desc = ""
        if ctx.asset:
            context_desc = f"Concept: {ctx.asset.get('prompt', ctx.asset.get('description', ''))}"
        
        prompt = f"""Generate a {style} name for the following:

{context_desc}
{constraints}

The name should be:
- Memorable and unique
- Fitting for the concept
- 1-4 words

Respond with just the name, nothing else."""
        
        # Get text provider
        provider = ctx.providers.get_text_provider("litellm")
        
        try:
            results = []
            for i in range(variations):
                result = await provider.generate(prompt)
                results.append(result.strip())
            
            duration = int((time.time() - start) * 1000)
            
            return StepResult(
                success=True,
                output={"names": results},
                variations=results,
                duration_ms=duration,
            )
        except Exception as e:
            return StepResult(
                success=False,
                error=str(e),
            )


@register_executor("generate_prompt")
class GeneratePromptExecutor(StepExecutor):
    """Execute image prompt generation steps."""
    
    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute an image prompt generation step.
        
        Config:
            template: Base template for the prompt
            use: What context to incorporate (e.g., ["research", "asset"])
        """
        import time
        start = time.time()
        
        template = config.get("template", "")
        
        # Substitute template variables
        prompt_template = substitute_template(
            template,
            ctx.context,
            ctx.asset,
            ctx.step_outputs,
        )
        
        # If template is empty, build from context
        if not prompt_template:
            parts = []
            
            # Add style from context
            if "style" in ctx.context:
                parts.append(ctx.context["style"])
            
            # Add asset description
            if ctx.asset:
                if "prompt" in ctx.asset:
                    parts.append(ctx.asset["prompt"])
                elif "description" in ctx.asset:
                    parts.append(ctx.asset["description"])
                if "name" in ctx.asset:
                    parts.insert(0, ctx.asset["name"])
            
            prompt_template = ", ".join(parts)
        
        duration = int((time.time() - start) * 1000)
        
        return StepResult(
            success=True,
            output={"prompt": prompt_template},
            duration_ms=duration,
        )
