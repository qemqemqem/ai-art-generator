# Interactive Mode Specification

## Overview

Interactive mode provides a web-based workflow for generating and approving AI art assets. Users configure their pipeline, submit content, and work through an approval queue where they make decisions on generated options.

## Screen Flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Content Input  │────▶│   Flow Setup    │────▶│  Art Direction  │────▶│ Approval Queue  │
│    (Screen 1)   │     │   (Screen 2)    │     │   (Screen 3)    │     │   (Screen 4)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        │                       │                       │
        ▼                       ▼                       ▼
   Can skip if              Can skip if             Can skip if
   --input flag             --flow flag             --style flag
```

---

## Screen 1: Content Input

### Purpose
Import the list of concepts/descriptions to generate art for.

### UI Components

```
┌──────────────────────────────────────────────────────────────────┐
│  AI Art Generator - Content Input                                │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Paste your content (one item per line):                     ││
│  │                                                             ││
│  │ Fire Dragon with scales of obsidian                         ││
│  │ Ice Wizard holding a crystalline staff                      ││
│  │ Forest Spirit emerging from an ancient oak                  ││
│  │ ...                                                         ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ─── OR ───                                                      │
│                                                                  │
│  [ Drop file here or click to upload ]                           │
│  Supported: .txt, .csv, .tsv, .json, .jsonl                      │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Preview (12 items detected):                                ││
│  │ ┌─────┬──────────────────────────────────────┬────────────┐ ││
│  │ │ #   │ Description                          │ ID         │ ││
│  │ ├─────┼──────────────────────────────────────┼────────────┤ ││
│  │ │ 1   │ Fire Dragon with scales of obsidian  │ dragon_01  │ ││
│  │ │ 2   │ Ice Wizard holding a crystalline...  │ wizard_01  │ ││
│  │ │ 3   │ Forest Spirit emerging from an...    │ spirit_01  │ ││
│  │ └─────┴──────────────────────────────────────┴────────────┘ ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│                                        [ Continue → ]            │
└──────────────────────────────────────────────────────────────────┘
```

### Behavior
- Auto-detect format (plain text, CSV, JSON, JSONL)
- Show preview table with detected items
- Allow inline editing of parsed items
- Generate IDs from descriptions if not provided (slugify)

### CLI Skip
```bash
artgen interactive --input creatures.jsonl
```

---

## Screen 2: Flow Setup

### Purpose
Define the pipeline - what gets generated for each concept.

### UI Components

```
┌──────────────────────────────────────────────────────────────────┐
│  AI Art Generator - Flow Setup                                   │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  For each concept, what do you need to generate?                 │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ Pipeline Steps (drag to reorder)                    [+ Add] ││
│  │                                                              ││
│  │ ┌────────────────────────────────────────────────────────┐  ││
│  │ │ 1. 🔍 AI Research                          [×]         │  ││
│  │ │    └─ Research the concept for richer context          │  ││
│  │ │    └─ Provider: [Tavily ▼]                             │  ││
│  │ └────────────────────────────────────────────────────────┘  ││
│  │       │                                                      ││
│  │       ▼                                                      ││
│  │ ┌────────────────────────────────────────────────────────┐  ││
│  │ │ 2. ✏️ Generate Name                        [×]         │  ││
│  │ │    └─ Generate a creative name for the concept         │  ││
│  │ │    └─ Provider: [Claude ▼]  Variations: [4]            │  ││
│  │ │    └─ [✓] Requires approval                            │  ││
│  │ └────────────────────────────────────────────────────────┘  ││
│  │       │                                                      ││
│  │       ▼                                                      ││
│  │ ┌────────────────────────────────────────────────────────┐  ││
│  │ │ 3. 🖼️ Generate Portrait                    [×]         │  ││
│  │ │    └─ Main artwork for the concept                     │  ││
│  │ │    └─ Provider: [Gemini ▼]  Variations: [4]            │  ││
│  │ │    └─ Size: [1024x1024 ▼]                              │  ││
│  │ │    └─ [✓] Requires approval                            │  ││
│  │ └────────────────────────────────────────────────────────┘  ││
│  │       │                                                      ││
│  │       ├────────────┐  (parallel)                             ││
│  │       ▼            ▼                                         ││
│  │ ┌──────────────┐ ┌──────────────────────────────────────┐   ││
│  │ │ 4. 🎮 Sprite │ │ 5. 📝 Text Description               │   ││
│  │ │   [Gemini]   │ │    [Claude]                          │   ││
│  │ │   [✓] Remove │ │    Variations: [2]                   │   ││
│  │ │      bg      │ │    [✓] Requires approval             │   ││
│  │ └──────────────┘ └──────────────────────────────────────┘   ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  Presets: [ Magic Card ] [ Game Sprite ] [ Character Sheet ]     │
│                                                                  │
│                              [ ← Back ]  [ Continue → ]          │
└──────────────────────────────────────────────────────────────────┘
```

### Step Types
| Type | Description | Outputs |
|------|-------------|---------|
| `research` | AI web search for context | text (appended to context) |
| `generate_name` | Create names/titles | text options |
| `generate_image` | Create artwork | image options |
| `generate_sprite` | Create pixel art | image options |
| `generate_text` | Create descriptions | text options |
| `remove_background` | Strip bg from image | processed image |
| `upscale` | Increase resolution | processed image |

### Parallel Execution
- By default, steps run sequentially
- Steps can be marked as "parallel with previous" 
- Parallel steps share the same input context
- All parallel steps must complete before next sequential step

### CLI Skip
```bash
artgen interactive --input creatures.jsonl --flow pipeline.json
```

---

## Screen 3: Art Direction

### Purpose
Configure style, prompts, and generation parameters for each step.

### UI Components

```
┌──────────────────────────────────────────────────────────────────┐
│  AI Art Generator - Art Direction                                │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ Global Style (applies to all image steps)                   ││
│  │ ┌──────────────────────────────────────────────────────────┐││
│  │ │ Fantasy illustration style, rich colors, detailed        │││
│  │ │ textures, dramatic lighting, painterly quality           │││
│  │ └──────────────────────────────────────────────────────────┘││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  Per-Step Configuration:                                         │
│                                                                  │
│  ▼ Generate Portrait                                             │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ Prompt Template:                                            ││
│  │ ┌──────────────────────────────────────────────────────────┐││
│  │ │ {global_style}. Portrait of {description}. {research}.   │││
│  │ │ Centered composition, character focus.                   │││
│  │ └──────────────────────────────────────────────────────────┘││
│  │                                                              ││
│  │ Variations: [4 ▼]     Size: [1024x1024 ▼]                   ││
│  │ Approval Mode: (●) Choose 1 of N  ( ) Accept/Reject each    ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ▼ Generate Sprite                                               │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ Prompt Template:                                            ││
│  │ ┌──────────────────────────────────────────────────────────┐││
│  │ │ Pixel art sprite, 32-bit style. {description}.           │││
│  │ │ Front-facing, game asset, clean edges.                   │││
│  │ └──────────────────────────────────────────────────────────┘││
│  │                                                              ││
│  │ Variations: [4 ▼]     Size: [256x256 ▼]                     ││
│  │ [✓] Remove background after generation                      ││
│  │ Approval Mode: ( ) Choose 1 of N  (●) Accept/Reject each    ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ▶ Generate Text Description (click to expand)                   │
│                                                                  │
│                              [ ← Back ]  [ Start Generation → ]  │
└──────────────────────────────────────────────────────────────────┘
```

### Template Variables
| Variable | Description |
|----------|-------------|
| `{description}` | Original input description |
| `{id}` | Asset ID |
| `{research}` | Output from research step |
| `{name}` | Output from name generation |
| `{global_style}` | The global style prompt |
| `{previous_text}` | Output from previous text step |

### Approval Modes
1. **Choose 1 of N**: Generate N variations, user picks the best
2. **Accept/Reject**: Generate one at a time until user accepts

### CLI Skip
```bash
artgen interactive --input creatures.jsonl --flow pipeline.json --style style.json
```

---

## Screen 4: Approval Queue

### Purpose
The main work screen where users review and approve generated content.

### UI Components - Queue Overview

```
┌──────────────────────────────────────────────────────────────────┐
│  AI Art Generator - Approval Queue                    [⚙️] [📊]  │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Progress: ████████░░░░░░░░░░░░ 8/20 concepts complete          │
│  Queue: 3 awaiting approval │ 5 generating │ 12 pending          │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ Current: Fire Dragon (dragon_01)                            ││
│  │ Step: Generate Portrait (3 of 5)                            ││
│  │                                                              ││
│  │ Context:                                                     ││
│  │ ┌──────────────────────────────────────────────────────────┐││
│  │ │ Description: Fire Dragon with scales of obsidian         │││
│  │ │ Research: Dragons in mythology often symbolize power...  │││
│  │ │ Name: Pyraxion, the Obsidian Flame ✓                     │││
│  │ └──────────────────────────────────────────────────────────┘││
│  │                                                              ││
│  │ Choose a portrait:                                           ││
│  │ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌──────────┐││
│  │ │             │ │             │ │             │ │          │││
│  │ │   [img 1]   │ │   [img 2]   │ │   [img 3]   │ │ [img 4]  │││
│  │ │             │ │             │ │             │ │          │││
│  │ │     (1)     │ │     (2)     │ │     (3)     │ │   (4)    │││
│  │ └─────────────┘ └─────────────┘ └─────────────┘ └──────────┘││
│  │                                                              ││
│  │ [ 🔄 Regenerate All ]  [ ➕ Generate More ]  [ ⏭️ Skip ]     ││
│  │                                                              ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  Keyboard: 1-4 = Select  │  R = Regenerate  │  S = Skip          │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### UI Components - Accept/Reject Mode

