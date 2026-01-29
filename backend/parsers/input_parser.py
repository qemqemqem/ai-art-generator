"""Flexible input parser supporting multiple formats."""

import csv
import json
import re
from enum import Enum
from pathlib import Path
from typing import Optional, TextIO
import uuid

from app.models import InputItem


class InputFormat(str, Enum):
    """Supported input file formats."""
    TEXT = "text"        # One description per line
    CSV = "csv"          # CSV with headers
    TSV = "tsv"          # Tab-separated
    JSON = "json"        # JSON array
    JSONL = "jsonl"      # JSON Lines


def detect_format(file_path: Path) -> InputFormat:
    """Auto-detect the format of an input file.
    
    Args:
        file_path: Path to the input file
        
    Returns:
        Detected InputFormat
    """
    suffix = file_path.suffix.lower()
    
    if suffix == ".json":
        return InputFormat.JSON
    elif suffix == ".jsonl":
        return InputFormat.JSONL
    elif suffix == ".csv":
        return InputFormat.CSV
    elif suffix == ".tsv":
        return InputFormat.TSV
    elif suffix in (".txt", ".text", ""):
        # Try to detect if it's actually CSV/TSV
        with open(file_path, "r", encoding="utf-8") as f:
            first_line = f.readline()
            if "\t" in first_line and first_line.count("\t") > 0:
                return InputFormat.TSV
            elif "," in first_line and first_line.count(",") > 1:
                # Likely CSV if multiple commas
                return InputFormat.CSV
        return InputFormat.TEXT
    else:
        return InputFormat.TEXT


def _generate_id() -> str:
    """Generate a unique ID for an item."""
    return str(uuid.uuid4())[:8]


def _parse_text(content: str) -> list[InputItem]:
    """Parse simple text format (one item per line)."""
    items = []
    item_num = 0
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        
        item_num += 1
        
        # Check for "ID: Description" format
        id_match = re.match(r"^(\w+):\s*(.+)$", line)
        if id_match:
            item_id, description = id_match.groups()
        else:
            item_id = f"item-{item_num:03d}"
            description = line
        
        items.append(InputItem(
            id=item_id,
            description=description,
        ))
    
    return items


def _parse_csv(content: str, delimiter: str = ",") -> list[InputItem]:
    """Parse CSV/TSV format."""
    items = []
    reader = csv.DictReader(content.strip().split("\n"), delimiter=delimiter)
    
    for i, row in enumerate(reader):
        # Normalize keys to lowercase
        row = {k.lower().strip(): v for k, v in row.items()}
        
        # Find description field (try multiple common names)
        description = None
        for key in ["description", "desc", "prompt", "text", "content", "name"]:
            if key in row and row[key]:
                description = row[key]
                break
        
        if not description:
            # Use first non-id column
            for key, value in row.items():
                if key not in ("id", "index", "num", "number") and value:
                    description = value
                    break
        
        if not description:
            continue
        
        # Get or generate ID
        item_id = row.get("id") or row.get("index") or f"item-{i+1:03d}"
        
        # Extract name if separate from description
        name = None
        if "name" in row and row["name"] != description:
            name = row["name"]
        
        # Collect remaining fields as metadata
        metadata = {}
        skip_keys = {"id", "index", "description", "desc", "prompt", "text", "content", "name"}
        for key, value in row.items():
            if key not in skip_keys and value:
                metadata[key] = value
        
        items.append(InputItem(
            id=item_id,
            description=description,
            name=name,
            metadata=metadata,
        ))
    
    return items


def _parse_json(content: str) -> list[InputItem]:
    """Parse JSON array format."""
    data = json.loads(content)
    
    if not isinstance(data, list):
        data = [data]
    
    items = []
    for i, obj in enumerate(data):
        if isinstance(obj, str):
            # Simple string array
            items.append(InputItem(
                id=f"item-{i+1:03d}",
                description=obj,
            ))
        elif isinstance(obj, dict):
            # Find description
            description = None
            for key in ["description", "desc", "prompt", "text", "content"]:
                if key in obj and obj[key]:
                    description = obj[key]
                    break
            
            if not description:
                continue
            
            item_id = obj.get("id") or f"item-{i+1:03d}"
            name = obj.get("name")
            
            # Collect remaining as metadata
            metadata = {}
            skip_keys = {"id", "description", "desc", "prompt", "text", "content", "name"}
            for key, value in obj.items():
                if key not in skip_keys:
                    metadata[key] = value
            
            items.append(InputItem(
                id=item_id,
                description=description,
                name=name,
                metadata=metadata,
            ))
    
    return items


def _parse_jsonl(content: str) -> list[InputItem]:
    """Parse JSON Lines format."""
    items = []
    for i, line in enumerate(content.strip().split("\n")):
        line = line.strip()
        if not line:
            continue
        
        obj = json.loads(line)
        
        if isinstance(obj, str):
            items.append(InputItem(
                id=f"item-{i+1:03d}",
                description=obj,
            ))
        elif isinstance(obj, dict):
            description = None
            for key in ["description", "desc", "prompt", "text", "content"]:
                if key in obj and obj[key]:
                    description = obj[key]
                    break
            
            if not description:
                continue
            
            item_id = obj.get("id") or f"item-{i+1:03d}"
            name = obj.get("name")
            
            metadata = {}
            skip_keys = {"id", "description", "desc", "prompt", "text", "content", "name"}
            for key, value in obj.items():
                if key not in skip_keys:
                    metadata[key] = value
            
            items.append(InputItem(
                id=item_id,
                description=description,
                name=name,
                metadata=metadata,
            ))
    
    return items


def parse_input_file(
    file_path: Path,
    format: Optional[InputFormat] = None,
) -> list[InputItem]:
    """Parse an input file into a list of InputItems.
    
    Supports multiple formats:
    - TEXT: One description per line
    - CSV: CSV with headers (auto-detects description column)
    - TSV: Tab-separated values
    - JSON: JSON array of objects or strings
    - JSONL: JSON Lines format
    
    Args:
        file_path: Path to the input file
        format: Explicit format (auto-detected if not provided)
        
    Returns:
        List of InputItem objects
    """
    if format is None:
        format = detect_format(file_path)
    
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    if format == InputFormat.TEXT:
        return _parse_text(content)
    elif format == InputFormat.CSV:
        return _parse_csv(content, delimiter=",")
    elif format == InputFormat.TSV:
        return _parse_csv(content, delimiter="\t")
    elif format == InputFormat.JSON:
        return _parse_json(content)
    elif format == InputFormat.JSONL:
        return _parse_jsonl(content)
    else:
        raise ValueError(f"Unknown format: {format}")


def parse_input_string(
    content: str,
    format: InputFormat = InputFormat.TEXT,
) -> list[InputItem]:
    """Parse input content from a string.
    
    Args:
        content: The input content string
        format: The format of the content
        
    Returns:
        List of InputItem objects
    """
    if format == InputFormat.TEXT:
        return _parse_text(content)
    elif format == InputFormat.CSV:
        return _parse_csv(content, delimiter=",")
    elif format == InputFormat.TSV:
        return _parse_csv(content, delimiter="\t")
    elif format == InputFormat.JSON:
        return _parse_json(content)
    elif format == InputFormat.JSONL:
        return _parse_jsonl(content)
    else:
        raise ValueError(f"Unknown format: {format}")
