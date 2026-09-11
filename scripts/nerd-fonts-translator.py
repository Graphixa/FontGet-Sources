#!/usr/bin/env python3
"""
Nerd Fonts Translator for FontGet

Fetches font data from Nerd Fonts GitHub releases and transforms it to FontGet format.
Each release asset stem is one package. When both ``.zip`` and ``.tar.xz`` exist,
both URLs are published under the same variant ``files`` object (``zip`` + ``tar_xz``);
FontGet chooses which to download. Uses the GitHub API for release metadata.
"""

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

# Tooling / non-font archives published alongside font packages.
SKIP_STEMS = frozenset({"FontPatcher"})

# Exact GitHub release asset stem -> (package_id, display_name).
# Scheme: humanized reserved/original names (not RFN card titles like CaskaydiaCove).
# Overrides fix brand tokens that naive CamelCase splitting breaks.
STEM_OVERRIDES: Dict[str, tuple] = {
    "iA-Writer": ("ia-writer", "iA Writer"),
    "JetBrainsMono": ("jetbrains-mono", "JetBrains Mono"),
    "MPlus": ("m-plus", "M+"),
    "DejaVuSansMono": ("dejavu-sans-mono", "DejaVu Sans Mono"),
    "DaddyTimeMono": ("daddytime-mono", "DaddyTime Mono"),
    "ProggyClean": ("proggyclean", "ProggyClean"),
    "HeavyData": ("heavydata", "HeavyData"),
    "NerdFontsSymbolsOnly": ("symbols-only", "Symbols Only"),
    "0xProto": ("0xproto", "0xProto"),
    "ProFont": ("profont", "ProFont"),
    "D2Coding": ("d2coding", "D2Coding"),
    "Go-Mono": ("go-mono", "Go Mono"),
    "OpenDyslexic": ("opendyslexic", "OpenDyslexic"),
    "Recursive": ("recursive", "Recursive Mono"),
}


