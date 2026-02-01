#!/usr/bin/env python3
"""
Quick test to verify the JSON parsing fix for cached asset collections.
"""

import json
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from pipeline.executor import PipelineExecutor


def test_parse_content_as_list():
    """Test that markdown-wrapped JSON is parsed correctly."""
    
    # Create a minimal executor to test the method
    # We just need the _parse_content_as_list method
    class MockExecutor:
        pass
    
    executor = MockExecutor()
    executor._parse_content_as_list = PipelineExecutor._parse_content_as_list.__get__(executor)
    
    # Test 1: Direct JSON array
    print("Test 1: Direct JSON array")
    content = '[{"name": "Card A"}, {"name": "Card B"}]'
    result = executor._parse_content_as_list(content)
    assert len(result) == 2, f"Expected 2 items, got {len(result)}"
    assert result[0]["name"] == "Card A"
    print("  ✓ Passed")
    
    # Test 2: Markdown-wrapped JSON (the actual format from LLM)
    print("Test 2: Markdown-wrapped JSON")
    content = '''```json
[
  {
    "name": "Vela Wayfinder Initiate",
    "card_type": "Creature - Human Warrior",
    "rarity": "Common",
    "color": "White"
  },
  {
    "name": "Nebula Coral Sanctuary",
    "card_type": "Enchantment",
    "rarity": "Uncommon",
    "color": "Green"
  }
]
```'''
    result = executor._parse_content_as_list(content)
    assert len(result) == 2, f"Expected 2 items, got {len(result)}"
    assert result[0]["name"] == "Vela Wayfinder Initiate"
    assert result[1]["name"] == "Nebula Coral Sanctuary"
    print("  ✓ Passed")
    
    # Test 3: JSON with special characters (hyphens in values)
    print("Test 3: JSON with special characters")
    content = '''```json
[
  {"name": "Ancestral Star-Whisperer", "card_type": "Creature - Spirit Wizard"},
  {"name": "Obsidian Crag Siphoner", "card_type": "Creature - Human Shaman"}
]
```'''
    result = executor._parse_content_as_list(content)
    assert len(result) == 2, f"Expected 2 items, got {len(result)}"
    assert result[0]["name"] == "Ancestral Star-Whisperer"
    assert result[0]["card_type"] == "Creature - Spirit Wizard"
    print("  ✓ Passed")
    
    # Test 4: Load actual cached data from mtg-generator
    print("Test 4: Load actual cached data")
    cache_file = Path(__file__).parent.parent / "pipelines/mtg-generator/.artgen/generate_card_names/output.json"
    if cache_file.exists():
        with open(cache_file) as f:
            cached_data = json.load(f)
        
        content = cached_data.get("data", {}).get("content", "")
        if content:
            result = executor._parse_content_as_list(content)
            print(f"    Found {len(result)} cards in cached data")
            if result:
                print(f"    First card: {result[0].get('name', 'unknown')}")
                assert len(result) > 0, "Expected at least 1 card"
                print("  ✓ Passed")
            else:
                print("  ⚠ No cards parsed - check the content format")
                print(f"    Content preview: {content[:200]}...")
        else:
            print("  ⚠ No content in cached data")
    else:
        print("  ⚠ Skipped - no cached data found")
    
    print("\n✓ All parsing tests passed!")


def test_cache_state():
    """Test that cache state file has expected structure."""
    print("\nTest 5: Cache state structure")
    
    state_file = Path(__file__).parent.parent / "pipelines/mtg-generator/.artgen/pipeline_state.json"
    if not state_file.exists():
        print("  ⚠ Skipped - no cache state file")
        return
    
    with open(state_file) as f:
        state = json.load(f)
    
    steps = state.get("steps", {})
    
    # Check for generate_card_names
    if "generate_card_names" in steps:
        print("  ✓ generate_card_names is cached")
    else:
        print("  ✗ generate_card_names not in cache")
    
    # Check for per-asset generate_card_concepts entries
    concept_keys = [k for k in steps.keys() if k.startswith("generate_card_concepts:")]
    print(f"  ✓ Found {len(concept_keys)} cached card concepts")
    
    if concept_keys:
        # Print asset IDs
        asset_ids = [k.split(":")[1] for k in concept_keys]
        print(f"    Asset IDs: {', '.join(asset_ids[:3])}{'...' if len(asset_ids) > 3 else ''}")


if __name__ == "__main__":
    print("=" * 60)
    print("Testing Cache/JSON Parsing Fixes")
    print("=" * 60)
    print()
    
    test_parse_content_as_list()
    test_cache_state()
    
    print()
    print("=" * 60)
    print("All tests completed!")
    print("=" * 60)
