# Product Vision: ArtGen

## The Core Insight

Great creative work—whether poetry, art, or game assets—requires **orchestrated iteration**. 

Gwern's experiments with LLM poetry demonstrate that a single prompt rarely produces greatness. Instead, the creative process looks like this:

1. **Research** - Gather domain knowledge, vocabulary, references
2. **Brainstorm** - Generate many diverse directions
3. **Critique** - Evaluate each direction rigorously
4. **Create** - Execute the best direction
5. **Refine** - Critique and revise line by line
6. **Iterate** - Repeat until excellent

This is what poets do. What artists do. What game designers do. ArtGen is a tool that lets creators **define and execute this process** for visual assets at scale.

---

## What Makes Great Art?

From the essay on LLMs and poetry:

> "A great poem is both particular and universal. A great poem is 'about' a specific person or moment embedded in a particular culture, composed in such a way that it reaches across time and distance to resonate with readers outside that culture."

For visual art, the same principle applies. Great game art isn't generic fantasy—it's *this* game's fantasy, with specific visual language, specific references, specific constraints. The art resonates because it's coherent with itself and connected to broader visual traditions.

**LLMs have the training data. They lack the orchestration.**

A model asked to "draw a wizard" will produce generic wizard imagery. But a model that has:
- Researched the specific game's existing art style
- Built a vocabulary of visual elements (robes, staves, runes, lighting)
- Defined what makes *this* wizard different from every other wizard
- Generated many variations
- Critiqued each against specific criteria
- Refined the best candidate

...will produce something particular. Something that belongs to this project.

---

## The Pipeline as Creative Process

Gwern's poetry process maps directly to a pipeline:

| Gwern's Process | ArtGen Pipeline Step |
|-----------------|---------------------|
| "Analyze the style, content, and intent" | `analyze` / `research` |
| "Brainstorm 10+ different directions" | `brainstorm` with `variations=10` |
| "Critique each direction. Rate 1-5 stars" | `assess` with scoring rubric |
| "Write the best one" | `generate` from top-rated direction |
| "Critique and edit line by line" | `refine` with detailed feedback |
| "Generate a new clean draft" | `regenerate` incorporating feedback |
| "Repeat at least twice" | `loop` with `min_iterations=2` |
| "Print final version" | `export` |

### The Databank Concept

Gwern's Pindaric Ode project compiled a databank of domain-specific vocabulary:

> "categories, from geography (Vivarium, Laminar Flow, Autoclave) to heroes (Laika, Dolly, OncoMouse) to tribes (C57BL/6, Wistar Rat) to priests (Abbie Lathrop, Claude Bernard)..."

For visual art, this translates to:
- **Visual vocabulary** - specific colors, textures, shapes for this project
- **Reference library** - existing art that defines the style
- **Constraint set** - what must be present, what must be avoided
- **Proper nouns** - named characters, places, items that recur

The databank prevents the model from "reaching for generic images and ideas."

### Different Models for Different Tasks

Gwern uses different models for different purposes:
- **Claude** for "better taste and curating"
- **o1-pro** for brainstorming and initial generation  
- **Kimi K2** for critique

ArtGen should support this naturally:
```yaml
steps:
  - type: brainstorm
    model: creative  # High temperature, diverse output
    
  - type: assess
    model: critic    # Analytical, detail-oriented
    
  - type: generate
    model: visual    # Best image generation
    
  - type: refine
    model: editor    # Good at iterative improvement
```

### The "Reviewer #2" Technique

> "Gwern prompted the model to evaluate the poem as if it were a submission to Poetry magazine, then asks for a 'reviewer #2' report with detailed criticism and suggestions. He finds that adopting this persona 'unhobbles' the model's feedback."

This is a **prompt engineering pattern** we should build into assessment steps:
- Don't just ask "is this good?"
- Ask "you are an art director at [prestigious studio], reviewing this for publication"
- The persona unlocks more rigorous, useful critique

---

## Pipeline Architecture: DAG, Not Stages

The user's insight: **it's not two-stage (global then per-asset)**. 

Instead, think of the pipeline as a **directed acyclic graph (DAG)** with:
- **Parallel operations** - can run concurrently (generating multiple assets)
- **Gather operations** - synchronization points that require all previous work

### Example: Game Sprite Pipeline

