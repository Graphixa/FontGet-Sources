#!/usr/bin/env python3
"""
Font Squirrel Translator for FontGet

Fetches font data from Font Squirrel API and transforms it to FontGet format.
Uses Font Squirrel's public API to get font information.
"""

import json
import os
import requests
from datetime import datetime
from typing import Dict, List, Any, Optional
import re


class FontSquirrelTranslator:
    def __init__(self):
        """Initialize translator."""
        self.base_url = "https://www.fontsquirrel.com/api"
        self.fontlist_url = f"{self.base_url}/fontlist/all"
        self.familyinfo_url = f"{self.base_url}/familyinfo"
        
        # Font Squirrel categories mapping
        self.category_mapping = {
            "sans-serif": "Sans Serif",
            "serif": "Serif", 
            "display": "Display",
            "handwriting": "Handwriting",
            "monospace": "Monospace",
            "script": "Script",
            "decorative": "Decorative",
            "symbol": "Symbol",
            "icon": "Icon"
        }
    
    def fetch_fonts(self) -> List[Dict[str, Any]]:
        """Fetch all fonts from Font Squirrel API."""
        response = requests.get(self.fontlist_url)
        response.raise_for_status()
        return response.json()
    
    def fetch_font_details(self, font_urlname: str) -> Dict[str, Any]:
        """Fetch detailed information for a specific font using familyinfo API."""
        try:
            response = requests.get(f"{self.familyinfo_url}/{font_urlname}", timeout=10)
            response.raise_for_status()
            
            # Check if response is valid JSON
            if response.text.strip():
                return response.json()
            else:
                return {}
        except Exception as e:
            # Only print warning for first few failures to avoid spam
            print(f"Warning: Failed to fetch details for font {font_urlname}: {e}")
            return {}
    
    def transform_font(self, font_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform Font Squirrel data to FontGet format."""
        font_name = font_data.get("family_name", "")
        font_urlname = font_data.get("family_urlname", "")
        
        if not font_name or not font_urlname:
            return None
        
        # Skip detailed font information for now - just use basic data
        details = {}
        
        # Extract basic info
        family = font_name
        font_get_id = f"squirrel.{font_name.lower().replace(' ', '-')}"
        
        # Transform categories
        categories = []
        if "classification" in font_data:
            classification = font_data["classification"].lower()
            if classification in self.category_mapping:
                categories.append(self.category_mapping[classification])
        
        # Extract license information
        license_info = self._extract_license(font_data, details)
        
        # Transform variants
        variants = self._transform_variants(font_data, details)
        
        # Calculate popularity score
        popularity = self._calculate_popularity(font_data, details)
        
        # Extract tags
        tags = self._extract_tags(font_data, details)
        
        return {
            "name": font_name,
            "family": family,
            "license": license_info["type"],
            "license_url": license_info["url"],
            "designer": font_data.get("designer", ""),
            "foundry": font_data.get("foundry", "Font Squirrel"),
            "version": font_data.get("version", "1.0"),
            "description": font_data.get("description", ""),
            "categories": categories,
            "tags": tags,
            "popularity": popularity,
            "last_modified": font_data.get("date_added", ""),
            "metadata_url": f"https://www.fontsquirrel.com/fonts/{font_urlname}",
            "source_url": f"https://www.fontsquirrel.com/fonts/{font_urlname}",
            "variants": variants,
            "unicode_ranges": self._extract_unicode_ranges(font_data, details),
            "languages": self._extract_languages(font_data, details),
            "sample_text": "The quick brown fox jumps over the lazy dog"
        }
    
    def _extract_license(self, font_data: Dict[str, Any], details: Dict[str, Any]) -> Dict[str, str]:
        """Extract license information."""
        # Font Squirrel API doesn't provide license information
        # We need to use the individual license page for each font
        family_urlname = font_data.get("family_urlname", "")
        
        if family_urlname:
            license_url = f"https://www.fontsquirrel.com/license/{family_urlname}"
        else:
            license_url = ""
        
        return {
            "type": "See license page",
            "url": license_url
        }
    
    def _transform_variants(self, font_data: Dict[str, Any], details: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Transform font variants to FontGet format."""
        variants = []
        
        # Get variants from details if available
        font_files = details.get("font_files", []) if details and isinstance(details, dict) else []
        
        if not font_files:
            # Fallback: create basic variants from font data
            # Use the fontfacekit download URL for the font
            family_urlname = font_data.get("family_urlname", "")
            download_url = f"https://www.fontsquirrel.com/fontfacekit/{family_urlname}" if family_urlname else ""
            
            variants.append({
                "name": f"{font_data.get('family_name', 'Font')} Regular",
                "weight": 400,
                "style": "normal",
                "subsets": ["latin"],
                "files": {
                    "ttf": download_url
                }
            })
        else:
            # Process actual font files from familyinfo API
            for file_info in font_files:
                variant = self._create_variant_from_file(file_info, font_data.get("family_name", "Font"), font_data.get("family_urlname", ""))
                if variant:
                    variants.append(variant)
        
        return variants
    
    def _create_variant_from_file(self, file_info: Dict[str, Any], family_name: str, family_urlname: str = "") -> Optional[Dict[str, Any]]:
        """Create variant from file information."""
        filename = file_info.get("filename", "")
        download_url = file_info.get("download_url", "")
        style_name = file_info.get("style_name", "")
        
        if not filename:
            return None
        
        # Extract weight and style from filename or style_name
        if style_name:
            weight, style = self._parse_weight_style_from_name(style_name)
        else:
            weight, style = self._parse_weight_style(filename)
        
        # Determine file format
        file_format = "ttf"  # Default
        if filename.endswith(".otf"):
            file_format = "otf"
        elif filename.endswith(".fon"):
            file_format = "fon"
        
        variant_name = self._generate_variant_name(family_name, weight, style)
        
        # Use download_url if available, otherwise use fontfacekit URL
        if not download_url and family_urlname:
            # Font Squirrel files are available via fontfacekit:
            # https://www.fontsquirrel.com/fontfacekit/{family_urlname}
            download_url = f"https://www.fontsquirrel.com/fontfacekit/{family_urlname}"
        
        return {
            "name": variant_name,
            "weight": weight,
            "style": style,
            "subsets": ["latin", "latin-ext"],
            "files": {
                file_format: download_url
            }
        }
    
    def _parse_weight_style(self, filename: str) -> tuple[int, str]:
        """Parse weight and style from filename."""
        filename_lower = filename.lower()
        
        # Determine style
        if "italic" in filename_lower or "oblique" in filename_lower:
            style = "italic"
        else:
            style = "normal"
        
        # Determine weight
        if "thin" in filename_lower or "100" in filename:
            weight = 100
        elif "extralight" in filename_lower or "ultralight" in filename_lower or "200" in filename:
            weight = 200
        elif "light" in filename_lower or "300" in filename:
            weight = 300
        elif "regular" in filename_lower or "normal" in filename_lower or "400" in filename:
            weight = 400
        elif "medium" in filename_lower or "500" in filename:
            weight = 500
        elif "semibold" in filename_lower or "demi" in filename_lower or "600" in filename:
            weight = 600
        elif "bold" in filename_lower or "700" in filename:
            weight = 700
        elif "extrabold" in filename_lower or "ultrabold" in filename_lower or "800" in filename:
            weight = 800
        elif "black" in filename_lower or "heavy" in filename_lower or "900" in filename:
            weight = 900
        else:
            weight = 400  # Default
        
        return weight, style
    
    def _parse_weight_style_from_name(self, style_name: str) -> tuple[int, str]:
        """Parse weight and style from style name."""
        style_lower = style_name.lower()
        
        # Determine style
        if "italic" in style_lower or "oblique" in style_lower:
            style = "italic"
        else:
            style = "normal"
        
        # Determine weight
        if "thin" in style_lower or "100" in style_name:
            weight = 100
        elif "extralight" in style_lower or "ultralight" in style_lower or "200" in style_name:
            weight = 200
        elif "light" in style_lower or "300" in style_name:
            weight = 300
        elif "regular" in style_lower or "normal" in style_lower or "400" in style_name:
            weight = 400
        elif "medium" in style_lower or "500" in style_name:
            weight = 500
        elif "semibold" in style_lower or "demi" in style_lower or "600" in style_name:
            weight = 600
        elif "bold" in style_lower or "700" in style_name:
            weight = 700
        elif "extrabold" in style_lower or "ultrabold" in style_lower or "800" in style_name:
            weight = 800
        elif "black" in style_lower or "heavy" in style_lower or "900" in style_name:
            weight = 900
        else:
            weight = 400  # Default
        
        return weight, style
    
    def _generate_variant_name(self, family_name: str, weight: int, style: str) -> str:
        """Generate variant name."""
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
        
        weight_name = weight_names.get(weight, str(weight))
        style_name = "Italic" if style == "italic" else ""
        
        if style_name:
            return f"{family_name} {weight_name} {style_name}"
        else:
            return f"{family_name} {weight_name}"
    
    def _calculate_popularity(self, font_data: Dict[str, Any], details: Dict[str, Any]) -> int:
        """Calculate popularity score."""
        score = 50  # Base score
        
        # Bonus for having description
        if font_data.get("description"):
            score += 10
        
        # Bonus for having designer info
        if font_data.get("designer"):
            score += 10
        
        # Bonus for having multiple variants
        if details and details.get("font_files"):
            score += min(len(details["font_files"]) * 5, 20)
        
        # Bonus for being recently added
        if font_data.get("date_added"):
            try:
                date_added = datetime.fromisoformat(font_data["date_added"].replace("Z", "+00:00"))
                days_old = (datetime.now() - date_added).days
                if days_old < 30:
                    score += 10
                elif days_old < 90:
                    score += 5
            except:
                pass
        
        return min(score, 100)
    
    def _extract_tags(self, font_data: Dict[str, Any], details: Dict[str, Any]) -> List[str]:
        """Extract tags from font data."""
        tags = []
        
        # Add classification as tag
        if "classification" in font_data:
            tags.append(font_data["classification"].lower().replace(" ", "-"))
        
        # Add style tags
        if font_data.get("designer"):
            tags.append("designer-font")
        
        if font_data.get("foundry"):
            tags.append("foundry-font")
        
        # Add from details if available
        if details and details.get("tags"):
            tags.extend(details["tags"])
        
        return list(set(tags))  # Remove duplicates
    
    def _extract_unicode_ranges(self, font_data: Dict[str, Any], details: Dict[str, Any]) -> List[str]:
        """Extract Unicode ranges."""
        # Font Squirrel doesn't provide detailed Unicode ranges
        # Return common ranges
        return ["U+0000-00FF", "U+0100-017F"]
    
    def _extract_languages(self, font_data: Dict[str, Any], details: Dict[str, Any]) -> List[str]:
        """Extract supported languages."""
        # Font Squirrel doesn't provide detailed language info
        # Return common languages
        return ["Latin", "Latin Extended"]
    
    def translate(self, limit: int = None) -> Dict[str, Any]:
        """Main translation function."""
        print("Fetching fonts from Font Squirrel API...")
        raw_data = self.fetch_fonts()
        
        print(f"Found {len(raw_data)} fonts")
        
        # Limit fonts for testing if specified
        if limit:
            raw_data = raw_data[:limit]
            print(f"Processing first {limit} fonts for testing")
        
        # Transform fonts
        fonts = {}
        for font_data in raw_data:
            try:
                transformed = self.transform_font(font_data)
                if transformed:
                    # Clean font name for ID: lowercase, replace spaces/special chars with hyphens
                    clean_name = re.sub(r'[^a-z0-9-]', '-', font_data['family_name'].lower())
                    clean_name = re.sub(r'-+', '-', clean_name).strip('-')
                    font_id = clean_name
                    fonts[font_id] = transformed
            except Exception as e:
                print(f"Warning: Failed to transform font {font_data.get('family_name', 'unknown')}: {e}")
                continue
        
        print(f"Successfully transformed {len(fonts)} fonts")
        
        # Create source structure
        source_data = {
            "source_info": {
                "name": "Font Squirrel",
                "description": "Free fonts from Font Squirrel",
                "url": "https://www.fontsquirrel.com",
                "api_endpoint": "https://www.fontsquirrel.com/api/fontlist/all",
                "version": "1.0",
                "last_updated": datetime.utcnow().isoformat() + "Z",
                "total_fonts": len(fonts)
            },
            "fonts": fonts
        }
        
        return source_data


def main():
    """Main function."""
    try:
        translator = FontSquirrelTranslator()
        # Limit to 50 fonts for testing - remove limit for production
        source_data = translator.translate(limit=50)
        
        # Write to file
        output_file = "sources/font-squirrel.json"
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
