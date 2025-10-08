#!/usr/bin/env python3
"""
Google Fonts API Translator for FontGet

Fetches font data from Google Fonts API and transforms it to FontGet format.
Requires GOOGLE_FONTS_API_KEY environment variable.
"""

import json
import os
import requests
import re
from datetime import datetime
from typing import Dict, List, Any, Optional


class GoogleFontsTranslator:
    def __init__(self, api_key: Optional[str] = None):
        """Initialize translator with API key."""
        # Hardcoded for local testing
        self.api_key = api_key or os.getenv("GOOGLE_FONTS_API_KEY")
        self.base_url = "https://www.googleapis.com/webfonts/v1/webfonts"
        
        if not self.api_key:
            raise ValueError("Google Fonts API key is required. Set GOOGLE_FONTS_API_KEY environment variable.")
    
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
            
            #Additional re-mappings to core 10 categories
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
    
    def fetch_fonts(self) -> Dict[str, Any]:
        """Fetch all fonts from Google Fonts API."""
        params = {
            "key": self.api_key,
            "sort": "popularity"  # Sort by popularity for better user experience
        }
        
        response = requests.get(self.base_url, params=params)
        response.raise_for_status()
        return response.json()
    
    def transform_font(self, font_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform Google Fonts data to FontGet format."""
        # Extract basic info
        family = font_data["family"]
        # Clean font name for ID: lowercase, replace spaces/special chars with hyphens
        clean_name = re.sub(r'[^a-z0-9-]', '-', family.lower())
        clean_name = re.sub(r'-+', '-', clean_name).strip('-')
        font_id = clean_name
        
        # Transform variants
        variants = []
        for variant in font_data.get("variants", []):
            variant_data = self._parse_variant(variant, family, font_data)
            if variant_data:
                variants.append(variant_data)
        
        # Extract categories (normalize to title case)
        categories = []
        if "category" in font_data:
            category = font_data["category"]
            normalized_category = self._normalize_category(category)
            categories.append(normalized_category)
        
        # Calculate popularity score (0-100)
        popularity = self._calculate_popularity(font_data)
        
        return {
            "name": family,
            "family": family,
            "license": "OFL",  # Temporarily disabled license extraction for speed
            "license_url": f"https://fonts.google.com/specimen/{family.replace(' ', '+')}/license",
            "designer": font_data.get("designer", ""),
            "foundry": "Google",
            "version": font_data.get("version", "1.0"),
            "description": font_data.get("description", ""),
            "categories": categories,
            "tags": self._extract_tags(font_data),
            "popularity": popularity,
            "last_modified": font_data.get("lastModified", ""),
            "metadata_url": f"https://raw.githubusercontent.com/google/fonts/main/ofl/{family.lower().replace(' ', '')}/METADATA.pb",
            "source_url": f"https://fonts.google.com/specimen/{family.replace(' ', '+')}",
            "variants": variants,
            "unicode_ranges": self._extract_unicode_ranges(font_data),
            "languages": self._extract_languages(font_data),
            "sample_text": "The quick brown fox jumps over the lazy dog"
        }
    
    def _parse_variant(self, variant: str, family: str, font_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse Google Fonts variant string into FontGet format."""
        # Google Fonts variants are like "regular", "700", "italic", "700italic"
        if variant == "regular":
            weight = 400
            style = "normal"
            name = f"{family} Regular"
        elif variant == "italic":
            weight = 400
            style = "italic"
            name = f"{family} Italic"
        elif variant.isdigit():
            weight = int(variant)
            style = "normal"
            name = f"{family} {self._weight_to_name(weight)}"
        elif variant.endswith("italic"):
            weight = int(variant[:-6])
            style = "italic"
            name = f"{family} {self._weight_to_name(weight)} Italic"
        else:
            # Skip unsupported variants
            return None
        
        # Generate file URLs using actual Google Fonts API data
        files = self._generate_file_urls(font_data, variant)
        
        return {
            "name": name,
            "weight": weight,
            "style": style,
            "subsets": ["latin", "latin-ext"],  # Default subsets
            "files": files
        }
    
    def _weight_to_name(self, weight: int) -> str:
        """Convert numeric weight to name."""
        weight_names = {
            100: "Thin",
            200: "Extra Light",
            300: "Light",
            400: "Regular",
            500: "Medium",
            600: "Semi Bold",
            700: "Bold",
            800: "Extra Bold",
            900: "Black"
        }
        return weight_names.get(weight, str(weight))
    
    def _generate_file_urls(self, font_data: Dict[str, Any], variant: str) -> Dict[str, str]:
        """Generate file URLs for a font variant using actual Google Fonts API data."""
        files = {}
        
        # Get the actual file URL from Google Fonts API
        font_files = font_data.get("files", {})
        if variant in font_files:
            # Google Fonts provides direct download URLs
            file_url = font_files[variant]
            # Determine file type from URL or default to ttf
            if file_url.endswith('.ttf'):
                files["ttf"] = file_url
            elif file_url.endswith('.otf'):
                files["otf"] = file_url
            else:
                # Default to ttf for Google Fonts
                files["ttf"] = file_url
        
        return files
    
    def _calculate_popularity(self, font_data: Dict[str, Any]) -> int:
        """Calculate popularity score (0-100) based on available data."""
        # Google Fonts doesn't provide explicit popularity scores
        # We'll use a simple heuristic based on available data
        variants_count = len(font_data.get("variants", []))
        subsets_count = len(font_data.get("subsets", []))
        
        # Base score from variants (more variants = more popular)
        score = min(variants_count * 10, 50)
        
        # Bonus for more subsets
        score += min(subsets_count * 5, 30)
        
        # Bonus for having description
        if font_data.get("description"):
            score += 10
        
        # Bonus for having designer info
        if font_data.get("designer"):
            score += 10
        
        return min(score, 100)
    
    def _extract_tags(self, font_data: Dict[str, Any]) -> List[str]:
        """Extract tags from font data."""
        tags = []
        
        # Add category as tag
        if "category" in font_data:
            tags.append(font_data["category"].lower().replace(" ", "-"))
        
        # Add style tags based on variants
        variants = font_data.get("variants", [])
        if any("italic" in v for v in variants):
            tags.append("italic")
        if any(v.isdigit() and int(v) >= 700 for v in variants):
            tags.append("bold")
        
        return tags
    
    def _extract_unicode_ranges(self, font_data: Dict[str, Any]) -> List[str]:
        """Extract Unicode ranges from font data."""
        # Google Fonts doesn't provide detailed Unicode ranges in the API
        # We'll return common ranges based on subsets
        subsets = font_data.get("subsets", [])
        ranges = []
        
        if "latin" in subsets:
            ranges.append("U+0000-00FF")
        if "latin-ext" in subsets:
            ranges.append("U+0100-017F")
        if "cyrillic" in subsets:
            ranges.append("U+0400-04FF")
        if "greek" in subsets:
            ranges.append("U+0370-03FF")
        
        return ranges
    
    def _extract_languages(self, font_data: Dict[str, Any]) -> List[str]:
        """Extract supported languages from font data."""
        subsets = font_data.get("subsets", [])
        languages = []
        
        subset_languages = {
            "latin": "Latin",
            "latin-ext": "Latin Extended",
            "cyrillic": "Cyrillic",
            "cyrillic-ext": "Cyrillic Extended",
            "greek": "Greek",
            "greek-ext": "Greek Extended",
            "vietnamese": "Vietnamese",
            "arabic": "Arabic",
            "devanagari": "Devanagari",
            "hebrew": "Hebrew",
            "thai": "Thai",
            "chinese-simplified": "Chinese Simplified",
            "chinese-traditional": "Chinese Traditional",
            "japanese": "Japanese",
            "korean": "Korean"
        }
        
        for subset in subsets:
            if subset in subset_languages:
                languages.append(subset_languages[subset])
        
        return languages
    
    def translate(self) -> Dict[str, Any]:
        """Main translation function."""
        print("Fetching fonts from Google Fonts API...")
        raw_data = self.fetch_fonts()
        
        total_fonts = len(raw_data.get('items', []))
        print(f"Found {total_fonts} fonts")
        
        # Transform fonts
        fonts = {}
        for i, font_data in enumerate(raw_data.get("items", []), 1):
            try:
                if i % 50 == 0 or i == 1:  # Log every 50 fonts
                    print(f"Processing font {i}/{total_fonts}: {font_data.get('family', 'Unknown')}")
                
                transformed = self.transform_font(font_data)
                # Clean font name for ID: lowercase, replace spaces/special chars with hyphens
                clean_name = re.sub(r'[^a-z0-9-]', '-', font_data['family'].lower())
                clean_name = re.sub(r'-+', '-', clean_name).strip('-')
                font_id = clean_name
                fonts[font_id] = transformed
            except Exception as e:
                print(f"Warning: Failed to transform font {font_data.get('family', 'unknown')}: {e}")
                continue
        
        # Create source structure
        source_data = {
            "source_info": {
                "name": "Google Fonts",
                "description": "Open source fonts from Google",
                "url": "https://fonts.google.com",
                "api_endpoint": "https://www.googleapis.com/webfonts/v1/webfonts",
                "version": "1.0",
                "last_updated": datetime.utcnow().isoformat() + "Z",
                "total_fonts": len(fonts)
            },
            "fonts": fonts
        }
        
        return source_data
    
    def _extract_google_fonts_license(self, font_data: Dict[str, Any]) -> str:
        """Extract license from Google Fonts METADATA.pb file."""
        family = font_data['family']
        
        # Clean family name for URL
        family_clean = family.lower().replace(' ', '')
        
        # Try to fetch METADATA.pb file
        try:
            url = f"https://raw.githubusercontent.com/google/fonts/main/ofl/{family_clean}/METADATA.pb"
            response = requests.get(url, timeout=3)  # Reduced timeout
            
            if response.status_code == 200:
                content = response.text
                # Extract license line
                for line in content.split('\n'):
                    if line.strip().startswith('license:'):
                        # Extract license from: license: "OFL"
                        license_match = line.split('"')
                        if len(license_match) > 1:
                            return license_match[1]  # Return "OFL"
        except Exception as e:
            # Don't print warnings for every failed license fetch to reduce noise
            pass
        
        # Fallback: Most Google Fonts are OFL
        return "OFL"


def main():
    """Main function."""
    try:
        translator = GoogleFontsTranslator()
        source_data = translator.translate()
        
        # Write to file
        output_file = "sources/google-fonts.json"
        os.makedirs("sources", exist_ok=True)
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(source_data, f, indent=2, ensure_ascii=False)
        
        print(f"Successfully generated {output_file} with {len(source_data['fonts'])} fonts")
        
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
