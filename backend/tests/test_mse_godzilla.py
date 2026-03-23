"""
Test Godzilla Name Bar support for MSE card rendering.

The Godzilla name bar (from MSE's m15-godzilla stylesheet) renders cards with:
  - A prominent alternate name in the main title bar (the "name" field)
  - The real card name in a smaller alias bar underneath (the "alias" field)

For the bird deck, this means:
  - name = "Northern Goshawk" (the bird species)
  - alias = "Aven Mindcensor" (the real MTG card name)

Run: python -m pytest tests/test_mse_godzilla.py -v
"""

import json
import re
from pathlib import Path

import pytest

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Real bird deck data (copied from examples/bird_deck/.artgen/)
# ---------------------------------------------------------------------------

SUGGEST_BIRD_NAME_OUTPUTS = {
    "baleful-strix": {
        "data": {
            "content": (
                "BIRD: Black-banded Owl\n"
                "RATIONALE: This nocturnal owl's dark, barred plumage perfectly captures "
                "the shadowy colors and mystery associated with Baleful Strix."
            ),
        },
    },
    "aven-mindcensor": {
        "data": {
            "content": (
                "BIRD: Northern Goshawk\n"
                "RATIONALE: The Northern Goshawk is a formidable and highly agile predator "
                "renowned for its relentless pursuit through dense environments."
            ),
        },
    },
    "birds-of-paradise": {
        "data": {
            "content": (
                "BIRD: Raggiana Bird-of-paradise\n"
                "RATIONALE: The Raggiana Bird-of-paradise is famed for its spectacular "
                "and diverse plumage."
            ),
        },
    },
}

CARD_STATS = {
    "baleful-strix": {
        "mana_cost": "{U}{B}",
        "type_line": "Artifact Creature \u2014 Bird",
        "oracle_text": "Flying, deathtouch\nWhen this creature enters, draw a card.",
        "power": "1",
        "toughness": "1",
        "rarity": "rare",
    },
    "aven-mindcensor": {
        "mana_cost": "{2}{W}",
        "type_line": "Creature \u2014 Bird Wizard",
        "oracle_text": (
            "Flash\nFlying\nIf an opponent would search a library, "
            "that player searches the top four cards of that library instead."
        ),
        "power": "2",
        "toughness": "1",
        "rarity": "uncommon",
    },
    "birds-of-paradise": {
        "mana_cost": "{G}",
        "type_line": "Creature \u2014 Bird",
        "oracle_text": "Flying\n{T}: Add one mana of any color.",
        "power": "0",
        "toughness": "1",
        "rarity": "rare",
    },
}


# ---------------------------------------------------------------------------
# Tests: Name extraction
# ---------------------------------------------------------------------------

class TestExtractNameFromStep:
    """Test extracting an alternate name from a pipeline step's output content."""

    def test_extracts_bird_name_default_pattern(self):
        """The default BIRD: pattern should pull out the species name."""
        from pipeline.executors.mse import extract_name_from_step_content

        content = SUGGEST_BIRD_NAME_OUTPUTS["aven-mindcensor"]["data"]["content"]
        name = extract_name_from_step_content(content)

        assert name == "Northern Goshawk"

    def test_extracts_hyphenated_bird_name(self):
        """Should handle hyphenated names like 'Bird-of-paradise'."""
        from pipeline.executors.mse import extract_name_from_step_content

        content = SUGGEST_BIRD_NAME_OUTPUTS["birds-of-paradise"]["data"]["content"]
        name = extract_name_from_step_content(content)

        assert name == "Raggiana Bird-of-paradise"

    def test_extracts_with_custom_pattern(self):
        """A custom regex pattern should work for non-bird pipelines."""
        from pipeline.executors.mse import extract_name_from_step_content

        content = "ALTERNATE NAME: Optimus Prime\nDESCRIPTION: A cool robot."
        name = extract_name_from_step_content(
            content, pattern=r"ALTERNATE NAME:\s*(.+)"
        )

        assert name == "Optimus Prime"

    def test_returns_none_when_no_match(self):
        """Should return None when the pattern doesn't match."""
        from pipeline.executors.mse import extract_name_from_step_content

        name = extract_name_from_step_content("No bird here, just vibes.")
        assert name is None

    def test_strips_whitespace(self):
        """Should strip leading/trailing whitespace from the extracted name."""
        from pipeline.executors.mse import extract_name_from_step_content

        name = extract_name_from_step_content("BIRD:   Snowy Owl   \nRATIONALE: ...")
        assert name == "Snowy Owl"


