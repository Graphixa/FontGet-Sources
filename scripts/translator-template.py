#!/usr/bin/env python3
"""
Font Source Translator Template for FontGet

Template for creating new font source translators.
Copy this file and modify for your specific font source API.

Required: Update the class name, API endpoints, and data extraction logic.
"""

import json
import os
import re
from datetime import datetime
from typing import Dict, List, Any, Optional

import requests

# Omit ids present in sources/google-fonts.json when True (see sibling translators).
DEDUPLICATE_GOOGLE_FONTS = False


class YourSourceTranslator:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("YOUR_API_KEY")
        self.base_url = "https://your-api-endpoint.com/api"

        if not self.api_key:
            raise ValueError("API key is required. Set YOUR_API_KEY environment variable.")
    
    def _normalize_category(self, category: str) -> str:
        if not category or not category.strip():
            return "Other"

        cleaned = category.replace("-", " ").replace("_", " ").strip()
        words = cleaned.split()
        normalized = " ".join(word.capitalize() for word in words)

        category_mapping = {
            "Sans Serif": "Sans Serif",
            "Serif": "Serif",
            "Slab Serif": "Slab Serif",
            "Display": "Display",
            "Monospace": "Monospace",
            "Script": "Script",
            "Handwriting": "Handwriting",
            "Decorative": "Decorative",
            "Symbol": "Symbol",
            "Blackletter": "Blackletter",
            "Typewriter": "Display",
            "Novelty": "Decorative",
            "Comic": "Decorative",
            "Dingbat": "Symbol",
            "Handdrawn": "Handwriting",
            "Calligraphic": "Script",
            "Cursive": "Script",
            "Programming": "Monospace",
            "Retro": "Decorative",
            "Grunge": "Decorative",
            "Pixel": "Decorative",
            "Stencil": "Decorative",
            "Monospaced": "Monospace",
        }

        if normalized in category_mapping:
            return category_mapping[normalized]

        normalized_lower = normalized.lower()
        for key, value in category_mapping.items():
            if key.lower() == normalized_lower:
                return value

        return normalized

    def _clean_id(self, value: str) -> str:
        clean = re.sub(r"[^a-z0-9-]", "-", value.lower())
        clean = re.sub(r"-+", "-", clean).strip("-")
        return clean
    
    def _extract_tags(self, font_data: Dict[str, Any]) -> List[str]:
        tags = []

        if "tags" in font_data:
            if isinstance(font_data["tags"], list):
                tags.extend(font_data["tags"])
            elif isinstance(font_data["tags"], str):
                tags.append(font_data["tags"])

        return list(set(tag.strip() for tag in tags if tag.strip()))

    def fetch_fonts(self) -> Dict[str, Any]:
        # TODO: GET self.base_url/fonts etc.
        return {"items": []}

    def translate_font(self, font_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            font_name = font_data.get("name", "")
            if not font_name:
                return None

            font_id = self._clean_id(font_name)

            categories = []
            if "category" in font_data:
                category = font_data["category"]
                normalized_category = self._normalize_category(category)
                categories.append(normalized_category)

            variants = []

            font = {
                "name": font_name,
                "family": font_name,
                "license": font_data.get("license", "Unknown"),
                "license_url": font_data.get("license_url", ""),
                "designer": font_data.get("designer", ""),
                "foundry": font_data.get("foundry", ""),
                "version": font_data.get("version", "1.0"),
                "description": font_data.get("description", ""),
                "categories": categories,
                "tags": self._extract_tags(font_data),
                "popularity": 0,
                "last_modified": datetime.utcnow().isoformat() + "Z",
                "metadata_url": font_data.get("metadata_url", ""),
                "source_url": font_data.get("source_url", ""),
                "variants": variants,
                "unicode_ranges": [],
                "languages": [],
                "sample_text": font_data.get("sample_text", "The quick brown fox jumps over the lazy dog"),
            }
            
            return font

        except Exception as e:
            print(f"Warning: Failed to translate font {font_data.get('name', 'unknown')}: {e}")
            return None
    
    def translate(self) -> Dict[str, Any]:
        print("Fetching your font source…")

        api_data = self.fetch_fonts()

        fonts = {}
        font_items = api_data.get("items", [])

        print(f"Found {len(font_items)} items from upstream.")
        
        for font_data in font_items:
            translated_font = self.translate_font(font_data)
            if translated_font:
                font_id = self._clean_id(translated_font["name"])
                fonts[font_id] = translated_font
        
        print(f"Built {len(fonts)} font families.")

        source_info = {
            "name": "Your Source Name",
            "description": "Description of your font source",
            "url": "https://your-source-website.com",
            "api_endpoint": self.base_url,
            "version": "1.0",
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "total_fonts": len(fonts),
        }
        
        return {
            "source_info": source_info,
            "fonts": fonts,
        }


def main() -> int:
    try:
        translator = YourSourceTranslator()
        source_data = translator.translate()

        os.makedirs("sources", exist_ok=True)

        output_file = "sources/your-source.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(source_data, f, indent=2, ensure_ascii=False)
        
        n = source_data["source_info"]["total_fonts"]
        print(f"Wrote {output_file} ({n} fonts).")
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
