# Clarifying Questions

## 1. Technology Stack

**Question:** What's your preferred language/framework?

Options:
- **A) Python backend + React frontend** - Best AI library support, but two codebases
- **B) Full TypeScript** - Single language, but some AI tools Python-only  
- **C) Python with Gradio/Streamlit** - Fastest to build, but less flexible UI

My recommendation: **Option A** - Python handles AI/image processing beautifully, React gives you a polished interactive UI.

---

## 2. Primary Image Generator

**Question:** Which image generator should be the default?

Options:
- **DALL-E 3** - Best prompt understanding, easiest API, $0.04-0.12/image
- **FLUX.2** - Newest, high quality, cheaper ($0.014+), hex color control
- **Stable Diffusion** - Cheapest, most customizable, can run locally

For Magic cards / fantasy art: I'd lean **DALL-E 3** for reliability or **FLUX.2** for value.

---

## 3. What is "nano banana"?

You mentioned "nano banana" as an AI art generator. I couldn't find this - did you mean:
- **Leonardo AI**?
- **NightCafe**?
- Something else?

---

## 4. Midjourney Support

**Question:** How important is Midjourney support?

The catch: Midjourney has **no official API**. Options:
- **Skip it** - Use DALL-E/FLUX/SD instead
- **Third-party wrapper** - Works but violates Midjourney ToS, could break anytime
- **Semi-manual** - Generate prompts, user pastes into Discord, uploads results back

---

## 5. Pixel Art Approach

**Question:** For sprites, should we:
- **A) Use PixelLab API** - Purpose-built, good results, ~$0.01/sprite
- **B) Use DALL-E/FLUX + downscale** - Cheaper if already generating, may need cleanup
- **C) Support both** - Let user choose per project

---

## 6. Local vs Cloud Processing

**Question:** For background removal, should we:
- **A) Local only (rembg)** - Free, no API keys, slower
- **B) Cloud only (remove.bg)** - Fast, costs money, needs API key
- **C) Local default, cloud fallback** - Best of both

I recommend **C**.

---

## 7. Interactive UI Scope

**Question:** For the web UI, what's the MVP?

Minimum:
- [ ] Queue of pending approvals
- [ ] View variations side-by-side
- [ ] Accept/reject buttons
- [ ] Progress indicator

Nice to have:
- [ ] Regenerate with modified prompt
- [ ] Inline prompt editing
- [ ] Batch accept/reject
- [ ] Real-time generation preview
- [ ] Style guide editor
- [ ] Export options (ZIP, specific formats)

What's essential for your first use case?

---

## 8. Input Format

**Question:** What format will your input lists be in?

Options:
- **A) Simple text file** - One item per line
  ```
  Wise owl wizard
  Fire-breathing dragon
  Enchanted forest
  ```

- **B) CSV/TSV with metadata**
  ```csv
  id,name,description,style_override
  001,Owlmancer,A wise owl wizard,dark fantasy
  002,Flamewing,Fire-breathing dragon,
  ```

- **C) JSON/JSONL**
  ```json
  {"id": "001", "name": "Owlmancer", "description": "A wise owl wizard"}
  ```

I can support all three - which do you prefer as primary?

---

## 9. Multi-Project or Single Project?

**Question:** Will you typically:
- **A) Run one project at a time** - Simpler state management
- **B) Run multiple projects concurrently** - Needs more robust isolation

---

## 10. Deployment

**Question:** Where will this run?
- **A) Local machine only** - Simpler, can use local models
- **B) Cloud server** - Accessible from anywhere, needs auth
- **C) Both** - Start local, option to deploy

---

## 11. Budget Constraints

**Question:** Any budget limits per project?
- Should the tool warn/stop at certain spend thresholds?
- Should it track costs per asset?

---

## 12. Wingspan EDH / Magic Cards Specifics

**Question:** For the Magic card use case:
- Do you need specific aspect ratios? (Standard Magic art is ~1.4:1)
- Do you need card frame generation, or just the art?
- Any specific art styles to default to? (e.g., "MTG style", "digital painting")

---

## Summary: Minimum Decisions Needed

To start building, I need answers to:

1. **Stack:** Python+React, TypeScript, or Python+Gradio?
2. **Primary image gen:** DALL-E, FLUX, or SD?
3. **What's nano banana?**
4. **Midjourney:** Skip, wrapper, or semi-manual?
5. **Input format preference:** txt, csv, or json?
