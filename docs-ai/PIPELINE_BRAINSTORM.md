# Pipeline Brainstorm: Use Cases & Elements

## Core Concept

A pipeline is a **directed acyclic graph (DAG)** of steps. Steps can:
- **Run in parallel** when they have no dependencies on each other
- **Wait for dependencies** when they need output from earlier steps
- **Gather** when they need ALL previous parallel work to complete
- **Loop** when they iterate until a condition is met
- **Branch** when different paths are taken based on criteria
- **Pause** when human approval is required

### Key Insight: Gather Operations

Some steps are "gather" operations that require all work from a previous stage to complete before proceeding. For example:
- "Generate a spritesheet" requires all individual sprites to exist first
- "Define a style guide" might require analyzing ALL reference images first
- "Create a summary" requires all research to complete

This is NOT a simple two-stage "global then per-asset" model. It's a flexible DAG where gather points can occur anywhere.

```
[research_a] ──┬──► [synthesize] ──► [generate_1] ──┬──► [gather: atlas]
[research_b] ──┘                 └──► [generate_2] ──┘
                                 └──► [generate_3] ──┘
```

---

## Use Case Brainstorm

### 1. Trading Card Games (Magic-style)

**Assets needed per card:**
- Card name
- Flavor text / lore
- Art prompt
- Main illustration
- Card frame/border overlay
- Mechanics (cost, abilities, stats)

**Pipeline might look like:**
```
GLOBAL:
  - research: "Magic the Gathering art styles and card design"
  - define_style: "Dark fantasy, painterly, dramatic lighting"
  - create_template: "Card frame template with text areas"

PER_CARD:
  - generate_name: "Create evocative fantasy name"
  - generate_lore: "Write 2-sentence flavor text"
  - generate_prompt: "Create detailed art prompt from name + lore"
  - generate_image: variations=4
  - assess_image: "Check for composition, style match, no artifacts"
  - user_select: "Choose best of 4"
  - composite: "Overlay card frame, add text"
```

### 2. Video Game Sprites (Strategy/RPG)

**Assets needed:**
- Unit sprites (Archer, Knight, Wizard, etc.)
- Building sprites
- Terrain tiles
- UI icons
- Character portraits

**Pipeline might look like:**
```
GLOBAL:
  - analyze_existing: "Assess style of reference images"
  - research: "Pixel art trends for strategy games 2024"
  - define_style: "16-bit inspired, limited palette, clean edges"
  - create_palette: "Generate 32-color palette"

PER_UNIT:
  - generate_prompt: "Detailed sprite prompt using style guide"
  - generate_sprite: variations=3
  - remove_background: automatic
  - assess_sprite: "Check transparency, size consistency, style match"
  - user_approve: required=true
  - resize: "Export at 64x64, 128x128, 256x256"
  - generate_spritesheet: "Create animation-ready sheet"
```

### 3. Children's Book Illustrations

**Assets needed:**
- Character designs (main character, supporting cast)
- Scene illustrations (10-20 per book)
- Cover art
- End papers / decorative elements

**Pipeline might look like:**
```
GLOBAL:
  - research: "Children's book illustration styles, age-appropriate"
  - define_characters: "Create character sheets for consistency"
  - define_style: "Warm watercolor, friendly faces, soft edges"
  - generate_character_refs: "Create reference images for each character"

PER_SCENE:
  - generate_prompt: "Scene description with character placement"
  - generate_image: variations=4, use_character_refs=true
  - assess_consistency: "Check characters match references"
  - user_select: "Choose best composition"
  - color_correct: "Match to book's color palette"
```

### 4. Indie Game Item Icons

**Assets needed:**
- Weapon icons (swords, bows, staves)
- Armor icons
- Consumables (potions, food)
- Materials (wood, iron, gems)
- Quest items

**Pipeline might look like:**
```
GLOBAL:
  - analyze_existing: "Match existing UI style"
  - define_style: "Hand-painted, slight glow, consistent lighting"
  - create_template: "Icon background/frame"

PER_ITEM:
  - categorize: "Determine item type and rarity"
  - generate_prompt: "Item-specific prompt with rarity indicators"
  - generate_image: variations=2
  - remove_background: automatic
  - add_frame: "Apply rarity-colored border"
  - resize: "Export at 32x32, 64x64, 128x128"
```

### 5. Tabletop RPG Monster Manual

**Assets needed per monster:**
- Full illustration
- Stat block
- Lore/description
- Habitat illustration (optional)

