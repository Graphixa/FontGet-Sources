#!/usr/bin/env python3
"""
Nerd Fonts Translator for FontGet

Fetches font data from Nerd Fonts GitHub releases and transforms it to FontGet format.
Uses GitHub API to get release information and font files.
"""

import json
import os
import requests
from datetime import datetime
from typing import Dict, List, Any, Optional
import re


class NerdFontsTranslator:
    def __init__(self):
        """Initialize translator."""
        self.base_url = "https://api.github.com/repos/ryanoasis/nerd-fonts"
        self.releases_url = f"{self.base_url}/releases"
        self.contents_url = f"{self.base_url}/contents"
        
        # Common Nerd Fonts patterns
        self.font_patterns = {
            "FiraCode": "Fira Code",
            "JetBrainsMono": "JetBrains Mono", 
            "CascadiaCode": "Cascadia Code",
            "SourceCodePro": "Source Code Pro",
            "Hack": "Hack",
            "RobotoMono": "Roboto Mono",
            "UbuntuMono": "Ubuntu Mono",
            "DejaVuSansMono": "DejaVu Sans Mono",
            "DroidSansMono": "Droid Sans Mono",
            "Mononoki": "Mononoki",
            "Noto": "Noto Sans Mono",
            "SpaceMono": "Space Mono",
            "Terminus": "Terminus",
            "VictorMono": "Victor Mono",
            "Meslo": "Meslo",
            "Lilex": "Lilex",
            "Iosevka": "Iosevka",
            "Agave": "Agave",
            "Arimo": "Arimo",
            "AurulentSansMono": "Aurulent Sans Mono",
            "BigBlueTerminal": "Big Blue Terminal",
            "BitstreamVeraSansMono": "Bitstream Vera Sans Mono",
            "BlexMono": "Blex Mono",
            "CodeNewRoman": "Code New Roman",
            "ComicShannsMono": "Comic Shanns Mono",
            "Cousine": "Cousine",
            "DaddyTimeMono": "DaddyTime Mono",
            "FantasqueSansMono": "Fantasque Sans Mono",
            "GoMono": "Go Mono",
            "Gohu": "Gohu",
            "HeavyData": "Heavy Data",
            "Hermit": "Hermit",
            "iA-Writer": "iA Writer Mono",
            "IBMPlexMono": "IBM Plex Mono",
            "Inconsolata": "Inconsolata",
            "InconsolataGo": "Inconsolata Go",
            "InconsolataLGC": "Inconsolata LGC",
            "IntelOneMono": "Intel One Mono",
            "Lekton": "Lekton",
            "LiberationMono": "Liberation Mono",
            "LuxiMono": "Luxi Mono",
            "MPlus": "M+",
            "Overpass": "Overpass Mono",
            "ProFont": "ProFont",
            "ProggyClean": "ProggyClean",
            "PTMono": "PT Mono",
            "Raleway": "Raleway",
            "SauceCodePro": "Sauce Code Pro",
            "ShureTechMono": "Shure Tech Mono",
            "Tinos": "Tinos",
            "Tight": "Tight",
            "TlwgMono": "Tlwg Mono",
            "TwilioSansMono": "Twilio Sans Mono",
            "VazirCode": "Vazir Code",
            "YaHeiConsolasHybrid": "YaHei Consolas Hybrid"
        }
    
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
    
    def fetch_releases(self) -> List[Dict[str, Any]]:
        """Fetch all releases from Nerd Fonts GitHub."""
        response = requests.get(self.releases_url)
        response.raise_for_status()
        return response.json()
    
    def get_latest_release(self) -> Dict[str, Any]:
        """Get the latest release."""
        releases = self.fetch_releases()
        if not releases:
            raise ValueError("No releases found")
        return releases[0]
    
    def extract_font_info_from_assets(self, assets: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Extract font information from release assets."""
        fonts = {}
        
        for asset in assets:
            name = asset["name"]
            download_url = asset["browser_download_url"]
            
            # Skip non-font files
            if not name.endswith(('.zip', '.tar.xz')):
                continue
            
            # Extract font name from filename
            font_name = self._extract_font_name(name)
            if not font_name:
                continue
            
            # Clean font name for ID: lowercase, replace spaces/special chars with hyphens
            clean_name = re.sub(r'[^a-z0-9-]', '-', font_name.lower())
            clean_name = re.sub(r'-+', '-', clean_name).strip('-')
            font_id = clean_name
            
            if font_id not in fonts:
                fonts[font_id] = {
                    "name": font_name,
                    "family": font_name,
                    "license": "Mixed",  # Nerd Fonts combines original font licenses with added icon licenses
                    "license_url": "https://raw.githubusercontent.com/ryanoasis/nerd-fonts/refs/heads/master/LICENSE",
                    "designer": "Ryan L McIntyre (Nerd Fonts Patcher)",
                    "foundry": "Nerd Fonts",
                    "version": "3.0.2",  # Current Nerd Fonts version
                    "description": f"Patched version of {font_name} with additional icon glyphs",
                    "categories": [self._normalize_category("Nerd Font")],
                    "tags": ["nerd-fonts", "icons", "patched", "monospace", "programming"],
                    "popularity": self._calculate_popularity(font_name),
                    "last_modified": datetime.utcnow().isoformat() + "Z",
                    "metadata_url": "https://github.com/ryanoasis/nerd-fonts",
                    "source_url": f"https://github.com/ryanoasis/nerd-fonts/releases/latest",
                    "variants": [],
                    "unicode_ranges": ["U+0000-00FF", "U+2190-21FF", "U+2600-26FF", "U+1F300-1F5FF"],
                    "languages": ["Latin", "Symbols"],
                    "sample_text": "Hello World! ⚡ 🔥 💻"
                }
            
            # Add variant information
            variant = self._create_variant(name, download_url, font_name)
            if variant:
                fonts[font_id]["variants"].append(variant)
        
        return fonts
    
    def _extract_font_name(self, filename: str) -> Optional[str]:
        """Extract font name from filename."""
        # Remove common suffixes
        name = filename.replace('.zip', '').replace('.tar.xz', '')
        
        # Try to match known patterns
        for pattern, display_name in self.font_patterns.items():
            if pattern.lower() in name.lower():
                return display_name
        
        # Try to extract from common patterns
        # Remove "NerdFont" or "Nerd Font" from name
        name = re.sub(r'[Nn]erd[Ff]ont[s]?', '', name)
        name = re.sub(r'[Nn]erd\s*[Ff]ont[s]?', '', name)
        
        # Remove version numbers
        name = re.sub(r'v?\d+\.\d+\.?\d*', '', name)
        
        # Clean up and format
        name = name.replace('_', ' ').replace('-', ' ').strip()
        if name:
            return name.title()
        
        return None
    
    def _create_variant(self, filename: str, download_url: str, font_name: str) -> Optional[Dict[str, Any]]:
        """Create variant information from filename."""
        # Nerd Fonts typically have Regular and Bold variants
        if "Bold" in filename or "bold" in filename:
            weight = 700
            style = "normal"
            name = f"{font_name} Bold"
        else:
            weight = 400
            style = "normal"
            name = f"{font_name} Regular"
        
        return {
            "name": name,
            "weight": weight,
            "style": style,
            "subsets": ["latin", "latin-ext"],
            "files": {
                "ttf": download_url  # Nerd Fonts provides zip files with TTF inside
            }
        }
    
    def _calculate_popularity(self, font_name: str) -> int:
        """Calculate popularity score based on font name."""
        # Popular programming fonts get higher scores
        popular_fonts = {
            "Fira Code": 95,
            "JetBrains Mono": 90,
            "Cascadia Code": 85,
            "Source Code Pro": 80,
            "Hack": 75,
            "Roboto Mono": 70,
            "Ubuntu Mono": 65,
            "DejaVu Sans Mono": 60,
            "Mononoki": 55,
            "Noto Sans Mono": 50,
            "Space Mono": 45,
            "Terminus": 40,
            "Victor Mono": 35,
            "Meslo": 30
        }
        
        return popular_fonts.get(font_name, 25)
    
    def translate(self) -> Dict[str, Any]:
        """Main translation function."""
        print("Fetching Nerd Fonts release data...")
        latest_release = self.get_latest_release()
        
        print(f"Processing release: {latest_release['tag_name']}")
        print(f"Found {len(latest_release['assets'])} assets")
        
        # Extract font information
        fonts = self.extract_font_info_from_assets(latest_release['assets'])
        
        print(f"Extracted {len(fonts)} fonts")
        
        # Create source structure
        source_data = {
            "source_info": {
                "name": "Nerd Fonts",
                "description": "Patched fonts with additional icon glyphs for programming",
                "url": "https://www.nerdfonts.com",
                "api_endpoint": "https://api.github.com/repos/ryanoasis/nerd-fonts/releases",
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
        translator = NerdFontsTranslator()
        source_data = translator.translate()
        
        # Write to file
        output_file = "sources/nerd-fonts.json"
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
