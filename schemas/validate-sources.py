#!/usr/bin/env python3
"""
FontGet Source Validation Tool

1. Validates font source JSON files against ``font-source-schema.json`` (JSON Schema).
2. Checks ``variants[].files`` keys against URL path semantics (suffix rules JSON Schema cannot express).

Usage::

    python validate-sources.py <source-file.json> [source-file2.json ...]
    python validate-sources.py <directory>
    python validate-sources.py --files-keys-warn-only <file.json>
"""

from __future__ import annotations

import json
import jsonschema
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse


def _path_from_url(url: str) -> str:
    try:
        return urlparse(url).path or ""
    except Exception:
        return ""


def _zip_url_allowed(url: str, path_lower: str) -> bool:
    """``files.zip`` may be a ``.zip`` path, Font Squirrel fontfacekit, or Fontshare bundle API."""
    if "fontfacekit" in path_lower:
        return True
    if re.search(r"\.zip$", path_lower):
        return True
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    if "fontshare.com" in host and "/fonts/download/" in path_lower:
        return True
    return False


def _validate_files_object(files: Dict[str, Any], *, context: str) -> List[str]:
    errs: List[str] = []
    if not isinstance(files, dict):
        return [f"{context}: files is not an object"]

    url_to_keys: Dict[str, List[str]] = {}
    for key, val in files.items():
        if not isinstance(val, str) or not val.strip():
            errs.append(f"{context}: files.{key} is empty or not a string")
            continue
        url = val.strip()
        url_to_keys.setdefault(url, []).append(str(key))
    for url, keys in url_to_keys.items():
        if len(set(keys)) > 1:
            errs.append(f"{context}: same URL used for keys {sorted(set(keys))}: {url[:120]}")

    for key, val in files.items():
        if not isinstance(val, str):
            continue
        url = val.strip()
        path = _path_from_url(url)
        pl = path.lower()

        if key == "ttf":
            if not re.search(r"\.ttf$", pl):
                errs.append(f"{context}: files.ttf path must end with .ttf: {url[:160]}")
        elif key == "otf":
            if not re.search(r"\.otf$", pl):
                errs.append(f"{context}: files.otf path must end with .otf: {url[:160]}")
        elif key == "zip":
            if not _zip_url_allowed(url, pl):
                errs.append(
                    f"{context}: files.zip must be .zip, fontfacekit, or Fontshare /fonts/download/: {url[:160]}"
                )
        elif key == "tar_xz":
            if not re.search(r"\.tar\.xz$", pl):
                errs.append(f"{context}: files.tar_xz path must end with .tar.xz: {url[:160]}")
        else:
            errs.append(f"{context}: unknown files key {key!r} (allowed: ttf, otf, zip, tar_xz)")

    return errs


def files_key_errors(data: Any, *, file_label: str) -> List[str]:
    """Return human-readable errors for ``variants[].files`` / URL alignment (empty if OK)."""
    errs: List[str] = []
    if not isinstance(data, dict):
        return [f"{file_label}: root must be an object"]

    fonts = data.get("fonts")
    if not isinstance(fonts, dict):
        return [f"{file_label}: fonts must be an object"]

    for font_id, font in fonts.items():
        if not isinstance(font, dict):
            errs.append(f"{file_label}: fonts[{font_id!r}] is not an object")
            continue
        variants = font.get("variants")
        if not isinstance(variants, list):
            continue
        for i, var in enumerate(variants):
            if not isinstance(var, dict):
                errs.append(f"{file_label}: fonts[{font_id!r}].variants[{i}] is not an object")
                continue
            files = var.get("files")
            ctx = f"{file_label} font={font_id!r} variant[{i}]"
            if not isinstance(files, dict):
                errs.append(f"{ctx}: files must be an object")
                continue
            errs.extend(_validate_files_object(files, context=ctx))
    return errs


class SourceValidator:
    def __init__(self, schema_path: str = None, *, files_keys_warn_only: bool = False):
        """Initialize validator with schema file."""
        if schema_path is None:
            schema_path = Path(__file__).parent / "font-source-schema.json"

        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

        self.validator = jsonschema.Draft7Validator(self.schema)
        self.files_keys_warn_only = files_keys_warn_only

    def validate_file(self, file_path: str) -> Dict[str, Any]:
        """Validate a single source file."""
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            schema_errors = list(self.validator.iter_errors(data))
            error_messages = [self._format_error(error) for error in schema_errors]

            fk_messages = files_key_errors(data, file_label=file_path)
            warnings = self._check_warnings(data)

            if self.files_keys_warn_only:
                for msg in fk_messages:
                    warnings.append(f"[files] {msg}")
            else:
                error_messages.extend(fk_messages)

            return {
                "valid": len(error_messages) == 0,
                "file": file_path,
                "errors": error_messages,
                "warnings": warnings,
            }
        except json.JSONDecodeError as e:
            return {
                "valid": False,
                "file": file_path,
                "errors": [f"JSON syntax error: {e}"],
                "warnings": [],
            }
        except Exception as e:
            return {
                "valid": False,
                "file": file_path,
                "errors": [f"Validation error: {e}"],
                "warnings": [],
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

        if not data.get("fonts"):
            warnings.append("No fonts found in source")

        fonts = data.get("fonts", {})
        fonts_without_popularity = [
            font_id for font_id, font in fonts.items() if "popularity" not in font
        ]
        if fonts_without_popularity:
            warnings.append(f"Fonts without popularity data: {len(fonts_without_popularity)}")

        single_variant_fonts = [
            font_id for font_id, font in fonts.items() if len(font.get("variants", [])) == 1
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
        status = "[VALID]" if result["valid"] else "[INVALID]"
        print(f"{status} {result['file']}")

        if result["errors"]:
            print("  Errors:")
            for error in result["errors"]:
                print(f"    • {error}")

        if result["warnings"]:
            print("  Warnings:")
            for warning in result["warnings"]:
                print(f"    [WARNING] {warning}")

        print()


def _parse_argv(argv: List[str]) -> tuple[List[str], bool]:
    """Return (paths, files_keys_warn_only)."""
    warn = False
    paths: List[str] = []
    for a in argv:
        if a == "--files-keys-warn-only":
            warn = True
        else:
            paths.append(a)
    return paths, warn


def main():
    paths, files_keys_warn_only = _parse_argv(sys.argv[1:])
    if len(paths) < 1:
        print("Usage: python validate-sources.py [--files-keys-warn-only] <source-file.json> [...]")
        print("       python validate-sources.py [--files-keys-warn-only] <directory>")
        print()
        print("  --files-keys-warn-only   Report files-key / URL suffix issues as warnings, not errors.")
        sys.exit(1)

    validator = SourceValidator(files_keys_warn_only=files_keys_warn_only)
    results = []

    for arg in paths:
        if os.path.isfile(arg):
            results.append(validator.validate_file(arg))
        elif os.path.isdir(arg):
            results.extend(validator.validate_directory(arg))
        else:
            print(f"Error: {arg} is not a valid file or directory")
            sys.exit(1)

    print_results(results)

    if any(not result["valid"] for result in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