**Pipeline might look like:**
```
GLOBAL:
  - research: "D&D monster art, fantasy creature design"
  - define_style: "Detailed realism, dramatic poses, dark backgrounds"
  - define_format: "Stat block template, lore format"

PER_MONSTER:
  - generate_concept: "Brief monster concept from name"
  - generate_stats: "CR-appropriate stat block"
  - generate_lore: "2-paragraph backstory and ecology"
  - generate_prompt: "Detailed art prompt from concept + lore"
  - generate_image: variations=3
  - assess_image: "Check for anatomical consistency, menace factor"
  - user_select: "Choose most evocative"
  - generate_variants: "Action pose, portrait crop"
```

### 6. Marketing Asset Pack

**Assets needed:**
- Hero images
- Social media posts (various sizes)
- Banner ads
- Product shots
- Email headers

**Pipeline might look like:**
```
GLOBAL:
  - define_brand: "Colors, fonts, tone from brand guide"
  - research: "Competitor visual styles"
  - create_templates: "Social post frames, banner layouts"

PER_CAMPAIGN:
  - generate_concept: "Campaign theme and messaging"
  - generate_hero: "Main campaign image"
  - user_approve: required=true
  - generate_variants: "Adapt hero for each platform"
  - resize_batch: "Export all required sizes"
  - add_overlays: "Add CTAs, logos, text"
```

### 7. NFT/Collectible Series

**Assets needed:**
- Base character/object designs
- Trait variations (hats, backgrounds, accessories)
- Rarity tiers
- Collection metadata

**Pipeline might look like:**
```
GLOBAL:
  - define_collection: "Theme, traits, rarity distribution"
  - generate_base_designs: "Core character variations"
  - generate_trait_library: "All possible accessories/backgrounds"

PER_NFT:
  - select_traits: "Randomly assign based on rarity"
  - composite_image: "Combine base + traits"
  - assess_uniqueness: "Ensure no duplicates"
  - generate_metadata: "Create JSON with traits"
```

### 8. Educational Flashcards

**Assets needed per card:**
- Concept illustration
- Term/definition
- Mnemonic image (optional)

**Pipeline might look like:**
```
GLOBAL:
  - define_subject: "Biology, history, language, etc."
  - define_style: "Clear, friendly, age-appropriate"
  - create_template: "Card layout with image + text areas"

PER_CONCEPT:
  - generate_definition: "Clear, concise explanation"
  - generate_prompt: "Visual representation of concept"
  - generate_image: variations=2
  - assess_clarity: "Is the concept visually clear?"
  - user_approve: required=true
  - composite: "Place in card template"
```

### 9. Music Album Art Series

**Assets needed:**
- Album cover
- Track-specific artwork
- Promotional images
- Social media variants

**Pipeline might look like:**
```
GLOBAL:
  - research: "Genre visual trends, artist's existing style"
  - define_aesthetic: "Color palette, mood, recurring motifs"
  - generate_concept: "Overarching visual narrative"

PER_TRACK:
  - analyze_lyrics: "Extract key themes and imagery"
  - generate_prompt: "Track-specific visual concept"
  - generate_image: variations=3
  - assess_cohesion: "Does it fit album aesthetic?"
  - user_select: "Artist chooses preferred version"
  - generate_variants: "Square, banner, story formats"
```

### 10. Architectural Visualization Mood Boards

**Assets needed:**
- Style references
- Material palettes
- Lighting studies
- Space concepts

**Pipeline might look like:**
```
GLOBAL:
  - research: "Client preferences, site context"
  - define_constraints: "Budget, materials, climate"

PER_SPACE:
  - generate_concepts: "3-5 style directions"
  - user_select: "Client narrows to 2"
  - generate_detailed: "Higher fidelity renders"
  - iterate: until=approved
  - generate_material_callouts: "Specific product references"
```

---

## Pipeline Element Categories

### 1. Research & Planning Steps (Global)

| Step | Description | Example |
|------|-------------|---------|
| `research` | AI researches a topic | "Pixel art techniques for game sprites" |
| `analyze_existing` | Assess style of reference images | Uploaded images → style description |
| `define_style` | Create a style guide document | "Watercolor, warm palette, soft edges" |
| `create_palette` | Generate a color palette | 32-color limited palette |
| `create_template` | Design reusable templates | Card frame, icon background |
| `define_characters` | Create character reference sheets | For consistency across images |

### 2. Generation Steps (Per-Asset)

