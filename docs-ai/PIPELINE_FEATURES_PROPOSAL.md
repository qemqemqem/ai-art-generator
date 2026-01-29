# Pipeline Features Proposal

**Date:** January 29, 2026  
**Status:** Brainstorm - Awaiting Sign-off

---

## Current State

The pipeline orchestrator currently supports:
- Sequential step execution with approval gates
- Multiple variations per step
- Step types: `generate_image`, `generate_sprite`, `generate_name`, `generate_text`, `research`, `remove_background`
- Auto-approve mode for batch processing
- Basic prompt building from previous steps

---

## Creator Personas & Use Cases

Before diving into features, here's who we're building for:

| Persona | Primary Use Case | Key Needs |
|---------|------------------|-----------|
| **Game Developer** | Sprites, tilesets, UI icons | Consistency, transparency, sprite sheets |
| **Card Game Designer** | Card art, sets of 50-500 cards | Style consistency, templates, batch processing |
| **Indie Creator** | Placeholder art, rapid iteration | Speed, variations, easy export |
| **Content Creator** | Thumbnails, social images | Quick generation, branding consistency |
| **Author/Writer** | Book covers, character portraits | High quality, specific dimensions |

---

## Proposed Features

### Tier 1: High Impact, Should Have (Priority: HIGH)

#### 1. Image-to-Image Generation
**Why:** Creators rarely start from scratch. They have sketches, references, or existing art they want to build on.

```yaml
# Example pipeline step
- id: refine_sketch
  type: image_to_image
  config:
    source: "user_upload"  # or previous step
    strength: 0.7          # how much to change (0=identical, 1=ignore input)
    mode: "style_transfer" # or "variation", "upscale", "inpaint"
```

**Capabilities:**
- Generate variations of existing images
- Apply style transfer (make this sketch look like pixel art)
- Upscale low-resolution images
- Inpaint/edit specific regions

#### 2. Reference Image Support
**Why:** Style consistency is the #1 pain point. "Make it look like THIS" is the most common request.

```yaml
# In project config
style:
  reference_images:
    - path: "references/style_guide.png"
      weight: 0.8
    - path: "references/color_palette.png"
      weight: 0.5
```

**Capabilities:**
- Attach reference images to project
- AI uses references to guide generation
- Multiple references with different weights
- Automatic style consistency checking

#### 3. Post-Processing Pipeline
**Why:** Generated images almost always need processing before they're usable.

```yaml
- id: process_output
  type: post_process
  config:
    operations:
      - resize: { width: 64, height: 64, mode: "contain" }
      - add_border: { color: "#000000", width: 2 }
      - optimize: { format: "png", compression: 9 }
```

**New step types:**
- `resize` - Resize/crop to specific dimensions
- `composite` - Layer images together
- `add_border` - Add borders/frames
- `color_adjust` - Adjust brightness, contrast, saturation
- `create_spritesheet` - Combine multiple sprites into atlas
- `export_multi_resolution` - Generate 1x, 2x, 3x versions

#### 4. Conditional Steps
**Why:** Not every asset needs every step. Smart pipelines adapt.

```yaml
- id: fix_transparency
  type: remove_background
  condition:
    check: "transparency_percentage"
    operator: "<"
    value: 80
```

**Condition types:**
- `transparency_percentage` - Check alpha coverage
- `image_dimensions` - Check width/height
- `file_size` - Check output size
- `previous_step_status` - Check if step succeeded
- `metadata_field` - Check asset metadata
- `custom_script` - Run Python function

#### 5. Parallel Asset Processing
**Why:** Processing 100 assets one-by-one is painfully slow.

```yaml
# In project settings
settings:
  parallel_assets: 4       # Process 4 assets simultaneously
  rate_limit_provider:
    gemini: 10/minute      # Respect API limits
    dalle: 5/minute
```

**Capabilities:**
- Configure parallelism per project
- Automatic rate limiting per provider
- Progress tracking across parallel jobs
- Smart retry with backoff

---

### Tier 2: Nice to Have (Priority: MEDIUM)

#### 6. Templates & Presets
**Why:** Nobody wants to configure the same pipeline twice.

```bash
# Use a preset
artgen init --preset game-sprites
artgen init --preset card-game
artgen init --preset social-media

# Save current config as template
artgen config save-preset my-pixel-style
```

**Built-in presets:**
- `game-sprites` - Pixel art sprites with transparency
- `card-game` - Card art with consistent dimensions
- `social-media` - Thumbnails and social images
- `book-cover` - High-res book cover art
- `icon-set` - App icons in multiple sizes

#### 7. Quality Gates
**Why:** Catch bad generations before they waste time in approval.

