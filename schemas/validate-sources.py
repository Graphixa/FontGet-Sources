#!/usr/bin/env python3
"""
FontGet Source Validation Tool

Validates font source JSON files against the FontGet schema.
Usage: python validate-sources.py <source-file.json>
"""

import json
import jsonschema
import sys
import os
from pathlib import Path
from typing import List, Dict, Any


class SourceValidator:
    def __init__(self, schema_path: str = None):
        """Initialize validator with schema file."""
        if schema_path is None:
            schema_path = Path(__file__).parent / "font-source-schema.json"
        
        with open(schema_path, 'r', encoding='utf-8') as f:
            self.schema = json.load(f)
        
        self.validator = jsonschema.Draft7Validator(self.schema)
    
    def validate_file(self, file_path: str) -> Dict[str, Any]:
        """Validate a single source file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            errors = list(self.validator.iter_errors(data))
            
            return {
                "valid": len(errors) == 0,
                "file": file_path,
                "errors": [self._format_error(error) for error in errors],
                "warnings": self._check_warnings(data)
            }
        except json.JSONDecodeError as e:
            return {
                "valid": False,
                "file": file_path,
                "errors": [f"JSON syntax error: {e}"],
                "warnings": []
            }
        except Exception as e:
            return {
                "valid": False,
                "file": file_path,
                "errors": [f"Validation error: {e}"],
                "warnings": []
            }
    
    def validate_directory(self, dir_path: str) -> List[Dict[str, Any]]:
        """Validate all JSON files in a directory."""
        results = []
        for file_path in Path(dir_path).glob("*.json"):
            results.append(self.validate_file(str(file_path)))
        return results
    
    def _format_error(self, error) -> str:
        """Format a validation error for display."""
        path = " -> ".join(str(p) for p in error.absolute_path)
        return f"{path}: {error.message}"
    
    def _check_warnings(self, data: Dict[str, Any]) -> List[str]:
        """Check for potential issues that aren't schema violations."""
        warnings = []
        
        # Check for empty sources
        if not data.get("fonts"):
            warnings.append("No fonts found in source")
        
        # Check for missing popularity data
        fonts = data.get("fonts", {})
        fonts_without_popularity = [
            font_id for font_id, font in fonts.items() 
            if "popularity" not in font
        ]
        if fonts_without_popularity:
            warnings.append(f"Fonts without popularity data: {len(fonts_without_popularity)}")
        
        # Check for fonts with single variants
        single_variant_fonts = [
            font_id for font_id, font in fonts.items()
            if len(font.get("variants", [])) == 1
        ]
        if single_variant_fonts:
            warnings.append(f"Fonts with only one variant: {len(single_variant_fonts)}")
        
        return warnings


def print_results(results: List[Dict[str, Any]]):
    """Print validation results in a readable format."""
    total_files = len(results)
    valid_files = sum(1 for r in results if r["valid"])
    
    print(f"\n=== FontGet Source Validation Results ===")
    print(f"Total files: {total_files}")
    print(f"Valid files: {valid_files}")
    print(f"Invalid files: {total_files - valid_files}")
    print()
    
    for result in results:
        status = "✅ VALID" if result["valid"] else "❌ INVALID"
        print(f"{status} {result['file']}")
        
        if result["errors"]:
            print("  Errors:")
            for error in result["errors"]:
                print(f"    • {error}")
        
        if result["warnings"]:
            print("  Warnings:")
            for warning in result["warnings"]:
                print(f"    ⚠️  {warning}")
        
        print()


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate-sources.py <source-file.json> [source-file2.json ...]")
        print("       python validate-sources.py <directory>")
        sys.exit(1)
    
    validator = SourceValidator()
    results = []
    
    for arg in sys.argv[1:]:
        if os.path.isfile(arg):
            results.append(validator.validate_file(arg))
        elif os.path.isdir(arg):
            results.extend(validator.validate_directory(arg))
        else:
            print(f"Error: {arg} is not a valid file or directory")
            sys.exit(1)
    
    print_results(results)
    
    # Exit with error code if any files are invalid
    if any(not result["valid"] for result in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
