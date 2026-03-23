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


def get_nested_value(data: dict, path: str) -> Any | None:
    """Resolve a dot-separated path against a nested dict.

    >>> get_nested_value({"a": {"b": "hello"}}, "a.b")
    'hello'
    """
    current: Any = data
    for key in path.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


GODZILLA_STYLESHEET = "m15-godzilla"
GODZILLA_STYLESHEET_VERSION = "2024-06-06"

STYLESHEET_HEADERS: dict[str, dict[str, str]] = {
    "m15-altered": {
        "stylesheet": "m15-altered",
        "stylesheet_version": "2020-09-04",
        "styling_key": "magic-m15-altered",
        "styling_body": (
            "\t\tother_options: auto vehicles, auto nyx crowns\n"
            "\t\ttext_box_mana_symbols: magic-mana-small.mse-symbol-font\n"
            "\t\tlevel_mana_symbols: magic-mana-large.mse-symbol-font\n"
            "\t\toverlay:\n"
        ),
    },
    "m15-godzilla": {
        "stylesheet": "m15-godzilla",
        "stylesheet_version": "2024-06-06",
        "styling_key": "magic-m15-godzilla",
        "styling_body": (
            "\t\ttext_box_mana_symbols: magic-mana-small.mse-symbol-font\n"
            "\t\toverlay:\n"
        ),
    },
}


