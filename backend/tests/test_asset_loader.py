"""Tests for the asset loader."""

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from pipeline.asset_loader import (
    AssetLoadError,
    load_from_file,
    load_csv,
    load_json,
    load_yaml,
    load_jsonl,
    load_txt,
    validate_asset,
)
from pipeline.spec_parser import TypeDef, FieldType


class TestLoadCSV:
    """Tests for CSV loading."""
    
    def test_basic_csv(self, tmp_path):
        """Test loading a basic CSV file."""
        csv_file = tmp_path / "units.csv"
        csv_file.write_text(
            "id,name,unit_class\n"
            "archer,Elven Archer,ranged\n"
            "knight,Royal Knight,infantry\n"
        )
        
        items = load_csv(csv_file)
        
        assert len(items) == 2
        assert items[0]["id"] == "archer"
        assert items[0]["name"] == "Elven Archer"
        assert items[1]["unit_class"] == "infantry"
    
    def test_empty_values(self, tmp_path):
        """Test that empty CSV values become None."""
        csv_file = tmp_path / "data.csv"
        csv_file.write_text(
            "id,name,notes\n"
            "item1,Test,\n"
        )
        
        items = load_csv(csv_file)
        
        assert items[0]["notes"] is None


class TestLoadJSON:
    """Tests for JSON loading."""
    
    def test_basic_json(self, tmp_path):
        """Test loading a basic JSON file."""
        json_file = tmp_path / "units.json"
        json_file.write_text(json.dumps([
            {"id": "archer", "name": "Archer"},
            {"id": "knight", "name": "Knight"},
        ]))
        
        items = load_json(json_file)
        
        assert len(items) == 2
        assert items[0]["id"] == "archer"
    
    def test_invalid_json_structure(self, tmp_path):
        """Test that non-array JSON raises error."""
        json_file = tmp_path / "invalid.json"
        json_file.write_text('{"not": "an array"}')
        
        with pytest.raises(AssetLoadError):
            load_json(json_file)


class TestLoadYAML:
    """Tests for YAML loading."""
    
    def test_basic_yaml(self, tmp_path):
        """Test loading a basic YAML file."""
        yaml_file = tmp_path / "units.yaml"
        yaml_file.write_text(yaml.dump([
            {"id": "archer", "name": "Archer"},
            {"id": "knight", "name": "Knight"},
        ]))
        
        items = load_yaml(yaml_file)
        
        assert len(items) == 2
        assert items[0]["id"] == "archer"
    
    def test_invalid_yaml_structure(self, tmp_path):
        """Test that non-list YAML raises error."""
        yaml_file = tmp_path / "invalid.yaml"
        yaml_file.write_text("not: a list")
        
        with pytest.raises(AssetLoadError):
            load_yaml(yaml_file)


class TestLoadJSONL:
    """Tests for JSONL loading."""
    
    def test_basic_jsonl(self, tmp_path):
        """Test loading a basic JSONL file."""
        jsonl_file = tmp_path / "units.jsonl"
        jsonl_file.write_text(
            '{"id": "archer", "name": "Archer"}\n'
            '{"id": "knight", "name": "Knight"}\n'
        )
        
        items = load_jsonl(jsonl_file)
        
        assert len(items) == 2
        assert items[0]["id"] == "archer"
    
    def test_blank_lines_ignored(self, tmp_path):
        """Test that blank lines are ignored."""
        jsonl_file = tmp_path / "sparse.jsonl"
        jsonl_file.write_text(
            '{"id": "item1"}\n'
            '\n'
            '{"id": "item2"}\n'
        )
        
        items = load_jsonl(jsonl_file)
        
        assert len(items) == 2
    
    def test_invalid_line(self, tmp_path):
        """Test that invalid JSON line raises error."""
        jsonl_file = tmp_path / "bad.jsonl"
        jsonl_file.write_text(
            '{"id": "item1"}\n'
            'not valid json\n'
        )
        
        with pytest.raises(AssetLoadError):
            load_jsonl(jsonl_file)


class TestLoadTXT:
    """Tests for text file loading."""
    
    def test_basic_txt(self, tmp_path):
        """Test loading a basic text file."""
        txt_file = tmp_path / "items.txt"
        txt_file.write_text(
            "First item\n"
            "Second item\n"
            "Third item\n"
        )
        
        items = load_txt(txt_file)
        
        assert len(items) == 3
        assert items[0]["content"] == "First item"
        assert items[0]["id"] == "item-001"
    
    def test_blank_lines_ignored(self, tmp_path):
        """Test that blank lines are ignored."""
        txt_file = tmp_path / "sparse.txt"
        txt_file.write_text(
            "Item 1\n"
            "\n"
            "Item 2\n"
        )
        
        items = load_txt(txt_file)
        
        assert len(items) == 2


class TestLoadFromFile:
    """Tests for auto-detecting file format."""
    
    def test_csv_by_extension(self, tmp_path):
        """Test that .csv extension triggers CSV loading."""
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("id,name\nitem1,Test\n")
        
        items = load_from_file(csv_file)
        
        assert items[0]["id"] == "item1"
    
    def test_file_not_found(self, tmp_path):
        """Test that missing file raises error."""
        with pytest.raises(AssetLoadError):
            load_from_file(tmp_path / "missing.csv")
    
    def test_unsupported_format(self, tmp_path):
        """Test that unsupported format raises error."""
        bad_file = tmp_path / "data.xyz"
        bad_file.write_text("content")
        
        with pytest.raises(AssetLoadError):
            load_from_file(bad_file)


class TestValidateAsset:
    """Tests for asset validation."""
    
    def test_valid_asset(self):
        """Test validating a valid asset."""
        type_def = TypeDef(
            name="GameSprite",
            fields={
                "name": FieldType(base="text"),
                "unit_class": FieldType(base="enum", enum_values=["ranged", "infantry"]),
            }
        )
        
        asset = {"name": "Archer", "unit_class": "ranged"}
        result = validate_asset(asset, type_def)
        
        assert result["name"] == "Archer"
        assert result["unit_class"] == "ranged"
    
    def test_invalid_enum_value(self):
        """Test that invalid enum value raises error."""
        type_def = TypeDef(
            name="GameSprite",
            fields={
                "unit_class": FieldType(base="enum", enum_values=["ranged", "infantry"]),
            }
        )
        
        asset = {"unit_class": "invalid"}
        
        with pytest.raises(AssetLoadError):
            validate_asset(asset, type_def)
    
    def test_number_coercion(self):
        """Test that numbers are coerced correctly."""
        type_def = TypeDef(
            name="Stats",
            fields={
                "power": FieldType(base="number"),
                "speed": FieldType(base="number"),
            }
        )
        
        asset = {"power": "5", "speed": "3.5"}
        result = validate_asset(asset, type_def)
        
        assert result["power"] == 5
        assert result["speed"] == 3.5
    
    def test_boolean_coercion(self):
        """Test that booleans are coerced correctly."""
        type_def = TypeDef(
            name="Config",
            fields={
                "enabled": FieldType(base="boolean"),
            }
        )
        
        asset = {"enabled": "true"}
        result = validate_asset(asset, type_def)
        
        assert result["enabled"] is True
        
        asset = {"enabled": "false"}
        result = validate_asset(asset, type_def)
        
        assert result["enabled"] is False