```
┌──────────────────────────────────────────────────────────────────┐
│  Current: Ice Wizard (wizard_01)                                 │
│  Step: Generate Sprite (4 of 5)                                  │
│                                                                  │
│  ┌────────────────────────────────────────────────────┐          │
│  │                                                    │          │
│  │                                                    │          │
│  │                   [sprite image]                   │          │
│  │                                                    │          │
│  │                                                    │          │
│  └────────────────────────────────────────────────────┘          │
│                                                                  │
│  Is this sprite acceptable?                                      │
│                                                                  │
│  [ ✓ Accept (Y) ]    [ ✗ Reject & Regenerate (N) ]    [ Skip ]   │
│                                                                  │
│  Attempt 2 of 10 max                                             │
└──────────────────────────────────────────────────────────────────┘
```

### Queue Sidebar (Optional View)

```
┌──────────────────────────────────────┐
│ Queue                        [Hide]  │
├──────────────────────────────────────┤
│ ⏳ Awaiting Approval                  │
│   • dragon_01 - Portrait (now)       │
│   • wizard_01 - Sprite               │
│   • spirit_01 - Name                 │
│                                      │
│ ⚡ Generating                         │
│   • golem_01 - Research              │
│   • phoenix_01 - Portrait            │
│   • hydra_01 - Portrait              │
│                                      │
│ ✅ Completed                          │
│   • knight_01 ✓                      │
│   • archer_01 ✓                      │
│                                      │
│ ⏸️ Pending                            │
│   • vampire_01                       │
│   • werewolf_01                      │
│   • ...12 more                       │
└──────────────────────────────────────┘
```

