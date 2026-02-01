# MTG Random Migration Plan

## Overview

This document outlines a plan to recreate the `~/Dev/mtgrandom/` Magic: The Gathering card generation pipeline using our ai-art-generator pipeline system.

## Current mtgrandom Pipeline Analysis

### Pipeline Stages (from main.py)

The existing project has 4 main actions that run in sequence:

1. **`set`** - Generate set description and card suggestions
2. **`cards`** - Generate full card JSON for each card
3. **`images`** - Generate art for each card
4. **`full`** - Render complete cards with art + stats

### Detailed Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           SET GENERATION                                │
│  (Global/Gather - runs once for the whole set)                          │
├─────────────────────────────────────────────────────────────────────────┤
│  1. generate_set_description()                                          │
│     - Input: set theme description                                      │
│     - Output: mechanics, archetypes, color distribution, thematic guide │
│                                                                         │
│  2. generate_story_and_elements()                                       │
│     - Input: set description                                            │
│     - Output: story narrative + list of card elements                   │
│                                                                         │
│  3. create_balanced_set()                                               │
│     - Input: card elements                                              │
│     - Output: balanced card suggestions (by color/rarity)               │
│                                                                         │
│  4. generate_card_suggestions()                                         │
│     - Input: balanced suggestions + story                               │
│     - Output: detailed card ideas with descriptions                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         CARD GENERATION                                 │
│  (Per-Asset - runs for each card)                                       │
├─────────────────────────────────────────────────────────────────────────┤
│  For each card_idea:                                                    │
│                                                                         │
│  5. generate_card() - Brainstorm mechanics                              │
│     - Input: card idea, set mechanics, color advice                     │
│     - Output: 15 possible mechanics with scores                         │
│                                                                         │
│  6. generate_sets_with_target_complexity()                              │
│     - Input: mechanics list, target complexity                          │
│     - Output: 3 possible mechanic combinations                          │
│                                                                         │
│  7. Final card design                                                   │
│     - Input: mechanic combinations, card idea                           │
│     - Output: full card JSON (name, type, cost, text, etc.)             │
│                                                                         │
│  8. criticize_and_try_to_improve_card() × 4 iterations                  │
│     - Input: card JSON                                                  │
│     - Output: improved card JSON                                        │
│                                                                         │
│  9. get_art_prompt()                                                    │
│     - Input: card JSON                                                  │
│     - Output: art prompt + artist credit                                │
│                                                                         │
│  10. write_flavor_for_card()                                            │
│      - Input: card JSON, story                                          │
│      - Output: flavor text                                              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         IMAGE GENERATION                                │
│  (Per-Asset - runs for each card)                                       │
├─────────────────────────────────────────────────────────────────────────┤
│  11. generate_image_and_save_to_file()                                  │
│      - Input: art_prompt                                                │
│      - Output: PNG image                                                │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         FULL CARD RENDER                                │
│  (Per-Asset - runs for each card)                                       │
├─────────────────────────────────────────────────────────────────────────┤
│  12. create_magic_card() or mse_gen                                     │
│      - Input: card JSON + image                                         │
│      - Output: final rendered card PNG                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Structures

**Card JSON Schema:**
```json
{
  "name": "Card Name",
  "supertype": "Creature",
  "subtype": "Human Wizard",
  "power": "2",
  "toughness": "3",
  "rule_text": "Flying\n{T}: Draw a card",
  "flavor_text": "A wise quote.",
  "mana_cost": "{2}{U}{U}",
  "rarity": "Rare",
  "art_prompt": "A mystical wizard...",
  "artist_credit": "Artist Name"
}
```

## Pipeline Translation

### Proposed artgen Pipeline Structure

