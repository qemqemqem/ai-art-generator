# ArtGen Pipeline Format

This document describes the YAML format for defining ArtGen pipelines.

## Table of Contents

1. [Basic Structure](#basic-structure)
2. [Pipeline Metadata](#pipeline-metadata)
3. [Types](#types)
4. [Context](#context)
5. [Providers](#providers)
6. [State Configuration](#state-configuration)
7. [Assets](#assets)
8. [Steps](#steps)
9. [Template Variables](#template-variables)
10. [Human-in-the-Loop](#human-in-the-loop)
11. [Caching](#caching)
12. [Examples](#examples)

---

## Basic Structure

A pipeline file is a YAML document with the following top-level keys:

```yaml
name: my-pipeline            # Required
version: "1.0"               # Optional, default "1.0"
description: "Description"   # Optional

types: {}                    # Optional, custom type definitions
context: {}                  # Optional, pipeline-wide variables
providers:                   # Optional, AI provider configuration
  text: litellm              # Default text provider
  image: gemini              # Default image provider
state:                       # Optional, caching configuration
  directory: .artgen

assets:                      # Optional, what we're producing
  items: []

steps: []                    # Required, the pipeline steps
```

---

## Pipeline Metadata

### `name` (required)

A unique identifier for the pipeline. Used in logging and state management.

```yaml
name: magic-card-generator
```

### `version` (optional)

Semantic version string. Used for cache invalidation when pipeline changes.

```yaml
version: "1.2.0"
```

### `description` (optional)

Human-readable description of what the pipeline does.

```yaml
description: |
  Generates Magic: The Gathering style cards with 
  custom mechanics, flavor text, and AI-generated art.
```

---

## Types

Define custom data types for your assets. These are like data classes that specify the structure of your output.

```yaml
types:
  MagicCard:
    name: text
    mana_cost: text
    type_line: text
    abilities: text
    flavor: text?           # Optional field (?)
    power: number?
    toughness: number?
    art: image
    rarity: common | uncommon | rare | mythic   # Enum type
```

### Supported Field Types

| Type | Description |
|------|-------------|
| `text` | String value |
| `image` | Image file path |
| `number` | Numeric value |
| `boolean` | True/false |
| `list` | Array of values |
| `TypeName` | Reference to another type |
| `a \| b \| c` | Enum with specific values |
| `Type?` | Optional field |

---

## Context

Pipeline-wide variables accessible in all steps via `{context.key}` or `{ctx.key}`.

```yaml
context:
  style: "pixel art, 16-bit, nostalgic"
  game: "Fantasy RPG"
  author: "ArtGen"
  output_size: 512
```

Context values are automatically included in LLM prompts to maintain consistency across steps.

---

## Providers

Configure default AI providers for text and image generation. These can be overridden per-step.

```yaml
providers:
  text: litellm         # Default text provider: litellm, gemini
  image: gemini         # Default image provider: gemini, dalle, pixellab
  text_model: gpt-4     # Optional: specific model for text
  image_model: imagen-3 # Optional: specific model for images
```

### Available Providers

#### Text Providers
| Provider | Description |
|----------|-------------|
| `litellm` | LiteLLM (supports OpenAI, Anthropic, etc.) |
| `gemini` | Google Gemini |

#### Image Providers
| Provider | Description |
|----------|-------------|
| `gemini` | Google Gemini Imagen |
| `dalle` | OpenAI DALL-E |
| `pixellab` | PixelLab for pixel art |

### Per-Step Override

Override the default provider for a specific step:

```yaml
steps:
  - id: generate_text
    type: generate_text
    provider: gemini    # Use Gemini instead of default litellm
    config:
      prompt: "Write a description..."

  - id: generate_art
    type: generate_image
    provider: dalle     # Use DALL-E instead of default gemini
    config:
      prompt: "Create an image..."
```

The provider is displayed in the web GUI so you can see which AI service is processing each step.

---

## State Configuration

Controls caching and checkpointing.

```yaml
state:
  directory: .artgen        # Where to store state (default: .artgen)
```

The state directory contains:
- `pipeline_state.json` - Overall pipeline state
- `{step_id}/output.json` - Global step outputs
- `{step_id}/{asset_id}/output.json` - Per-asset outputs

---

## Output Configuration

Controls automatic collection of final outputs after the pipeline completes.

```yaml
output:
  directory: output/        # Where to collect outputs (default: output/)
  flatten: false            # If true, all files go to root; if false, organize by asset
  naming: "{asset.id}"      # Optional naming pattern for output files
  copy: true                # If true, copy files; if false, create symlinks
```

### Marking Output Steps

To indicate which steps produce final output artifacts, add `is_output: true` to those steps:

```yaml
steps:
  - id: research
    type: research
    config:
      query: "Research {asset.concept}"
  
  - id: generate_art
    type: generate_image
    for_each: asset
    is_output: true           # This step's output will be collected
    config:
      prompt: "{asset.name}: {asset.description}"
```

### Output Directory Structure

With `flatten: false` (default):
```
output/
  asset-001/
    image.png
  asset-002/
    image.png
```

With `flatten: true`:
```
output/
  asset-001_generate_art_image.png
  asset-002_generate_art_image.png
```

### Naming Patterns

The `naming` option supports these placeholders:
- `{asset.id}` - The asset's ID
- `{asset.name}` - The asset's name
- `{step.id}` - The step that produced the output

Example: `naming: "{asset.name}_{step.id}"` produces files like `Hero_generate_art.png`

---

## Assets

Define what the pipeline produces. Assets can be:

### Inline Items

```yaml
assets:
  items:
    - id: sword
      name: "Flame Blade"
      description: "A sword wreathed in magical fire"
      
    - id: shield
      name: "Tower Shield"
      description: "A massive defensive shield"
```

### From External File

```yaml
assets:
  from_file: assets.csv     # Supports: .csv, .json, .yaml, .jsonl, .txt
```

Example `assets.csv`:
```csv
id,name,description
sword,Flame Blade,A sword wreathed in magical fire
shield,Tower Shield,A massive defensive shield
```

### Generated Count

```yaml
assets:
  type: image
  count: 10                 # Generate 10 images
```

### With Custom Type

```yaml
assets:
  type: MagicCard           # Use a custom type defined above
  items:
    - id: card-001
      name: "Bureaucratic Ooze"
```

---

## Steps

Steps are the core of the pipeline. They execute in dependency order.

### Step Properties

```yaml
steps:
  - id: my_step             # Required, unique identifier
    type: generate_text     # Required, step type
    requires:               # Optional, dependencies
      - previous_step
    for_each: asset         # Optional, run per-asset
    gather: false           # Optional, wait for all assets
    condition: "rarity == 'rare'"  # Optional, conditional execution
    config: {}              # Step-specific configuration
    cache: true             # Optional, caching behavior
    save_to: outputs/       # Optional, save path pattern
```

### Top-Level Convenience Keys

Common config keys can be specified at the step level for cleaner YAML:

```yaml
# These two are equivalent:
- id: my_step
  type: generate_text
  prompt: "Write something..."    # Convenience: prompt at step level

- id: my_step
  type: generate_text
  config:
    prompt: "Write something..."  # Standard: prompt inside config
```

Supported top-level keys: `prompt`, `query`, `criteria`, `title`

### Writing to Asset Fields

Use `writes_to` to specify which asset field a step's output populates:

```yaml
- id: generate_mechanics
  type: generate_text
  for_each: asset
  writes_to: mechanics        # Output stored in asset.mechanics
  config:
    prompt: "Design mechanics for {asset.name}..."

- id: use_mechanics
  type: generate_text
  for_each: asset
  requires: [generate_mechanics]
  config:
    prompt: "Based on {asset.mechanics}, write flavor text..."  # Reference the field
```

This allows subsequent steps to access the output via `{asset.fieldname}`.

### Step Types

#### `research` - AI Research

```yaml
- id: research_topic
  type: research
  config:
    query: |
      Research {asset.name}: {asset.description}
      Focus on visual characteristics and historical context.
    max_tokens: 4096        # Optional: limit output length
```

#### `generate_text` - Text Generation

```yaml
- id: write_flavor
  type: generate_text
  for_each: asset
  config:
    prompt: |
      Write flavor text for {asset.name}.
      Style: {context.style}
    variations: 3           # Generate 3 options
    include_context: true   # Include rich context (default: true)
    max_tokens: 8192        # Optional: limit output length (default: no limit)
```

### Token Limits

By default, text generation steps have **no token limit** - the model will use its natural output length. To constrain output, set `max_tokens` in the step config:

```yaml
config:
  prompt: "Write a brief description..."
  max_tokens: 1024          # Limit to ~750 words
```

Common values:
- `1024` - Short responses (~750 words)
- `4096` - Medium responses (~3000 words)
- `8192` - Long responses (~6000 words)
- `16384+` - Very long content (model may cap at its own maximum)

If not specified, the model will generate as much content as it deems appropriate for the prompt.

#### `generate_image` - Image Generation

```yaml
- id: create_art
  type: generate_image
  for_each: asset
  config:
    prompt: |
      {asset.name}: {asset.description}
      Style: {context.style}
    size: 512               # Image size (default: 1024)
    variations: 4           # Generate 4 variations
```

#### `assess` - AI Vision Assessment

```yaml
- id: check_quality
  type: assess
  for_each: asset
  requires:
    - create_art
  config:
    source_step: create_art  # Which step's output to assess
    criteria: |
      - Is the subject clearly visible?
      - Does it match the requested style?
      - Are there any artifacts or issues?
    threshold: 7            # Minimum score (1-10)
```

#### `user_select` - User Selection

```yaml
- id: pick_best
  type: user_select
  config:
    prompt: "Select the best option"
    options_from: generate_variations
```

#### `user_approve` - User Approval

```yaml
- id: approve_result
  type: user_approve
  config:
    prompt: "Approve this result?"
```

#### `review` - Checkpoint Review

Pause the pipeline to review all completed work. Shows a summary of all previous steps and requires human approval before continuing. Useful for reviewing major milestones (e.g., "review set design before generating individual cards").

```yaml
- id: review_set_design
  type: review
  requires: [design_mechanics, write_story, generate_concepts]
  config:
    title: "Set Design Review"
    description: |
      Review the completed set design work before proceeding.
      
      Approve to continue, or reject to restart.
    review_steps:  # Optional: only show specific steps (default: all previous)
      - design_mechanics
      - write_story
      - generate_concepts
  cache: true
```

The review step:
- Shows all completed step outputs in a readable format
- In CLI mode: displays a summary and waits for confirmation
- In web mode: shows a dedicated review panel with expandable step details
- Saves the approval decision with timestamp to cache

### Global vs Per-Asset Steps

**Global steps** run once for the entire pipeline:

```yaml
- id: decide_style
  type: generate_text
  config:
    prompt: "Decide on an art style for this project..."
```

**Per-asset steps** run once for each asset:

```yaml
- id: generate_art
  type: generate_image
  for_each: asset           # This makes it per-asset
  config:
    prompt: "{asset.name}: {asset.description}"
```

### Dependencies

Use `requires` to specify step dependencies:

```yaml
steps:
  - id: research
    type: research
    config:
      query: "Research {asset.concept}"
      
  - id: design
    type: generate_text
    requires:
      - research            # Waits for research to complete
    config:
      prompt: |
        Based on: {research.content}
        Design the visual concept.
```

---

## Template Variables

Use `{namespace.field}` syntax to reference values:

### Available Namespaces

| Namespace | Description | Example |
|-----------|-------------|---------|
| `context` or `ctx` | Pipeline context | `{context.style}` |
| `asset` | Current asset | `{asset.name}` |
| `{step_id}` | Step output | `{research.content}` |

### Nested Access

```yaml
prompt: "{asset.stats.health}"    # Access nested fields
prompt: "{context.dimensions.width}"
```

### In Step Config

Templates work in any string value:

```yaml
config:
  prompt: "Create {asset.name} in {context.style} style"
  size: "{context.output_size}"
```

---

## Human-in-the-Loop

Two patterns for human interaction:

### Variations + Selection

Generate multiple options and let user choose:

```yaml
- id: generate_options
  type: generate_image
  for_each: asset
  variations: 4             # Generate 4 options
  select: user              # User selects best one
  config:
    prompt: "{asset.description}"
```

### Approval Loop

Generate until user approves:

```yaml
- id: generate_until_happy
  type: generate_image
  for_each: asset
  until: approved           # Keep generating until approved
  max_attempts: 5           # Maximum regenerations
  config:
    prompt: "{asset.description}"
```

---

## Caching

Steps are automatically cached to enable resuming interrupted pipelines.

### Cache Settings

```yaml
cache: true           # Cache this step (default for global steps)
cache: false          # Don't cache
cache: skip_existing  # Only process assets not yet cached (default for per-asset)
```

### Smart Defaults

- Global steps: `cache: true` - Always cache
- Per-asset steps: `cache: skip_existing` - Skip completed assets

### Cache Invalidation

Cache is automatically invalidated when:
- Pipeline definition changes
- Step configuration changes

Manual invalidation:
```bash
artgen clean pipeline.yaml              # Clear all
artgen clean pipeline.yaml -s step_id   # Clear specific step
artgen clean pipeline.yaml -a asset_id  # Clear specific asset
```

---

## Examples

### Simple Image Pipeline

```yaml
name: simple-sprites
version: "1.0"
description: "Generate game sprites"

context:
  style: "pixel art, 32x32, clean edges"

assets:
  items:
    - id: hero
      name: "Hero"
      description: "A brave adventurer"
    - id: enemy
      name: "Goblin"
      description: "A sneaky goblin"

steps:
  - id: generate
    type: generate_image
    for_each: asset
    config:
      prompt: |
        {asset.name}: {asset.description}
        Style: {context.style}
      size: 512
```

### Full Magic Card Pipeline

```yaml
name: magic-cards
version: "1.0"

types:
  MagicCard:
    name: text
    mana_cost: text
    abilities: text
    flavor: text
    art: image

context:
  game: "Magic: The Gathering"
  art_style: "dark fantasy illustration"

assets:
  items:
    - id: card-001
      name: "Storm Elemental"
      concept: "A being of pure lightning"

steps:
  - id: research
    type: research
    for_each: asset
    config:
      query: "MTG card design: {asset.name} - {asset.concept}"

  - id: mechanics
    type: generate_text
    for_each: asset
    requires: [research]
    config:
      prompt: |
        Design mechanics for {asset.name}
        Research: {research.content}

  - id: flavor
    type: generate_text
    for_each: asset
    requires: [mechanics]
    config:
      prompt: |
        Write flavor text for {asset.name}
        Mechanics: {mechanics.content}

  - id: art
    type: generate_image
    for_each: asset
    requires: [mechanics, flavor]
    variations: 3
    select: user
    config:
      prompt: |
        {asset.name}: {asset.concept}
        Style: {context.art_style}
```

### Iterative Refinement Pipeline

```yaml
name: portrait-refinement
version: "1.0"

context:
  style: "oil painting portrait"

assets:
  items:
    - id: portrait-001
      subject: "A wise old wizard"

steps:
  - id: initial
    type: generate_image
    for_each: asset
    config:
      prompt: "{asset.subject}, {context.style}"

  - id: assess
    type: assess
    for_each: asset
    requires: [initial]
    config:
      criteria: |
        - Is the face well-rendered?
        - Does it match the style?
      threshold: 7

  - id: refined
    type: generate_image
    for_each: asset
    requires: [assess]
    condition: "assess.passed == false"
    until: approved
    max_attempts: 3
    config:
      prompt: |
        {asset.subject}, {context.style}
        Previous issues: {assess.assessment}
```

---

## CLI Reference

```bash
# Run a pipeline
artgen run pipeline.yaml

# With options
artgen run pipeline.yaml --auto-approve  # Skip human interactions
artgen run pipeline.yaml --parallel 5    # 5 concurrent assets
artgen run pipeline.yaml --verbose       # Detailed output

# Validate without running
artgen validate pipeline.yaml

# Show pipeline structure
artgen show pipeline.yaml --graph

# Clear cache
artgen clean pipeline.yaml

# List pipelines in directory
artgen list
```

---

## Best Practices

1. **Use meaningful step IDs** - They appear in logs and cache paths
2. **Set context early** - Define style and parameters at the top
3. **Use dependencies wisely** - Only require what you actually need
4. **Cache appropriately** - Disable cache for steps with side effects
5. **Include context in prompts** - LLMs work better with more context
6. **Test incrementally** - Start with 1-2 assets, then scale up
7. **Use variations for quality** - Generate multiple options and select best