# ---------------------------------------------------------------------------
# Tests: Godzilla set file generation
# ---------------------------------------------------------------------------

class TestGodzillaSetFile:
    """Test that the MSE set file uses the Godzilla stylesheet and alias field."""

    def _build_godzilla_cards(self) -> list[dict]:
        """Build card dicts the way the executor would for Godzilla mode."""
        cards = []
        for asset_id, stats in CARD_STATS.items():
            bird_content = SUGGEST_BIRD_NAME_OUTPUTS[asset_id]["data"]["content"]
            # Extract bird name
            match = re.search(r"BIRD:\s*(.+)", bird_content)
            bird_name = match.group(1).strip() if match else "Unknown Bird"

            original_name = asset_id.replace("-", " ").title()

            type_line = stats["type_line"]
            if " \u2014 " in type_line:
                supertype, subtype = type_line.split(" \u2014 ", 1)
            else:
                supertype, subtype = type_line, ""

            cards.append({
                "name": bird_name,
                "alias": original_name,
                "supertype": supertype.strip(),
                "subtype": subtype.strip(),
                "mana_cost": stats["mana_cost"],
                "rule_text": stats["oracle_text"],
                "power": stats["power"],
                "toughness": stats["toughness"],
                "rarity": stats["rarity"],
            })
        return cards

    def test_uses_godzilla_stylesheet(self, tmp_path):
        """The set file should declare the m15-godzilla stylesheet."""
        from pipeline.executors.mse import write_mse_set_file

        cards = self._build_godzilla_cards()
        set_file = tmp_path / "set"
        write_mse_set_file(cards, set_file, "test_set", stylesheet="m15-godzilla")

        content = set_file.read_text()
        assert "stylesheet: m15-godzilla" in content
        assert "magic-m15-godzilla:" in content

    def test_does_not_use_altered_stylesheet(self, tmp_path):
        """Godzilla mode should NOT reference the m15-altered stylesheet."""
        from pipeline.executors.mse import write_mse_set_file

        cards = self._build_godzilla_cards()
        set_file = tmp_path / "set"
        write_mse_set_file(cards, set_file, "test_set", stylesheet="m15-godzilla")

        content = set_file.read_text()
        assert "m15-altered" not in content

    def test_writes_alias_field(self, tmp_path):
        """Each card should have an alias: line with the real MTG card name."""
        from pipeline.executors.mse import write_mse_set_file

        cards = self._build_godzilla_cards()
        set_file = tmp_path / "set"
        write_mse_set_file(cards, set_file, "test_set", stylesheet="m15-godzilla")

        content = set_file.read_text()

        assert "\talias: Baleful Strix" in content
        assert "\talias: Aven Mindcensor" in content
        assert "\talias: Birds Of Paradise" in content

    def test_name_is_bird_not_original(self, tmp_path):
        """The name: field should be the bird species, not the MTG card name."""
        from pipeline.executors.mse import write_mse_set_file

        cards = self._build_godzilla_cards()
        set_file = tmp_path / "set"
        write_mse_set_file(cards, set_file, "test_set", stylesheet="m15-godzilla")

        content = set_file.read_text()

        assert "\tname: Black-banded Owl" in content
        assert "\tname: Northern Goshawk" in content
        assert "\tname: Raggiana Bird-of-paradise" in content

    def test_no_alias_when_not_godzilla(self, tmp_path):
        """Standard m15-altered cards should NOT have alias lines."""
        from pipeline.executors.mse import write_mse_set_file

        cards = [{"name": "Test Card", "supertype": "Creature", "subtype": "",
                   "mana_cost": "{W}", "rule_text": "", "rarity": "common"}]
        set_file = tmp_path / "set"
        write_mse_set_file(cards, set_file, "test_set")

        content = set_file.read_text()
        assert "alias:" not in content

    def test_godzilla_frame_tall(self, tmp_path):
        """The 'tall' frame option should appear in styling."""
        from pipeline.executors.mse import write_mse_set_file

        cards = self._build_godzilla_cards()[:1]
        set_file = tmp_path / "set"
        write_mse_set_file(
            cards, set_file, "test_set",
            stylesheet="m15-godzilla", godzilla_frame="tall",
        )

        content = set_file.read_text()
        assert "frame_options: tall" in content

    def test_godzilla_frame_default_no_frame_option(self, tmp_path):
        """Without a frame variant, no frame_options line should appear."""
        from pipeline.executors.mse import write_mse_set_file

        cards = self._build_godzilla_cards()[:1]
        set_file = tmp_path / "set"
        write_mse_set_file(
            cards, set_file, "test_set", stylesheet="m15-godzilla",
        )

        content = set_file.read_text()
        assert "frame_options" not in content


