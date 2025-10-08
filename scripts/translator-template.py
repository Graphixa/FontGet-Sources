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


class YourSourceTranslator:
    def __init__(self, api_key: Optional[str] = None):
        """Initialize translator with API key if needed."""
        self.api_key = api_key or os.getenv("YOUR_API_KEY")
        self.base_url = "https://your-api-endpoint.com/api"
        
        # Add any required validation
        if not self.api_key:
            raise ValueError("API key is required. Set YOUR_API_KEY environment variable.")
    
    def _normalize_category(self, category: str) -> str:
        """Normalize category with comprehensive enum mapping and fallback."""
        if not category or not category.strip():
            return "Other"
        
        # First normalize: replace hyphens/underscores with spaces, title case
        cleaned = category.replace("-", " ").replace("_", " ").strip()
        words = cleaned.split()
        normalized = " ".join(word.capitalize() for word in words)
        
        # 10-category mapping with intelligent fallback
        category_mapping = {
            # Core 10 categories
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
            
            # Additional re-mappings to core 10 categories
            "Typewriter": "Display",           # Typewriter → Display
            "Novelty": "Decorative",           # Novelty → Decorative
            "Comic": "Decorative",             # Comic → Decorative
            "Dingbat": "Symbol",               # Dingbat → Symbol
            "Handdrawn": "Handwriting",        # Handdrawn → Handwriting
            "Calligraphic": "Script",          # Calligraphic → Script
            "Cursive": "Script",               # Cursive → Script
            "Programming": "Monospace",        # Programming → Monospace
            "Retro": "Decorative",             # Retro → Decorative
            "Grunge": "Decorative",            # Grunge → Decorative
            "Pixel": "Decorative",             # Pixel → Decorative
            "Stencil": "Decorative",           # Stencil → Decorative
            "Monospaced": "Monospace",         # Monospaced → Monospace
            "Cursive": "Script",               # Cursive → Script
            
            # Add source-specific mappings here
            # "Your Source Category": "Mapped Category",
        }
        
        # Check for exact match after normalization
        if normalized in category_mapping:
            return category_mapping[normalized]
        
        # Check for case-insensitive match
        normalized_lower = normalized.lower()
        for key, value in category_mapping.items():
            if key.lower() == normalized_lower:
                return value
        
        # Fallback: return normalized (title case) for unknown categories
        # This allows custom sources to add new categories like "Graffiti", "Halloween", etc.
        return normalized
    
    def _clean_id(self, value: str) -> str:
        """Clean font ID to match schema requirements."""
        clean = re.sub(r"[^a-z0-9-]", "-", value.lower())
        clean = re.sub(r"-+", "-", clean).strip("-")
        return clean
    
    def _extract_tags(self, font_data: Dict[str, Any]) -> List[str]:
        """Extract all relevant tags from font data."""
        tags = []
        
        # Add common tags
        if "tags" in font_data:
            if isinstance(font_data["tags"], list):
                tags.extend(font_data["tags"])
            elif isinstance(font_data["tags"], str):
                tags.append(font_data["tags"])
        
        # Add source-specific tag extraction
        # if "your_tag_field" in font_data:
        #     tags.append(font_data["your_tag_field"])
        
        # Remove duplicates and empty tags
        return list(set(tag.strip() for tag in tags if tag.strip()))
    
    def fetch_fonts(self) -> Dict[str, Any]:
        """Fetch all fonts from your source API."""
        # TODO: Implement API call
        # Example:
        # params = {"key": self.api_key} if self.api_key else {}
        # response = requests.get(f"{self.base_url}/fonts", params=params)
        # response.raise_for_status()
        # return response.json()
        
        # For now, return empty structure
        return {"items": []}
    
    def translate_font(self, font_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Translate a single font from source format to FontGet format."""
        try:
            # Extract basic info
            font_name = font_data.get("name", "")
            if not font_name:
                return None
            
            font_id = self._clean_id(font_name)
            
            # Extract categories
            categories = []
            if "category" in font_data:
                category = font_data["category"]
                normalized_category = self._normalize_category(category)
                categories.append(normalized_category)
            
            # Extract variants
            variants = []
            # TODO: Implement variant extraction based on your API structure
            # Example:
            # for variant_data in font_data.get("variants", []):
            #     variant = self._parse_variant(variant_data, font_name)
            #     if variant:
            #         variants.append(variant)
            
            # Build font object
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
                "popularity": 0,  # TODO: Calculate based on your metrics
                "last_modified": datetime.utcnow().isoformat() + "Z",
                "metadata_url": font_data.get("metadata_url", ""),
                "source_url": font_data.get("source_url", ""),
                "variants": variants,
                "unicode_ranges": [],  # TODO: Extract if available
                "languages": [],       # TODO: Extract if available
                "sample_text": font_data.get("sample_text", "The quick brown fox jumps over the lazy dog"),
            }
            
            return font
            
        except Exception as e:
            print(f"Error translating font {font_data.get('name', 'unknown')}: {e}")
            return None
    
    def translate(self) -> Dict[str, Any]:
        """Main translation method."""
        print(f"Fetching fonts from {self.__class__.__name__}...")
        
        # Fetch data from API
        api_data = self.fetch_fonts()
        
        # Process fonts
        fonts = {}
        font_items = api_data.get("items", [])  # Adjust based on your API structure
        
        print(f"Found {len(font_items)} fonts")
        
        for font_data in font_items:
            translated_font = self.translate_font(font_data)
            if translated_font:
                font_id = self._clean_id(translated_font["name"])
                fonts[font_id] = translated_font
        
        print(f"Successfully transformed {len(fonts)} fonts")
        
        # Build source info
        source_info = {
            "name": "Your Source Name",  # TODO: Update
            "description": "Description of your font source",  # TODO: Update
            "url": "https://your-source-website.com",  # TODO: Update
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
    """Main entry point for the translator."""
    try:
        translator = YourSourceTranslator()
        source_data = translator.translate()
        
        # Ensure sources directory exists
        os.makedirs("sources", exist_ok=True)
        
        # Write output file
        output_file = "sources/your-source.json"  # TODO: Update filename
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(source_data, f, indent=2, ensure_ascii=False)
        
        print(f"Successfully generated {output_file} with {source_data['source_info']['total_fonts']} fonts")
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
