#!/usr/bin/env python3
"""
Google Fonts API Translator for FontGet

Fetches font data from Google Fonts API and transforms it to FontGet format.
Requires ``GOOGLE_FONTS_API_KEY`` (environment variable). The repo-root ``.env`` is loaded on
each run: ``python-dotenv`` when installed, plus a built-in line parser for this key so a
missing ``pip install`` does not block local use.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from urllib.parse import urlparse

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from license_ids import canonical_license

# Google fonts repo: directory name → upstream license code in METADATA.pb.
_GOOGLE_LICENSE_DIRS: Tuple[Tuple[str, str], ...] = (
    ("ofl", "OFL"),
    ("apache", "APACHE2"),
    ("ufl", "UFL"),
)
_GITHUB_TREE = "https://api.github.com/repos/google/fonts/git/trees"


def family_slug(family: str) -> str:
    """Slug used under google/fonts/{ofl|apache|ufl}/."""
    return family.lower().replace(" ", "")


def load_google_fonts_license_index(
    session: Optional[requests.Session] = None,
) -> Dict[str, Tuple[str, str]]:
    """Map family slug → (license_dir, license_code) via four Git Trees API calls.

    Uses the Trees API (not Contents): Contents truncates at 1,000 entries and
    ``ofl/`` is larger than that.
    """
    sess = session or requests.Session()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "FontGet-Sources"}
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    root = sess.get(f"{_GITHUB_TREE}/main", headers=headers, timeout=60)
    root.raise_for_status()
    wanted = {d: code for d, code in _GOOGLE_LICENSE_DIRS}
    dir_shas: Dict[str, str] = {}
    for entry in root.json().get("tree") or []:
        path = entry.get("path")
        if path in wanted and entry.get("type") == "tree" and entry.get("sha"):
            dir_shas[path] = entry["sha"]

    missing = [d for d, _ in _GOOGLE_LICENSE_DIRS if d not in dir_shas]
    if missing:
        raise RuntimeError(f"google/fonts main tree missing dirs: {missing}")

    index: Dict[str, Tuple[str, str]] = {}
    for dirname, code in _GOOGLE_LICENSE_DIRS:
        tree = sess.get(f"{_GITHUB_TREE}/{dir_shas[dirname]}", headers=headers, timeout=60)
        tree.raise_for_status()
        for entry in tree.json().get("tree") or []:
            if entry.get("type") != "tree":
                continue
            name = entry.get("path")
            if isinstance(name, str) and name:
                index[name] = (dirname, code)
    return index


def _bootstrap_google_fonts_key_from_dotenv_file(env_path: Path) -> None:
    """Set ``GOOGLE_FONTS_API_KEY`` from ``.env`` if unset (works without python-dotenv)."""
    if os.environ.get("GOOGLE_FONTS_API_KEY", "").strip():
        return
    if not env_path.is_file():
        return
    try:
        raw = env_path.read_text(encoding="utf-8-sig")
    except OSError:
        return
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.lower().startswith("export "):
            s = s[7:].lstrip()
        if "=" not in s:
            continue
        key, _, val = s.partition("=")
        key = key.strip()
        if key != "GOOGLE_FONTS_API_KEY":
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if val:
            os.environ["GOOGLE_FONTS_API_KEY"] = val
        return


def _load_repo_dotenv() -> None:
    """Load repo-root ``.env`` via dotenv when installed, then bootstrap API key."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    try:
        from dotenv import load_dotenv
    except ImportError:
        pass
    else:
        load_dotenv(env_path, encoding="utf-8-sig")
    _bootstrap_google_fonts_key_from_dotenv_file(env_path)


