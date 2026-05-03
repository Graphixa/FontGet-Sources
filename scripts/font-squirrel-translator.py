#!/usr/bin/env python3
"""
Font Squirrel Translator for FontGet

Fetches font data from Font Squirrel API and transforms it to FontGet format.
Uses Font Squirrel's public API to get font information.

``/fontfacekit/{family_urlname}`` responses are ZIP webfont kits (CSS plus fonts);
variant ``files`` use a ``zip`` key for those URLs. Direct file URLs use extension keys.

When ``DEDUPLICATE_GOOGLE_FONTS`` is True, families whose normalized id matches an entry in
``sources/google-fonts.json`` are omitted from retrieval (name/slug match, not binary identity).
``--no-google-dedupe`` disables that for one run.
"""

import argparse
import json
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from urllib.parse import urlparse
import re

# When True, omit Font Squirrel families that already appear in ``sources/google-fonts.json``.
DEDUPLICATE_GOOGLE_FONTS = True


def _font_id_from_family_name(family_name: str) -> str:
    clean_name = re.sub(r"[^a-z0-9-]", "-", family_name.lower())
    clean_name = re.sub(r"-+", "-", clean_name).strip("-")
    return clean_name


def _load_google_font_family_ids(google_fonts_json: Path) -> Set[str]:
    with open(google_fonts_json, encoding="utf-8") as f:
        data = json.load(f)
    ids: Set[str] = set()
    for key, entry in data.get("fonts", {}).items():
        ids.add(key)
        fam = (entry.get("family") or entry.get("name") or "").strip()
        if fam:
            ids.add(_font_id_from_family_name(fam))
    return ids


