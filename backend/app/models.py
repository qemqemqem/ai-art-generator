"""Data models for AI Art Generator."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class AssetStatus(str, Enum):
    """Status of an asset in the pipeline."""
    PENDING = "pending"
    PROCESSING = "processing"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"


class ImageProvider(str, Enum):
    """Available image generation providers."""
    GEMINI = "gemini"
    GEMINI_PRO = "gemini_pro"
    DALLE = "dalle"
    STABLE_DIFFUSION = "stable_diffusion"
    FLUX = "flux"
    PIXELLAB = "pixellab"


class TextProvider(str, Enum):
    """Available text generation providers."""
    GEMINI = "gemini"
    CLAUDE = "claude"
    GPT = "gpt"


class ResearchProvider(str, Enum):
    """Available research providers."""
    TAVILY = "tavily"
    PERPLEXITY = "perplexity"


class StepType(str, Enum):
    """Types of pipeline steps."""
    RESEARCH = "research"
    GENERATE_NAME = "generate_name"
    GENERATE_TEXT = "generate_text"
    GENERATE_IMAGE = "generate_image"
    GENERATE_SPRITE = "generate_sprite"
    REMOVE_BACKGROUND = "remove_background"
    CUSTOM = "custom"


# --- Pipeline Configuration ---

class PipelineStep(BaseModel):
    """A single step in the generation pipeline."""
    id: str
    type: StepType
    provider: Optional[str] = None
    prompt_template: Optional[str] = None
    requires_approval: bool = False
    variations: int = 1
    parallel_with: Optional[list[str]] = None
    config: dict[str, Any] = Field(default_factory=dict)


class StyleConfig(BaseModel):
    """Style configuration for image generation."""
    global_prompt_prefix: str = ""
    global_prompt_suffix: str = ""
    negative_prompt: str = ""
    aspect_ratio: str = "1:1"
    image_size: str = "1K"


class ProjectConfig(BaseModel):
    """Configuration for a generation project."""
    name: str
    description: str = ""
    style: StyleConfig = Field(default_factory=StyleConfig)
    pipeline: list[PipelineStep] = Field(default_factory=list)
    default_image_provider: ImageProvider = ImageProvider.GEMINI
    default_text_provider: TextProvider = TextProvider.GEMINI
    settings: dict[str, Any] = Field(default_factory=dict)


# --- Asset State ---

class GeneratedArtifact(BaseModel):
    """A generated artifact (image, text, etc.)."""
    type: str  # "image", "text", "research"
    path: Optional[str] = None  # For files
    content: Optional[str] = None  # For text
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StepResult(BaseModel):
    """Result of a pipeline step execution."""
    step_id: str
    status: AssetStatus
    variations: list[GeneratedArtifact] = Field(default_factory=list)
    selected_index: Optional[int] = None
    approved: bool = False
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class Asset(BaseModel):
    """An asset being generated through the pipeline."""
    id: str
    input_description: str
    input_metadata: dict[str, Any] = Field(default_factory=dict)
    status: AssetStatus = AssetStatus.PENDING
    current_step: Optional[str] = None
    results: dict[str, StepResult] = Field(default_factory=dict)  # step_id -> result
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# --- Input Formats ---

class InputItem(BaseModel):
    """A single input item for generation."""
    id: Optional[str] = None
    description: str
    name: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BatchInput(BaseModel):
    """Batch input for asset generation."""
    items: list[InputItem]
    style_override: Optional[StyleConfig] = None


# --- API Request/Response Models ---

class CreateProjectRequest(BaseModel):
    """Request to create a new project."""
    name: str
    description: str = ""
    style: Optional[StyleConfig] = None
    pipeline: Optional[list[PipelineStep]] = None


class GenerateRequest(BaseModel):
    """Request to generate images."""
    prompt: str
    provider: ImageProvider = ImageProvider.GEMINI
    style: Optional[StyleConfig] = None
    variations: int = 1


class ApprovalRequest(BaseModel):
    """Request to approve/reject a step result."""
    asset_id: str
    step_id: str
    approved: bool
    selected_index: Optional[int] = None  # Which variation to select
    regenerate: bool = False
    modified_prompt: Optional[str] = None


class QueueItem(BaseModel):
    """An item in the approval queue."""
    asset: Asset
    step: StepResult
    step_config: PipelineStep