| Step | Description | Options |
|------|-------------|---------|
| `generate_name` | Create names for assets | style, length, themes |
| `generate_text` | Generate descriptions/lore | tone, length, format |
| `generate_prompt` | Create detailed art prompts | from context + style guide |
| `generate_image` | Generate images | variations, size, model |
| `generate_sprite` | Generate with transparency | variations, palette |
| `generate_variants` | Create variations of existing | poses, crops, formats |

### 3. Assessment Steps (AI Judgment)

| Step | Description | Criteria |
|------|-------------|----------|
| `assess_quality` | General quality check | artifacts, composition |
| `assess_style_match` | Compare to style guide | consistency score |
| `assess_consistency` | Compare to references | character/object match |
| `assess_uniqueness` | Check for duplicates | similarity threshold |
| `assess_suitability` | Domain-specific checks | "appropriate for children" |

### 4. Human-in-the-Loop Steps

| Step | Description | Behavior |
|------|-------------|----------|
| `user_approve` | Yes/no approval gate | Block until decision |
| `user_select` | Choose best of N | Present options, wait |
| `user_feedback` | Collect refinement notes | Free-form input |
| `user_edit` | Allow manual prompt editing | Show/edit before generation |

### 5. Post-Processing Steps

| Step | Description | Options |
|------|-------------|---------|
| `remove_background` | Transparent background | auto, manual threshold |
| `resize` | Change dimensions | sizes[], maintain_aspect |
| `crop` | Extract region | coordinates, auto-detect |
| `composite` | Layer multiple images | foreground, background, frame |
| `color_correct` | Adjust colors | palette, brightness, contrast |
| `add_frame` | Apply border/overlay | template, padding |
| `generate_spritesheet` | Combine into sheet | grid, animation frames |

### 6. Control Flow Steps

| Step | Description | Example |
|------|-------------|---------|
| `conditional` | Run step if condition met | if quality < 0.8 |
| `loop` | Repeat until condition | until approved |
| `retry` | Retry on failure | max_attempts=3 |
| `branch` | Different paths by type | if rarity == "legendary" |
| `parallel` | Run steps concurrently | generate all variants at once |

### 7. Data & Export Steps

| Step | Description | Output |
|------|-------------|--------|
| `generate_metadata` | Create JSON/YAML | NFT traits, asset info |
| `export_batch` | Export all formats | sizes[], formats[] |
| `archive` | Package deliverables | ZIP with structure |
| `version` | Create versioned snapshot | Git-style tagging |

---

## Pipeline Configuration Ideas

### DAG-Based YAML Format

```yaml
name: "Fantasy Card Game"

steps:
  # --- Research Phase (can run in parallel) ---
  - id: research_mtg
    type: research
    query: "Magic the Gathering card art styles"
  
  - id: research_fantasy
    type: research  
    query: "Dark fantasy art, dramatic lighting techniques"

  # --- Synthesis (gather: needs both research steps) ---
  - id: style_guide
    type: define_style
    requires: [research_mtg, research_fantasy]  # Wait for both
    prompt: "Create a style guide for dark fantasy cards"

  # --- Per-Asset Steps (run for each asset, in parallel) ---
  - id: card_name
    type: generate_name
    for_each: asset
    style: "Fantasy, evocative"
  
  - id: flavor_text
    type: generate_text
    for_each: asset
    requires: [card_name]  # Needs the name first
    template: "Write flavor text for {card_name}"
    max_length: 50
  
  - id: art_prompt
    type: generate_prompt
    for_each: asset
    requires: [card_name, flavor_text, style_guide]
  
  - id: card_art
    type: generate_image
    for_each: asset
    requires: [art_prompt]
    variations: 4
    size: "1024x1024"
  
  - id: quality_check
    type: assess
    for_each: asset
    requires: [card_art]
    threshold: 0.8
    on_fail: retry
  
  - id: art_selection
    type: user_select
    for_each: asset
    requires: [quality_check]
    prompt: "Choose the best card art"
  
  - id: final_card
    type: composite
    for_each: asset
    requires: [art_selection, card_name, flavor_text]
    template: card_frame

  # --- Final Gather (needs all cards complete) ---
  - id: card_atlas
    type: spritesheet
    gather: true  # Wait for ALL per-asset steps
    requires: [final_card]
```

### Dependency Visualization

The above config produces this execution graph:

