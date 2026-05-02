#!/usr/bin/env python3
"""
Fontsource translator for FontGet Sources.

Uses the Fontsource list endpoint plus **per-font** ``GET /v1/fonts/{id}`` so each
``variants[].files`` entry uses **TTF/OTF** URLs returned by the API (webfont URLs are omitted).

Listing endpoint:

- When deduplication is **on** (see ``DEDUPLICATE_GOOGLE_FONTS`` / ``--no-google-dedupe``),
  we call ``/v1/fonts?type=other`` so Fontsource omits Google-catalog fonts at the API,
  then still filter against ``sources/google-fonts.json`` for any id mismatches.
- When deduplication is **off**, we call ``/v1/fonts`` (full list, including Google-mirrored families).

Output default: ``sources/fontsource.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests

# When True, omit font families that already appear in ``sources/google-fonts.json``.
DEDUPLICATE_GOOGLE_FONTS = True

# Only desktop/installable keys (see ``schemas/font-source-schema.json`` ``variant.files``).
ALLOWED_FILE_KEYS: Set[str] = {"ttf", "otf"}

# Subset strings from the API → schema ``variant.subsets`` enum.
_SCHEMA_SUBSETS: Set[str] = {
    "latin",
    "latin-ext",
    "cyrillic",
    "cyrillic-ext",
    "greek",
    "greek-ext",
    "vietnamese",
    "arabic",
    "devanagari",
    "hebrew",
    "thai",
    "chinese-simplified",
    "chinese-traditional",
    "japanese",
    "korean",
    "other",
}


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


API_BASE = "https://api.fontsource.org/v1/fonts"


def fonts_list_url(*, deduplicate_google_fonts: bool) -> str:
    """Fontsource: ``type=other`` excludes Google-catalog rows; bare URL returns the full catalog."""
    if deduplicate_google_fonts:
        return f"{API_BASE}?type=other"
    return API_BASE


LICENSE_URLS: Dict[str, str] = {
    "OFL-1.1": "https://opensource.org/licenses/OFL-1.1",
    "MIT": "https://opensource.org/licenses/MIT",
    "Apache-2.0": "https://opensource.org/licenses/Apache-2.0",
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "IPA": "https://opensource.org/licenses/IPA",
}

CATEGORY_MAP: Dict[str, str] = {
    "sans-serif": "Sans Serif",
    "serif": "Serif",
    "monospace": "Monospace",
    "display": "Display",
    "handwriting": "Handwriting",
    "other": "Decorative",
}


def _font_slug_id(family_id: str) -> str:
    """Stable dict key (Fontsource ``id`` is already slug-like)."""
    return family_id.strip().lower()


def _weight_to_name(weight: int) -> str:
    names = {
        100: "Thin",
        200: "Extra Light",
        300: "Light",
        400: "Regular",
        500: "Medium",
        600: "Semi Bold",
        700: "Bold",
        800: "Extra Bold",
        900: "Black",
    }
    return names.get(weight, str(weight))


def _variant_name(family: str, weight: int, style: str) -> str:
    base = f"{family} {_weight_to_name(weight)}"
    if style == "italic":
        return f"{base} Italic"
    return base


def _license_url(code: str) -> str:
    if code in LICENSE_URLS:
        return LICENSE_URLS[code]
    safe = re.sub(r"[^A-Za-z0-9_.-]", "", code)
    return f"https://opensource.org/licenses/{safe}"


def _map_category(api_category: str) -> str:
    if not api_category:
        return "Decorative"
    return CATEGORY_MAP.get(api_category.strip().lower(), "Decorative")


def _subset_for_schema(raw: str) -> str:
    s = str(raw).strip().lower().replace(" ", "-")
    if s in _SCHEMA_SUBSETS and s != "other":
        return s
    return "other"


def fetch_fonts(session: requests.Session, *, deduplicate_google_fonts: bool) -> List[Dict[str, Any]]:
    url = fonts_list_url(deduplicate_google_fonts=deduplicate_google_fonts)
    r = session.get(url, timeout=60)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise ValueError("Fontsource API returned unexpected JSON (expected list)")
    return data


def fetch_font_detail(session: requests.Session, font_id: str) -> Optional[Dict[str, Any]]:
    r = session.get(f"{API_BASE}/{font_id}", timeout=60)
    if r.status_code != 200:
        print(f"Warning: GET {API_BASE}/{font_id} -> HTTP {r.status_code}")
        return None
    return r.json()


def _files_from_api_url_block(url_block: Any) -> Dict[str, str]:
    if not isinstance(url_block, dict):
        return {}
    out: Dict[str, str] = {}
    for fmt, u in url_block.items():
        if not isinstance(fmt, str) or not isinstance(u, str):
            continue
        k = fmt.strip().lower()
        if k in ALLOWED_FILE_KEYS:
            out[k] = u.strip()
    return out


def _variants_from_detail(detail: Dict[str, Any], family: str) -> List[Dict[str, Any]]:
    """One FontGet variant per (weight, style, subset) with API-provided file URLs."""
    variants_out: List[Dict[str, Any]] = []
    vroot = detail.get("variants")
    if not isinstance(vroot, dict):
        return variants_out

    for w_key, by_style in vroot.items():
        try:
            weight = int(str(w_key))
        except (TypeError, ValueError):
            continue
        if weight < 100 or weight > 900 or weight % 100 != 0:
            continue
        if not isinstance(by_style, dict):
            continue
        for style, by_subset in by_style.items():
            style_s = str(style).lower()
            if style_s not in {"normal", "italic", "oblique"}:
                style_s = "normal"
            if not isinstance(by_subset, dict):
                continue
            for raw_subset, leaf in by_subset.items():
                subset_schema = _subset_for_schema(str(raw_subset))
                if not isinstance(leaf, dict):
                    continue
                url_obj = leaf.get("url")
                files = _files_from_api_url_block(url_obj)
                if not files:
                    continue
                base_name = _variant_name(family, weight, style_s)
                name = f"{base_name} · {subset_schema}"
                variants_out.append(
                    {
                        "name": name,
                        "weight": weight,
                        "style": style_s,
                        "subsets": [subset_schema],
                        "files": files,
                    }
                )
    return variants_out


def translate(
    rows: List[Dict[str, Any]],
    session: requests.Session,
    *,
    limit: Optional[int] = None,
    deduplicate_google_fonts: bool = True,
    detail_delay_s: float = 0.0,
) -> Dict[str, Any]:
    if limit is not None:
        rows = rows[: max(0, limit)]

    google_ids: Set[str] = set()
    if deduplicate_google_fonts:
        path = Path(__file__).resolve().parent.parent / "sources" / "google-fonts.json"
        if not path.is_file():
            raise FileNotFoundError(f"Cannot exclude Google Fonts overlaps without {path}")
        google_ids = _load_google_font_family_ids(path)
        print(f"Cross-checking google-fonts.json ({len(google_ids)} ids).")
    else:
        print("Google Fonts deduplication disabled for this run.")

    print(f"Found {len(rows)} fonts in list.")

    fonts: Dict[str, Any] = {}
    skipped_google_overlap = 0
    detail_failures = 0
    total_rows = len(rows)

    for idx, row in enumerate(rows, start=1):
        fid = row.get("id")
        family = (row.get("family") or "").strip()
        if not fid or not family:
            continue

        font_id = _font_slug_id(str(fid))
        if deduplicate_google_fonts:
            candidates = {font_id, _font_id_from_family_name(family)}
            if candidates & google_ids:
                skipped_google_overlap += 1
                continue

        if idx == 1 or idx % 20 == 0:
            print(f"Processing {idx}/{total_rows}: {font_id}")

        detail = fetch_font_detail(session, str(fid))
        if detail_delay_s > 0:
            time.sleep(detail_delay_s)
        if not isinstance(detail, dict):
            detail_failures += 1
            continue

        variants = _variants_from_detail(detail, family)
        if not variants:
            detail_failures += 1
            continue

        category = _map_category(str(detail.get("category") or row.get("category") or ""))
        license_code = str(detail.get("license") or row.get("license") or "OFL-1.1").strip()
        version = str(detail.get("npmVersion") or detail.get("version") or row.get("npmVersion") or "5.2.1")

        api_category = str(detail.get("category") or row.get("category") or "").lower().replace(" ", "-")
        tags = [api_category] if api_category else []

        fonts[font_id] = {
            "name": family,
            "family": family,
            "license": license_code,
            "license_url": _license_url(license_code),
            "designer": "",
            "foundry": "Fontsource",
            "version": version,
            "description": "Open source font from Fontsource",
            "categories": [category],
            "tags": tags,
            "popularity": 50,
            "last_modified": str(detail.get("lastModified") or row.get("lastModified") or ""),
            "metadata_url": f"https://fontsource.org/fonts/{font_id}",
            "source_url": f"https://fontsource.org/fonts/{font_id}",
            "variants": variants,
            "unicode_ranges": [],
            "languages": [],
            "sample_text": "The quick brown fox jumps over the lazy dog",
        }

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    list_url = fonts_list_url(deduplicate_google_fonts=deduplicate_google_fonts)
    if deduplicate_google_fonts:
        desc = (
            "Open source fonts from Fontsource; per-font API detail for file URLs; "
            "listing uses API type=other, plus omission of families matching sources/google-fonts.json."
        )
    else:
        desc = (
            "Open source fonts from Fontsource; per-font API detail for file URLs; "
            "full API listing (includes Google-catalog families)."
        )
    if deduplicate_google_fonts and skipped_google_overlap:
        print(f"Skipped {skipped_google_overlap} families already in google-fonts.json.")
    if detail_failures:
        print(f"Warning: skipped or empty detail for {detail_failures} list row(s).")

    return {
        "source_info": {
            "name": "Fontsource",
            "description": desc,
            "url": "https://fontsource.org",
            "api_endpoint": list_url,
            "version": "1.0",
            "last_updated": now,
            "total_fonts": len(fonts),
        },
        "fonts": fonts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate FontGet source JSON for Fontsource (per-font API file URLs)."
    )
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N fonts from the API list.")
    parser.add_argument(
        "--no-google-dedupe",
        action="store_true",
        help="Use the full /v1/fonts listing (include Google-catalog fonts) and skip google-fonts.json filtering.",
    )
    parser.add_argument(
        "--detail-delay",
        type=float,
        default=0.0,
        help="Optional sleep (seconds) between per-font detail requests (rate limiting).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output path (default: sources/fontsource.json).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    out = args.output or (repo_root / "sources" / "fontsource.json")

    try:
        session = requests.Session()
        dedupe = DEDUPLICATE_GOOGLE_FONTS and not args.no_google_dedupe
        list_url = fonts_list_url(deduplicate_google_fonts=dedupe)
        print("Fetching Fontsource…")
        print(f"List: {list_url}")
        rows = fetch_fonts(session, deduplicate_google_fonts=dedupe)
        data = translate(
            rows,
            session,
            limit=args.limit,
            deduplicate_google_fonts=dedupe,
            detail_delay_s=max(0.0, args.detail_delay),
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Wrote {out} ({data['source_info']['total_fonts']} fonts).")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
