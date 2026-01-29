# AI Art Generator - Architecture Design

## Overview

A flexible utility for batch AI art generation with support for:
- Simple batch mode (CLI)
- Interactive mode (web UI with human-in-the-loop)
- Multi-step pipelines (research → generate → refine)

---

## Core Concepts

### Project
A directory containing all state for a batch generation job. The CLI runs from within
this directory (it's the current working directory):
```
my-magic-cards/              # Run 'uvicorn app.main:app' from here
├── artgen.json              # Project config, style settings, pipeline
├── .artgen/                 # Internal state (gitignored)
│   ├── assets.jsonl         # Asset state
│   └── queue.jsonl          # Work queue
├── outputs/
│   ├── card-001/
│   │   ├── portrait.png
│   │   ├── sprite.png
│   │   └── sprite_nobg.png
│   └── card-002/
│       └── ...
└── .env.local               # API keys (gitignored)
```

### Asset
A single item being generated (e.g., one Magic card, one game sprite).
Each asset has:
- Unique ID
- Input description
- Current pipeline stage
- Generated artifacts (images, text)
- Human decisions (accept/reject history)

### Pipeline
A sequence of generation steps. Configurable per project:

```yaml
pipeline:
  - step: research
    provider: tavily
    optional: true
  - step: generate_name
    provider: claude
    requires_approval: true
  - step: generate_portrait
    provider: dalle
    variations: 4
    requires_approval: true
  - step: generate_sprite
    provider: pixellab
    parallel_with: generate_portrait
    requires_approval: true
  - step: generate_description
    provider: claude
    parallel_with: generate_portrait
```

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         CLI / Web UI                         │
├─────────────────────────────────────────────────────────────┤
│                      Orchestrator                            │
│  - Manages pipeline execution                                │
│  - Handles parallelization                                   │
│  - Persists state                                            │
├──────────────┬──────────────┬──────────────┬────────────────┤
│   Research   │   Text Gen   │  Image Gen   │  Post-Process  │
│   Provider   │   Provider   │   Provider   │    Provider    │
├──────────────┼──────────────┼──────────────┼────────────────┤
│   Tavily     │   Claude     │   DALL-E     │   rembg        │
│   Perplexity │   GPT-4o     │   FLUX       │   remove.bg    │
│              │              │   PixelLab   │                │
│              │              │   SD         │                │
└──────────────┴──────────────┴──────────────┴────────────────┘
```

---

## Modes of Operation

### 1. Batch Mode (CLI)
```bash
# Generate all assets, no human approval
ai-art generate ./my-project --auto

# Generate with specific steps
ai-art generate ./my-project --steps research,portrait

# Just generate sprites with background removal
ai-art generate ./my-project --steps sprite --remove-bg
```

### 2. Interactive Mode (Web UI)
```bash
# Launch web server for interactive approval
cd my-project
uvicorn app.main:app --reload --port 8000
# Then open http://localhost:5173 for the frontend
```

Web UI features:
- **Wizard Flow:** 4-step setup (Content → Flow → Style → Queue)
- **Queue-based Approval:** Real-time async generation with approval queue
- **Choose 1 of N:** Select best option from multiple variations
- **Accept/Reject:** Approve or request regeneration
- **Keyboard Shortcuts:** 1-4 to select, Y/N to accept/reject, R to regenerate
- **WebSocket Updates:** Real-time progress tracking
- **Side-by-side Comparison:** Grid view for image options

See `docs-ai/INTERACTIVE_MODE.md` for full specification.

---

## Queue System

### Work Queue States
```
PENDING     → Ready to process
PROCESSING  → Currently being generated
AWAITING    → Waiting for human approval
APPROVED    → Human approved, continue pipeline
REJECTED    → Human rejected, needs regeneration
COMPLETED   → Fully done
FAILED      → Error during generation
```

### Async Processing
- Background workers pull from queue
- Pre-generate variations while user reviews
- Predictive generation (start next asset while reviewing current)

---

## Data Models

### Project Config (project.json)
```json
{
  "name": "Magic Card Art",
  "style": {
    "global_prompt_prefix": "fantasy art, detailed illustration",
    "global_prompt_suffix": "dramatic lighting, 4k",
    "negative_prompt": "blurry, low quality"
  },
  "pipeline": [...],
  "providers": {
    "image": "dalle",
    "text": "claude",
    "research": "tavily",
    "pixel_art": "pixellab"
  },
  "settings": {
    "variations_per_step": 4,
    "auto_approve": false,
    "remove_backgrounds": false
  }
}
```

### Asset State (in progress.jsonl)
```json
{
  "id": "card-001",
  "input": "A wise owl wizard",
  "status": "awaiting",
  "current_step": "generate_portrait",
  "research": { "summary": "...", "sources": [...] },
  "name": { "value": "Owlmancer", "approved": true },
  "portrait": {
    "variations": ["v1.png", "v2.png", "v3.png", "v4.png"],
    "selected": null,
    "approved": false
  },
  "created_at": "2026-01-25T10:00:00Z",
  "updated_at": "2026-01-25T10:05:00Z"
}
```

---

## Technology Stack

**Backend (Python):**
- FastAPI for REST API + WebSocket
- Pydantic for data models
- google-genai for Gemini image/text generation
- rembg for local background removal
- asyncio for async processing

**Frontend (TypeScript/React):**
- React 18 with hooks
- TailwindCSS for styling
- Vite for dev server and build
- WebSocket for real-time updates

**Project Structure:**
```
ai-art-generator/
├── backend/
│   ├── app/              # FastAPI application
│   │   ├── main.py       # API endpoints
│   │   ├── models.py     # Pydantic models
│   │   ├── config.py     # Configuration
│   │   ├── queue_manager.py  # Interactive mode queue
│   │   ├── worker.py     # Background generation worker
│   │   └── websocket.py  # WebSocket handler
│   ├── providers/        # AI provider implementations
│   ├── pipeline/         # Pipeline orchestration
│   ├── parsers/          # Input format parsers
│   └── tests/            # Test suite
├── frontend/
│   └── src/
│       ├── pages/        # Wizard screens
│       ├── components/   # Reusable components
│       ├── hooks/        # Custom hooks (useWebSocket)
│       └── api/          # API client
└── docs-ai/              # Design documentation
```
