#!/usr/bin/env python3
"""
Fontshare Translator for FontGet Sources

Uses Fontshare's JSON API plus official download URLs hosted under api.fontshare.com.

When ``DEDUPLICATE_GOOGLE_FONTS`` is True, families that match ``sources/google-fonts.json``
are omitted from retrieval. ``--no-google-dedupe`` disables that for one run.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests

# When True, omit font families that already appear in ``sources/google-fonts.json``.
DEDUPLICATE_GOOGLE_FONTS = False


def _font_id_from_family_name(family_name: str) -> str:
    clean_name = re.sub(r"[^a-z0-9-]", "-", family_name.lower())
    clean_name = re.sub(r"-+", "-", clean_name).strip("-")
    return clean_name


def _load_google_font_family_ids(google_fonts_json: Path) -> Set[str]:
    """Google Fonts JSON keys plus normalized ``family`` strings for overlap checks."""
    with open(google_fonts_json, encoding="utf-8") as f:
        data = json.load(f)
    ids: Set[str] = set()
    for key, entry in data.get("fonts", {}).items():
        ids.add(key)
        fam = (entry.get("family") or entry.get("name") or "").strip()
        if fam:
            ids.add(_font_id_from_family_name(fam))
    return ids


class FontshareTranslator:
    def __init__(self) -> None:
        self.list_url = "https://api.fontshare.com/api/fonts"
        self.detail_url_tpl = "https://api.fontshare.com/v2/fonts/{font_id}"

    def fetch_font_rows(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; FontGet-Sources/1.0; +https://github.com/Graphixa/FontGet-Sources)"
        }
        params = {"limit": limit, "offset": offset}
        resp = requests.get(self.list_url, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        fonts = data.get("fonts")
        if not isinstance(fonts, list):
            raise ValueError("Unexpected Fontshare list response shape")
        return fonts

    def fetch_font_detail(self, font_uuid: str) -> Dict[str, Any]:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; FontGet-Sources/1.0; +https://github.com/Graphixa/FontGet-Sources)"
        }
        url = self.detail_url_tpl.format(font_id=font_uuid)
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        font = payload.get("font")
        if not isinstance(font, dict):
            raise ValueError(f"Unexpected Fontshare detail response shape for {font_uuid}")
        return font

    @staticmethod
    def _normalize_category(category: str) -> str:
        if not category or not category.strip():
            return "Decorative"

        cleaned = category.replace("-", " ").replace("_", " ").strip()
        words = cleaned.split()
        normalized = " ".join(word.capitalize() for word in words)

        mapping = {
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
            # Fontshare-ish simplifications
            "Sans": "Sans Serif",
            "Sans-Serif": "Sans Serif",
            "Serif Slab": "Slab Serif",
            "Slab": "Slab Serif",
        }

        if normalized in mapping:
            return mapping[normalized]

        lowered = normalized.lower()
        for key, value in mapping.items():
            if key.lower() == lowered:
                return value

        # Schema has no free-form "Other"; keep unknowns inside allowed-ish buckets.
        return "Decorative"

    @staticmethod
    def _license_display_name(license_type: str) -> str:
        """
        Map Fontshare license_type codes to short strings that fit schema maxLength.

        Fontshare uses values like: sil_ofl, itf_ffl, ...
        """
        if not license_type:
            return "Unknown"

        lt = license_type.strip().lower()
        if lt == "sil_ofl":
            return "OFL"
        if lt == "itf_ffl":
            return "ITF FFL"
        return license_type.strip()

    @staticmethod
    def _license_url(license_type: str) -> str:
        lt = (license_type or "").strip().lower()
        if lt == "sil_ofl":
            return "https://www.fontshare.com/licenses/sil-ofl"
        if lt == "itf_ffl":
            return "https://www.fontshare.com/licenses/itf-ffl"
        return "https://www.fontshare.com/licenses"

    @staticmethod
    def _designers(font_detail: Dict[str, Any]) -> str:
        designers = font_detail.get("designers") or []
        if not isinstance(designers, list):
            return ""
        names: List[str] = []
        for d in designers:
            if isinstance(d, dict):
                n = (d.get("name") or "").strip()
                if n:
                    names.append(n)
        return ", ".join(names)

    @staticmethod
    def _publisher(font_detail: Dict[str, Any]) -> str:
        pub = font_detail.get("publisher")
        if isinstance(pub, dict):
            return (pub.get("name") or "").strip()
        return ""

    @staticmethod
    def _truncate_field(text: str, max_len: int) -> str:
        s = (text or "").strip()
        if len(s) <= max_len:
            return s
        if max_len <= 1:
            return s[:max_len]
        return s[: max_len - 1].rstrip() + "\u2026"

    @staticmethod
    def _clamp_variant_weight(weight: int) -> int:
        """Fontshare style weights are not always multiples of 100; schema requires multipleOf 100."""
        w = int(round(int(weight) / 100.0) * 100)
        return max(100, min(900, w))

    def _variants_from_detail(self, font_detail: Dict[str, Any], slug: str) -> List[Dict[str, Any]]:
        """
        Fontshare exposes individual webfont asset paths, but FontGet supports zip bundles.

        Official family download endpoint (typically ``application/zip`` body; path has no ``.zip`` suffix):
          https://api.fontshare.com/v2/fonts/download/{slug}
        We key it as ``files.zip`` (bundle); ``schemas/validate-sources.py`` allowlists this URL pattern for ``files.zip``.
        """
        styles = font_detail.get("styles") or []
        if not isinstance(styles, list) or not styles:
            raise ValueError("Fontshare font detail missing styles")

        variant_names: List[str] = []
        weights: List[int] = []
        style_flags: Set[str] = set()

        for st in styles:
            if not isinstance(st, dict):
                continue
            w = st.get("weight") or {}
            if isinstance(w, dict):
                num = w.get("number") or w.get("weight")
                try:
                    wi = int(num)
                    if 100 <= wi <= 900:
                        weights.append(wi)
                except Exception:
                    pass
                label = (w.get("label") or w.get("name") or "").strip()
                if label:
                    variant_names.append(label)

            if st.get("is_italic"):
                style_flags.add("italic")

        weight = self._clamp_variant_weight(max(weights) if weights else 400)
        if len(style_flags) == 1:
            style = next(iter(style_flags))
        else:
            # Multiple italic/normal mixes: keep a conservative default.
            style = "normal"

        name_bits = [font_detail.get("name") or slug]
        if variant_names:
            # Keep filename-ish variant summary compact
            uniq = []
            for vn in variant_names:
                if vn not in uniq:
                    uniq.append(vn)
            summary = ", ".join(uniq[:6])
            if len(uniq) > 6:
                summary += ", …"
            name_bits.append(summary)

        variant_name = self._truncate_field(" ".join(name_bits).strip(), 100)

        bundle_url = f"https://api.fontshare.com/v2/fonts/download/{slug}"
        return [
            {
                "name": variant_name,
                "weight": weight,
                "style": style,
                "subsets": ["latin"],
                "files": {"zip": bundle_url},
            }
        ]

    def translate(self, limit: Optional[int] = None, deduplicate_google_fonts: bool = True) -> Dict[str, Any]:
        repo_root = Path(__file__).resolve().parent.parent
        google_path = repo_root / "sources" / "google-fonts.json"
        google_ids: Set[str] = set()
        if deduplicate_google_fonts:
            if not google_path.is_file():
                raise FileNotFoundError(f"Cannot exclude Google Fonts overlaps without {google_path}")
            google_ids = _load_google_font_family_ids(google_path)
            print(f"Cross-checking google-fonts.json ({len(google_ids)} ids).")
        else:
            print("Google Fonts deduplication disabled for this run.")

        print("Fetching Fontshare…")
        rows = self.fetch_font_rows(limit=100, offset=0)
        if limit is not None:
            rows = rows[:limit]

        print(f"Found {len(rows)} fonts in listing.")

        fonts: Dict[str, Any] = {}
        skipped_google_overlap = 0
        skipped_failed = 0

        for idx, row in enumerate(rows, start=1):
            slug = (row.get("slug") or "").strip()
            name = (row.get("name") or "").strip()
            font_uuid = (row.get("id") or "").strip()
            if not slug or not name or not font_uuid:
                skipped_failed += 1
                continue

            font_id = _font_id_from_family_name(name)
            if deduplicate_google_fonts and font_id in google_ids:
                skipped_google_overlap += 1
                continue

            try:
                detail = self.fetch_font_detail(font_uuid)
                detail_name = (detail.get("name") or name).strip()
                detail_slug = (detail.get("slug") or slug).strip()
                license_type = str(detail.get("license_type") or row.get("license_type") or "")

                categories: List[str] = []
                cat = detail.get("category") or row.get("category")
                if isinstance(cat, str) and cat.strip():
                    categories.append(self._normalize_category(cat))

                story = (detail.get("story") or "").strip()
                fonts[font_id] = {
                    "name": self._truncate_field(detail_name, 100),
                    "family": self._truncate_field(detail_name, 100),
                    "license": self._license_display_name(license_type),
                    "license_url": self._license_url(license_type),
                    "designer": self._truncate_field(self._designers(detail), 200),
                    "foundry": self._truncate_field(self._publisher(detail) or "Fontshare", 100),
                    "version": str(detail.get("version") or row.get("version") or ""),
                    "description": self._truncate_field(story, 1000),
                    "categories": categories,
                    "tags": [],
                    "popularity": 50,
                    "last_modified": str(detail.get("inserted_at") or detail.get("updated_at") or ""),
                    "metadata_url": f"https://www.fontshare.com/fonts/{detail_slug}",
                    "source_url": f"https://www.fontshare.com/fonts/{detail_slug}",
                    "variants": self._variants_from_detail(detail, detail_slug),
                    "unicode_ranges": [],
                    "languages": [],
                    "sample_text": "The quick brown fox jumps over the lazy dog",
                }

                if idx % 25 == 0 or idx == 1:
                    print(f"Processing {idx}/{len(rows)}: {detail_name}")

            except Exception as e:
                skipped_failed += 1
                print(f"Warning: Failed to transform Fontshare font {name} ({slug}): {e}")
                continue

        source_data = {
            "source_info": {
                "name": "Fontshare",
                "description": "Free fonts from Fontshare (official Fontshare download URLs)",
                "url": "https://www.fontshare.com",
                "api_endpoint": "https://api.fontshare.com/api/fonts",
                "version": "1.0",
                "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "total_fonts": len(fonts),
            },
            "fonts": fonts,
        }

        if deduplicate_google_fonts and skipped_google_overlap:
            print(f"Skipped {skipped_google_overlap} families already in google-fonts.json.")
        if skipped_failed:
            print(f"Warning: skipped or failed {skipped_failed} listing row(s).")
        print(f"Built {len(fonts)} font families.")
        return source_data


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate FontGet source JSON for Fontshare.")
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N fonts from the listing.")
    parser.add_argument(
        "--no-google-dedupe",
        action="store_true",
        help="Do not exclude fonts whose normalized family id matches sources/google-fonts.json.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output path (default: sources/fontshare.json).",
    )
    args = parser.parse_args()

    try:
        translator = FontshareTranslator()
        dedupe = DEDUPLICATE_GOOGLE_FONTS and not args.no_google_dedupe
        source_data = translator.translate(limit=args.limit, deduplicate_google_fonts=dedupe)

        repo_root = Path(__file__).resolve().parent.parent
        output_file = args.output or (repo_root / "sources" / "fontshare.json")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(source_data, f, indent=2, ensure_ascii=False)

        n = len(source_data["fonts"])
        print(f"Wrote {output_file} ({n} fonts).")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
