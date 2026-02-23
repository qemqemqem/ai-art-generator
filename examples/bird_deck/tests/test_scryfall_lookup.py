"""Tests for the Scryfall lookup script (examples/bird_deck/scripts/scryfall_lookup.py).

Mocks all HTTP calls — no real Scryfall traffic.
"""

import json
import subprocess
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import scryfall_lookup


BIRDS_OF_PARADISE_RESPONSE = {
    "mana_cost": "{G}",
    "type_line": "Creature — Bird",
    "oracle_text": "Flying\n{T}: Add one mana of any color.",
    "power": "0",
    "toughness": "1",
    "colors": ["G"],
    "color_identity": ["G"],
    "cmc": 1.0,
    "rarity": "rare",
    "set_name": "Ravnica Allegiance",
    "scryfall_uri": "https://scryfall.com/card/rna/123/birds-of-paradise",
}


def _mock_urlopen(response_data):
    """Create a mock for urllib.request.urlopen that returns given data."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response_data).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestExtractCard:
    """Tests for _extract_card field extraction."""

    def test_extracts_all_fields(self):
        result = scryfall_lookup._extract_card(BIRDS_OF_PARADISE_RESPONSE)

        assert result["mana_cost"] == "{G}"
        assert result["type_line"] == "Creature — Bird"
        assert result["oracle_text"].startswith("Flying")
        assert result["power"] == "0"
        assert result["toughness"] == "1"
        assert result["colors"] == ["G"]
        assert result["color_identity"] == ["G"]
        assert result["cmc"] == 1.0
        assert result["rarity"] == "rare"

    def test_missing_fields_get_defaults(self):
        result = scryfall_lookup._extract_card({"name": "Some Land"})

        assert result["mana_cost"] == ""
        assert result["oracle_text"] == ""
        assert result["power"] is None
        assert result["toughness"] is None
        assert result["colors"] == []


class TestLookup:
    """Tests for the lookup function with mocked HTTP."""

    @patch("scryfall_lookup._fetch")
    @patch("scryfall_lookup.time.sleep")
    def test_exact_match(self, mock_sleep, mock_fetch):
        mock_fetch.return_value = BIRDS_OF_PARADISE_RESPONSE

        result = scryfall_lookup.lookup("Birds of Paradise")

        assert result["mana_cost"] == "{G}"
        assert result["type_line"] == "Creature — Bird"
        mock_fetch.assert_called_once()
        assert "exact=" in mock_fetch.call_args[0][0]

    @patch("scryfall_lookup._fetch")
    @patch("scryfall_lookup.time.sleep")
    def test_fuzzy_fallback_on_404(self, mock_sleep, mock_fetch):
        http_404 = urllib.error.HTTPError(
            url="https://api.scryfall.com/cards/named?exact=Birdz",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=MagicMock(),
        )
        mock_fetch.side_effect = [http_404, BIRDS_OF_PARADISE_RESPONSE]

        result = scryfall_lookup.lookup("Birdz")

        assert result["mana_cost"] == "{G}"
        assert mock_fetch.call_count == 2
        assert "fuzzy=" in mock_fetch.call_args[0][0]

    @patch("scryfall_lookup._fetch")
    @patch("scryfall_lookup.time.sleep")
    def test_non_404_http_error_raises(self, mock_sleep, mock_fetch):
        http_500 = urllib.error.HTTPError(
            url="https://api.scryfall.com/cards/named",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=MagicMock(),
        )
        mock_fetch.side_effect = http_500

        with pytest.raises(urllib.error.HTTPError):
            scryfall_lookup.lookup("Birds of Paradise")

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            scryfall_lookup.lookup("")

    def test_none_name_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            scryfall_lookup.lookup(None)

    @patch("scryfall_lookup._fetch")
    @patch("scryfall_lookup.time.sleep")
    def test_rate_limit_sleep_called(self, mock_sleep, mock_fetch):
        mock_fetch.return_value = BIRDS_OF_PARADISE_RESPONSE

        scryfall_lookup.lookup("Birds of Paradise")

        mock_sleep.assert_called_with(0.1)


class TestMainEntryPoint:
    """Tests for the main() stdin/stdout contract."""

    @patch("scryfall_lookup.lookup")
    def test_valid_input_outputs_json(self, mock_lookup, capsys):
        mock_lookup.return_value = {"mana_cost": "{G}", "type_line": "Creature — Bird"}

        payload = {"asset": {"id": "birds-of-paradise", "name": "Birds of Paradise"}}

        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            # json.load reads from stdin, so we need to mock it properly
            with patch("json.load", return_value=payload):
                scryfall_lookup.main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["mana_cost"] == "{G}"

    @patch("json.load", side_effect=json.JSONDecodeError("bad", "doc", 0))
    def test_invalid_json_exits_1(self, mock_json, capsys):
        with pytest.raises(SystemExit) as exc_info:
            scryfall_lookup.main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Invalid JSON" in captured.err

    @patch("json.load", return_value={})
    def test_missing_asset_exits_1(self, mock_json, capsys):
        with pytest.raises(SystemExit) as exc_info:
            scryfall_lookup.main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "asset" in captured.err.lower()

    @patch("json.load", return_value={"asset": {"id": "x"}})
    def test_missing_name_exits_1(self, mock_json, capsys):
        with pytest.raises(SystemExit) as exc_info:
            scryfall_lookup.main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "name" in captured.err.lower()

    @patch("json.load", return_value={"asset": {"id": "x", "name": "Fake Card"}})
    @patch("scryfall_lookup.lookup")
    def test_http_error_exits_1(self, mock_lookup, mock_json, capsys):
        mock_lookup.side_effect = urllib.error.HTTPError(
            url="https://api.scryfall.com",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"details": "Card not found"}'),
        )

        with pytest.raises(SystemExit) as exc_info:
            scryfall_lookup.main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Scryfall lookup failed" in captured.err
