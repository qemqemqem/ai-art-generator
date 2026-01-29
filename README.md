# AI Art Generator

A CLI-first batch AI art generation tool with optional interactive approval workflow.

## Features

- **CLI-First**: Simple command-line interface for batch generation
- **Multiple Providers**: Gemini (default), Gemini Pro for higher quality
- **Flexible Input**: text files, CSV, JSON, JSONL formats
- **Multi-step Pipelines**: Research → Name → Portrait → Sprite → Description
- **Background Removal**: Create sprites with transparent backgrounds
- **Interactive UI**: Optional web-based approval queue for human-in-the-loop workflows

## Use Cases

- Video game sprites and assets
- Magic: The Gathering card art
- Concept art generation
- Batch illustration generation

## Quick Start

### 1. Install

```bash
# Clone and setup
git clone <repo>
cd ai-art-generator

# Create virtual environment and install
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# Or with pip:
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure API Key

```bash
# Create .env.local with your Gemini API key
echo "GOOGLE_API_KEY=your-api-key-here" > .env.local
```

Get your API key from [Google AI Studio](https://aistudio.google.com/apikey).

### 3. Generate!

```bash
# Create a simple input file
echo "A wise owl wizard
A fire-breathing dragon
An enchanted forest" > my-prompts.txt

# Generate images
cd backend
python artgen.py ../my-prompts.txt --env ../.env.local
```

## CLI Usage

### Basic Generation

```bash
# Generate one image per line in your file
artgen birds.txt

# Generate with 4 variations each
artgen birds.txt -n 4

# Apply a style to all prompts
artgen birds.txt --style "pixel art, 16-bit style"

# Create sprites with transparent backgrounds
artgen units.txt --transparent

# Use higher quality model
artgen portraits.txt --provider gemini_pro

# Specify output directory
artgen cards.csv -o ./my-outputs

# Verbose output (show file paths)
artgen birds.txt -v
```

### CLI Options

```
artgen <file> [options]

Options:
  -e, --env PATH          Path to .env file with API keys
  -o, --output DIR        Output directory (default: ./outputs)
  -s, --style STYLE       Style prompt to apply (e.g. 'pixel art, 16-bit')
  -t, --transparent       Create sprites with transparent backgrounds
  -n, --variations N      Variations per item (default: 1)
  -p, --provider NAME     Image provider: gemini or gemini_pro
  -v, --verbose           Show detailed output
```

### Project Management

```bash
# List all assets in current project
artgen list

# Filter by status
artgen list --status failed
artgen list --status completed

# Show details of a specific asset
artgen show item-001

# Resume processing failed/pending assets
artgen resume

# Only retry failed assets
artgen resume --failed-only
```

### Other Commands

```bash
# Show project status and API key info
artgen status

# Initialize a new project with artgen.json
artgen init

# Start interactive browser-based UI
artgen interactive
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_API_KEY` | Yes | Google/Gemini API key for image generation |
| `OPENAI_API_KEY` | No | OpenAI API key for DALL-E (future) |
| `ANTHROPIC_API_KEY` | No | Anthropic API key for Claude text generation |

### Environment File Search Order

The CLI looks for environment files in this order:
1. `--env` flag (explicit path)
2. `ARTGEN_ENV_FILE` environment variable
3. `.env.local` in current directory
4. `.env` in current directory
5. `~/.config/artgen/.env`
6. `~/.env.local`

## Input Formats

The CLI auto-detects file format based on extension.

**Plain text** (`.txt`) - one description per line:
```
A wise owl wizard
A fire-breathing dragon
An enchanted forest
```

Lines starting with `#` are treated as comments.

**CSV** (`.csv`) - with headers:
```csv
id,description,style
owl,A wise owl wizard,dark fantasy
dragon,Fire-breathing dragon,epic
```

**JSON** (`.json`) - array of objects:
```json
[
  {"id": "owl", "description": "A wise owl wizard"},
  {"id": "dragon", "description": "Fire-breathing dragon"}
]
```

**JSON Lines** (`.jsonl`) - one object per line:
```jsonl
{"id": "owl", "description": "A wise owl wizard"}
{"id": "dragon", "description": "Fire-breathing dragon"}
```

## Output Structure

Generated files are organized by item:

```
outputs/
├── item-001/
│   ├── generate_image_v1.png
│   ├── generate_image_v2.png
│   ├── generate_image_v3.png
│   └── generate_image_v4.png
├── item-002/
│   └── generate_image_v1.png
├── artgen.json              # Project config
└── .artgen/
    └── progress.jsonl       # State tracking
```

## Interactive Mode

For workflows requiring human approval (choosing between variations, rejecting bad outputs):

```bash
# Start interactive mode
artgen interactive

# Pre-load content
artgen interactive my-cards.csv
```

This launches:
- Backend API on port 8000
- Frontend UI on port 5173
- Opens browser automatically

## Advanced: Pipeline Configuration

For complex workflows, create an `artgen.json` in your project:

```json
{
  "name": "Magic Cards",
  "pipeline": [
    {
      "id": "generate_name",
      "type": "generate_name",
      "variations": 3,
      "requires_approval": true
    },
    {
      "id": "generate_portrait",
      "type": "generate_image",
      "variations": 4,
      "requires_approval": true
    }
  ],
  "style": {
    "global_prompt_prefix": "fantasy art, Magic: The Gathering style",
    "global_prompt_suffix": "detailed illustration, dramatic lighting"
  }
}
```

Available step types:
- `generate_image` - Generate images from description
- `generate_sprite` - Generate pixel art sprites
- `generate_name` - Generate creative names
- `generate_text` - Generate text descriptions
- `research` - Research concepts (requires Tavily API)
- `remove_background` - Remove backgrounds from images

## Troubleshooting

**"No API key configured"**
- Set `GOOGLE_API_KEY` in your environment or `.env.local` file

**"ModuleNotFoundError: No module named 'pydantic'"**
- Activate your virtual environment: `source .venv/bin/activate`

**Images are too large**
- Output is 1024x1024 by default. Resize with ImageMagick: `mogrify -resize 128x128 *.png`

## License

MIT
