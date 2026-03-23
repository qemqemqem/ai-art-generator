#!/usr/bin/env python3
"""
Scryfall card lookup for the fake cards pipeline.

Reads asset data from stdin (JSON), fetches the card from the Scryfall API
(exact match first, then fuzzy fallback), and prints the relevant stats as JSON to stdout.

Uses asset.real_name as the lookup key.

Scryfall API docs: https://scryfall.com/docs/api
Rate limit: under 10 req/s — we sleep 100ms between requests.
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SCRYFALL_API = "https://api.scryfall.com/cards/named"
RATE_LIMIT_SEC = 0.1

HEADERS = {
    "User-Agent": "artgen-fake-cards/1.0 (https://github.com/ai-art-generator)",
    "Accept": "application/json;q=0.9,*/*;q=0.8",
}


def _fetch(url: str) -> dict:
    """Fetch JSON from URL. Raises urllib.error.HTTPError on 4xx/5xx."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def _extract_card(data: dict) -> dict:
    """Extract required fields from Scryfall card object."""
    return {
        "mana_cost": data.get("mana_cost", ""),
        "type_line": data.get("type_line", ""),
        "oracle_text": data.get("oracle_text", ""),
        "power": data.get("power"),
        "toughness": data.get("toughness"),
        "colors": data.get("colors", []),
        "color_identity": data.get("color_identity", []),
        "cmc": data.get("cmc"),
        "rarity": data.get("rarity", ""),
        "set_name": data.get("set_name", ""),
        "scryfall_uri": data.get("scryfall_uri", ""),
    }


def lookup(card_name: str) -> dict:
    """Look up card by exact name, then fuzzy if no exact match."""
    if not card_name or not isinstance(card_name, str):
        raise ValueError("card_name must be a non-empty string")

    name = card_name.strip()
    if not name:
        raise ValueError("card_name must be a non-empty string")

    # Exact match
    time.sleep(RATE_LIMIT_SEC)
    params = urllib.parse.urlencode({"exact": name})
    url = f"{SCRYFALL_API}?{params}"

    try:
        data = _fetch(url)
        return _extract_card(data)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        # No exact match — try fuzzy
        pass

    # Fuzzy match
    time.sleep(RATE_LIMIT_SEC)
    params = urllib.parse.urlencode({"fuzzy": name})
    url = f"{SCRYFALL_API}?{params}"
    data = _fetch(url)
    return _extract_card(data)


def _error(msg: str) -> None:
    """Print JSON error to stderr."""
    print(json.dumps({"error": msg}), file=sys.stderr)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        _error(f"Invalid JSON on stdin: {e}")
        sys.exit(1)

    asset = payload.get("asset")
    if not asset or not isinstance(asset, dict):
        _error("Missing or invalid 'asset' in input")
        sys.exit(1)

    card_name = asset.get("real_name")
    if card_name is None:
        _error("Missing 'asset.real_name' in input")
        sys.exit(1)

    try:
        stats = lookup(card_name)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()
            err_obj = json.loads(body)
            detail = err_obj.get("details", err_obj.get("message", body))
        except (ValueError, json.JSONDecodeError):
            detail = str(e)
        _error(f"Scryfall lookup failed for '{card_name}': HTTP {e.code} — {detail}")
        sys.exit(1)
    except urllib.error.URLError as e:
        _error(f"Scryfall lookup failed for '{card_name}': {e.reason}")
        sys.exit(1)
    except ValueError as e:
        _error(str(e))
        sys.exit(1)

    json.dump(stats, sys.stdout)


if __name__ == "__main__":
    main()
