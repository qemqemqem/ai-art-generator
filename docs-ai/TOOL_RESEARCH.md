# AI Art Generation Tools Research

## Image Generation APIs

### Tier 1: Production-Ready Official APIs

| Provider | API Access | Pricing | Best For | Notes |
|----------|------------|---------|----------|-------|
| **Gemini / Nano Banana** (Google) | Official API | Included in Gemini API | Default choice, excellent quality | Native image gen in Gemini, supports editing |
| **Gemini 3 Pro Image** (Google) | Official API | Included in Gemini API | Professional assets, 4K output | "Thinking" mode, Google Search grounding |
| **DALL-E 3** (OpenAI) | Official API | $0.04-0.12/image | Superior prompt understanding, commercial use | Most straightforward integration |
| **Stable Diffusion** (Stability.ai) | Official REST API | Cheapest per image | High volume, customization, open-source | Most developer-friendly, CFG scale, samplers |
| **FLUX.2** (Black Forest Labs) | Official API | From $0.014/image | Photorealistic, fast inference | Newest option, 4MP output, hex color control |
| **Leonardo AI** | Official API | Tiered plans | Multiple models, LoRA training | Good for variety of styles |

### Tier 2: Unofficial/Limited Access (TODO)

| Provider | API Access | Notes |
|----------|------------|-------|
| **Midjourney** | NO official API | Discord-only. Third-party wrappers exist but violate ToS. Skipping for now. |

---

## Gemini / Nano Banana Details (DEFAULT)

**Models:**
- `gemini-2.5-flash-image` (Nano Banana) - Fast, efficient, 1024px output
- `gemini-3-pro-image-preview` (Nano Banana Pro) - Professional quality, 4K output, "thinking" mode

**Features:**
- Text-to-image generation
- Image editing (text + image → image)
- Multi-turn conversational editing
- Style transfer
- Inpainting (semantic masking)
- Up to 14 reference images (Pro model)
- Google Search grounding for real-time info
- Aspect ratios: 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9

**Python Usage:**
```python
from google import genai
from google.genai import types

client = genai.Client()
response = client.models.generate_content(
    model="gemini-2.5-flash-image",
    contents=["A fantasy dragon in watercolor style"],
    config=types.GenerateContentConfig(
        response_modalities=['TEXT', 'IMAGE'],
        image_config=types.ImageConfig(aspect_ratio="3:2")
    )
)

for part in response.parts:
    if part.inline_data is not None:
        image = part.as_image()
        image.save("output.png")
```

### Pixel Art Specialists

| Provider | API Access | Pricing | Features |
|----------|------------|---------|----------|
| **PixelLab** | Official API | $0.007-0.013/image | Pixflux/Bitforge models, animations, 8-directional sprites, inpainting |
| **PixAI** | Coming soon | TBD | Custom color palettes |
| **SpriteCook** | Web-based | TBD | Style consistency across assets |

**Recommendation for pixel art:** PixelLab has the most mature API with game-specific features (rotations, animations, palette forcing).

---

## Background Removal APIs

| Provider | Pricing | Speed | Features |
|----------|---------|-------|----------|
| **remove.bg** | 50 free/month, then paid | Fast | Up to 50MP, bulk (500/min), SDKs for all languages |
| **RemoveBG API** | Claims 95% cheaper | <5s | 36MP, "hair-level precision" |
| **rembg** | Free (open source) | Local | Python library, runs locally, no API costs |

**Recommendation:** Start with `rembg` for local processing (no API costs, no rate limits), fall back to remove.bg for quality issues.

---

## AI Research APIs

| Provider | Pricing | Latency | Best For |
|----------|---------|---------|----------|
| **Perplexity** | $5/1000 requests | <400ms | Fast agentic queries, filtering |
| **Tavily** | 1000 free credits/month | Moderate | RAG systems, structured JSON with citations |

**Perplexity Deep Research** (Feb 2025): Autonomous research spending 2-4 min per query, reads hundreds of sources. Free tier available.

**Recommendation:** Tavily for structured research output (citations included), Perplexity for speed.

---

## Text Generation (for descriptions, names)

| Provider | Model | Best For |
|----------|-------|----------|
| **Anthropic** | Claude 3.5/4 | Creative writing, descriptions |
| **OpenAI** | GPT-4o | General purpose |

---

## Recommended Stack

### Primary Image Generation
1. **DALL-E 3** - Best prompt understanding, reliable
2. **FLUX.2 [pro]** - High quality, good value
3. **Stable Diffusion** - Fallback, cheapest for volume

### Pixel Art
1. **PixelLab** - Purpose-built for game assets

### Background Removal
1. **rembg** (local) - Primary, free
2. **remove.bg** - Fallback for quality issues

### Research
1. **Tavily** - Structured output with citations

### Text Generation
1. **Claude** - Via Anthropic API

---

## Cost Estimates (per asset)

| Component | Low Estimate | High Estimate |
|-----------|--------------|---------------|
| Research (Tavily) | $0.001 | $0.002 |
| Name generation (Claude) | $0.002 | $0.005 |
| Portrait (DALL-E 3) | $0.04 | $0.12 |
| Pixel sprite (PixelLab) | $0.007 | $0.013 |
| Description (Claude) | $0.002 | $0.005 |
| Background removal | $0 (rembg) | $0.05 (remove.bg) |
| **Total per asset** | **~$0.05** | **~$0.20** |

For 100 assets: $5-20 estimated.

---

## API Key Requirements

To use this utility, users will need API keys for:
- [ ] OpenAI (DALL-E, GPT)
- [ ] Anthropic (Claude)
- [ ] Stability.ai OR Black Forest Labs (FLUX)
- [ ] PixelLab (for pixel art)
- [ ] Tavily OR Perplexity (for research)
- [ ] remove.bg (optional, for cloud background removal)