```
[research_mtg] ───┬──► [style_guide] ──────────────────────────────┐
[research_fantasy]┘                                                │
                                                                   ▼
            ┌──────────────── FOR EACH ASSET (parallel) ───────────┴──────────┐
            │                                                                  │
            │  [card_name] ──► [flavor_text] ──┬──► [art_prompt] ──► [card_art]│
            │                                  │          │              │     │
            │                                  │          └──────────────┘     │
            │                                  │                   ▼           │
            │                                  │          [quality_check]      │
            │                                  │                   │           │
            │                                  │                   ▼           │
            │                                  │          [art_selection]      │
            │                                  │                   │           │
            │                                  └───────────► [final_card] ◄────┤
            │                                                      │           │
            └──────────────────────────────────────────────────────┼───────────┘
                                                                   │
                                                    GATHER ────────┘
                                                                   ▼
                                                            [card_atlas]
```

### Conditional Branches

```yaml
steps:
  - id: categorize
    type: classify
    for_each: asset
    output: rarity  # "common", "rare", "legendary"
  
  - id: generate_art
    type: generate_image
    for_each: asset
    requires: [categorize]
    # Variations based on rarity
    variations: 
      when:
        - condition: "rarity == 'common'"
          value: 1
        - condition: "rarity == 'rare'"
          value: 3
        - condition: "rarity == 'legendary'"
          value: 5
  
  - id: legendary_approval
    type: user_approve
    for_each: asset
    requires: [generate_art]
    condition: "rarity == 'legendary'"  # Only runs for legendary
```

### Iteration Loops

```yaml
steps:
  - id: generate_prompt
    type: generate_text
    for_each: asset

  - id: refinement_loop
    type: loop
    for_each: asset
    requires: [generate_prompt]
    max_iterations: 5
    until: "quality >= 0.85"
    steps:
      - id: generate
        type: generate_image
        variations: 2
      
      - id: assess
        type: assess_quality
        output: quality
      
      - id: refine
        type: refine_prompt
        condition: "quality < 0.85"
        feedback: "assessment from {assess}"
          variations: 2
      - assess_quality:
          threshold: 0.85
      - branch:
          condition: "quality >= threshold"
          then: break
          else:
            - refine_prompt:
                feedback: quality_report
```

---

## Questions to Resolve

### Architecture Questions

1. **Step Dependencies**: How do steps reference outputs from previous steps?
   - Option A: Explicit variable binding (`output: my_var`, `use: my_var`)
   - Option B: Implicit context (each step sees all previous outputs)
   - Option C: Scoped contexts (global vs per-asset namespace)

2. **Compound Assets**: How do we handle assets that have multiple parts?
   - Option A: Asset has sub-assets (card.name, card.art, card.text)
   - Option B: Separate asset types that link together
   - Option C: Steps that generate multiple outputs

3. **State Persistence**: How do we save/resume mid-pipeline?
   - Current: progress.jsonl with asset status
   - Needed: Step-level progress within each asset

4. **Human-in-the-Loop UX**: How does approval work?
   - CLI: Blocking prompt? Queue for later?
   - Web: Real-time queue? Notification?
   - Batch: Skip and mark for review?

### Feature Priority Questions

1. **Which use case should we optimize for first?**
   - Game sprites (simpler, clear deliverables)
   - Trading cards (compound assets, good demo)
   - Generic (flexible but less polished)

2. **Should global steps run automatically or require explicit trigger?**
   - Auto-run on project init
   - Run when first asset starts
   - Manual `artgen run-global` command

3. **How sophisticated should assessment be?**
   - Simple: Binary pass/fail
   - Moderate: Score + reason
   - Advanced: Multi-criteria rubric

4. **What's the right level of pipeline customization?**
   - Simple: Presets only (game_sprites, trading_cards)
   - Moderate: Presets + overrides
   - Advanced: Full YAML/JSON DSL

---

## Next Steps

1. **Pick a primary use case** to fully implement first
2. **Define the step interface** - inputs, outputs, config
3. **Build assessment step** - this enables quality loops
4. **Add human-in-the-loop** - approval queue
5. **Create first preset** - e.g., `artgen init --preset game-sprites`

---

## Raw Ideas (Parking Lot)

- **Prompt library**: Save and reuse effective prompts
- **Style transfer**: Apply style from reference image
- **Batch retouching**: Apply same edit across multiple assets
- **A/B testing**: Generate with different prompts, track success
- **Cost tracking**: Show API costs per step, per asset
- **Collaboration**: Multiple users approving in queue
- **Version diffing**: Compare outputs across pipeline versions
- **Audit log**: Full history of who approved what, when
- **Webhooks**: Notify external systems on completion
- **Plugin system**: Custom steps written in Python