```yaml
name: mtg-set-generator
description: Generate a complete Magic: The Gathering set

types:
  MagicCard:
    name: string
    concept: string
    color: string
    rarity: string
    supertype: string
    subtype: string
    power: string
    toughness: string
    mana_cost: string
    rule_text: string
    flavor_text: string
    art_prompt: string
    artist_credit: string
    card_art_path: string

context:
  set_theme: "A dark gothic horror set inspired by Eastern European folklore"
  set_size: 18

assets:
  type: MagicCard
  generate: true  # We'll generate cards from set design

output:
  directory: output/cards/
  naming: "{asset.name}"

steps:
  # ═══════════════════════════════════════════════════════════════════
  # PHASE 1: SET DESIGN (Global/Gather Steps)
  # ═══════════════════════════════════════════════════════════════════
  
  - id: design_set_mechanics
    type: generate_text
    description: "Design set mechanics and color distribution"
    prompt: |
      I'm designing a new Magic: The Gathering set.
      
      Theme: {context.set_theme}
      Set Size: {context.set_size} cards
      
      Please design:
      1. 6 existing mechanics appropriate for this theme
      2. 2 new mechanics unique to this set
      3. Color distribution (what each color represents thematically)
      4. 10 two-color draft archetypes
      5. Thematic guidance for art and flavor
      
      Format as structured sections with clear headers.
    writes_to: set_mechanics
    cache: true

  - id: write_set_story
    type: generate_text
    requires: [design_set_mechanics]
    description: "Write the narrative story for the set"
    prompt: |
      Theme: {context.set_theme}
      Mechanics: {step_outputs.design_set_mechanics}
      
      Write a rich story for this Magic set:
      1. The main narrative (500+ words)
      2. Key characters (heroes, villains, supporting)
      3. Important locations
      4. Major events/conflicts
      
      Include a mix of legendary figures and common folk.
    writes_to: set_story
    cache: true

  - id: generate_card_concepts
    type: generate_text
    requires: [design_set_mechanics, write_set_story]
    description: "Generate balanced card concepts"
    prompt: |
      Based on this set:
      
      Story: {step_outputs.write_set_story}
      Mechanics: {step_outputs.design_set_mechanics}
      
      Generate {context.set_size} card concepts, balanced across:
      - Colors (roughly equal distribution)
      - Rarities (60% common, 25% uncommon, 15% rare)
      - Card types (creatures, spells, enchantments, artifacts)
      
      For each card, provide:
      * Card Name. Type. Rarity. Color. Brief thematic description.
      
      Output as a list, one card per line starting with *.
    writes_to: card_concepts
    cache: true

  - id: parse_card_list
    type: generate_text
    requires: [generate_card_concepts]
    description: "Parse card concepts into structured data"
    prompt: |
      Parse these card concepts into JSON:
      
      {step_outputs.generate_card_concepts}
      
      Output a JSON array where each card has:
      {
        "name": "Card Name",
        "concept": "Brief description",
        "color": "White/Blue/Black/Red/Green/Colorless",
        "rarity": "Common/Uncommon/Rare"
      }
      
      Output only the JSON array, no other text.
    writes_to: parsed_cards
    creates_assets: true  # This populates the asset list

  # ═══════════════════════════════════════════════════════════════════
  # PHASE 2: CARD DESIGN (Per-Asset Steps)
  # ═══════════════════════════════════════════════════════════════════

  - id: brainstorm_mechanics
    type: generate_text
    for_each: asset
    requires: [parse_card_list]
    description: "Brainstorm mechanics for {asset.name}"
    prompt: |
      Card: {asset.name}
      Concept: {asset.concept}
      Color: {asset.color}
      Rarity: {asset.rarity}
      
      Set Mechanics: {step_outputs.design_set_mechanics}
      
      Brainstorm 15 possible mechanics for this card.
      For each mechanic:
      1. Write the oracle text
      2. Rate complexity (1-5)
      3. Rate flavor fit (1-5)
      4. Rate synergy with set (1-5)
      
      Format: 
      1. [Mechanic text]. Complexity X. Flavor X. Synergy X.
    writes_to: mechanics_brainstorm
    cache: true

  - id: design_card
    type: generate_text
    for_each: asset
    requires: [brainstorm_mechanics]
    description: "Design full card stats for {asset.name}"
    prompt: |
      Design the final card:
      
      Card: {asset.name}
      Concept: {asset.concept}
      Color: {asset.color}
      Rarity: {asset.rarity}
      
      Brainstormed mechanics:
      {asset.mechanics_brainstorm}
      
      Target complexity: Common=3, Uncommon=5, Rare=7
      Max mechanics: Common=2, Uncommon=2, Rare=3
      
      Choose the best combination of mechanics and design the full card.
      
      Output as JSON:
      {
        "name": "...",
        "supertype": "Creature/Sorcery/Instant/Enchantment/Artifact/Land",
        "subtype": "Human Wizard/etc (if applicable)",
        "mana_cost": "{2}{U}{U}",
        "power": "2" (if creature),
        "toughness": "3" (if creature),
        "rule_text": "Full oracle text",
        "rarity": "Common/Uncommon/Rare"
      }
    writes_to: card_design
    cache: true

  - id: critique_card
    type: generate_text
    for_each: asset
    requires: [design_card]
    description: "Critique and refine {asset.name}"
    prompt: |
      Review this Magic card design:
      
      {asset.card_design}
      
      Check for:
      1. Missing details (mana cost, power/toughness for creatures)
      2. Mechanical validity (can rules be executed?)
      3. Oracle text style (proper MTG formatting)
      4. Power level (appropriate for rarity?)
      5. Complexity (appropriate for rarity?)
      6. Flavor match (do mechanics fit the concept?)
      
      If issues found, output an improved JSON.
      If card is good, output "APPROVED" then the JSON unchanged.
    writes_to: card_design_refined
    cache: true

  - id: generate_art_prompt
    type: generate_text
    for_each: asset
    requires: [critique_card]
    description: "Create art direction for {asset.name}"
    prompt: |
      Create an art prompt for this Magic card:
      
      {asset.card_design_refined}
      
      Story context: {step_outputs.write_set_story}
      
      Consider:
      1. Central figure/subject
      2. Character details (if applicable)
      3. Action/scene
      4. Background/setting
      5. Lighting/mood
      6. Art style
      7. Reference artists
      
      Output:
      Final Prompt: "[description for image generation]"
      Artist Credit: [artist name for card credit]
    writes_to: art_direction
    cache: true

  - id: write_flavor_text
    type: generate_text
    for_each: asset
    requires: [critique_card]
    description: "Write flavor text for {asset.name}"
    prompt: |
      Write flavor text for this Magic card:
      
      {asset.card_design_refined}
      
      Story: {step_outputs.write_set_story}
      
      The card has limited space. Based on rule_text length:
      - Short rules: 2-3 lines of flavor
      - Medium rules: 1-2 lines
      - Long rules: 1 short line or none
      
      Options to consider:
      - A quote from a character: "Quote" —Character Name
      - Brief narrative moment
      - Atmospheric description
      - Poetry or verse
      
      Output:
      Flavor: [your flavor text]
    writes_to: flavor_text
    cache: true

  # ═══════════════════════════════════════════════════════════════════
  # PHASE 3: ART GENERATION (Per-Asset)
  # ═══════════════════════════════════════════════════════════════════

  - id: generate_card_art
    type: generate_image
    for_each: asset
    requires: [generate_art_prompt]
    is_output: true
    description: "Generate art for {asset.name}"
    prompt: "{asset.art_direction}"
    provider: gemini
    writes_to: card_art_path
    cache: true

  # ═══════════════════════════════════════════════════════════════════
  # OPTIONAL: Human Review
  # ═══════════════════════════════════════════════════════════════════

  # Uncomment for human-in-the-loop art approval:
  # - id: approve_art
  #   type: approve
  #   for_each: asset
  #   requires: [generate_card_art]
  #   until: approved
  #   max_attempts: 3
  #   message: "Approve art for {asset.name}?"
```

