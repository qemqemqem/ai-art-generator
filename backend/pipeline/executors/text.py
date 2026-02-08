"""
Text Generation Executors.

Handles text-based steps:
  - research: AI research on a topic
  - generate_text: General text generation
  - generate_name: Name generation
  - generate_prompt: Image prompt generation

All text executors automatically include rich context from:
  - Global/gather step outputs
  - Previous per-asset step outputs for the current asset
  - Pipeline context variables
"""

from typing import Any

from .base import ExecutorContext, StepExecutor, StepResult
from .registry import register_executor
from ..templates import substitute_template


def _build_context_section(ctx: ExecutorContext) -> str:
    """
    Build a context section to include in LLM prompts.
    
    Includes:
      - Pipeline context variables (style, etc.)
      - Outputs from previous steps for this asset
    """
    parts = []
    
    # Include pipeline context
    if ctx.context:
        context_items = []
        for key, value in ctx.context.items():
            if isinstance(value, (str, int, float, bool)):
                context_items.append(f"- {key}: {value}")
        if context_items:
            parts.append("Project Context:")
            parts.extend(context_items)
            parts.append("")
    
    # Include asset info
    if ctx.asset:
        asset_items = []
        for key, value in ctx.asset.items():
            if key != "id" and isinstance(value, (str, int, float, bool)):
                asset_items.append(f"- {key}: {value}")
        if asset_items:
            parts.append("Current Asset:")
            parts.extend(asset_items)
            parts.append("")
    
    # Include relevant step outputs
    if ctx.step_outputs:
        for step_id, output in ctx.step_outputs.items():
            # Skip internal keys
            if step_id.startswith("_"):
                continue
            
            content = _extract_content(output)
            if content:
                parts.append(f"Previous Step '{step_id}':")
                # Truncate long content
                if len(content) > 500:
                    content = content[:500] + "..."
                parts.append(content)
                parts.append("")
    
    return "\n".join(parts)


def _extract_content(output: Any) -> str | None:
    """Extract displayable content from a step output."""
    if isinstance(output, str):
        return output
    
    if isinstance(output, dict):
        # Try common content keys
        for key in ["content", "text", "result", "output", "prompt"]:
            if key in output and output[key]:
                val = output[key]
                if isinstance(val, str):
                    return val
    
    return None


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
            max_tokens: Maximum output tokens (optional, no limit if not specified)
        """
        import time
        start = time.time()
        
        query = config.get("query", "")
        max_tokens = config.get("max_tokens")  # None = no limit
        
        # Substitute template variables
        query = substitute_template(
            query,
            ctx.context,
            ctx.asset,
            ctx.step_outputs,
        )
        
        # Get text provider (use context's configured provider)
        provider = ctx.providers.get_text_provider(ctx.text_provider)
        
        # Build context section
        context_section = _build_context_section(ctx)
        
        prompt = f"""Research the following topic and provide useful background information:

{query}

{context_section}

Provide:
1. A brief summary of the key points
2. Relevant visual elements or characteristics
3. Historical or cultural context if applicable
4. Suggestions for creative interpretation

