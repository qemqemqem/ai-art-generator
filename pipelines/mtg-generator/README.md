# MTG Set Generator Pipeline

Generate Magic: The Gathering cards with full mechanics, art, and flavor text.

Based on the workflow from `~/Dev/mtgrandom/`.

## Quick Start

```bash
cd pipelines/mtg-generator

# Run with default cards
artgen run pipeline.yaml

# Run with web GUI for art review
artgen run --web pipeline.yaml
```

## Pipeline Stages

### Phase 1: Set Design (Global)
1. **design_set_mechanics** - Creates the mechanical framework (mechanics, colors, archetypes)
2. **write_set_story** - Generates narrative story with characters and locations
3. **generate_card_concepts** - Produces balanced card ideas (for reference)

### Phase 2: Card Design (Per-Card)
4. **brainstorm_mechanics** - Generates 10 mechanic options per card
5. **design_full_card** - Creates complete card with mana cost, stats, rules
6. **critique_and_refine** - Reviews and fixes any issues
7. **generate_art_direction** - Creates detailed art prompt
8. **write_flavor_text** - Writes thematic flavor text

### Phase 3: Art Generation (Per-Card)
9. **generate_art** - Generates card art using Gemini Imagen

## Customization

### Change the Theme
Edit `context.set_theme` in `pipeline.yaml`:

```yaml
context:
  set_theme: "A steampunk world where magic and technology collide"
  set_size: 12
```

### Modify the Card List
Edit `cards.yaml` to define your own cards:

```yaml
- name: "Steam Golem"
  concept: "A mechanical construct powered by magical steam"
  color: "Colorless"
  rarity: "Rare"
  card_type: "Artifact Creature"
```

### Enable Art Review
Uncomment the `review_art` step in `pipeline.yaml` for human-in-the-loop approval.

## Output

Generated content is saved to:
- `.artgen/` - Cached step outputs (JSON)
- `output/` - Final card art images

### Card Data Structure
Each card generates these fields:
- `set_mechanics` - Set-wide mechanical framework
- `set_story` - Narrative context
- `mechanics_brainstorm` - 10 mechanic options
- `card_json` - Full card stats (name, cost, power, rules)
- `card_refined` - Reviewed and fixed card
- `art_direction` - Art prompt and artist credit
- `flavor_text` - Card flavor text
- `card_art` - Generated image path

## Extending

### Add Card Rendering
The pipeline generates card data and art separately. To create finished cards:

1. Export card JSON from `.artgen/design_full_card/`
2. Use a tool like Magic Set Editor (MSE)
3. Or port `mtgrandom/graphics_utils/render_full_card.py`

### Different Art Provider
Change the provider in the `generate_art` step:

```yaml
- id: generate_art
  type: generate_image
  provider: litellm  # Use DALL-E via LiteLLM
```

## Example Output

After running the pipeline, you'll have:

```
pipelines/mtg-generator/
├── .artgen/
│   ├── design_set_mechanics/
│   │   └── output.json
│   ├── write_set_story/
│   │   └── output.json
│   ├── design_full_card/
│   │   ├── moonlit-hunter/
│   │   │   └── output.json
│   │   └── blood-covenant/
│   │       └── output.json
│   └── generate_art/
│       ├── moonlit-hunter/
│       │   └── output.json  # Contains image path
│       └── ...
└── output/
    ├── Moonlit Hunter.png
    ├── Blood Covenant.png
    └── ...
```