## Key Translation Decisions

### 1. Two-Phase Structure
The original code has a clear "set design" → "per-card generation" structure. We preserve this with:
- Global steps for set-level content (mechanics, story, card list)
- Per-asset steps that run `for_each: asset`

### 2. Asset Generation
The original generates card ideas dynamically. We handle this with:
- `parse_card_list` step with `creates_assets: true`
- This populates the asset list from LLM output

### 3. Iteration/Critique
The original runs 4 critique iterations. We simplify to:
- One `critique_card` step that either approves or fixes
- Could add `max_iterations` for more refinement

### 4. Art Prompting
The original has elaborate art direction. We keep:
- Separate `generate_art_prompt` step with full brainstorming
- Feeds into `generate_card_art` step

### 5. Caching Alignment
Original checks if files exist before regenerating. Our `cache: true` provides equivalent behavior.

## Implementation Steps

### Phase 1: Core Pipeline
1. Create `pipelines/mtg-generator/pipeline.yaml` with the structure above
2. Test set generation steps (mechanics, story, concepts)
3. Test card design steps on a few cards

### Phase 2: Asset Dynamic Generation  
4. Implement `creates_assets: true` functionality
5. Test full pipeline with dynamic card list
6. Verify caching works for incremental runs

### Phase 3: Human Review
7. Add optional approval steps for art
8. Test web GUI with art review workflow

### Phase 4: Card Rendering (Future)
9. Port `render_full_card.py` as a custom step executor
10. Or use external tooling for final renders

## Files to Create

```
ai-art-generator/
├── pipelines/
│   └── mtg-generator/
│       ├── pipeline.yaml      # Main pipeline definition
│       └── README.md          # Usage instructions
```

## Missing Features in Our Pipeline System

To fully support this use case, we may need:

1. **`creates_assets: true`** - A step that can generate the asset list dynamically from LLM output (JSON parsing)

2. **Iteration loops** - For the critique/improve cycle (currently we only have `variations` and `until: approved`)

3. **JSON extraction** - Better support for extracting structured data from LLM responses

4. **Custom executors** - For the card rendering step (combining art + stats)

## Next Steps

1. **Validate pipeline structure** - Run the basic pipeline to ensure syntax is correct
2. **Test set generation** - Verify the global steps produce good content
3. **Implement dynamic assets** - Add the `creates_assets` feature if needed
4. **Full integration test** - Generate a small set (5 cards) end-to-end
5. **Art quality tuning** - Adjust art prompts for best results with Gemini/DALL-E

## Notes

- The original uses GPT-3.5/GPT-4 via OpenAI. We can use `litellm` provider for the same models
- Art generation in original uses DALL-E 2 at 512x512. We use Gemini Imagen which may have different characteristics
- The card rendering step (`render_full_card.py`) is HTML-based and fairly crude. This could be improved separately