### Behavior
1. **Async Generation**: Background workers continuously generate content
2. **Priority Queue**: Items needing approval bubble to the top
3. **Context Display**: Always show what's been decided for this concept
4. **Keyboard Shortcuts**: Fast approval with number keys, Y/N
5. **Auto-advance**: After approval, immediately show next item
6. **Batch Operations**: Approve/reject multiple similar items

### Image Zoom/Compare
- Click image to view full size
- Side-by-side compare mode for similar options
- Pan/zoom for detailed inspection

---

## Data Model Updates

### ApprovalItem

```python
class ApprovalItem(BaseModel):
    """An item waiting for user approval"""
    id: str
    asset_id: str
    step_name: str
    step_index: int
    
    # What we're asking about
    approval_type: Literal["choose_one", "accept_reject"]
    
    # The options
    options: list[GeneratedOption]
    
    # Context from previous steps
    context: dict[str, Any]
    
    # Timestamps
    created_at: datetime
    
class GeneratedOption(BaseModel):
    """One option in an approval item"""
    id: str
    type: Literal["image", "text"]
    
    # For images
    image_path: Optional[str]
    thumbnail_path: Optional[str]
    
    # For text
    text_content: Optional[str]
    
    # Metadata
    generation_params: dict[str, Any]
```

### QueueStatus

```python
class QueueStatus(BaseModel):
    """Overall queue status"""
    total_assets: int
    completed_assets: int
    
    awaiting_approval: int
    currently_generating: int
    pending: int
    
    items_awaiting: list[ApprovalItemSummary]
    items_generating: list[GeneratingItemSummary]
```

---

## API Endpoints

### Queue Management

```
GET  /queue/status              # Get overall queue status
GET  /queue/next                # Get next item needing approval
GET  /queue/items               # List all items awaiting approval

POST /queue/approve             # Approve an item
     {
       "item_id": "...",
       "choice": "option_2"     # or "accepted" / "rejected"
     }

POST /queue/regenerate          # Request regeneration
     {
       "item_id": "...",
       "regenerate_all": true   # or specific option IDs
     }

POST /queue/skip                # Skip this item for now
     {
       "item_id": "..."
     }
```

