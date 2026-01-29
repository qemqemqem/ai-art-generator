# Pipeline v1: Design Decisions

This document captures key design decisions for the v1 pipeline implementation.

---

## Expression Language: `simpleeval`

We use [simpleeval](https://github.com/danthedeckie/simpleeval) for safe expression evaluation.

**Supported syntax:**
```python
# Comparisons
rarity == 'legendary'
quality >= 0.8

# Boolean logic
rarity in ['rare', 'mythic'] and quality > 0.7
not approved

# Ternary
4 if rarity == 'legendary' else 2

# Math
cost * 2 + 1
```

**NOT supported (by design):**
- Function calls (unless we explicitly allow them)
- Imports
- Arbitrary attribute access
- Statements/assignments

**Usage in YAML:**
```yaml
steps:
  - id: generate_art
    when: "rarity in ['rare', 'mythic']"
    config:
      variations: "4 if rarity == 'legendary' else 2"
```

---

## Smart Defaults

### Caching

| Step Type | Default `cache` |
|-----------|-----------------|
| Global (no `for_each`) | `true` |
| Per-asset (`for_each: asset`) | `skip_existing` |
| Explicitly set | Use explicit value |

### Save Location

If `save_to` is not specified, auto-generate from step ID:

| Step Type | Default `save_to` |
|-----------|-------------------|
| Global step | `{step.id}.json` |
| Per-asset step | `{step.id}/{asset.id}/` |
| Image output | `{step.id}/{asset.id}/{step.id}_v{n}.png` |

### Example: Implicit vs Explicit

```yaml
# These are equivalent:

# Implicit (recommended)
steps:
  - id: research_style
    type: research
    config:
      query: "Pixel art styles"

# Explicit (verbose)
steps:
  - id: research_style
    type: research
    save_to: research_style.json
    cache: true
    config:
      query: "Pixel art styles"
```

---

## Explicit Field Binding

Steps that produce output for an asset field must declare it:

```yaml
types:
  MagicCard:
    name: text
    art: image
    flavor: text?

steps:
  - id: generate_art
    type: generate_image
    for_each: asset
    writes_to: asset.art        # Explicit: this fills the 'art' field
    config:
      prompt: "..."

  - id: generate_flavor
    type: generate_text
    for_each: asset
    writes_to: asset.flavor     # Explicit: this fills the 'flavor' field
    config:
      prompt: "..."
```

**Benefits:**
- Clear data flow
- Validation at parse time (does `art` exist on the type?)
- Documentation of what each step produces

---

## Simplified Loop Model

No generic `loop` step. Instead, two declarative patterns:

### Pattern 1: Select-from-K

Generate K variations, user selects the best one.

```yaml
- id: generate_art
  type: generate_image
  for_each: asset
  variations: 4               # Generate 4 options
  select: user                # "user" = async queue, "auto" = AI picks best
  writes_to: asset.art
```

Execution:
1. Generate 4 images
2. Save all to `{step.id}/{asset.id}/v1.png`, `v2.png`, etc.
3. Add to approval queue
4. When user selects, mark that version as "selected"
5. Pipeline continues with selected version

### Pattern 2: Accept/Reject Loop

Generate one at a time until user accepts.

```yaml
- id: generate_art
  type: generate_image
  for_each: asset
  until: approved             # Keep generating until accepted
  max_attempts: 5             # Safety limit
  writes_to: asset.art
```

Execution:
1. Generate 1 image
2. Add to approval queue
3. If rejected, generate another (up to max_attempts)
4. If accepted, continue pipeline

### For v1: CLI-only Blocking Mode

In v1, `select: user` and `until: approved` will:
- Block at the terminal
- Show images (open in viewer or print paths)
- Prompt for selection/approval

The async queue is a v2 feature when we build the web UI.

---

## Human-in-the-Loop: Deferred to v2

For v1, human interaction is **CLI-blocking only**:

```
$ artgen run pipeline.yaml

[generate_art] Generated 4 variations for "Elven Archer"
  1. sprites/archer/v1.png
  2. sprites/archer/v2.png
  3. sprites/archer/v3.png
  4. sprites/archer/v4.png

Select best (1-4), or 'r' to regenerate all: 2

✓ Selected v2 for "Elven Archer"
```

For v2, we'll implement:
- Async approval queue
- Web UI for reviewing/selecting
- Batch approval workflows
- WebSocket updates for progress

---

## Template Variable Syntax

Simple interpolation with validation at parse time:

```yaml
config:
  prompt: "{context.style}, {asset.name}, {asset.prompt}"
```

**Available namespaces:**
- `context.*` - Values from context section
- `asset.*` - Current asset fields (in `for_each` steps)
- `{step_id}.*` - Output from a previous step

**Validation:**
- At parse time, check that referenced fields exist
- `context.style` → does `style` exist in context?
- `asset.name` → does `name` exist on the asset type?
- `research.output` → does step `research` exist and come before this step?

---

## v1 Scope

### In Scope
- [x] Type definitions
- [x] External input files (`from_file`)
- [x] Smart caching defaults
- [x] Auto-generated save paths
- [x] Explicit field binding (`writes_to`)
- [x] Simple conditions (`when: "expression"`)
- [x] Variable interpolation in prompts
- [x] `for_each: asset` parallelism
- [x] `variations: K` with CLI selection
- [x] CLI-blocking human interaction

### Out of Scope (v2)
- [ ] Async approval queue
- [ ] Web UI for review
- [ ] Generic loops
- [ ] Complex nested conditionals
- [ ] WebSocket progress updates

---

## Dependencies

```
simpleeval>=1.0.0    # Safe expression evaluation
pyyaml>=6.0          # YAML parsing
rich>=13.0           # CLI output
```

---

## Example: v1 Pipeline

```yaml
name: "Game Sprites"
version: "1.0"

types:
  GameSprite:
    name: text
    unit_class: infantry | cavalry | ranged | magic
    prompt: text
    sprite: image?

assets:
  type: GameSprite
  from_file: ./units.csv

context:
  style: "16-bit pixel art, clean edges"

steps:
  # Global research (auto-cached)
  - id: research_style
    type: research
    config:
      query: "Pixel art techniques for {context.style}"

  # Per-asset generation (auto-cached, CLI selection)
  - id: generate_sprite
    type: generate_sprite
    for_each: asset
    writes_to: asset.sprite
    variations: 3
    select: user              # CLI blocking in v1
    config:
      prompt: "{context.style}, {asset.prompt}"

  # Export (auto-cached)
  - id: export
    type: resize
    for_each: asset
    requires: [generate_sprite]
    config:
      sizes: [32, 64, 128]
```

Running:
```bash
$ artgen run sprites.yaml

[research_style] Researching pixel art techniques...
✓ Saved to .artgen/research_style.json

[generate_sprite] Processing 4 assets...

  Generating "Elven Archer" (1/4)...
  ✓ Generated 3 variations

  Select best for "Elven Archer":
    1. .artgen/generate_sprite/archer/v1.png
    2. .artgen/generate_sprite/archer/v2.png
    3. .artgen/generate_sprite/archer/v3.png
  Choice (1-3): 2
  ✓ Selected v2

  ... (repeat for other assets) ...

[export] Exporting 4 assets...
✓ Exported to .artgen/export/

Done! 4 sprites generated.
```
