"""
Test MSE Card Rendering.

Run: python -m pytest tests/test_mse_executor.py -v
Or directly: python tests/test_mse_executor.py
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


# Test data directory - uses existing mtg-generator output
MTG_STATE_DIR = Path(__file__).parent.parent.parent / "pipelines" / "mtg-generator" / ".artgen"
MSE_PATH = Path.home() / "Installs" / "M15-Magic-Pack" / "mse.exe"


def has_test_data():
    """Check if we have the mtg-generator output to test with."""
    return (MTG_STATE_DIR / "critique_and_refine").exists()


def has_mse():
    """Check if MSE is installed."""
    return MSE_PATH.exists()


def has_wine():
    """Check if Wine is installed."""
    result = subprocess.run(["which", "wine"], capture_output=True)
    return result.returncode == 0


@pytest.fixture
def output_dir(tmp_path):
    """Create a temp output directory."""
    return tmp_path / "mse_output"


class TestMSEDataCollection:
    """Test gathering card data for MSE rendering."""
    
    @pytest.mark.skipif(not has_test_data(), reason="No mtg-generator data")
    def test_finds_card_data(self):
        """Should find card data from critique_and_refine step."""
        card_data_dir = MTG_STATE_DIR / "critique_and_refine"
        
        cards = list(card_data_dir.iterdir())
        assert len(cards) > 0, "Should find at least one card"
        
        # Check first card has output.json
        for card_dir in cards:
            if card_dir.is_dir():
                output_json = card_dir / "output.json"
                assert output_json.exists(), f"Card {card_dir.name} should have output.json"
                break
    
    @pytest.mark.skipif(not has_test_data(), reason="No mtg-generator data")
    def test_parses_card_json(self):
        """Should parse card JSON from markdown code blocks."""
        from pipeline.executors.mse import extract_json_from_content
        
        # Load a real card
        card_dirs = [d for d in (MTG_STATE_DIR / "critique_and_refine").iterdir() if d.is_dir()]
        assert len(card_dirs) > 0
        
        with open(card_dirs[0] / "output.json") as f:
            output = json.load(f)
        
        content = output.get("data", {}).get("content", "")
        card_data = extract_json_from_content(content)
        
        assert card_data is not None, "Should parse card JSON"
        assert "name" in card_data, "Card should have name"
        assert "mana_cost" in card_data or "casting_cost" in card_data, "Card should have cost"
    
    @pytest.mark.skipif(not has_test_data(), reason="No mtg-generator data")
    def test_finds_art_images(self):
        """Should find art images for cards."""
        art_dir = MTG_STATE_DIR / "generate_art"
        
        if not art_dir.exists():
            pytest.skip("No generate_art data")
        
        for card_dir in art_dir.iterdir():
            if not card_dir.is_dir():
                continue
            
            output_json = card_dir / "output.json"
            if not output_json.exists():
                continue
            
            with open(output_json) as f:
                output = json.load(f)
            
            paths = output.get("data", {}).get("paths", [])
            assert len(paths) > 0, f"Card {card_dir.name} should have art paths"
            
            # Check path exists (relative to backend dir)
            art_path = Path(paths[0])
            assert art_path.exists(), f"Art should exist at {art_path}"
            break
    
    @pytest.mark.skipif(not has_test_data(), reason="No mtg-generator data")
    def test_extracts_artist_credit(self):
        """Should extract artist credit from art direction."""
        from pipeline.executors.mse import extract_artist_credit
        
        art_dir = MTG_STATE_DIR / "generate_art_direction"
        if not art_dir.exists():
            pytest.skip("No generate_art_direction data")
        
        for card_dir in art_dir.iterdir():
            if not card_dir.is_dir():
                continue
            
            output_json = card_dir / "output.json"
            if not output_json.exists():
                continue
            
            with open(output_json) as f:
                output = json.load(f)
            
            content = output.get("data", {}).get("content", "")
            artist = extract_artist_credit(content)
            
            assert artist, "Should extract artist credit"
            assert artist != "AI Generated" or "Artist Credit" not in content
            break


class TestMSESetGeneration:
    """Test MSE set file generation."""
    
    def test_writes_set_file(self, output_dir):
        """Should write valid MSE set file."""
        from pipeline.executors.mse import write_mse_set_file
        
        output_dir.mkdir(parents=True)
        
        cards = [
            {
                "name": "Test Card",
                "supertype": "Creature",
                "subtype": "Human Warrior",
                "mana_cost": "{1}{W}",
                "power": "2",
                "toughness": "2",
                "rule_text": "First strike",
                "flavor_text": "A test card.",
                "rarity": "common",
                "artist_credit": "Test Artist",
            }
        ]
        
        set_file = output_dir / "set"
        write_mse_set_file(cards, set_file, "test_set")
        
        assert set_file.exists()
        content = set_file.read_text()
        
        assert "mse_version:" in content
        assert "Test Card" in content
        assert "First strike" in content
        assert "Test Artist" in content
    
    def test_formats_mana_symbols(self, output_dir):
        """Should convert mana symbols to MSE format."""
        from pipeline.executors.mse import write_mse_set_file
        
        output_dir.mkdir(parents=True)
        
        cards = [
            {
                "name": "Mana Test",
                "supertype": "Instant",
                "subtype": "",
                "mana_cost": "{2}{U}{U}",
                "rule_text": "{T}: Add {G}. Sacrifice: Add {B}{B}.",
                "rarity": "rare",
            }
        ]
        
        set_file = output_dir / "set"
        write_mse_set_file(cards, set_file, "test_set")
        
        content = set_file.read_text()
        
        # Mana cost should have braces stripped
        assert "casting_cost: 2UU" in content
        
        # Rule text should use <sym> tags
        assert "<sym>T</sym>" in content
        assert "<sym>G</sym>" in content
        assert "<sym>B</sym>" in content


@pytest.mark.skipif(not has_mse(), reason="MSE not installed")
@pytest.mark.skipif(not has_wine(), reason="Wine not installed")
@pytest.mark.skipif(not has_test_data(), reason="No mtg-generator data")
class TestMSEExport:
    """Test actual MSE export (requires MSE + Wine)."""
    
    def test_creates_mse_set_zip(self, output_dir):
        """Should create valid .mse-set zip file."""
        from pipeline.executors.mse import create_mse_set
        
        # Gather one card
        cards = []
        card_data_dir = MTG_STATE_DIR / "critique_and_refine"
        
        for card_dir in sorted(card_data_dir.iterdir()):
            if not card_dir.is_dir():
                continue
            
            from pipeline.executors.mse import extract_json_from_content
            
            with open(card_dir / "output.json") as f:
                output = json.load(f)
            
            content = output.get("data", {}).get("content", "")
            card_data = extract_json_from_content(content)
            
            if card_data:
                # Get art
                art_output = MTG_STATE_DIR / "generate_art" / card_dir.name / "output.json"
                if art_output.exists():
                    with open(art_output) as f:
                        paths = json.load(f).get("data", {}).get("paths", [])
                    if paths and Path(paths[0]).exists():
                        card_data["image_path"] = str(Path(paths[0]).resolve())
                
                cards.append(card_data)
                break  # Just one card for test
        
        assert len(cards) == 1
        
        output_dir.mkdir(parents=True)
        mse_set = create_mse_set(cards, output_dir, "test_export")
        
        assert mse_set.exists()
        assert mse_set.suffix == ".mse-set"
        assert mse_set.stat().st_size > 1000  # Should be substantial with image
    
    def test_exports_card_images(self, output_dir):
        """Should export card images via MSE."""
        from pipeline.executors.mse import create_mse_set, run_mse_export, extract_json_from_content
        
        # Gather cards with images
        cards = []
        card_data_dir = MTG_STATE_DIR / "critique_and_refine"
        
        for card_dir in sorted(card_data_dir.iterdir()):
            if not card_dir.is_dir():
                continue
            
            with open(card_dir / "output.json") as f:
                output = json.load(f)
            
            content = output.get("data", {}).get("content", "")
            card_data = extract_json_from_content(content)
            
            if not card_data:
                continue
            
            # Get art
            art_output = MTG_STATE_DIR / "generate_art" / card_dir.name / "output.json"
            if art_output.exists():
                with open(art_output) as f:
                    paths = json.load(f).get("data", {}).get("paths", [])
                if paths and Path(paths[0]).exists():
                    card_data["image_path"] = str(Path(paths[0]).resolve())
                    cards.append(card_data)
            
            if len(cards) >= 2:  # Test with 2 cards
                break
        
        assert len(cards) >= 1, "Need at least one card with art"
        
        output_dir.mkdir(parents=True)
        mse_set = create_mse_set(cards, output_dir, "test_export")
        
        cards_dir = output_dir / "cards"
        exported = run_mse_export(mse_set, cards_dir, MSE_PATH)
        
        assert len(exported) == len(cards), f"Should export {len(cards)} cards"
        
        for png in exported:
            assert png.suffix == ".png"
            assert png.stat().st_size > 10000  # Should be real images


def run_quick_test():
    """Run a quick manual test of MSE rendering."""
    print("=== Quick MSE Test ===\n")
    
    if not has_test_data():
        print("SKIP: No mtg-generator data found")
        print(f"  Expected: {MTG_STATE_DIR}")
        return
    
    if not has_mse():
        print("SKIP: MSE not installed")
        print(f"  Expected: {MSE_PATH}")
        return
    
    if not has_wine():
        print("SKIP: Wine not installed")
        return
    
    from pipeline.executors.mse import (
        extract_json_from_content,
        extract_artist_credit,
        create_mse_set,
        run_mse_export,
    )
    
    # Gather cards
    print("Gathering cards...")
    cards = []
    card_data_dir = MTG_STATE_DIR / "critique_and_refine"
    
    for card_dir in sorted(card_data_dir.iterdir()):
        if not card_dir.is_dir():
            continue
        
        with open(card_dir / "output.json") as f:
            output = json.load(f)
        
        content = output.get("data", {}).get("content", "")
        card_data = extract_json_from_content(content)
        
        if not card_data:
            continue
        
        # Flavor text
        flavor_path = MTG_STATE_DIR / "write_flavor_text" / card_dir.name / "output.json"
        if flavor_path.exists():
            with open(flavor_path) as f:
                card_data["flavor_text"] = json.load(f).get("data", {}).get("content", "")
        
        # Artist credit
        art_dir_path = MTG_STATE_DIR / "generate_art_direction" / card_dir.name / "output.json"
        if art_dir_path.exists():
            with open(art_dir_path) as f:
                art_direction = json.load(f).get("data", {}).get("content", "")
            card_data["artist_credit"] = extract_artist_credit(art_direction)
        
        # Art image
        art_output = MTG_STATE_DIR / "generate_art" / card_dir.name / "output.json"
        if art_output.exists():
            with open(art_output) as f:
                paths = json.load(f).get("data", {}).get("paths", [])
            if paths and Path(paths[0]).exists():
                card_data["image_path"] = str(Path(paths[0]).resolve())
        
        cards.append(card_data)
    
    print(f"Found {len(cards)} cards:")
    for c in cards:
        has_img = "image_path" in c
        print(f"  - {c.get('name')}: {'with art' if has_img else 'NO ART'}")
    
    if not cards:
        print("\nNo cards found!")
        return
    
    # Create MSE set
    output_dir = Path("/tmp/mse_quick_test")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir()
    
    print(f"\nCreating MSE set...")
    mse_set = create_mse_set(cards, output_dir, "quick_test")
    print(f"  Created: {mse_set}")
    print(f"  Size: {mse_set.stat().st_size:,} bytes")
    
    # Export
    print(f"\nRunning MSE export...")
    cards_dir = output_dir / "cards"
    exported = run_mse_export(mse_set, cards_dir, MSE_PATH)
    
    print(f"\nExported {len(exported)} card images:")
    for png in exported:
        print(f"  - {png.name} ({png.stat().st_size:,} bytes)")
    
    print(f"\nOutput directory: {output_dir}")
    print("SUCCESS!")


if __name__ == "__main__":
    run_quick_test()
