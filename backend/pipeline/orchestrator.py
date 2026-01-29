"""Pipeline orchestrator for executing multi-step generation."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image

from app.models import (
    Asset,
    AssetStatus,
    GeneratedArtifact,
    PipelineStep,
    StepResult,
    StepType,
    StyleConfig,
)
from providers import get_provider_registry

from .project import Project


class PipelineOrchestrator:
    """Orchestrates the execution of generation pipelines."""
    
    def __init__(self, project: Project):
        """Initialize the orchestrator.
        
        Args:
            project: The project to orchestrate
        """
        self.project = project
        self.registry = get_provider_registry()
    
    async def process_asset(
        self,
        asset: Asset,
        auto_approve: bool = False,
    ) -> Asset:
        """Process an asset through the pipeline.
        
        Args:
            asset: The asset to process
            auto_approve: If True, automatically approve all steps
            
        Returns:
            The updated asset
        """
        pipeline = self.project.config.pipeline
        if not pipeline:
            # Use default simple pipeline
            from .project import DEFAULT_SIMPLE_PIPELINE
            pipeline = DEFAULT_SIMPLE_PIPELINE
        
        asset.status = AssetStatus.PROCESSING
        await self.project.save_asset(asset)
        
        # Process each step
        for step in pipeline:
            if self._should_skip_step(asset, step):
                continue
            
            asset.current_step = step.id
            await self.project.save_asset(asset)
            
            result = await self._execute_step(asset, step)
            asset.results[step.id] = result
            
            if result.status == AssetStatus.FAILED:
                asset.status = AssetStatus.FAILED
                await self.project.save_asset(asset)
                return asset
            
            if step.requires_approval and not auto_approve:
                asset.status = AssetStatus.AWAITING_APPROVAL
                await self.project.save_asset(asset)
                return asset  # Wait for human approval
            
            # Auto-approve: select first variation
            if result.variations and result.selected_index is None:
                result.selected_index = 0
                result.approved = True
            
            result.status = AssetStatus.COMPLETED
            await self.project.save_asset(asset)
        
        asset.status = AssetStatus.COMPLETED
        asset.current_step = None
        await self.project.save_asset(asset)
        return asset
    
    def _should_skip_step(self, asset: Asset, step: PipelineStep) -> bool:
        """Check if a step should be skipped."""
        if step.id in asset.results:
            result = asset.results[step.id]
            if result.status == AssetStatus.COMPLETED:
                return True
        return False
    
    async def _execute_step(
        self,
        asset: Asset,
        step: PipelineStep,
    ) -> StepResult:
        """Execute a single pipeline step.
        
        Args:
            asset: The asset being processed
            step: The step to execute
            
        Returns:
            The step result
        """
        result = StepResult(
            step_id=step.id,
            status=AssetStatus.PROCESSING,
            started_at=datetime.utcnow(),
        )
        
        try:
            if step.type == StepType.GENERATE_IMAGE:
                artifacts = await self._generate_images(asset, step)
            elif step.type == StepType.GENERATE_SPRITE:
                artifacts = await self._generate_sprites(asset, step)
            elif step.type == StepType.GENERATE_NAME:
                artifacts = await self._generate_name(asset, step)
            elif step.type == StepType.GENERATE_TEXT:
                artifacts = await self._generate_text(asset, step)
            elif step.type == StepType.RESEARCH:
                artifacts = await self._do_research(asset, step)
            elif step.type == StepType.REMOVE_BACKGROUND:
                artifacts = await self._remove_background(asset, step)
            else:
                raise ValueError(f"Unknown step type: {step.type}")
            
            result.variations = artifacts
            result.status = AssetStatus.AWAITING_APPROVAL if step.requires_approval else AssetStatus.COMPLETED
            result.completed_at = datetime.utcnow()
            
        except Exception as e:
            result.status = AssetStatus.FAILED
            result.error = str(e)
            result.completed_at = datetime.utcnow()
        
        return result
    
    async def _generate_images(
        self,
        asset: Asset,
        step: PipelineStep,
    ) -> list[GeneratedArtifact]:
        """Generate images for an asset."""
        provider_name = step.provider or self.project.config.default_image_provider.value
        provider = self.registry.get_image_provider(provider_name)
        
        # Build prompt
        prompt = self._build_image_prompt(asset, step)
        style = self.project.config.style
        
        # Generate images
        images = await provider.generate(
            prompt=prompt,
            style=style,
            variations=step.variations,
        )
        
        # Save images and create artifacts
        artifacts = []
        asset_dir = self.project.get_asset_dir(asset.id)
        
        for i, img in enumerate(images):
            filename = f"{step.id}_v{i+1}.png"
            filepath = asset_dir / filename
            img.save(filepath)
            
            artifacts.append(GeneratedArtifact(
                type="image",
                path=str(filepath.relative_to(self.project.path)),
                metadata={
                    "width": img.width,
                    "height": img.height,
                    "provider": provider_name,
                },
            ))
        
        return artifacts
    
    async def _generate_sprites(
        self,
        asset: Asset,
        step: PipelineStep,
    ) -> list[GeneratedArtifact]:
        """Generate pixel art sprites for an asset.
        
        Config options:
            auto_remove_background: If True, automatically remove the white background
                                    using rembg to create true transparency. Default: True
        """
        # Use pixellab if available, otherwise use gemini with pixel art prompt
        try:
            provider = self.registry.get_image_provider("pixellab")
            provider_name = "pixellab"
        except ValueError:
            provider_name = self.project.config.default_image_provider.value
            provider = self.registry.get_image_provider(provider_name)
        
        # Build pixel art specific prompt
        # Note: We use "solid white background" instead of "transparent background" because
        # AI image generators don't produce true alpha transparency - they literally draw
        # checkerboard patterns when asked for transparency. We rely on post-processing
        # with rembg to create actual transparency.
        base_prompt = asset.input_description
        prompt = f"Pixel art sprite, {base_prompt}, clean edges, suitable for video games, isolated on solid white background"
        
        style = StyleConfig(
            aspect_ratio="1:1",
            global_prompt_prefix="pixel art, 16-bit style, game sprite",
        )
        
        images = await provider.generate(
            prompt=prompt,
            style=style,
            variations=step.variations,
        )
        
        # Check if we should auto-remove background (default: True for sprites)
        auto_remove_bg = step.config.get("auto_remove_background", True)
        
        if auto_remove_bg:
            from rembg import remove
            processed_images = []
            for img in images:
                processed_images.append(remove(img))
            images = processed_images
        
        # Save sprites
        artifacts = []
        asset_dir = self.project.get_asset_dir(asset.id)
        
        for i, img in enumerate(images):
            filename = f"{step.id}_v{i+1}.png"
            filepath = asset_dir / filename
            img.save(filepath)
            
            artifacts.append(GeneratedArtifact(
                type="sprite",
                path=str(filepath.relative_to(self.project.path)),
                metadata={
                    "width": img.width,
                    "height": img.height,
                    "provider": provider_name,
                    "transparent": auto_remove_bg,
                },
            ))
        
        return artifacts
    
    async def _generate_name(
        self,
        asset: Asset,
        step: PipelineStep,
    ) -> list[GeneratedArtifact]:
        """Generate a name for an asset."""
        provider_name = step.provider or self.project.config.default_text_provider.value
        provider = self.registry.get_text_provider(provider_name)
        
        prompt = f"""Generate a creative, evocative name for the following concept:

{asset.input_description}

The name should be:
- Memorable and unique
- Fitting for the concept
- 1-4 words

Respond with just the name, nothing else."""
        
        # Generate multiple name options
        names = []
        for _ in range(step.variations or 3):
            name = await provider.generate(prompt)
            names.append(name.strip())
        
        return [
            GeneratedArtifact(
                type="name",
                content=name,
                metadata={"provider": provider_name},
            )
            for name in names
        ]
    
    async def _generate_text(
        self,
        asset: Asset,
        step: PipelineStep,
    ) -> list[GeneratedArtifact]:
        """Generate text description for an asset."""
        provider_name = step.provider or self.project.config.default_text_provider.value
        provider = self.registry.get_text_provider(provider_name)
        
        # Get context from previous steps
        context_parts = [f"Concept: {asset.input_description}"]
        
        if "generate_name" in asset.results:
            name_result = asset.results["generate_name"]
            if name_result.variations and name_result.selected_index is not None:
                selected_name = name_result.variations[name_result.selected_index]
                context_parts.append(f"Name: {selected_name.content}")
        
        context = "\n".join(context_parts)
        
        prompt_template = step.prompt_template or """Write a vivid, evocative description for the following:

{context}

The description should be:
- 2-3 sentences
- Atmospheric and engaging
- Suitable for a fantasy game or collectible card

Respond with just the description."""
        
        prompt = prompt_template.format(context=context)
        
        text = await provider.generate(prompt)
        
        return [
            GeneratedArtifact(
                type="text",
                content=text.strip(),
                metadata={"provider": provider_name},
            )
        ]
    
    async def _do_research(
        self,
        asset: Asset,
        step: PipelineStep,
    ) -> list[GeneratedArtifact]:
        """Do research on an asset concept."""
        try:
            provider_name = step.provider or "tavily"
            provider = self.registry.get_research_provider(provider_name)
            
            result = await provider.research(asset.input_description)
            
            return [
                GeneratedArtifact(
                    type="research",
                    content=result.get("summary", ""),
                    metadata={
                        "provider": provider_name,
                        "sources": result.get("sources", []),
                    },
                )
            ]
        except ValueError:
            # No research provider available, use text provider for research
            provider = self.registry.get_text_provider(
                self.project.config.default_text_provider.value
            )
            
            prompt = f"""Research the following concept and provide useful background information:

{asset.input_description}

Provide:
1. A brief summary of what this concept represents
2. Key visual elements associated with it
3. Any relevant historical or cultural context
4. Suggestions for artistic interpretation"""
            
            text = await provider.generate(prompt)
            
            return [
                GeneratedArtifact(
                    type="research",
                    content=text.strip(),
                    metadata={"provider": "text_fallback"},
                )
            ]
    
    async def _remove_background(
        self,
        asset: Asset,
        step: PipelineStep,
    ) -> list[GeneratedArtifact]:
        """Remove background from generated images."""
        # Find the source step (usually the previous image generation step)
        source_step = step.config.get("source_step", "generate_image")
        
        if source_step not in asset.results:
            raise ValueError(f"Source step {source_step} not found in asset results")
        
        source_result = asset.results[source_step]
        if not source_result.variations:
            raise ValueError(f"No images found in source step {source_step}")
        
        # Get the selected image (or first if none selected)
        idx = source_result.selected_index or 0
        source_artifact = source_result.variations[idx]
        
        if source_artifact.type != "image" or not source_artifact.path:
            raise ValueError("Source artifact is not an image")
        
        # Load the image
        source_path = self.project.path / source_artifact.path
        img = Image.open(source_path)
        
        # Remove background using rembg
        from rembg import remove
        result_img = remove(img)
        
        # Save the result
        asset_dir = self.project.get_asset_dir(asset.id)
        filename = f"{step.id}.png"
        filepath = asset_dir / filename
        result_img.save(filepath)
        
        return [
            GeneratedArtifact(
                type="image",
                path=str(filepath.relative_to(self.project.path)),
                metadata={
                    "width": result_img.width,
                    "height": result_img.height,
                    "transparent": True,
                    "source": source_artifact.path,
                },
            )
        ]
    
    def _build_image_prompt(self, asset: Asset, step: PipelineStep) -> str:
        """Build the image generation prompt for an asset."""
        parts = [asset.input_description]
        
        # Add context from previous steps
        if "generate_name" in asset.results:
            name_result = asset.results["generate_name"]
            if name_result.variations and name_result.selected_index is not None:
                name = name_result.variations[name_result.selected_index].content
                parts.insert(0, f'"{name}"')
        
        if "research" in asset.results:
            research_result = asset.results["research"]
            if research_result.variations:
                # Add key context from research
                research_content = research_result.variations[0].content
                if research_content:
                    # Extract first sentence or two for context
                    sentences = research_content.split(". ")[:2]
                    parts.append(". ".join(sentences))
        
        # Add step-specific config
        if step.config.get("image_type") == "portrait":
            parts.append("portrait style, detailed face and upper body")
        
        return ", ".join(parts)
    
    async def approve_step(
        self,
        asset: Asset,
        step_id: str,
        selected_index: int,
    ) -> Asset:
        """Approve a step and select a variation.
        
        Args:
            asset: The asset to update
            step_id: The step to approve
            selected_index: Index of the selected variation
            
        Returns:
            The updated asset
        """
        if step_id not in asset.results:
            raise ValueError(f"Step {step_id} not found in asset results")
        
        result = asset.results[step_id]
        result.selected_index = selected_index
        result.approved = True
        result.status = AssetStatus.COMPLETED
        
        # Continue processing if there are more steps
        asset.status = AssetStatus.PROCESSING
        await self.project.save_asset(asset)
        
        # Process remaining steps
        return await self.process_asset(asset)
    
    async def reject_step(
        self,
        asset: Asset,
        step_id: str,
        modified_prompt: Optional[str] = None,
    ) -> Asset:
        """Reject a step and optionally regenerate with a modified prompt.
        
        Args:
            asset: The asset to update
            step_id: The step to reject
            modified_prompt: Optional modified prompt for regeneration
            
        Returns:
            The updated asset with regenerated results
        """
        if step_id not in asset.results:
            raise ValueError(f"Step {step_id} not found in asset results")
        
        # Find the step configuration
        step_config = None
        for step in self.project.config.pipeline:
            if step.id == step_id:
                step_config = step
                break
        
        if not step_config:
            raise ValueError(f"Step configuration not found for {step_id}")
        
        # Update the asset's input if a modified prompt was provided
        if modified_prompt:
            asset.input_description = modified_prompt
        
        # Clear the step result and regenerate
        del asset.results[step_id]
        asset.status = AssetStatus.PROCESSING
        await self.project.save_asset(asset)
        
        # Re-execute just this step
        result = await self._execute_step(asset, step_config)
        asset.results[step_id] = result
        
        if result.status == AssetStatus.FAILED:
            asset.status = AssetStatus.FAILED
        else:
            asset.status = AssetStatus.AWAITING_APPROVAL
        
        await self.project.save_asset(asset)
        return asset