```
[analyze_existing_art] ──┐
                         ├──► [define_style_guide] ──► [create_palette]
[research_pixel_art] ────┘                                    │
                                                              ▼
                    ┌─────────────────────────────────────────┴───────┐
                    │              FOR EACH ASSET (parallel)          │
                    │  ┌──────────────────────────────────────────┐   │
                    │  │ [generate_prompt] ──► [generate_sprite]  │   │
                    │  │         │                    │           │   │
                    │  │         ▼                    ▼           │   │
                    │  │   [refine_prompt] ◄── [assess_quality]   │   │
                    │  │         │                    │           │   │
                    │  │         └────────► [loop until approved] │   │
                    │  └──────────────────────────────────────────┘   │
                    └─────────────────────────────────────────────────┘
                                              │
                                              ▼
                              [gather: generate_spritesheet]
                                              │
                                              ▼
                                    [export_all_formats]
```

### Dependency Types

1. **Data dependency** - Step B needs output from Step A
   ```yaml
   - id: style_guide
     type: define_style
     
   - id: generate_prompt  
     type: generate
     requires: [style_guide]  # Must wait for style_guide
   ```

2. **Gather dependency** - Step requires ALL previous items to complete
   ```yaml
   - id: spritesheet
     type: composite
     gather: true  # Wait for all per-asset steps to finish
   ```

3. **No dependency** - Steps can run in parallel
   ```yaml
   assets:
     - id: archer
     - id: knight
     - id: wizard
   # All three can generate simultaneously
   ```

### Flexible Ordering

The pipeline should support any valid DAG:

```yaml
# Linear (simple)
steps: [research, generate, refine, export]

# Fan-out (parallel generation)
steps:
  - research
  - generate_variants: {parallel: true, count: 5}
  - select_best
  - export

# Fan-in (gather)
steps:
  - for_each_asset: [generate, assess, approve]
  - gather: create_atlas
  - export

# Complex DAG
steps:
  - id: a
  - id: b  
  - id: c
    requires: [a, b]  # Wait for both
  - id: d
    requires: [a]     # Only needs a
  - id: e
    requires: [c, d]  # Final gather
```

---

## The Creator's Role

From the essay:

> "As a poet and scholar of poetry I feel comfortable arguing that Gwern's work engineering prompts is, in effect, writing poetry."

The creator using ArtGen is not delegating to AI. They are:
- **Defining the vision** - What makes this project's art distinctive?
- **Building the vocabulary** - What visual language does this project speak?
- **Designing the process** - What steps produce the quality we need?
- **Curating the output** - Which variations best serve the project?

ArtGen is the tool that executes the creator's process at scale.

---

## What We're Building Toward

### Phase 1: Execution Engine (Current)
- Run defined pipelines reliably
- Handle multiple input formats
- Post-process outputs (transparency, resize)
- Track progress and enable resume

### Phase 2: Iteration & Refinement
- Assessment steps with scoring rubrics
- Refinement loops (iterate until quality threshold)
- Human-in-the-loop approval queues
- Best-of-N selection

### Phase 3: Intelligence
- Style analysis from reference images
- Databank generation (project-specific vocabulary)
- Prompt enhancement using style guides
- Cross-asset consistency checking

### Phase 4: Orchestration
- DAG-based pipeline execution
- Parallel processing with gather points
- Conditional branching
- Multi-model routing (different models for different tasks)

### Phase 5: Creative Partnership
- Pipeline templates for common use cases
- Learning from approval patterns
- Suggested refinements based on critique
- Version comparison and A/B testing

---

## Success Criteria

We'll know ArtGen is working when:

1. **Particularity** - Output looks like it belongs to THIS project, not generic
2. **Consistency** - Assets cohere with each other
3. **Quality** - Output meets professional standards without manual touchup
4. **Efficiency** - 100 assets take hours, not weeks
5. **Control** - Creator's vision is preserved, not overwritten by AI defaults

---

## The Gwern Test

Could ArtGen support Gwern's poetry process?

| His Need | ArtGen Feature |
|----------|----------------|
| Multi-stage prompting | Pipeline steps with data flow |
| Brainstorm 10+ directions | `brainstorm` step with `variations` |
| Critique with star ratings | `assess` step with rubric |
| Different models for different tasks | Model routing per step |
| Databank of domain vocabulary | `research` step output as context |
| "Reviewer #2" persona | Prompt templates for assessment |
| Iterative refinement | `loop` with quality threshold |
| Treating poem as living document | Resume and re-run capabilities |

If we can support this workflow, we can support any creative pipeline.

---

## Closing Thought

> "The point of the databank was to prevent the model from reaching for generic images and ideas while also requiring that the poem stays in its lane."

This is the core problem ArtGen solves. Not "generate art" but "generate *this* art, in *this* style, for *this* project, meeting *these* standards."

The orchestration is the art.