class FontSquirrelTranslator:
    FONTFACEKIT_PATH = "/fontfacekit/"

    def __init__(self):
        self.base_url = "https://www.fontsquirrel.com/api"
        self.fontlist_url = f"{self.base_url}/fontlist/all"
        self.familyinfo_url = f"{self.base_url}/familyinfo"

    @staticmethod
    def _fontfacekit_download_url(family_urlname: str) -> str:
        if not family_urlname or not str(family_urlname).strip():
            return ""
        return f"https://www.fontsquirrel.com/fontfacekit/{family_urlname.strip()}"

    def _is_zip_bundle_url(self, url: str) -> bool:
        if not url or not url.strip():
            return False
        if self.FONTFACEKIT_PATH in url.lower():
            return True
        path = urlparse(url).path.lower()
        return path.endswith(".zip")

    def _files_dict_for_download_url(self, url: str) -> Dict[str, str]:
        if not url or not url.strip():
            return {}
        url = url.strip()
        if self._is_zip_bundle_url(url):
            return {"zip": url}
        path = urlparse(url).path.lower()
        if path.endswith(".tar.xz"):
            return {"tar_xz": url}
        if path.endswith(".ttf"):
            return {"ttf": url}
        if path.endswith(".otf"):
            return {"otf": url}
        return {}
    
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

    def _map_category(self, classification: str) -> str:
        if classification and classification.strip():
            return self._normalize_category(classification)

        print("Note: empty Font Squirrel category — mapping to 'Other'.")
        return "Other"

    def fetch_fonts(self) -> List[Dict[str, Any]]:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; FontGet/1.0; +https://github.com/Graphixa/FontGet-Sources)'
            }
            response = requests.get(self.fontlist_url, headers=headers, timeout=30)
            response.raise_for_status()

            if not response.text or not response.text.strip():
                raise ValueError(f"Empty response from Font Squirrel API: {self.fontlist_url}")

            try:
                data = response.json()
            except json.JSONDecodeError as e:
                preview = response.text[:500] if len(response.text) > 500 else response.text
                raise ValueError(
                    f"Invalid JSON response from Font Squirrel API. "
                    f"Status: {response.status_code}, "
                    f"Content-Type: {response.headers.get('Content-Type', 'unknown')}, "
                    f"Response preview: {preview}"
                ) from e
            
            return data
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to fetch fonts from Font Squirrel API: {e}") from e
    
    def fetch_font_details(self, font_urlname: str) -> Dict[str, Any]:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; FontGet/1.0; +https://github.com/Graphixa/FontGet-Sources)'
            }
            response = requests.get(f"{self.familyinfo_url}/{font_urlname}", headers=headers, timeout=10)
            response.raise_for_status()

            if response.text.strip():
                return response.json()
            return {}
        except Exception as e:
            print(f"Warning: Failed to fetch details for font {font_urlname}: {e}")
            return {}

    def transform_font(self, font_data: Dict[str, Any]) -> Dict[str, Any]:
        font_name = font_data.get("family_name", "")
        font_urlname = font_data.get("family_urlname", "")
        
        if not font_name or not font_urlname:
            return None

        details = {}

        family = font_name
        font_get_id = font_name.lower().replace(' ', '-')

        categories = []
        if "classification" in font_data:
            classification = font_data["classification"]
            mapped_category = self._map_category(classification)
            categories.append(mapped_category)

        license_info = self._extract_license(font_data, details)
        variants = self._transform_variants(font_data, details)
        popularity = self._calculate_popularity(font_data, details)
        tags = self._extract_tags(font_data, details)

        return {
            "name": font_name,
            "family": family,
            "license": license_info["type"],
            "license_url": license_info["url"],
            "designer": font_data.get("designer", ""),
            "foundry": font_data.get("foundry_name", "Unknown"),
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
        family_urlname = font_data.get('family_urlname', '')
        
        if not family_urlname:
            return {
                "type": "Unknown",
                "url": ""
            }
        
        license_url = f"https://www.fontsquirrel.com/license/{family_urlname}"

        return {
            "type": "Other",
            "url": license_url
        }

    def _transform_variants(self, font_data: Dict[str, Any], details: Dict[str, Any]) -> List[Dict[str, Any]]:
        variants = []

        font_files = details.get("font_files", []) if details and isinstance(details, dict) else []

        if not font_files:
            family_urlname = font_data.get("family_urlname", "")
            download_url = self._fontfacekit_download_url(family_urlname)
            files = self._files_dict_for_download_url(download_url)
            if files:
                variants.append({
                    "name": f"{font_data.get('family_name', 'Font')} Regular",
                    "weight": 400,
                    "style": "normal",
                    "subsets": ["latin"],
                    "files": files,
                })
        else:
            for file_info in font_files:
                variant = self._create_variant_from_file(file_info, font_data.get("family_name", "Font"), font_data.get("family_urlname", ""))
                if variant:
                    variants.append(variant)
        
        return variants
    
    def _create_variant_from_file(self, file_info: Dict[str, Any], family_name: str, family_urlname: str = "") -> Optional[Dict[str, Any]]:
        filename = (file_info.get("filename") or "").strip()
        download_url = (file_info.get("download_url") or "").strip()
        style_name = (file_info.get("style_name") or "").strip()
        
        if not filename:
            return None

        if style_name:
            weight, style = self._parse_weight_style_from_name(style_name)
        else:
            weight, style = self._parse_weight_style(filename)
        
        variant_name = self._generate_variant_name(family_name, weight, style)
        
        if not download_url and family_urlname:
            download_url = self._fontfacekit_download_url(family_urlname)
        
        files = self._files_dict_for_download_url(download_url)
        if not files:
            return None
        
        return {
            "name": variant_name,
            "weight": weight,
            "style": style,
            "subsets": ["latin", "latin-ext"],
            "files": files,
        }
    
    def _parse_weight_style(self, filename: str) -> tuple[int, str]:
        filename_lower = filename.lower()

        if "italic" in filename_lower or "oblique" in filename_lower:
            style = "italic"
        else:
            style = "normal"

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
            weight = 400

        return weight, style

    def _parse_weight_style_from_name(self, style_name: str) -> tuple[int, str]:
        style_lower = style_name.lower()

        if "italic" in style_lower or "oblique" in style_lower:
            style = "italic"
        else:
            style = "normal"

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
            weight = 400

        return weight, style

    def _generate_variant_name(self, family_name: str, weight: int, style: str) -> str:
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
        score = 40

        if font_data.get("description"):
            score += 10

        if font_data.get("designer"):
            score += 10

        if details and details.get("font_files"):
            score += min(len(details["font_files"]) * 5, 20)

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
        tags = []

        if "classification" in font_data:
            tags.append(font_data["classification"].lower().replace(" ", "-"))

        if font_data.get("designer"):
            tags.append("designer-font")
        
        if font_data.get("foundry"):
            tags.append("foundry-font")

        if details and details.get("tags"):
            tags.extend(details["tags"])

        return list(set(tags))

    def _extract_unicode_ranges(self, font_data: Dict[str, Any], details: Dict[str, Any]) -> List[str]:
        return ["U+0000-00FF", "U+0100-017F"]

    def _extract_languages(self, font_data: Dict[str, Any], details: Dict[str, Any]) -> List[str]:
        return ["Latin", "Latin Extended"]
    
    def translate(
        self, limit: Optional[int] = None, deduplicate_google_fonts: Optional[bool] = None
    ) -> Dict[str, Any]:
        if deduplicate_google_fonts is None:
            deduplicate_google_fonts = DEDUPLICATE_GOOGLE_FONTS

        repo_root = Path(__file__).resolve().parent.parent
        google_path = repo_root / "sources" / "google-fonts.json"
        google_ids: Set[str] = set()
        if deduplicate_google_fonts:
            if not google_path.is_file():
                raise FileNotFoundError(
                    f"Cannot exclude Google Fonts overlaps without {google_path}"
                )
            google_ids = _load_google_font_family_ids(google_path)
            print(f"Cross-checking google-fonts.json ({len(google_ids)} ids).")
        else:
            print("Google Fonts deduplication disabled for this run.")

        print("Fetching Font Squirrel…")
        raw_data = self.fetch_fonts()
        font_squirrel_api_count = len(raw_data)

        print(f"Found {font_squirrel_api_count} families in API listing.")

        if limit:
            raw_data = raw_data[:limit]
            print(f"Limit: processing first {limit} families only.")

        fonts = {}
        skipped_google_overlap = 0
        for font_data in raw_data:
            try:
                family_name = font_data.get("family_name", "")
                font_id = _font_id_from_family_name(family_name)
                if deduplicate_google_fonts and font_id in google_ids:
                    skipped_google_overlap += 1
                    continue

                transformed = self.transform_font(font_data)
                if transformed:
                    fonts[font_id] = transformed
            except Exception as e:
                print(f"Warning: Failed to transform font {font_data.get('family_name', 'unknown')}: {e}")
                continue

        if deduplicate_google_fonts:
            print(
                f"Skipped {skipped_google_overlap} families already in google-fonts.json; "
                f"kept {len(fonts)} families."
            )
        else:
            print(f"Included all {len(fonts)} families (deduplication off).")

        if deduplicate_google_fonts:
            desc = (
                "Free fonts from Font Squirrel (webfont kits as ZIP via fontfacekit URLs). "
                "Families whose normalized id matches sources/google-fonts.json are omitted "
                "to avoid duplicating the Google Fonts catalog."
            )
        else:
            desc = (
                "Free fonts from Font Squirrel (webfont kits as ZIP via fontfacekit URLs). "
                "All families from the Font Squirrel API are included."
            )

        source_data = {
            "source_info": {
                "name": "Font Squirrel",
                "description": desc,
                "url": "https://www.fontsquirrel.com",
                "api_endpoint": "https://www.fontsquirrel.com/api/fontlist/all",
                "version": "1.1" if deduplicate_google_fonts else "1.0",
                "last_updated": datetime.utcnow().isoformat() + "Z",
                "total_fonts": len(fonts),
            },
            "fonts": fonts,
        }

        return source_data


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate FontGet source JSON for Font Squirrel.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N fonts from the Font Squirrel listing (testing).",
    )
    parser.add_argument(
        "--no-google-dedupe",
        action="store_true",
        help="Do not exclude fonts whose normalized id matches sources/google-fonts.json.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output path (default: sources/font-squirrel.json).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    output_file = args.output or (repo_root / "sources" / "font-squirrel.json")

    try:
        translator = FontSquirrelTranslator()
        dedupe = DEDUPLICATE_GOOGLE_FONTS and not args.no_google_dedupe
        source_data = translator.translate(limit=args.limit, deduplicate_google_fonts=dedupe)

        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(source_data, f, indent=2, ensure_ascii=False)

        n = len(source_data["fonts"])
        print(f"Wrote {output_file} ({n} fonts).")

    except Exception as e:
        import traceback

        print(f"Error: {e}")
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
