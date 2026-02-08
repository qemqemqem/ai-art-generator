# Generate Game Sprites

This example shows how to generate a small set of video game sprites
from a base style description and a CSV list of assets. It is designed
for users who are new to this repo and just want a working recipe.

## What it does

- Loads a base art description from `base_description.txt`
- Loads sprite rows from `sprites.csv`
- Builds a per-asset prompt with an LLM
- Generates one image per asset
- Removes the background for transparency
- Saves results into `output/`

## Prerequisites

- You have installed the CLI as `artgen` via `pipx`
- You have configured the required API keys for your providers

## Run the pipeline

From the repo root:

```
artgen run examples/generate_sprites/pipeline.yaml
```

Outputs are written to:

```
examples/generate_sprites/output/
```

Files are named by asset id (for example, `archer.png`).

## Customize the sprites

Edit the base style description:

- `examples/generate_sprites/base_description.txt`

Edit the sprite list:

- `examples/generate_sprites/sprites.csv`

CSV columns:

- `id`: used for filenames
- `description`: the sprite details

Example:

```
id,description
knight,A stout armored knight with a broad shield and a short sword
archer,A nimble archer with a hooded cloak and a drawn bow
slime,A small translucent green slime with a cheerful face
```

## Re-run from scratch

If you want to regenerate everything (including prompts and images), clear
the cache and outputs first:

```
rm -rf examples/generate_sprites/.artgen examples/generate_sprites/output
artgen run examples/generate_sprites/pipeline.yaml
```

## Troubleshooting

- If images look the same, make sure the `sprites.csv` descriptions differ.
- If nothing runs, confirm your API keys are set and valid for your provider.