# ---------------------------------------------------------------------------
# Tests: Full card assembly (integration-style, uses real bird_deck data)
# ---------------------------------------------------------------------------

BIRD_DECK_STATE_DIR = (
    Path(__file__).parent.parent.parent
    / "examples" / "bird_deck" / ".artgen"
)


def has_bird_deck_data():
    return (BIRD_DECK_STATE_DIR / "suggest_bird_name").exists()


@pytest.mark.skipif(not has_bird_deck_data(), reason="No bird_deck data")
class TestGodzillaBirdDeckIntegration:
    """Integration test using actual bird_deck pipeline output."""

    def test_builds_godzilla_cards_from_bird_deck(self):
        """Should assemble cards with bird name as name and MTG name as alias."""
        from pipeline.executors.mse import extract_name_from_step_content

        name_step_dir = BIRD_DECK_STATE_DIR / "suggest_bird_name"

        for asset_dir in sorted(name_step_dir.iterdir()):
            if not asset_dir.is_dir():
                continue

            with open(asset_dir / "output.json") as f:
                output = json.load(f)

            content = output["data"]["content"]
            bird_name = extract_name_from_step_content(content)

            assert bird_name is not None, f"Should extract bird name for {asset_dir.name}"
            assert len(bird_name) > 2, f"Bird name too short: {bird_name!r}"
            assert "RATIONALE" not in bird_name, "Should not include rationale text"

    def test_generates_full_godzilla_set_file(self):
        """Should generate a complete Godzilla-style set file from bird deck data."""
        from pipeline.executors.mse import (
            extract_name_from_step_content,
            write_mse_set_file,
        )

        cards = []
        name_step_dir = BIRD_DECK_STATE_DIR / "suggest_bird_name"
        stats_step_dir = BIRD_DECK_STATE_DIR / "fetch_card_stats"

        for asset_dir in sorted(name_step_dir.iterdir()):
            if not asset_dir.is_dir():
                continue

            asset_id = asset_dir.name
            original_name = asset_id.replace("-", " ").title()

            # Bird name from suggest_bird_name
            with open(asset_dir / "output.json") as f:
                bird_content = json.load(f)["data"]["content"]
            bird_name = extract_name_from_step_content(bird_content)

            # Stats from fetch_card_stats
            stats_file = stats_step_dir / asset_id / "output.json"
            if not stats_file.exists():
                continue
            with open(stats_file) as f:
                stats = json.load(f)["data"]

            type_line = stats.get("type_line", "")
            if " \u2014 " in type_line:
                supertype, subtype = type_line.split(" \u2014 ", 1)
            else:
                supertype, subtype = type_line, ""

            cards.append({
                "name": bird_name,
                "alias": original_name,
                "supertype": supertype.strip(),
                "subtype": subtype.strip(),
                "mana_cost": stats.get("mana_cost", ""),
                "rule_text": stats.get("oracle_text", ""),
                "power": stats.get("power", ""),
                "toughness": stats.get("toughness", ""),
                "rarity": stats.get("rarity", "common"),
            })

        assert len(cards) >= 3, "Should find all 3 bird deck cards"

        output_dir = BIRD_DECK_STATE_DIR / "test_godzilla_output"
        output_dir.mkdir(parents=True, exist_ok=True)
        set_file = output_dir / "set"

        write_mse_set_file(
            cards, set_file, "aviary_of_the_ancients", stylesheet="m15-godzilla",
        )

        content = set_file.read_text()

        # Stylesheet
        assert "stylesheet: m15-godzilla" in content

        # Each card should have bird name as name and MTG name as alias
        for card in cards:
            assert f"\tname: {card['name']}" in content
            assert f"\talias: {card['alias']}" in content

        print(f"\n{'='*60}")
        print(f"GODZILLA SET FILE written to:")
        print(f"  {set_file}")
        print(f"Manually inspect with:  cat {set_file}")
        print(f"{'='*60}")
