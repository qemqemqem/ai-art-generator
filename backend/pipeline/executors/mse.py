"""
Magic Set Editor (MSE) Card Rendering Executor.

Renders full Magic: The Gathering cards using MSE via Wine.
This is a bespoke executor specifically for MTG card generation pipelines.
"""

import json
import os
import re
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import ExecutorContext, StepExecutor, StepResult
from .registry import register_executor


# Default MSE location - can be overridden in config
DEFAULT_MSE_PATH = Path.home() / "Installs" / "M15-Magic-Pack" / "mse.exe"


def extract_json_from_content(content: str) -> dict | None:
    """Extract JSON from a string that may contain markdown code blocks."""
    # Try to find JSON in code blocks first
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            pass
    
    # Try parsing the whole content as JSON
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError:
        pass
    
    return None


def extract_artist_credit(art_direction: str) -> str:
    """Extract artist credit from art direction text."""
    # Look for "Artist Credit:" line
    match = re.search(r'Artist Credit:\s*(.+?)(?:\n|$)', art_direction, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "AI Generated"


def write_mse_set_file(cards: list[dict], filepath: Path, set_name: str = "artgen_set"):
    """
    Write an MSE set file with card data.
    
    Args:
        cards: List of card dictionaries with all card data
        filepath: Path to write the set file
        set_name: Name of the set
    """
    with open(filepath, 'w', encoding='utf-8') as f:
        # MSE set header
        f.write("mse_version: 2.0.2\n")
        f.write("game: magic\n")
        f.write("game_version: 2020-04-25\n")
        f.write("stylesheet: m15-altered\n")
        f.write("stylesheet_version: 2020-09-04\n")
        f.write("set_info:\n")
        f.write(f"\ttitle: {set_name}\n")
        f.write("\tsymbol:\n")
        f.write("\tmasterpiece_symbol:\n")
        f.write("styling:\n")
        f.write("\tmagic-m15-altered:\n")
        f.write("\t\tother_options: auto vehicles, auto nyx crowns\n")
        f.write("\t\ttext_box_mana_symbols: magic-mana-small.mse-symbol-font\n")
        f.write("\t\tlevel_mana_symbols: magic-mana-large.mse-symbol-font\n")
        f.write("\t\toverlay:\n")
        
        # Write each card
        for idx, card in enumerate(cards):
            # Format rule text - replace mana symbols with MSE format
            rule_text = card.get('rule_text', '').strip().replace('\n', '\n\t\t')
            # Convert {T} to <sym>T</sym> and {X} to <sym>X</sym>
            rule_text = rule_text.replace('{T}', '<sym>T</sym>')
            rule_text = re.sub(r'\{(.)\}', r'<sym>\1</sym>', rule_text)
            
            # Format casting cost - strip braces for MSE
            casting_cost = card.get('mana_cost', card.get('casting_cost', ''))
            casting_cost = casting_cost.replace('{', '').replace('}', '')
            
            f.write("card:\n")
            f.write(f"\thas_styling: false\n")
            f.write(f"\ttime_created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"\ttime_modified: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"\tname: {card.get('name', 'Unknown').strip()}\n")
            f.write(f"\timage: image{idx}\n")
            f.write(f"\tsuper_type: <word-list-type>{card.get('supertype', card.get('type', ''))}</word-list-type>\n")
            f.write(f"\tsub_type: <word-list-type>{card.get('subtype', '')}</word-list-type>\n")
            f.write(f"\tcasting_cost: {casting_cost}\n")
            f.write(f"\trule_text:\n\t\t{rule_text}\n")
            f.write(f"\tflavor_text: <i-flavor>{card.get('flavor_text', '').strip()}</i-flavor>\n")
            f.write(f"\tpower: {card.get('power', '')}\n")
            f.write(f"\ttoughness: {card.get('toughness', '')}\n")
            f.write(f"\tloyalty: {card.get('loyalty', '')}\n")
            f.write(f"\tillustrator: {card.get('artist_credit', 'AI Generated')}\n")
            f.write(f"\trarity: {card.get('rarity', 'common').lower()}\n")


def create_mse_set(
    cards: list[dict],
    output_dir: Path,
    set_name: str = "artgen_set",
) -> Path:
    """
    Create an MSE set file (.mse-set) from card data.
    
    Args:
        cards: List of card dictionaries
        output_dir: Directory to create the set in
        set_name: Name of the set
        
    Returns:
        Path to the created .mse-set file
    """
    # Create temp directory for MSE set contents
    msegen_dir = output_dir / "msegen" / set_name
    msegen_dir.mkdir(parents=True, exist_ok=True)
    
    # Write the set file
    write_mse_set_file(cards, msegen_dir / "set", set_name)
    
    # Copy card images
    for idx, card in enumerate(cards):
        image_path = card.get('image_path')
        if image_path and Path(image_path).exists():
            # MSE expects images without extension
            dest_path = msegen_dir / f"image{idx}"
            shutil.copy2(image_path, dest_path)
    
    # Create the .mse-set ZIP file
    mse_set_path = output_dir / f"{set_name}.mse-set"
    with zipfile.ZipFile(mse_set_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(msegen_dir):
            for file in files:
                file_path = Path(root) / file
                # Archive path is relative to msegen_dir
                arc_path = file_path.relative_to(msegen_dir)
                zipf.write(file_path, arc_path)
    
    return mse_set_path


def run_mse_export(
    mse_set_path: Path,
    output_dir: Path,
    mse_exe_path: Path = DEFAULT_MSE_PATH,
) -> list[Path]:
    """
    Run MSE to export card images.
    
    Args:
        mse_set_path: Path to the .mse-set file
        output_dir: Directory to export images to
        mse_exe_path: Path to mse.exe
        
    Returns:
        List of exported image paths
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Run MSE via wine
    cmd = ["wine", str(mse_exe_path), "--export-images", str(mse_set_path)]
    
    # Run from output directory so images are exported there
    result = subprocess.run(
        cmd,
        cwd=output_dir,
        capture_output=True,
        text=True,
    )
    
    # Collect exported images
    exported = list(output_dir.glob("*.png"))
    return exported


@register_executor("render_mse_cards")
class RenderMSECardsExecutor(StepExecutor):
    """
    Render Magic cards using Magic Set Editor.
    
    This executor gathers card data from previous pipeline steps
    and renders full card images using MSE.
    """
    
    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute MSE card rendering.
        
        Config:
            mse_path: Path to MSE executable (default: ~/Installs/M15-Magic-Pack/mse.exe)
            set_name: Name for the generated set (default: from pipeline name)
            card_data_step: Step ID containing card JSON (default: critique_and_refine)
            flavor_text_step: Step ID containing flavor text (default: write_flavor_text)
            art_direction_step: Step ID containing art direction (default: generate_art_direction)
            art_step: Step ID containing card art (default: generate_art)
        """
        import time
        start = time.time()
        
        # Get configuration
        mse_path_str = config.get("mse_path", str(DEFAULT_MSE_PATH))
        mse_path = Path(mse_path_str).expanduser()
        set_name = config.get("set_name", ctx.pipeline_name.replace("-", "_"))
        card_data_step = config.get("card_data_step", "critique_and_refine")
        flavor_text_step = config.get("flavor_text_step", "write_flavor_text")
        art_direction_step = config.get("art_direction_step", "generate_art_direction")
        art_step = config.get("art_step", "generate_art")
        
        # Verify MSE is available
        if not mse_path.exists():
            return StepResult(
                success=False,
                error=f"MSE not found at {mse_path}. Install M15-Magic-Pack from https://github.com/MagicSetEditorPacks/M15-Magic-Pack",
            )
        
        # Check for wine
        wine_check = subprocess.run(["which", "wine"], capture_output=True)
        if wine_check.returncode != 0:
            return StepResult(
                success=False,
                error="Wine is not installed. Install with: sudo apt install wine",
            )
        
        # Gather card data from all assets
        cards = []
        step_id = config.get("_step_id", "render_mse_cards")
        
        # We need to iterate through all assets in the pipeline
        # The assets should be available via the context or we load from state
        state_dir = ctx.state_dir
        
        # Find all cards by looking at the card_data_step output directories
        card_data_dir = state_dir / card_data_step
        if not card_data_dir.exists():
            return StepResult(
                success=False,
                error=f"Card data not found. Run {card_data_step} step first.",
            )
        
        # Process each card
        for card_dir in sorted(card_data_dir.iterdir()):
            if not card_dir.is_dir():
                continue
            
            asset_id = card_dir.name
            
            # Load card JSON from card_data_step
            card_json_path = card_dir / "output.json"
            if not card_json_path.exists():
                continue
            
            with open(card_json_path) as f:
                card_output = json.load(f)
            
            # Extract the actual card data (may be in markdown code block)
            card_content = card_output.get("data", {}).get("content", "")
            card_data = extract_json_from_content(card_content)
            
            if not card_data:
                print(f"Warning: Could not parse card JSON for {asset_id}")
                continue
            
            # Load flavor text
            flavor_path = state_dir / flavor_text_step / asset_id / "output.json"
            if flavor_path.exists():
                with open(flavor_path) as f:
                    flavor_output = json.load(f)
                card_data["flavor_text"] = flavor_output.get("data", {}).get("content", "")
            
            # Load art direction for artist credit
            art_dir_path = state_dir / art_direction_step / asset_id / "output.json"
            if art_dir_path.exists():
                with open(art_dir_path) as f:
                    art_dir_output = json.load(f)
                art_direction = art_dir_output.get("data", {}).get("content", "")
                card_data["artist_credit"] = extract_artist_credit(art_direction)
            
            # Load art image path
            art_output_path = state_dir / art_step / asset_id / "output.json"
            if art_output_path.exists():
                with open(art_output_path) as f:
                    art_output = json.load(f)
                paths = art_output.get("data", {}).get("paths", [])
                if paths:
                    art_path = Path(paths[0])
                    
                    # Try multiple path resolution strategies
                    resolved_path = None
                    candidates = [
                        art_path,  # Absolute or as-is
                        ctx.base_path / art_path,  # Relative to pipeline dir
                        ctx.base_path.parent / art_path,  # Relative to parent (for ../pipelines/... paths)
                        state_dir / art_path,  # Relative to state dir
                        ctx.base_path / ".artgen" / art_path.name if art_path.name else None,  # Just filename in state
                    ]
                    
                    # Also try direct path from generate_image step if paths look like state paths
                    if ".artgen" in str(art_path) or "generate_image" in str(art_path):
                        # Extract just the relative state path
                        path_parts = str(art_path).split(".artgen/")
                        if len(path_parts) > 1:
                            candidates.append(state_dir / path_parts[1])
                    
                    for candidate in candidates:
                        if candidate and candidate.exists():
                            resolved_path = candidate
                            break
                    
                    if resolved_path:
                        card_data["image_path"] = str(resolved_path)
            
            cards.append(card_data)
        
        if not cards:
            return StepResult(
                success=False,
                error="No cards found to render. Ensure previous steps have completed.",
            )
        
        # Create output directory
        output_dir = state_dir / step_id
        output_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Create MSE set
            mse_set_path = create_mse_set(cards, output_dir, set_name)
            
            # Export card images
            cards_output_dir = output_dir / "cards"
            exported_images = run_mse_export(mse_set_path, cards_output_dir, mse_path)
            
            duration = int((time.time() - start) * 1000)
            
            return StepResult(
                success=True,
                output={
                    "mse_set": str(mse_set_path),
                    "cards_rendered": len(exported_images),
                    "card_paths": [str(p) for p in exported_images],
                },
                output_paths=exported_images,
                duration_ms=duration,
            )
            
        except Exception as e:
            return StepResult(
                success=False,
                error=f"MSE rendering failed: {str(e)}",
            )