class GoogleFontsTranslator:
    def __init__(self, api_key: Optional[str] = None, *, verbose: bool = False):
        self.api_key = api_key or os.getenv("GOOGLE_FONTS_API_KEY")
        self.base_url = "https://www.googleapis.com/webfonts/v1/webfonts"
        self.verbose = verbose or os.environ.get("GOOGLE_FONTS_TRANSLATOR_VERBOSE", "").strip() not in (
            "",
            "0",
            "false",
            "no",
        )

        # slug → (license_dir, license_code); filled in translate() / load_license_index().
        self._license_index: Dict[str, Tuple[str, str]] = {}
        self._session = requests.Session()

        if not self.api_key:
            root = Path(__file__).resolve().parent.parent
            dotenv_path = root / ".env"
            hint = ""
            if dotenv_path.is_file():
                hint = (
                    f" Repo file {dotenv_path} exists but ``GOOGLE_FONTS_API_KEY`` is still unset or empty. "
                    "Add a line exactly like: GOOGLE_FONTS_API_KEY=your_key_here "
                    "(no spaces around ``=`` unless the value is quoted). "
                    "Or ``export GOOGLE_FONTS_API_KEY=...`` is also accepted."
                )
            else:
                hint = f" Expected `{dotenv_path}` or ``export GOOGLE_FONTS_API_KEY`` in your environment."
            raise ValueError(
                "Google Fonts API key is required. Set GOOGLE_FONTS_API_KEY or add it to `.env` at the repo root."
                + hint
            )

    def load_license_index(self) -> None:
        """Fetch ofl/apache/ufl folder lists once for this run."""
        print("Loading Google Fonts license folders (ofl/apache/ufl)…")
        self._license_index = load_google_fonts_license_index(self._session)
        print(f"Indexed {len(self._license_index)} family folders.")

    def _license_for_family(self, family: str) -> Tuple[str, str]:
        """Return (canonical license id, metadata_url path dir)."""
        slug = family_slug(family)
        hit = self._license_index.get(slug)
        if hit:
            dirname, code = hit
            return canonical_license(code), dirname
        print(f"Warning: no ofl/apache/ufl folder for {family!r} ({slug}); license=Unknown")
        return "Unknown", "ofl"

    def _normalize_category(self, category: str) -> str:
        """Map API category strings to FontGet schema enums."""
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

    def fetch_fonts(self) -> Dict[str, Any]:
        """GET webfonts catalog JSON."""
        params = {
            "key": self.api_key,
            "sort": "popularity",
        }
        
        response = self._session.get(self.base_url, params=params)
        response.raise_for_status()
        return response.json()

    def transform_font(self, font_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """FontGet font dict, or None if no TTF/OTF-backed variants."""
        family = font_data["family"]
        clean_name = re.sub(r'[^a-z0-9-]', '-', family.lower())
        clean_name = re.sub(r'-+', '-', clean_name).strip('-')
        font_id = clean_name

        variants = []
        for variant in font_data.get("variants", []):
            variant_data = self._parse_variant(variant, family, font_data)
            if variant_data:
                variants.append(variant_data)

        if not variants:
            return None

        categories = []
        if "category" in font_data:
            category = font_data["category"]
            normalized_category = self._normalize_category(category)
            categories.append(normalized_category)

        popularity = self._calculate_popularity(font_data)
        license_id, license_dir = self._license_for_family(family)
        slug = family_slug(family)

        return {
            "name": family,
            "family": family,
            "license": license_id,
            "license_url": f"https://fonts.google.com/specimen/{family.replace(' ', '+')}/license",
            "designer": font_data.get("designer", ""),
            "foundry": "Google",
            "version": font_data.get("version", "1.0"),
            "description": font_data.get("description", ""),
            "categories": categories,
            "tags": self._extract_tags(font_data),
            "popularity": popularity,
            "last_modified": font_data.get("lastModified", ""),
            "metadata_url": (
                f"https://raw.githubusercontent.com/google/fonts/main/"
                f"{license_dir}/{slug}/METADATA.pb"
            ),
            "source_url": f"https://fonts.google.com/specimen/{family.replace(' ', '+')}",
            "variants": variants,
            "unicode_ranges": self._extract_unicode_ranges(font_data),
            "languages": self._extract_languages(font_data),
            "sample_text": "The quick brown fox jumps over the lazy dog"
        }
    
    def _parse_variant(self, variant: str, family: str, font_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse variant id (e.g. ``regular``, ``700``, ``700italic``)."""
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
            return None

        files = self._generate_file_urls(font_data, variant)
        if not files:
            return None

        return {
            "name": name,
            "weight": weight,
            "style": style,
            "subsets": ["latin", "latin-ext"],
            "files": files
        }
    
    def _weight_to_name(self, weight: int) -> str:
        """Weight label for display names."""
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
    
    @staticmethod
    def _file_key_from_google_font_url(file_url: str) -> Optional[str]:
        """Return ``ttf`` / ``otf`` from URL path suffix, or ``None`` for webfont-only URLs."""
        path = (urlparse(file_url).path or "").lower()
        if path.endswith(".ttf"):
            return "ttf"
        if path.endswith(".otf"):
            return "otf"
        return None

    def _generate_file_urls(self, font_data: Dict[str, Any], variant: str) -> Dict[str, str]:
        """TTF/OTF URLs from API ``files`` map."""
        files: Dict[str, str] = {}

        font_files = font_data.get("files", {})
        if variant in font_files:
            file_url = font_files[variant]
            key = self._file_key_from_google_font_url(file_url)
            if key is not None:
                files[key] = file_url
            elif self.verbose:
                print(
                    f"Verbose: skip non-TTF/OTF file for variant {variant!r} "
                    f"family={font_data.get('family')!r} url={file_url[:200]}"
                )

        return files
    
    def _calculate_popularity(self, font_data: Dict[str, Any]) -> int:
        """Heuristic 0–100 score from variants, subsets, description, designer."""
        variants_count = len(font_data.get("variants", []))
        subsets_count = len(font_data.get("subsets", []))

        score = min(variants_count * 10, 50)
        score += min(subsets_count * 5, 30)
        if font_data.get("description"):
            score += 10
        if font_data.get("designer"):
            score += 10

        return min(score, 100)
    
    def _extract_tags(self, font_data: Dict[str, Any]) -> List[str]:
        tags = []

        if "category" in font_data:
            tags.append(font_data["category"].lower().replace(" ", "-"))

        variants = font_data.get("variants", [])
        if any("italic" in v for v in variants):
            tags.append("italic")
        if any(v.isdigit() and int(v) >= 700 for v in variants):
            tags.append("bold")
        
        return tags
    
    def _extract_unicode_ranges(self, font_data: Dict[str, Any]) -> List[str]:
        """Rough Unicode ranges inferred from ``subsets``."""
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
        """Human-readable names from ``subsets``."""
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
        self.load_license_index()
        print("Fetching Google Fonts…")
        raw_data = self.fetch_fonts()

        total_fonts = len(raw_data.get("items", []))
        print(f"Found {total_fonts} families in catalog.")

        fonts = {}
        for i, font_data in enumerate(raw_data.get("items", []), 1):
            try:
                if i % 50 == 0 or i == 1:
                    print(f"Processing {i}/{total_fonts}: {font_data.get('family', 'Unknown')}")

                transformed = self.transform_font(font_data)
                if not transformed:
                    continue
                clean_name = re.sub(r'[^a-z0-9-]', '-', font_data['family'].lower())
                clean_name = re.sub(r'-+', '-', clean_name).strip('-')
                font_id = clean_name
                fonts[font_id] = transformed
            except Exception as e:
                print(f"Warning: Failed to transform font {font_data.get('family', 'unknown')}: {e}")
                continue

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


def main():
    try:
        _load_repo_dotenv()

        parser = argparse.ArgumentParser(description="Generate FontGet JSON from Google Fonts API.")
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Log when a variant file URL is skipped (not TTF/OTF).",
        )
        args = parser.parse_args()

        translator = GoogleFontsTranslator(verbose=args.verbose)
        source_data = translator.translate()

        output_file = "sources/google-fonts.json"
        os.makedirs("sources", exist_ok=True)
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(source_data, f, indent=2, ensure_ascii=False)
        
        n = len(source_data["fonts"])
        print(f"Wrote {output_file} ({n} fonts).")
        
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