class NerdFontsTranslator:
    def __init__(self):
        self.base_url = "https://api.github.com/repos/ryanoasis/nerd-fonts"
        self.releases_url = f"{self.base_url}/releases"
        self.contents_url = f"{self.base_url}/contents"
        self.release_version: str = "0.0.0"

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

    def fetch_releases(self) -> List[Dict[str, Any]]:
        response = requests.get(self.releases_url)
        response.raise_for_status()
        return response.json()

    def get_latest_release(self) -> Dict[str, Any]:
        releases = self.fetch_releases()
        if not releases:
            raise ValueError("No releases found")
        return releases[0]

    @staticmethod
    def _release_version_from_tag(tag_name: Optional[str]) -> str:
        if not tag_name:
            raise ValueError("Release has no tag_name")
        return tag_name.lstrip("vV")

    @staticmethod
    def _archive_stem(filename: str) -> Optional[str]:
        lower = filename.lower()
        if lower.endswith(".tar.xz"):
            return filename[: -len(".tar.xz")]
        if lower.endswith(".zip"):
            return filename[: -len(".zip")]
        return None

    @staticmethod
    def _split_stem_parts(stem: str) -> List[str]:
        """Split a release asset stem into display / id parts.

        Handles CamelCase, existing hyphens, and acronyms (IBMPlex → IBM-Plex).
        """
        if not stem:
            return []

        # Normalize underscores; keep hyphens as separators.
        text = stem.replace("_", "-")
        # aA → a-A. Do not split after a digit (keeps 0xProto, D2Coding intact).
        text = re.sub(r"(?<![0-9])([a-z])([A-Z])", r"\1-\2", text)
        # AAa → A-Aa (IBMPlex → IBM-Plex)
        text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", text)

        parts: List[str] = []
        for chunk in text.split("-"):
            chunk = chunk.strip()
            if chunk:
                parts.append(chunk)

        # Brands like ProFont: trailing "Font" is part of the name, not a word break.
        # Matches Nerd Fonts download labels (https://www.nerdfonts.com/font-downloads).
        if len(parts) >= 2 and parts[-1] == "Font":
            parts = parts[:-2] + [parts[-2] + parts[-1]]

        return parts

    @classmethod
    def stem_identity(cls, stem: str) -> tuple:
        """Return (font_id, display_name) for a release asset stem."""
        override = STEM_OVERRIDES.get(stem)
        if override is not None:
            return override[0], override[1]
        return cls.stem_id(stem), cls.stem_name(stem)

    @classmethod
    def stem_id(cls, stem: str) -> str:
        override = STEM_OVERRIDES.get(stem)
        if override is not None:
            return override[0]
        parts = cls._split_stem_parts(stem)
        raw = "-".join(p.lower() for p in parts)
        clean = re.sub(r"[^a-z0-9-]", "-", raw)
        clean = re.sub(r"-+", "-", clean).strip("-")
        if not clean:
            raise ValueError(f"Could not derive package id from stem {stem!r}")
        return clean

    @classmethod
    def stem_name(cls, stem: str) -> str:
        override = STEM_OVERRIDES.get(stem)
        if override is not None:
            return override[1]
        parts = cls._split_stem_parts(stem)
        if not parts:
            raise ValueError(f"Could not derive package name from stem {stem!r}")
        return " ".join(parts)

    def extract_font_info_from_assets(
        self,
        assets: List[Dict[str, Any]],
        *,
        release_version: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        version = release_version if release_version is not None else self.release_version
        # stem -> {font_id, font_name, files: {zip|tar_xz: url}}
        by_stem: Dict[str, Dict[str, Any]] = {}

        for asset in assets:
            name = asset["name"]
            download_url = asset["browser_download_url"]

            stem = self._archive_stem(name)
            if stem is None:
                continue
            if stem in SKIP_STEMS:
                continue

            fk = self._files_key_for_release_asset(name)
            if fk not in ("zip", "tar_xz"):
                continue

            if stem not in by_stem:
                font_id, font_name = self.stem_identity(stem)
                by_stem[stem] = {
                    "stem": stem,
                    "font_name": font_name,
                    "font_id": font_id,
                    "files": {},
                }
            by_stem[stem]["files"][fk] = download_url

        # Fail when two different stems map to the same package id.
        id_to_stem: Dict[str, str] = {}
        for stem, row in by_stem.items():
            font_id = row["font_id"]
            prev_stem = id_to_stem.get(font_id)
            if prev_stem is not None and prev_stem != stem:
                raise ValueError(
                    f"Duplicate package id {font_id!r} from stems {prev_stem!r} and {stem!r}"
                )
            id_to_stem[font_id] = stem

        fonts: Dict[str, Dict[str, Any]] = {}
        now = datetime.utcnow().isoformat() + "Z"

        for stem in sorted(by_stem.keys()):
            row = by_stem[stem]
            font_id = row["font_id"]
            font_name = row["font_name"]
            files = row["files"]
            if not files:
                continue

            # Stable key order: tar_xz then zip when both present.
            ordered_files: Dict[str, str] = {}
            for key in ("tar_xz", "zip"):
                if key in files:
                    ordered_files[key] = files[key]

            variant = {
                "name": f"{font_name} Regular",
                "weight": 400,
                "style": "normal",
                "subsets": ["latin", "latin-ext"],
                "files": ordered_files,
            }

            fonts[font_id] = {
                "name": font_name,
                "family": font_name,
                "license": "Mixed",
                "license_url": "https://raw.githubusercontent.com/ryanoasis/nerd-fonts/refs/heads/master/LICENSE",
                "designer": "Ryan L McIntyre (Nerd Fonts Patcher)",
                "foundry": "Nerd Fonts",
                "version": version,
                "description": f"Patched version of {font_name} with additional icon glyphs",
                "categories": [self._normalize_category("Nerd Font")],
                "tags": ["nerd-fonts", "icons", "patched", "monospace", "programming"],
                "popularity": self._calculate_popularity(font_name),
                "last_modified": now,
                "metadata_url": "https://github.com/ryanoasis/nerd-fonts",
                "source_url": "https://github.com/ryanoasis/nerd-fonts/releases/latest",
                "variants": [variant],
                "unicode_ranges": [
                    "U+0000-00FF",
                    "U+2190-21FF",
                    "U+2600-26FF",
                    "U+1F300-1F5FF",
                ],
                "languages": ["Latin", "Symbols"],
                "sample_text": "Hello World! ⚡ 🔥 💻",
            }

        # Deterministic key order by font id.
        return {fid: fonts[fid] for fid in sorted(fonts.keys())}

    @staticmethod
    def _files_key_for_release_asset(filename: str) -> Optional[str]:
        lower = filename.lower()
        if lower.endswith(".tar.xz"):
            return "tar_xz"
        if lower.endswith(".zip"):
            return "zip"
        if lower.endswith(".ttf"):
            return "ttf"
        if lower.endswith(".otf"):
            return "otf"
        return None

    def _calculate_popularity(self, font_name: str) -> int:
        # Keys must match display names (stem_name / STEM_OVERRIDES).
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
            "Noto": 50,
            "Space Mono": 45,
            "Terminus": 65,
            "Victor Mono": 35,
            "Meslo": 80,
            "Iosevka": 70,
        }

        return popular_fonts.get(font_name, 50)

    def translate(self) -> Dict[str, Any]:
        print("Fetching Nerd Fonts…")
        latest_release = self.get_latest_release()

        tag = latest_release.get("tag_name", "?")
        self.release_version = self._release_version_from_tag(
            latest_release.get("tag_name")
        )
        n_assets = len(latest_release.get("assets") or [])
        print(f"Release {tag} — {n_assets} assets.")

        fonts = self.extract_font_info_from_assets(
            latest_release["assets"],
            release_version=self.release_version,
        )

        print(f"Found {len(fonts)} font families after grouping.")

        source_data = {
            "source_info": {
                "name": "Nerd Fonts",
                "description": "Patched fonts with additional icon glyphs for programming",
                "url": "https://www.nerdfonts.com",
                "api_endpoint": "https://api.github.com/repos/ryanoasis/nerd-fonts/releases",
                "version": "1.0",
                "last_updated": datetime.utcnow().isoformat() + "Z",
                "total_fonts": len(fonts),
            },
            "fonts": fonts,
        }

        return source_data


def main():
    try:
        translator = NerdFontsTranslator()
        source_data = translator.translate()

        output_file = "sources/nerd-fonts.json"
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
