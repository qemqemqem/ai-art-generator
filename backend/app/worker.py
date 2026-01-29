"""Interactive mode background worker.

Handles async generation and approval workflow.
"""

import asyncio
import base64
import logging
from datetime import datetime
from io import BytesIO
from typing import Any, Optional

logger = logging.getLogger(__name__)

from app.models import (
    Asset,
    AssetStatus,
    PipelineStep,
    StepType,
    StepResult,
    GeneratedArtifact,
)
from app.queue_manager import (
    QueueManager,
    ApprovalItem,
    ApprovalType,
    GeneratedOption,
)
from pipeline import Project, PipelineOrchestrator
from providers import get_provider_registry


class InteractiveWorker:
    """Background worker for interactive generation.
    
    This worker:
    1. Picks up pending assets
    2. Runs pipeline steps
    3. For steps requiring approval, generates options and queues for user
    4. Waits for user decisions before continuing
    """
    
    def __init__(self, project: Project, queue_manager: QueueManager):
        self.project = project
        self.queue = queue_manager
        self.registry = get_provider_registry()
        self._running = False
        self._semaphore = asyncio.Semaphore(3)  # Max concurrent generations
    
    async def run(self):
        """Main worker loop."""
        self._running = True
        logger.info("Interactive worker started")
        
        while self._running and self.queue._running:
            if self.queue._paused:
                await asyncio.sleep(0.5)
                continue
            
            # Find work to do
            try:
                work = await self._find_work()
            except Exception as e:
                logger.error(f"Error finding work: {e}")
                await asyncio.sleep(1)
                continue
            
            if not work:
                # No work available, wait a bit
                await asyncio.sleep(0.5)
                continue
            
            asset_id, step = work
            logger.info(f"Processing asset {asset_id}, step {step.id} ({step.type})")
            
            # Process the step
            async with self._semaphore:
                try:
                    await self._process_step(asset_id, step)
                except Exception as e:
                    logger.error(f"Error processing step {step.id} for asset {asset_id}: {e}")
        
        logger.info("Interactive worker stopped")
        self._running = False
    
    async def _find_work(self) -> Optional[tuple[str, PipelineStep]]:
        """Find the next piece of work to do.
        
        Returns (asset_id, step) or None if no work available.
        """
        # Check pending assets first
        if self.queue._pending_asset_ids:
            asset_id = self.queue._pending_asset_ids.pop(0)
            asset = self.project.get_asset(asset_id)
            
            if asset and self.project.config.pipeline:
                # Start with first step
                return (asset_id, self.project.config.pipeline[0])
        
        # Check assets awaiting next step (after approval)
        for asset_id, asset in self.queue._assets.items():
            if asset.status == AssetStatus.PROCESSING:
                next_step = self._get_next_step(asset)
                if next_step:
                    return (asset_id, next_step)
        
        return None
    
    def _get_next_step(self, asset: Asset) -> Optional[PipelineStep]:
        """Get the next step for an asset."""
        pipeline = self.project.config.pipeline
        if not pipeline:
            return None
        
        # Find the last approved step
        last_approved_idx = -1
        for i, step in enumerate(pipeline):
            if step.id in asset.results:
                result = asset.results[step.id]
                if result.status == AssetStatus.APPROVED:
                    last_approved_idx = i
                elif result.status == AssetStatus.AWAITING_APPROVAL:
                    # Still waiting on this step
                    return None
        
        # Return next step if available
        next_idx = last_approved_idx + 1
        if next_idx < len(pipeline):
            return pipeline[next_idx]
        
        return None
    
    async def _process_step(self, asset_id: str, step: PipelineStep):
        """Process a single pipeline step."""
        asset = self.queue._assets.get(asset_id)
        if not asset:
            return
        
        # Update status
        asset.status = AssetStatus.PROCESSING
        asset.current_step = step.id
        
        # Track generation
        gen_id = self.queue.start_generating(asset_id, step.id, step.type.value)
        
        try:
            # Build context from previous steps
            context = self._build_context(asset)
            
            # Generate based on step type
            if step.type == StepType.RESEARCH:
                await self._run_research_step(asset, step, context, gen_id)
            elif step.type == StepType.GENERATE_NAME:
                await self._run_text_step(asset, step, context, gen_id)
            elif step.type == StepType.GENERATE_TEXT:
                await self._run_text_step(asset, step, context, gen_id)
            elif step.type in (StepType.GENERATE_IMAGE, StepType.GENERATE_SPRITE):
                await self._run_image_step(asset, step, context, gen_id)
            elif step.type == StepType.REMOVE_BACKGROUND:
                await self._run_bg_removal_step(asset, step, context, gen_id)
            
        except Exception as e:
            # Mark step as failed
            logger.error(f"Step {step.id} failed for asset {asset_id}: {e}", exc_info=True)
            asset.results[step.id] = StepResult(
                step_id=step.id,
                status=AssetStatus.FAILED,
                error=str(e),
            )
            asset.status = AssetStatus.FAILED
        finally:
            self.queue.finish_generating(gen_id)
            await self.project.save_asset(asset)
            logger.info(f"Completed step {step.id} for asset {asset_id}")
    
    def _build_context(self, asset: Asset) -> dict[str, Any]:
        """Build context dictionary from completed steps."""
        context = {
            "description": asset.input_description,
            "id": asset.id,
            "metadata": asset.input_metadata,
        }
        
        for step_id, result in asset.results.items():
            if result.status == AssetStatus.APPROVED and result.variations:
                selected_idx = result.selected_index or 0
                if selected_idx < len(result.variations):
                    artifact = result.variations[selected_idx]
                    
                    # Add to context based on type
                    if artifact.type == "text":
                        context[step_id] = artifact.content
                    elif artifact.type == "research":
                        context["research"] = artifact.content
                    elif artifact.type == "image":
                        context[step_id] = artifact.path
        
        return context
    
    async def _run_research_step(
        self,
        asset: Asset,
        step: PipelineStep,
        context: dict[str, Any],
        gen_id: str,
    ):
        """Run a research step."""
        # For now, skip research (TODO: implement Tavily/Perplexity)
        self.queue.update_progress(gen_id, 50.0)
        
        # Create placeholder result
        asset.results[step.id] = StepResult(
            step_id=step.id,
            status=AssetStatus.APPROVED,  # Auto-approve research
            approved=True,
            variations=[GeneratedArtifact(
                type="research",
                content=f"Research placeholder for: {asset.input_description}",
            )],
            selected_index=0,
        )
        
        self.queue.update_progress(gen_id, 100.0)
    
    async def _run_text_step(
        self,
        asset: Asset,
        step: PipelineStep,
        context: dict[str, Any],
        gen_id: str,
    ):
        """Run a text generation step."""
        provider_name = step.provider or self.project.config.default_text_provider.value
        provider = self.registry.get_text_provider(provider_name)
        
        # Build prompt from template
        prompt = self._render_template(step.prompt_template or "{description}", context)
        
        # Determine step type for structured output
        step_type = step.type.value if hasattr(step.type, 'value') else str(step.type)
        
        # Generate variations
        variations = []
        for i in range(step.variations):
            self.queue.update_progress(gen_id, (i / step.variations) * 100)
            
            # Use structured generation if provider supports it
            if hasattr(provider, 'generate_text_for_step'):
                text = await provider.generate_text_for_step(prompt, step_type)
            else:
                text = await provider.generate(prompt)
                
            variations.append(GeneratedArtifact(
                type="text",
                content=text,
                metadata={"prompt": prompt, "step_type": step_type},
            ))
        
        self.queue.update_progress(gen_id, 100.0)
        
        # Create step result
        asset.results[step.id] = StepResult(
            step_id=step.id,
            status=AssetStatus.AWAITING_APPROVAL if step.requires_approval else AssetStatus.APPROVED,
            variations=variations,
            approved=not step.requires_approval,
            selected_index=0 if not step.requires_approval else None,
        )
        
        # Add to approval queue if needed
        if step.requires_approval:
            asset.status = AssetStatus.AWAITING_APPROVAL
            
            options = [
                GeneratedOption(
                    type="text",
                    text_content=v.content,
                    prompt_used=prompt,
                )
                for v in variations
            ]
            
            approval_item = ApprovalItem(
                asset_id=asset.id,
                asset_description=asset.input_description,
                step_id=step.id,
                step_name=step.type.value,
                step_index=self._get_step_index(step.id),
                total_steps=len(self.project.config.pipeline),
                approval_type=ApprovalType.CHOOSE_ONE if step.variations > 1 else ApprovalType.ACCEPT_REJECT,
                options=options,
                context=context,
            )
            
            self.queue.add_approval_item(approval_item)
    
    async def _run_image_step(
        self,
        asset: Asset,
        step: PipelineStep,
        context: dict[str, Any],
        gen_id: str,
    ):
        """Run an image generation step."""
        provider_name = step.provider or self.project.config.default_image_provider.value
        provider = self.registry.get_image_provider(provider_name)
        
        # Build prompt from template
        prompt = self._render_template(step.prompt_template or "{description}", context)
        
        # Add global style
        style = self.project.config.style
        full_prompt = f"{style.global_prompt_prefix} {prompt} {style.global_prompt_suffix}".strip()
        
        # For sprite generation, ensure we use solid white background instead of "transparent"
        # AI generators draw checkerboard patterns when asked for transparency - we use
        # white background + rembg post-processing for true alpha transparency
        is_sprite = step.type == StepType.GENERATE_SPRITE
        if is_sprite:
            # Add solid white background to prompt if not already specified
            if "white background" not in full_prompt.lower() and "solid background" not in full_prompt.lower():
                full_prompt = f"{full_prompt}, isolated on solid white background"
        
        # Generate images
        self.queue.update_progress(gen_id, 10.0)
        
        images = await provider.generate(
            prompt=full_prompt,
            style=style,
            variations=step.variations,
        )
        
        # For sprites, auto-remove background to create true transparency (default: True)
        auto_remove_bg = step.config.get("auto_remove_background", True) if is_sprite else False
        if auto_remove_bg:
            import rembg
            self.queue.update_progress(gen_id, 70.0)
            processed_images = []
            for img in images:
                processed_images.append(rembg.remove(img))
            images = processed_images
        
        self.queue.update_progress(gen_id, 90.0)
        
        # Save images and create artifacts
        variations = []
        options = []
        
        for i, img in enumerate(images):
            # Save to disk
            filename = f"{asset.id}_{step.id}_{i}.png"
            filepath = self.project.path / "outputs" / asset.id / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            img.save(filepath)
            
            # Create base64 thumbnail
            buffer = BytesIO()
            thumbnail = img.copy()
            thumbnail.thumbnail((256, 256))
            thumbnail.save(buffer, format="PNG")
            b64 = base64.b64encode(buffer.getvalue()).decode()
            
            artifact_metadata = {
                "prompt": full_prompt,
                "width": img.width,
                "height": img.height,
            }
            if auto_remove_bg:
                artifact_metadata["transparent"] = True
            
            variations.append(GeneratedArtifact(
                type="image" if not is_sprite else "sprite",
                path=str(filepath.relative_to(self.project.path)),
                metadata=artifact_metadata,
            ))
            
            options.append(GeneratedOption(
                type="image",
                image_path=str(filepath.relative_to(self.project.path)),
                image_data_url=f"data:image/png;base64,{b64}",
                prompt_used=full_prompt,
                generation_params={"width": img.width, "height": img.height},
            ))
        
        self.queue.update_progress(gen_id, 100.0)
        
        # Create step result
        asset.results[step.id] = StepResult(
            step_id=step.id,
            status=AssetStatus.AWAITING_APPROVAL if step.requires_approval else AssetStatus.APPROVED,
            variations=variations,
            approved=not step.requires_approval,
            selected_index=0 if not step.requires_approval else None,
        )
        
        # Add to approval queue if needed
        if step.requires_approval:
            asset.status = AssetStatus.AWAITING_APPROVAL
            
            approval_item = ApprovalItem(
                asset_id=asset.id,
                asset_description=asset.input_description,
                step_id=step.id,
                step_name=step.type.value,
                step_index=self._get_step_index(step.id),
                total_steps=len(self.project.config.pipeline),
                approval_type=ApprovalType.CHOOSE_ONE if step.variations > 1 else ApprovalType.ACCEPT_REJECT,
                options=options,
                context=context,
            )
            
            self.queue.add_approval_item(approval_item)
    
    async def _run_bg_removal_step(
        self,
        asset: Asset,
        step: PipelineStep,
        context: dict[str, Any],
        gen_id: str,
    ):
        """Run background removal on the previous image."""
        import rembg
        from PIL import Image
        
        # Find the previous image step
        prev_image_path = None
        for step_id, result in asset.results.items():
            if result.status == AssetStatus.APPROVED and result.variations:
                selected_idx = result.selected_index or 0
                artifact = result.variations[selected_idx]
                if artifact.type == "image" and artifact.path:
                    prev_image_path = artifact.path
        
        if not prev_image_path:
            raise ValueError("No previous image found for background removal")
        
        self.queue.update_progress(gen_id, 20.0)
        
        # Load and process image
        full_path = self.project.path / prev_image_path
        img = Image.open(full_path)
        
        self.queue.update_progress(gen_id, 40.0)
        
        # Remove background
        result_img = rembg.remove(img)
        
        self.queue.update_progress(gen_id, 80.0)
        
        # Save result
        filename = f"{asset.id}_{step.id}_nobg.png"
        filepath = self.project.path / "outputs" / asset.id / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        result_img.save(filepath)
        
        self.queue.update_progress(gen_id, 100.0)
        
        # Create artifact (auto-approve background removal)
        asset.results[step.id] = StepResult(
            step_id=step.id,
            status=AssetStatus.APPROVED,
            approved=True,
            variations=[GeneratedArtifact(
                type="image",
                path=str(filepath.relative_to(self.project.path)),
                metadata={
                    "source": prev_image_path,
                    "width": result_img.width,
                    "height": result_img.height,
                },
            )],
            selected_index=0,
        )
    
    def _render_template(self, template: str, context: dict[str, Any]) -> str:
        """Render a prompt template with context variables."""
        result = template
        for key, value in context.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result
    
    def _get_step_index(self, step_id: str) -> int:
        """Get the index of a step in the pipeline."""
        for i, step in enumerate(self.project.config.pipeline):
            if step.id == step_id:
                return i
        return 0
    
    def stop(self):
        """Stop the worker."""
        self._running = False