Be thorough but concise. Focus on details that would help create visual art."""
        
        # Use generate_with_cost if available for cost tracking
        cost_usd = 0.0
        tokens_used = None
        
        if hasattr(provider, 'generate_with_cost'):
            gen_result = await provider.generate_with_cost(prompt, max_tokens=max_tokens)
            result = gen_result.content
            cost_usd = gen_result.cost_usd
            tokens_used = {
                "prompt_tokens": gen_result.prompt_tokens,
                "completion_tokens": gen_result.completion_tokens,
                "total_tokens": gen_result.total_tokens,
            }
        else:
            result = await provider.generate(prompt, max_tokens=max_tokens)
        
        duration = int((time.time() - start) * 1000)
        
        return StepResult(
            success=True,
            output={"content": result, "query": query},
            duration_ms=duration,
            prompt=prompt,
            cost_usd=cost_usd,
            tokens_used=tokens_used,
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
            max_tokens: Maximum output tokens (optional, no limit if not specified)
            variations: Number of variations to generate
            include_context: Whether to include rich context (default: True)
        """
        import time
        start = time.time()
        
        prompt = config.get("prompt", "")
        variations = config.get("variations", 1)
        include_context = config.get("include_context", True)
        max_tokens = config.get("max_tokens")  # None = no limit
        
        # Substitute template variables
        prompt = substitute_template(
            prompt,
            ctx.context,
            ctx.asset,
            ctx.step_outputs,
        )
        
        # Build full prompt with context
        if include_context:
            context_section = _build_context_section(ctx)
            if context_section:
                full_prompt = f"""Background Context:
{context_section}

Task:
{prompt}"""
            else:
                full_prompt = prompt
        else:
            full_prompt = prompt
        
        # Get text provider (use context's configured provider)
        provider = ctx.providers.get_text_provider(ctx.text_provider)
        
        results = []
        total_cost = 0.0
        total_tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        for i in range(variations):
            if hasattr(provider, 'generate_with_cost'):
                gen_result = await provider.generate_with_cost(full_prompt, max_tokens=max_tokens)
                results.append(gen_result.content)
                total_cost += gen_result.cost_usd
                total_tokens["prompt_tokens"] += gen_result.prompt_tokens
                total_tokens["completion_tokens"] += gen_result.completion_tokens
                total_tokens["total_tokens"] += gen_result.total_tokens
            else:
                result = await provider.generate(full_prompt, max_tokens=max_tokens)
                results.append(result)
        
        duration = int((time.time() - start) * 1000)
        
        return StepResult(
            success=True,
            output={"content": results[0]},
            variations=results,
            duration_ms=duration,
            prompt=full_prompt,
            cost_usd=total_cost,
            tokens_used=total_tokens if total_cost > 0 else None,
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
        
        # Get text provider (use context's configured provider)
        provider = ctx.providers.get_text_provider(ctx.text_provider)
        
        results = []
        total_cost = 0.0
        total_tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        for i in range(variations):
            if hasattr(provider, 'generate_with_cost'):
                gen_result = await provider.generate_with_cost(prompt)
                results.append(gen_result.content.strip())
                total_cost += gen_result.cost_usd
                total_tokens["prompt_tokens"] += gen_result.prompt_tokens
                total_tokens["completion_tokens"] += gen_result.completion_tokens
                total_tokens["total_tokens"] += gen_result.total_tokens
            else:
                result = await provider.generate(prompt)
                results.append(result.strip())
        
        duration = int((time.time() - start) * 1000)
        
        return StepResult(
            success=True,
            output={"names": results},
            variations=results,
            duration_ms=duration,
            prompt=prompt,
            cost_usd=total_cost,
            tokens_used=total_tokens if total_cost > 0 else None,
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
        
        template = config.get("prompt") or config.get("template", "")
        variations = config.get("variations", 1)
        include_context = config.get("include_context", False)
        max_tokens = config.get("max_tokens")
        
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

        # If we still don't have a template, just return the built prompt
        if not prompt_template:
            duration = int((time.time() - start) * 1000)
            return StepResult(
                success=True,
                output={"prompt": "", "output": ""},
                duration_ms=duration,
                prompt="(no prompt template provided)",
            )

        # Optionally include rich context in the instruction prompt
        if include_context:
            context_section = _build_context_section(ctx)
            if context_section:
                full_prompt = f"""Background Context:
{context_section}

Task:
{prompt_template}"""
            else:
                full_prompt = prompt_template
        else:
            full_prompt = prompt_template

        # Get text provider (use context's configured provider)
        provider = ctx.providers.get_text_provider(ctx.text_provider)

        results = []
        total_cost = 0.0
        total_tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        for _ in range(variations):
            if hasattr(provider, "generate_with_cost"):
                gen_result = await provider.generate_with_cost(full_prompt, max_tokens=max_tokens)
                results.append(gen_result.content)
                total_cost += gen_result.cost_usd
                total_tokens["prompt_tokens"] += gen_result.prompt_tokens
                total_tokens["completion_tokens"] += gen_result.completion_tokens
                total_tokens["total_tokens"] += gen_result.total_tokens
            else:
                result = await provider.generate(full_prompt, max_tokens=max_tokens)
                results.append(result)

        duration = int((time.time() - start) * 1000)

        return StepResult(
            success=True,
            output={"prompt": results[0], "output": results[0]},
            variations=results,
            duration_ms=duration,
            prompt=full_prompt,
            cost_usd=total_cost,
            tokens_used=total_tokens if total_cost > 0 else None,
        )