### Generation Control

```
POST /generate/start            # Start generation for all assets
POST /generate/pause            # Pause background generation
POST /generate/resume           # Resume generation
GET  /generate/status           # Get generation worker status
```

### Configuration

```
POST /config/flow               # Set pipeline configuration
POST /config/style              # Set style configuration
GET  /config                    # Get current configuration
```

---

## WebSocket Events

For real-time updates:

```typescript
// Server -> Client
interface QueueUpdate {
  type: "queue_update";
  status: QueueStatus;
}

interface NewApproval {
  type: "new_approval";
  item: ApprovalItem;
}

interface GenerationProgress {
  type: "generation_progress";
  asset_id: string;
  step: string;
  progress: number;  // 0-100
}

interface GenerationComplete {
  type: "generation_complete";
  asset_id: string;
  step: string;
}

interface GenerationError {
  type: "generation_error";
  asset_id: string;
  step: string;
  error: string;
}
```

---

## State Machine

### Asset State

```
                    ┌─────────────────────────────────────────────┐
                    │                                             │
                    ▼                                             │
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ PENDING  │──▶│GENERATING│──▶│ AWAITING │──▶│ APPROVED │──▶│ COMPLETE │
└──────────┘   └──────────┘   │ APPROVAL │   └──────────┘   └──────────┘
                    │         └──────────┘         │
                    │              │               │
                    │              │ reject        │
                    │              ▼               │
                    │         ┌──────────┐        │
                    └─────────│REGENERATE│────────┘
                              └──────────┘
                                   │
                                   │ max attempts
                                   ▼
                              ┌──────────┐
                              │ SKIPPED  │
                              └──────────┘
```

### Step State (per asset)

```
PENDING → GENERATING → AWAITING_APPROVAL → APPROVED
                           │
                           └─→ REJECTED → GENERATING (loop)
```

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `1-9` | Select option N (in choose mode) |
| `Y` | Accept (in accept/reject mode) |
| `N` | Reject and regenerate |
| `R` | Regenerate all options |
| `S` | Skip this item |
| `←` / `→` | Navigate between options |
| `Enter` | Confirm selection |
| `Space` | Toggle image zoom |
| `?` | Show keyboard shortcuts |

---

## Implementation Priority

### Phase 1: Core Queue (MVP)
- [ ] Approval queue backend (in-memory)
- [ ] Basic queue UI with image display
- [ ] Choose 1 of N approval mode
- [ ] Keyboard navigation

### Phase 2: Full Flow
- [ ] Content input screen
- [ ] Flow setup screen (basic)
- [ ] Art direction screen (basic)
- [ ] WebSocket real-time updates

### Phase 3: Polish
- [ ] Drag-and-drop flow editor
- [ ] Advanced art direction templates
- [ ] Image zoom/compare
- [ ] Batch operations
- [ ] Export/import configurations

### Phase 4: Persistence
- [ ] Save queue state to disk
- [ ] Resume interrupted sessions
- [ ] History/undo

---

## File Structure Updates

```
backend/
├── app/
│   ├── main.py              # Add queue endpoints
│   ├── websocket.py         # NEW: WebSocket handler
│   └── queue_manager.py     # NEW: Queue state management
├── pipeline/
│   ├── worker.py            # NEW: Background generation worker
│   └── orchestrator.py      # Update for async generation

frontend/
├── src/
│   ├── pages/
│   │   ├── ContentInput.tsx    # NEW: Screen 1
│   │   ├── FlowSetup.tsx       # NEW: Screen 2
│   │   ├── ArtDirection.tsx    # NEW: Screen 3
│   │   └── ApprovalQueue.tsx   # NEW: Screen 4
│   ├── components/
│   │   ├── ImageGrid.tsx       # NEW: Grid of image options
│   │   ├── ImageViewer.tsx     # NEW: Zoom/compare view
│   │   ├── QueueSidebar.tsx    # NEW: Queue status sidebar
│   │   ├── StepEditor.tsx      # NEW: Pipeline step config
│   │   └── TemplateEditor.tsx  # NEW: Prompt template editor
│   ├── hooks/
│   │   ├── useQueue.ts         # NEW: Queue state hook
│   │   └── useWebSocket.ts     # NEW: WebSocket hook
│   └── stores/
│       └── queueStore.ts       # NEW: Zustand store for queue
```