```yaml
- id: quality_check
  type: quality_gate
  config:
    checks:
      - min_resolution: { width: 512, height: 512 }
      - max_file_size: "5MB"
      - has_transparency: true
      - no_watermarks: true  # AI detection
    on_fail: "regenerate"    # or "flag", "skip"
    max_retries: 3
```

#### 8. Multi-Resolution Export
**Why:** Mobile games need 1x, 2x, 3x. Web needs WebP and PNG.

```yaml
- id: export
  type: multi_export
  config:
    formats:
      - { format: "png", scale: 1, suffix: "" }
      - { format: "png", scale: 2, suffix: "@2x" }
      - { format: "webp", scale: 1, quality: 90 }
    output_dir: "exports/{asset_id}/"
```

#### 9. Sprite Sheet Generation
**Why:** Game engines want atlases, not individual files.

```yaml
- id: create_atlas
  type: spritesheet
  config:
    assets: "all"                    # or list of asset IDs
    layout: "grid"                   # or "packed"
    padding: 2
    output: "atlas.png"
    metadata_format: "json"          # Unity, Godot, generic
```

#### 10. Prompt Enhancement
**Why:** Users write "a sword" but the AI needs more detail.

```yaml
- id: enhance_prompt
  type: prompt_enhance
  config:
    mode: "expand"           # Add detail to short prompts
    style_hints: true        # Add style-appropriate keywords
    negative_prompt: true    # Auto-generate negative prompt
```

**Example transformation:**
- Input: "a sword"
- Enhanced: "a medieval longsword with ornate crossguard, silver blade with engravings, leather-wrapped handle, fantasy game item, clean edges, isolated on white background"

---

### Tier 3: Future Vision (Priority: LOW)

#### 11. Character Consistency System
**Why:** "Generate 10 poses of the same character" is incredibly hard.

```yaml
# Define a character
characters:
  hero:
    description: "Young knight with red hair, blue armor"
    reference_images:
      - "references/hero_front.png"
      - "references/hero_side.png"
    traits:
      hair_color: "#cc4422"
      armor_color: "#2244aa"

# Use in pipeline
- id: generate_hero_attack
  type: generate_character_pose
  config:
    character: "hero"
    pose: "attack_swing"
```

#### 12. Animation Frame Generation
**Why:** Sprites often need animation.

```yaml
- id: walk_cycle
  type: generate_animation
  config:
    character: "hero"
    animation: "walk"
    frames: 8
    output: "spritesheet"   # or individual frames
```

#### 13. Tileset Generation
**Why:** Game tilesets need seamless connections.

```yaml
- id: grass_tileset
  type: generate_tileset
  config:
    base_tile: "grass"
    variants: 4
    connectors: true        # Generate edge tiles
    seamless: true
```

#### 14. A/B Comparison & Learning
**Why:** Learn from approval patterns.

```yaml
# Automatic learning from approvals
settings:
  learn_from_approvals: true
  preference_model: "project_local"
```

**Capabilities:**
- Track which variations get approved
- Suggest prompt improvements based on history
- Style drift detection ("your recent approvals are diverging from references")

#### 15. External Tool Integration
**Why:** Creators use many tools.

```yaml
integrations:
  - type: "figma_export"
    api_key: "${FIGMA_API_KEY}"
    auto_sync: true
    
  - type: "unity_package"
    output: "Assets/Generated/"
    auto_import: true
    
  - type: "webhook"
    url: "https://api.mysite.com/asset-ready"
    on: ["asset_completed", "batch_completed"]
```

---

## Implementation Priority

### Phase 1: Foundation (Weeks 1-2)
1. ✅ Basic pipeline orchestration (DONE)
2. Post-processing steps (resize, composite)
3. Parallel asset processing
4. Quality gates

### Phase 2: Creator Experience (Weeks 3-4)
5. Reference image support
6. Templates & presets
7. Multi-resolution export
8. Sprite sheet generation

### Phase 3: Advanced (Weeks 5-8)
9. Image-to-image generation
10. Conditional steps
11. Prompt enhancement
12. Character consistency (experimental)

---

## Questions for Sign-off

1. **Priority Check:** Does the tiering make sense? Should anything move up/down?

2. **Reference Images:** This is complex to implement well. Is it worth the effort for v1, or should we defer?

3. **Sprite Sheets:** Should we support multiple atlas formats (Unity JSON, Godot tres, generic)?

4. **Character Consistency:** This is the holy grail but very hard. Defer to v2?

5. **Presets:** Which built-in presets would be most valuable to ship with?

6. **Integration:** Any specific tools/platforms we should prioritize for integration?

---

## Notes

- All features should degrade gracefully (if reference image fails, continue without)
- Cost awareness is important (show estimated cost before batch runs)
- Keep CLI-first philosophy (all features accessible from command line)
- Don't break existing workflows (backward compatibility)
