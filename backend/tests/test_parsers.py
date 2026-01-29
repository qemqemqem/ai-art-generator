"""Tests for input parsing - no API calls, fast."""

import pytest
from parsers import parse_input_string, InputFormat


class TestTextParsing:
    """Test plain text input parsing."""
    
    def test_simple_lines(self):
        """Parse simple one-per-line format."""
        content = """Wise owl wizard
Fire-breathing dragon
Enchanted forest"""
        
        items = parse_input_string(content, InputFormat.TEXT)
        
        assert len(items) == 3
        assert items[0].description == "Wise owl wizard"
        assert items[1].description == "Fire-breathing dragon"
        assert items[2].description == "Enchanted forest"
    
    def test_with_ids(self):
        """Parse text with ID prefixes."""
        content = """owl: A wise owl wizard
dragon: Fire-breathing dragon"""
        
        items = parse_input_string(content, InputFormat.TEXT)
        
        assert len(items) == 2
        assert items[0].id == "owl"
        assert items[0].description == "A wise owl wizard"
        assert items[1].id == "dragon"
    
    def test_skip_empty_and_comments(self):
        """Skip empty lines and comments."""
        content = """# This is a comment
Wise owl wizard

# Another comment
Fire-breathing dragon
"""
        
        items = parse_input_string(content, InputFormat.TEXT)
        
        assert len(items) == 2
    
    def test_comment_skipping_preserves_sequential_ids(self):
        """IDs should be sequential based on actual items, not line numbers.
        
        This is a regression test for a bug where comments/empty lines
        caused IDs to skip numbers (e.g., item-002, item-003 instead of
        item-001, item-002).
        """
        content = """# Comment at start
First item
# Middle comment

Second item
# End comment
Third item"""
        
        items = parse_input_string(content, InputFormat.TEXT)
        
        assert len(items) == 3
        assert items[0].id == "item-001"
        assert items[0].description == "First item"
        assert items[1].id == "item-002"
        assert items[1].description == "Second item"
        assert items[2].id == "item-003"
        assert items[2].description == "Third item"
    
    def test_auto_generate_ids(self):
        """Auto-generate sequential IDs."""
        content = """First item
Second item"""
        
        items = parse_input_string(content, InputFormat.TEXT)
        
        assert items[0].id == "item-001"
        assert items[1].id == "item-002"


class TestCSVParsing:
    """Test CSV input parsing."""
    
    def test_basic_csv(self):
        """Parse basic CSV with description column."""
        content = """id,description
owl,A wise owl wizard
dragon,Fire-breathing dragon"""
        
        items = parse_input_string(content, InputFormat.CSV)
        
        assert len(items) == 2
        assert items[0].id == "owl"
        assert items[0].description == "A wise owl wizard"
    
    def test_csv_with_metadata(self):
        """Parse CSV with extra columns as metadata."""
        content = """id,description,style,priority
owl,A wise owl wizard,dark fantasy,high
dragon,Fire-breathing dragon,epic,medium"""
        
        items = parse_input_string(content, InputFormat.CSV)
        
        assert len(items) == 2
        assert items[0].metadata["style"] == "dark fantasy"
        assert items[0].metadata["priority"] == "high"
    
    def test_csv_alternate_column_names(self):
        """Support alternate column names like 'prompt' or 'text'."""
        content = """id,prompt
owl,A wise owl wizard"""
        
        items = parse_input_string(content, InputFormat.CSV)
        
        assert items[0].description == "A wise owl wizard"


class TestJSONParsing:
    """Test JSON input parsing."""
    
    def test_json_array_of_objects(self):
        """Parse JSON array of objects."""
        content = """[
  {"id": "owl", "description": "A wise owl wizard"},
  {"id": "dragon", "description": "Fire-breathing dragon"}
]"""
        
        items = parse_input_string(content, InputFormat.JSON)
        
        assert len(items) == 2
        assert items[0].id == "owl"
        assert items[0].description == "A wise owl wizard"
    
    def test_json_array_of_strings(self):
        """Parse JSON array of simple strings."""
        content = '["Wise owl wizard", "Fire-breathing dragon"]'
        
        items = parse_input_string(content, InputFormat.JSON)
        
        assert len(items) == 2
        assert items[0].description == "Wise owl wizard"
    
    def test_json_with_metadata(self):
        """Parse JSON with extra fields as metadata."""
        content = """[
  {"id": "owl", "description": "A wise owl wizard", "style": "fantasy", "tags": ["magic", "bird"]}
]"""
        
        items = parse_input_string(content, InputFormat.JSON)
        
        assert items[0].metadata["style"] == "fantasy"
        assert items[0].metadata["tags"] == ["magic", "bird"]


class TestJSONLParsing:
    """Test JSON Lines input parsing."""
    
    def test_jsonl_objects(self):
        """Parse JSON Lines format."""
        content = """{"id": "owl", "description": "A wise owl wizard"}
{"id": "dragon", "description": "Fire-breathing dragon"}"""
        
        items = parse_input_string(content, InputFormat.JSONL)
        
        assert len(items) == 2
        assert items[0].id == "owl"
        assert items[1].id == "dragon"
    
    def test_jsonl_strings(self):
        """Parse JSON Lines with simple strings."""
        content = """"Wise owl wizard"
"Fire-breathing dragon" """
        
        items = parse_input_string(content, InputFormat.JSONL)
        
        assert len(items) == 2
