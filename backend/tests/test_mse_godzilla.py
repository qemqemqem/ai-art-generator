"""
Test Godzilla Name Bar support for MSE card rendering.

The Godzilla name bar (from MSE's m15-godzilla stylesheet) renders cards with:
  - A prominent alternate name in the main title bar (the "name" field)
  - The real card name in a smaller alias bar underneath (the "alias" field)

For the bird deck, this means:
  - name = "Northern Goshawk" (the bird species)
  - alias = "Aven Mindcensor" (the real MTG card name)

The bird name reaches the renderer via structured JSON output from the
suggest_bird_name step (response_format: json), which is merged onto the
asset as ``bird_name``.  The renderer reads it via ``name_field: bird_name.bird``.

Run: python -m pytest tests/test_mse_godzilla.py -v
"""

import json
from pathlib import Path

import pytest

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Sample data (mirrors real bird deck outputs)
# ---------------------------------------------------------------------------

BIRD_NAME_OUTPUTS = {
    "baleful-strix": {"bird": "Black-banded Owl", "rationale": "Nocturnal owl..."},
    "aven-mindcensor": {"bird": "Northern Goshawk", "rationale": "Agile predator..."},
    "birds-of-paradise": {"bird": "Raggiana Bird-of-paradise", "rationale": "Vibrant plumage..."},
}

CARD_STATS = {
    "baleful-strix": {
        "mana_cost": "{U}{B}",
        "type_line": "Artifact Creature \u2014 Bird",
        "oracle_text": "Flying, deathtouch\nWhen this creature enters, draw a card.",
        "power": "1", "toughness": "1", "rarity": "rare",
    },
    "aven-mindcensor": {
        "mana_cost": "{2}{W}",
        "type_line": "Creature \u2014 Bird Wizard",
        "oracle_text": "Flash\nFlying\nIf an opponent would search a library, "
                       "that player searches the top four cards of that library instead.",
        "power": "2", "toughness": "1", "rarity": "uncommon",
    },
    "birds-of-paradise": {
        "mana_cost": "{G}",
        "type_line": "Creature \u2014 Bird",
        "oracle_text": "Flying\n{T}: Add one mana of any color.",
        "power": "0", "toughness": "1", "rarity": "rare",
    },
}


# ---------------------------------------------------------------------------
# Tests: get_nested_value
# ---------------------------------------------------------------------------

class TestGetNestedValue:
    """Test dot-path resolution on nested dicts."""

    def test_single_key(self):
        from pipeline.executors.mse import get_nested_value
        assert get_nested_value({"name": "Baleful Strix"}, "name") == "Baleful Strix"

    def test_nested_path(self):
        from pipeline.executors.mse import get_nested_value
        data = {"bird_name": {"bird": "Northern Goshawk", "rationale": "..."}}
        assert get_nested_value(data, "bird_name.bird") == "Northern Goshawk"

    def test_missing_key_returns_none(self):
        from pipeline.executors.mse import get_nested_value
        assert get_nested_value({"a": 1}, "b") is None

    def test_missing_nested_key_returns_none(self):
        from pipeline.executors.mse import get_nested_value
        assert get_nested_value({"a": {"b": 1}}, "a.c") is None

    def test_non_dict_intermediate_returns_none(self):
        from pipeline.executors.mse import get_nested_value
        assert get_nested_value({"a": "string"}, "a.b") is None


# ---------------------------------------------------------------------------
# Tests: Godzilla set file generation
# ---------------------------------------------------------------------------