def write_mse_set_file(
    cards: list[dict],
    filepath: Path,
    set_name: str = "artgen_set",
    stylesheet: str = "m15-altered",
    godzilla_frame: str | None = None,
    godzilla_alias: bool = False,
):
    """
    Write an MSE set file with card data.
    
    Args:
        cards: List of card dictionaries with all card data
        filepath: Path to write the set file
        set_name: Name of the set
        stylesheet: MSE stylesheet to use (e.g. "m15-altered", "m15-godzilla")
        godzilla_frame: Frame variant for Godzilla style — "tall", "short", or None
            for regular (Mothra-style). Only used when stylesheet is "m15-godzilla".
        godzilla_alias: When True and using "m15-altered", enable the
            "godzilla style alias" option so the alias field renders as a
            name bar below the card title.
    """
    header = STYLESHEET_HEADERS.get(stylesheet, STYLESHEET_HEADERS["m15-altered"])

    with open(filepath, 'w', encoding='utf-8') as f:
        # MSE set header
        f.write("mse_version: 2.0.2\n")
        f.write("game: magic\n")
        f.write("game_version: 2020-04-25\n")
        f.write(f"stylesheet: {header['stylesheet']}\n")
        f.write(f"stylesheet_version: {header['stylesheet_version']}\n")
        f.write("set_info:\n")
        f.write(f"\ttitle: {set_name}\n")
        f.write("\tsymbol:\n")
        f.write("\tmasterpiece_symbol:\n")
        f.write("styling:\n")
        f.write(f"\t{header['styling_key']}:\n")

        if stylesheet == GODZILLA_STYLESHEET and godzilla_frame in ("tall", "short"):
            f.write(f"\t\tframe_options: {godzilla_frame}\n")

        styling_body = header["styling_body"]
        if godzilla_alias and "other_options:" in styling_body:
            styling_body = styling_body.replace(
                "other_options:", "other_options: godzilla style alias,", 1
            )

        f.write(styling_body)
        
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

            alias = card.get('alias', '')
            if alias:
                f.write(f"\talias: {alias.strip()}\n")

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
    stylesheet: str = "m15-altered",
    godzilla_frame: str | None = None,
    godzilla_alias: bool = False,
) -> Path:
    """
    Create an MSE set file (.mse-set) from card data.
    
    Args:
        cards: List of card dictionaries
        output_dir: Directory to create the set in
        set_name: Name of the set
        stylesheet: MSE stylesheet to use
        godzilla_frame: Frame variant for Godzilla style
        godzilla_alias: Enable the Godzilla alias name bar on m15-altered
        
    Returns:
        Path to the created .mse-set file
    """
    # Create temp directory for MSE set contents
    msegen_dir = output_dir / "msegen" / set_name
    msegen_dir.mkdir(parents=True, exist_ok=True)
    
    # Write the set file
    write_mse_set_file(cards, msegen_dir / "set", set_name, stylesheet, godzilla_frame, godzilla_alias)
    
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
            stylesheet: MSE stylesheet to use (default: "m15-altered").
                Use "m15-godzilla" for the Godzilla name bar frame.
            godzilla_frame: Frame variant for Godzilla style — "tall", "short",
                or omit for regular (Mothra-style).
            godzilla_alias: Explicitly enable/disable the Godzilla alias name
                bar on the m15-altered stylesheet. Defaults to True when
                name_field is set.
            name_field: Dot-path into the asset dict for an alternate display name
                (e.g. "bird_name.bird").  When set, the original asset name is
                moved to the ``alias`` field (the small Godzilla sub-bar) and
                the resolved value becomes the card's main ``name``.
            card_data_step: Step ID containing card JSON (optional — falls back to assets)
            stats_field: Asset field containing a dict of card stats to merge (e.g. "card_stats").
                When set, the named field's dict values act as fallbacks for top-level asset fields.
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
        stylesheet = config.get("stylesheet", "m15-altered")
        godzilla_frame = config.get("godzilla_frame")
        name_field = config.get("name_field")
        godzilla_alias = config.get("godzilla_alias")
        if godzilla_alias is None:
            godzilla_alias = bool(name_field)
        card_data_step = config.get("card_data_step")
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
        card_asset_ids: list[str] = []  # parallel to cards, for output manifest
        step_id = config.get("_step_id", "render_mse_cards")
        state_dir = ctx.state_dir
        
        # Determine card data source: step output directory or pipeline assets
        card_data_dir = state_dir / card_data_step if card_data_step else None
        use_step_data = card_data_dir and card_data_dir.exists()
        
        if use_step_data:
            # Load card data from a previous step's output (e.g. critique_and_refine)
            for card_dir in sorted(card_data_dir.iterdir()):
                if not card_dir.is_dir():
                    continue
                
                asset_id = card_dir.name
                
                card_json_path = card_dir / "output.json"
                if not card_json_path.exists():
                    continue
                
                with open(card_json_path) as f:
                    card_output = json.load(f)
                
                card_content = card_output.get("data", {}).get("content", "")
                card_data = extract_json_from_content(card_content)
                
                if not card_data:
                    print(f"Warning: Could not parse card JSON for {asset_id}")
                    continue
                
                self._enrich_card(card_data, asset_id, state_dir, flavor_text_step, art_direction_step, art_step)
                cards.append(card_data)
                card_asset_ids.append(asset_id)
        else:
            # Build card data directly from pipeline assets (CSV / inline)
            if not ctx.assets:
                source = card_data_step or "assets"
                return StepResult(
                    success=False,
                    error=f"Card data not found. No '{source}' step output and no assets loaded.",
                )
            
            stats_field = config.get("stats_field")

            for asset in ctx.assets:
                asset_id = asset.get("id", "")

                # If a step merged a stats dict onto the asset, overlay it so
                # top-level asset fields still win but the nested dict provides
                # fallback values (e.g. card_stats from a Scryfall lookup).
                effective = dict(asset)
                if stats_field:
                    nested = asset.get(stats_field)
                    if isinstance(nested, dict):
                        for k, v in nested.items():
                            effective.setdefault(k, v)

                card_data = {
                    "name": effective.get("name", "Unknown"),
                    "mana_cost": effective.get("mana_cost", effective.get("casting_cost", "")),
                    "rule_text": effective.get("oracle_text", effective.get("rule_text", "")),
                    "rarity": effective.get("rarity", "common"),
                    "power": effective.get("power", ""),
                    "toughness": effective.get("toughness", ""),
                    "loyalty": effective.get("loyalty", ""),
                }
                
                # Parse type_line into supertype / subtype if available
                type_line = effective.get("type_line", effective.get("type", ""))
                if " — " in type_line:
                    supertype, subtype = type_line.split(" — ", 1)
                    card_data["supertype"] = supertype.strip()
                    card_data["subtype"] = subtype.strip()
                elif " - " in type_line:
                    supertype, subtype = type_line.split(" - ", 1)
                    card_data["supertype"] = supertype.strip()
                    card_data["subtype"] = subtype.strip()
                else:
                    card_data["supertype"] = type_line
                    card_data["subtype"] = ""
                
                self._enrich_card(card_data, asset_id, state_dir, flavor_text_step, art_direction_step, art_step)
                cards.append(card_data)
                card_asset_ids.append(asset_id)
        
        if not cards:
            source = f"step '{card_data_step}'" if card_data_step else "pipeline assets"
            return StepResult(
                success=False,
                error=f"No cards found to render from {source}. Ensure previous steps have completed.",
            )
        
        # Apply alternate name (Godzilla name bar): resolve name_field from
        # the asset, move original name → alias, resolved value → name.
        if name_field:
            for card, asset in zip(cards, ctx.assets or []):
                alt_name = get_nested_value(asset, name_field)
                if alt_name:
                    card["alias"] = card.get("name", "")
                    card["name"] = str(alt_name)
        
        # Create output directory
        output_dir = state_dir / step_id
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create MSE set
        mse_set_path = create_mse_set(cards, output_dir, set_name, stylesheet, godzilla_frame, godzilla_alias)
        
        # Export card images
        cards_output_dir = output_dir / "cards"
        exported_images = run_mse_export(mse_set_path, cards_output_dir, mse_path)

        # When using the Godzilla name bar, MSE names files after the display
        # name (bird) but we want them named after the real MTG card (alias).
        # MSE may strip special characters from filenames, so we normalise
        # both sides for lookup.
        if name_field:
            def _normalise(s: str) -> str:
                return re.sub(r"[^a-zA-Z0-9 -]", "", s).strip().lower()

            alias_by_norm = {
                _normalise(card["name"]): card["alias"]
                for card in cards
                if card.get("alias")
            }
            renamed: list[Path] = []
            for img in exported_images:
                real_name = alias_by_norm.get(_normalise(img.stem))
                if real_name:
                    new_path = img.with_name(f"{real_name}{img.suffix}")
                    img.rename(new_path)
                    renamed.append(new_path)
                else:
                    renamed.append(img)
            exported_images = renamed
        
        duration = int((time.time() - start) * 1000)
        
        # Build asset_map: filename -> asset_id so the output manifest can
        # attribute global-step outputs back to individual assets.
        asset_map: dict[str, str] = {}
        name_to_asset: dict[str, str] = {}
        for i, card in enumerate(cards):
            final_name = card.get("alias", card.get("name", ""))
            if i < len(card_asset_ids):
                name_to_asset[final_name] = card_asset_ids[i]
        for img in exported_images:
            matched = name_to_asset.get(img.stem)
            if matched:
                asset_map[img.name] = matched
        
        return StepResult(
            success=True,
            output={
                "mse_set": str(mse_set_path),
                "cards_rendered": len(exported_images),
                "paths": [str(p) for p in exported_images],
                "asset_map": asset_map,
            },
            output_paths=exported_images,
            duration_ms=duration,
        )
    
    @staticmethod
    def _enrich_card(
        card_data: dict,
        asset_id: str,
        state_dir: Path,
        flavor_text_step: str,
        art_direction_step: str,
        art_step: str,
    ) -> None:
        """Enrich card_data in-place with flavor text, art direction, and image path from step outputs."""
        # Flavor text
        flavor_path = state_dir / flavor_text_step / asset_id / "output.json"
        if flavor_path.exists():
            with open(flavor_path) as f:
                flavor_output = json.load(f)
            card_data["flavor_text"] = flavor_output.get("data", {}).get("content", "")
        
        # Art direction → artist credit
        art_dir_path = state_dir / art_direction_step / asset_id / "output.json"
        if art_dir_path.exists():
            with open(art_dir_path) as f:
                art_dir_output = json.load(f)
            art_direction = art_dir_output.get("data", {}).get("content", "")
            card_data["artist_credit"] = extract_artist_credit(art_direction)
        
        # Card art image path
        art_output_path = state_dir / art_step / asset_id / "output.json"
        if art_output_path.exists():
            with open(art_output_path) as f:
                art_output = json.load(f)
            paths = art_output.get("data", {}).get("paths", [])
            if paths:
                art_path_str = paths[0]
                art_path = Path(art_path_str)
                
                candidates = [
                    art_path if art_path.is_absolute() else None,
                    art_path,
                ]
                
                if ".artgen/" in art_path_str:
                    path_parts = art_path_str.split(".artgen/")
                    if len(path_parts) > 1:
                        candidates.append(state_dir / path_parts[1])
                
                if "generate_image" in art_path_str:
                    parts = art_path_str.split("generate_image/")
                    if len(parts) > 1:
                        candidates.append(state_dir / "generate_image" / parts[1])
                
                candidates.append(state_dir / "generate_image" / asset_id / "v1.png")
                
                for candidate in candidates:
                    if candidate and candidate.exists():
                        card_data["image_path"] = str(candidate.resolve())
                        break