class TestGodzillaSetFile:
    """Test that the MSE set file uses the Godzilla stylesheet and alias field."""

    def _build_godzilla_cards(self) -> list[dict]:
        """Build card dicts as the executor would when name_field is set."""
        cards = []
        for asset_id, stats in CARD_STATS.items():
            bird_data = BIRD_NAME_OUTPUTS[asset_id]
            original_name = asset_id.replace("-", " ").title()

            type_line = stats["type_line"]
            if " \u2014 " in type_line:
                supertype, subtype = type_line.split(" \u2014 ", 1)
            else:
                supertype, subtype = type_line, ""

            cards.append({
                "name": bird_data["bird"],
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
# Tests: JSON response parsing (generate_text with response_format: json)
# ---------------------------------------------------------------------------

class TestJsonResponseParsing:
    """Test that generate_text's JSON parsing handles LLM output correctly."""

    def test_parses_plain_json(self):
        from pipeline.executors.text import GenerateTextExecutor
        result = GenerateTextExecutor._parse_json_response(
            '{"bird": "Northern Goshawk", "rationale": "Agile predator."}'
        )
        assert result == {"bird": "Northern Goshawk", "rationale": "Agile predator."}

    def test_parses_json_in_code_fence(self):
        from pipeline.executors.text import GenerateTextExecutor
        result = GenerateTextExecutor._parse_json_response(
            '```json\n{"bird": "Snowy Owl", "rationale": "White plumage."}\n```'
        )
        assert result == {"bird": "Snowy Owl", "rationale": "White plumage."}

    def test_parses_json_in_bare_fence(self):
        from pipeline.executors.text import GenerateTextExecutor
        result = GenerateTextExecutor._parse_json_response(
            '```\n{"bird": "Snowy Owl"}\n```'
        )
        assert result == {"bird": "Snowy Owl"}

    def test_returns_none_for_invalid_json(self):
        from pipeline.executors.text import GenerateTextExecutor
        result = GenerateTextExecutor._parse_json_response("BIRD: Snowy Owl\nRATIONALE: ...")
        assert result is None

    def test_strips_whitespace(self):
        from pipeline.executors.text import GenerateTextExecutor
        result = GenerateTextExecutor._parse_json_response(
            '  \n  {"bird": "Snowy Owl"}  \n  '
        )
        assert result == {"bird": "Snowy Owl"}


# ---------------------------------------------------------------------------
# Tests: Full integration with real bird_deck data on disk
# ---------------------------------------------------------------------------

BIRD_DECK_STATE_DIR = (
    Path(__file__).parent.parent.parent
    / "examples" / "bird_deck" / ".artgen"
)


def has_bird_deck_data():
    return (BIRD_DECK_STATE_DIR / "suggest_bird_name").exists()


@pytest.mark.skipif(not has_bird_deck_data(), reason="No bird_deck data")
class TestGodzillaBirdDeckIntegration:
    """Integration test using actual bird_deck pipeline output on disk."""

    def test_generates_full_godzilla_set_file(self):
        """Should generate a complete Godzilla-style set file from bird deck data.

        This test simulates what the executor does: reads stats from
        fetch_card_stats, reads the bird name from suggest_bird_name
        (simulating structured JSON by parsing the BIRD: prefix), and
        writes a Godzilla-style set file.
        """
        from pipeline.executors.mse import get_nested_value, write_mse_set_file

        import re

        cards = []
        assets = []
        name_step_dir = BIRD_DECK_STATE_DIR / "suggest_bird_name"
        stats_step_dir = BIRD_DECK_STATE_DIR / "fetch_card_stats"

        for asset_dir in sorted(name_step_dir.iterdir()):
            if not asset_dir.is_dir():
                continue

            asset_id = asset_dir.name
            original_name = asset_id.replace("-", " ").title()

            # The existing suggest_bird_name output uses the old text format.
            # Extract the bird name to simulate what response_format: json
            # would produce as {"bird": "...", "rationale": "..."}.
            with open(asset_dir / "output.json") as f:
                raw_content = json.load(f)["data"]["content"]
            match = re.search(r"BIRD:\s*(.+)", raw_content)
            bird_name = match.group(1).strip() if match else "Unknown"

            # Build a simulated asset dict as it would look after structured
            # output merging: asset["bird_name"] = {"bird": "...", ...}
            asset = {
                "id": asset_id,
                "name": original_name,
                "bird_name": {"bird": bird_name},
            }
            assets.append(asset)

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

            card = {
                "name": original_name,
                "supertype": supertype.strip(),
                "subtype": subtype.strip(),
                "mana_cost": stats.get("mana_cost", ""),
                "rule_text": stats.get("oracle_text", ""),
                "power": stats.get("power", ""),
                "toughness": stats.get("toughness", ""),
                "rarity": stats.get("rarity", "common"),
            }

            # Simulate the executor's name_field resolution
            alt_name = get_nested_value(asset, "bird_name.bird")
            assert alt_name is not None, f"Should resolve bird_name.bird for {asset_id}"
            card["alias"] = card["name"]
            card["name"] = alt_name

            cards.append(card)

        assert len(cards) >= 3, "Should find all 3 bird deck cards"

        output_dir = BIRD_DECK_STATE_DIR / "test_godzilla_output"
        output_dir.mkdir(parents=True, exist_ok=True)
        set_file = output_dir / "set"

        write_mse_set_file(
            cards, set_file, "aviary_of_the_ancients", stylesheet="m15-godzilla",
        )

        content = set_file.read_text()

        assert "stylesheet: m15-godzilla" in content

        for card in cards:
            assert f"\tname: {card['name']}" in content
            assert f"\talias: {card['alias']}" in content

        print(f"\n{'='*60}")
        print(f"GODZILLA SET FILE written to:")
        print(f"  {set_file}")
        print(f"Manually inspect with:  cat {set_file}")
        print(f"{'='*60}")
