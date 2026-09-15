#!/usr/bin/env python3
"""
Nerd Fonts Translator for FontGet (catalog v2)

Pins metadata + binaries to one GitHub release tag:
  1. Resolve latest stable release of ryanoasis/nerd-fonts
  2. Fetch bin/scripts/lib/fonts.json from that tag
  3. Build download URLs from that tag's release assets (folderName stem)

Writes:
  - sources/nerd-fonts-v2.json  (maintained)
  - migrations/001-nerd-fonts-v1-to-v2.json  (FontGet registry remap)

Does NOT touch sources/nerd-fonts.json (frozen v1 for old clients).
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import requests

SKIP_STEMS = frozenset({"FontPatcher"})
V1_PATH = "sources/nerd-fonts.json"
V2_PATH = "sources/nerd-fonts-v2.json"
RENAMES_PATH = "migrations/001-nerd-fonts-v1-to-v2.json"
CLIENT_SOURCE_PREFIX = "nerd"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _full_font_id(bare_id: str) -> str:
    return f"{CLIENT_SOURCE_PREFIX}.{bare_id}"


class NerdFontsTranslator:
    def __init__(self):
        self.base_url = "https://api.github.com/repos/ryanoasis/nerd-fonts"
        self.releases_url = f"{self.base_url}/releases"
        self.release_tag: str = ""
        self.release_version: str = "0.0.0"

    def _normalize_category(self, category: str) -> str:
        if not category or not category.strip():
            return "Other"
        return "Nerd Font"

    def fetch_releases(self) -> List[Dict[str, Any]]:
        response = requests.get(self.releases_url, timeout=60)
        response.raise_for_status()
        return response.json()

    def get_latest_stable_release(self) -> Dict[str, Any]:
        for release in self.fetch_releases():
            if release.get("draft") or release.get("prerelease"):
                continue
            return release
        raise ValueError("No stable releases found")

    def fetch_fonts_json(self, tag: str) -> List[Dict[str, Any]]:
        url = (
            f"https://raw.githubusercontent.com/ryanoasis/nerd-fonts/"
            f"{tag}/bin/scripts/lib/fonts.json"
        )
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        data = response.json()
        fonts = data.get("fonts", data) if isinstance(data, dict) else data
        if not isinstance(fonts, list):
            raise ValueError(f"Unexpected fonts.json shape from {tag}")
        return fonts

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
    def _files_key_for_release_asset(filename: str) -> Optional[str]:
        lower = filename.lower()
        if lower.endswith(".tar.xz"):
            return "tar_xz"
        if lower.endswith(".zip"):
            return "zip"
        return None

    @staticmethod
    def _normalize_id(value: str) -> str:
        clean = re.sub(r"[^a-z0-9-]", "-", value.lower())
        clean = re.sub(r"-+", "-", clean).strip("-")
        if not clean:
            raise ValueError(f"Could not normalize id from {value!r}")
        return clean

    @staticmethod
    def _license_url(license_id: str, entry: Dict[str, Any], fallback: str) -> str:
        """SPDX page for a single listed id; else RFNException; else pinned LICENSE."""
        if (
            license_id
            and not license_id.startswith("LicenseRef-")
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+-]*", license_id)
        ):
            return f"https://spdx.org/licenses/{license_id}.html"
        rfn_exc = entry.get("RFNException")
        if isinstance(rfn_exc, str) and rfn_exc.strip():
            return rfn_exc.strip()
        return fallback

    @staticmethod
    def _display_name(entry: Dict[str, Any]) -> str:
        preview = (entry.get("imagePreviewFont") or "").strip()
        if preview:
            return preview
        patched = (entry.get("patchedName") or "").strip()
        if patched:
            return f"{patched} Nerd Font"
        raise ValueError(f"No display name for folder {entry.get('folderName')!r}")

    @staticmethod
    def _stem_from_files(files: Dict[str, str]) -> Optional[str]:
        for key in ("zip", "tar_xz"):
            url = files.get(key)
            if not url:
                continue
            path = unquote(urlparse(url).path)
            name = path.rsplit("/", 1)[-1]
            stem = NerdFontsTranslator._archive_stem(name)
            if stem:
                return stem
        return None

    @staticmethod
    def _aliases(
        entry: Dict[str, Any],
        font_id: str,
        old_bare_id: Optional[str] = None,
    ) -> List[str]:
        seen = {font_id}
        out: List[str] = []
        for raw in (
            entry.get("unpatchedName"),
            entry.get("patchedName"),
            entry.get("folderName"),
            old_bare_id,
            _full_font_id(old_bare_id) if old_bare_id else None,
        ):
            if not raw:
                continue
            text = str(raw).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    def _assets_by_stem(self, assets: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
        by_stem: Dict[str, Dict[str, str]] = {}
        for asset in assets:
            name = asset["name"]
            stem = self._archive_stem(name)
            if stem is None or stem in SKIP_STEMS:
                continue
            fk = self._files_key_for_release_asset(name)
            if fk not in ("zip", "tar_xz"):
                continue
            by_stem.setdefault(stem, {})[fk] = asset["browser_download_url"]
        return by_stem

    def _calculate_popularity(self, unpatched_name: str) -> int:
        popular = {
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
        return popular.get(unpatched_name, 50)

    def build_fonts(
        self,
        registry: List[Dict[str, Any]],
        assets: List[Dict[str, Any]],
        *,
        tag: str,
        version: str,
        v1_stem_to_id: Optional[Dict[str, str]] = None,
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
        """Return (fonts_by_id, stem_to_font_id)."""
        by_stem = self._assets_by_stem(assets)
        fonts: Dict[str, Dict[str, Any]] = {}
        stem_to_id: Dict[str, str] = {}
        now = _utc_now_iso()
        license_fallback = (
            f"https://raw.githubusercontent.com/ryanoasis/nerd-fonts/{tag}/LICENSE"
        )
        release_page = f"https://github.com/ryanoasis/nerd-fonts/releases/tag/{tag}"
        v1_stem_to_id = v1_stem_to_id or {}

        for entry in registry:
            folder = (entry.get("folderName") or "").strip()
            cask = (entry.get("caskName") or "").strip()
            if not folder or not cask:
                continue
            files = by_stem.get(folder)
            if not files:
                print(f"Skip {folder}: no release assets for {tag}")
                continue

            font_id = self._normalize_id(cask)
            if font_id in fonts:
                raise ValueError(f"Duplicate package id {font_id!r} (folder {folder!r})")

            old_bare = v1_stem_to_id.get(folder)
            if old_bare == font_id:
                old_bare = None

            license_id = (entry.get("licenseId") or "").strip()
            if not license_id:
                print(f"Warning: {folder} missing licenseId; using Mixed")
                license_id = "Mixed"

            font_name = self._display_name(entry)
            unpatched = (entry.get("unpatchedName") or folder).strip()

            ordered_files: Dict[str, str] = {}
            for key in ("tar_xz", "zip"):
                if key in files:
                    ordered_files[key] = files[key]

            fonts[font_id] = {
                "name": font_name,
                "family": font_name,
                "license": license_id,
                "license_url": self._license_url(license_id, entry, license_fallback),
                "designer": "Ryan L McIntyre (Nerd Fonts Patcher)",
                "foundry": "Nerd Fonts",
                "version": version,
                "description": (entry.get("description") or "").strip()
                or f"Patched version of {unpatched} with additional icon glyphs",
                "categories": [self._normalize_category("Nerd Font")],
                "tags": ["nerd-fonts", "icons", "patched", "monospace", "programming"],
                "aliases": self._aliases(entry, font_id, old_bare),
                "popularity": self._calculate_popularity(unpatched),
                "last_modified": now,
                "metadata_url": "https://github.com/ryanoasis/nerd-fonts",
                "source_url": release_page,
                "variants": [
                    {
                        "name": f"{font_name} Regular",
                        "weight": 400,
                        "style": "normal",
                        "subsets": ["latin", "latin-ext"],
                        "files": ordered_files,
                    }
                ],
                "unicode_ranges": [
                    "U+0000-00FF",
                    "U+2190-21FF",
                    "U+2600-26FF",
                    "U+1F300-1F5FF",
                ],
                "languages": ["Latin", "Symbols"],
                "sample_text": "Hello World! ⚡ 🔥 💻",
            }
            stem_to_id[folder] = font_id

        return {fid: fonts[fid] for fid in sorted(fonts.keys())}, stem_to_id

    @classmethod
    def load_v1_stem_to_id(cls, path: str = V1_PATH) -> Dict[str, str]:
        if not os.path.isfile(path):
            print(f"Warning: frozen v1 missing at {path}; renames map will be empty")
            return {}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        stem_to_id: Dict[str, str] = {}
        for font_id, font in (data.get("fonts") or {}).items():
            variants = font.get("variants") or []
            if not variants:
                continue
            files = variants[0].get("files") or {}
            stem = cls._stem_from_files(files)
            if not stem:
                continue
            prev = stem_to_id.get(stem)
            if prev is not None and prev != font_id:
                raise ValueError(
                    f"Frozen v1: stem {stem!r} maps to both {prev!r} and {font_id!r}"
                )
            stem_to_id[stem] = font_id
        return stem_to_id

    @staticmethod
    def build_renames(
        *,
        v1_stem_to_id: Dict[str, str],
        v2_stem_to_id: Dict[str, str],
        v2_fonts: Dict[str, Dict[str, Any]],
        release_tag: str,
    ) -> Dict[str, Any]:
        rows: List[Dict[str, str]] = []
        for stem, old_id in sorted(v1_stem_to_id.items(), key=lambda x: x[1]):
            new_id = v2_stem_to_id.get(stem)
            if not new_id or new_id == old_id:
                continue
            rows.append(
                {
                    "from": _full_font_id(old_id),
                    "to": _full_font_id(new_id),
                    "catalog_name": v2_fonts[new_id]["name"],
                }
            )
        return {
            "schema_version": "1",
            "source": "Nerd Fonts",
            "nerd_fonts_release": release_tag,
            "generated_at": _utc_now_iso(),
            "renames": rows,
        }

    def translate(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        print("Fetching Nerd Fonts…")
        latest_release = self.get_latest_stable_release()
        tag = latest_release["tag_name"]
        self.release_tag = tag
        self.release_version = self._release_version_from_tag(tag)
        n_assets = len(latest_release.get("assets") or [])
        print(f"Release {tag} — {n_assets} assets.")

        registry = self.fetch_fonts_json(tag)
        print(f"fonts.json ({tag}): {len(registry)} entries.")

        v1_stem_to_id = self.load_v1_stem_to_id()
        fonts, v2_stem_to_id = self.build_fonts(
            registry,
            latest_release["assets"],
            tag=tag,
            version=self.release_version,
            v1_stem_to_id=v1_stem_to_id,
        )
        print(f"Found {len(fonts)} font packages with release assets.")

        source_data = {
            "source_info": {
                "name": "Nerd Fonts",
                "description": "Patched fonts with additional icon glyphs for programming",
                "url": "https://www.nerdfonts.com",
                "api_endpoint": "https://api.github.com/repos/ryanoasis/nerd-fonts/releases",
                "version": "2.0",
                "last_updated": _utc_now_iso(),
                "total_fonts": len(fonts),
            },
            "fonts": fonts,
        }
        renames = self.build_renames(
            v1_stem_to_id=v1_stem_to_id,
            v2_stem_to_id=v2_stem_to_id,
            v2_fonts=fonts,
            release_tag=tag,
        )
        return source_data, renames


def _self_check() -> None:
    t = NerdFontsTranslator()
    v1_stem_to_id = {"CascadiaCode": "cascadia-code", "AdwaitaMono": "adwaita-mono"}
    registry = [
        {
            "unpatchedName": "Cascadia Code",
            "licenseId": "OFL-1.1-RFN",
            "patchedName": "CaskaydiaCove",
            "folderName": "CascadiaCode",
            "imagePreviewFont": "CaskaydiaCove Nerd Font",
            "caskName": "caskaydia-cove",
            "description": "Cascadia patched",
        },
        {
            "unpatchedName": "Adwaita Mono",
            "licenseId": "OFL-1.1-no-RFN",
            "patchedName": "AdwaitaMono",
            "folderName": "AdwaitaMono",
            "imagePreviewFont": "AdwaitaMono Nerd Font",
            "caskName": "adwaita-mono",
            "description": "Adwaita patched",
        },
    ]
    assets = [
        {
            "name": "CascadiaCode.zip",
            "browser_download_url": "https://example.com/v9.9.9/CascadiaCode.zip",
        },
        {
            "name": "AdwaitaMono.zip",
            "browser_download_url": "https://example.com/v9.9.9/AdwaitaMono.zip",
        },
    ]
    fonts, stem_to_id = t.build_fonts(
        registry,
        assets,
        tag="v9.9.9",
        version="9.9.9",
        v1_stem_to_id=v1_stem_to_id,
    )
    cas = fonts["caskaydia-cove"]
    assert cas["name"] == "CaskaydiaCove Nerd Font"
    assert cas["license_url"] == "https://spdx.org/licenses/OFL-1.1-RFN.html"
    assert "Cascadia Code" in cas["aliases"]
    assert "cascadia-code" in cas["aliases"]
    assert "nerd.cascadia-code" in cas["aliases"]
    assert fonts["adwaita-mono"]["name"] == "AdwaitaMono Nerd Font"
    renames = t.build_renames(
        v1_stem_to_id=v1_stem_to_id,
        v2_stem_to_id=stem_to_id,
        v2_fonts=fonts,
        release_tag="v9.9.9",
    )
    assert renames["schema_version"] == "1"
    assert renames["renames"] == [
        {
            "from": "nerd.cascadia-code",
            "to": "nerd.caskaydia-cove",
            "catalog_name": "CaskaydiaCove Nerd Font",
        }
    ]
    print("self-check ok")


def main() -> int:
    try:
        translator = NerdFontsTranslator()
        source_data, renames = translator.translate()

        os.makedirs("sources", exist_ok=True)
        os.makedirs(os.path.dirname(RENAMES_PATH), exist_ok=True)

        with open(V2_PATH, "w", encoding="utf-8") as f:
            json.dump(source_data, f, indent=2, ensure_ascii=False)

        with open(RENAMES_PATH, "w", encoding="utf-8") as f:
            json.dump(renames, f, indent=2, ensure_ascii=False)

        n = len(source_data["fonts"])
        print(f"Wrote {V2_PATH} ({n} fonts).")
        print(f"Wrote {RENAMES_PATH} ({len(renames['renames'])} renames).")
        print(f"Left frozen v1 untouched: {V1_PATH}")

        fonts = source_data["fonts"]
        assert fonts["caskaydia-cove"]["name"] == "CaskaydiaCove Nerd Font"
        assert "Cascadia Code" in fonts["caskaydia-cove"]["aliases"]
        assert "CascadiaCode" in fonts["caskaydia-cove"]["variants"][0]["files"]["zip"]
        assert fonts["adwaita-mono"]["name"] == "AdwaitaMono Nerd Font"
        assert any(
            r["from"] == "nerd.cascadia-code" and r["to"] == "nerd.caskaydia-cove"
            for r in renames["renames"]
        )
        print("Cascadia + Adwaita spot-check ok.")

    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--self-check":
        _self_check()
        raise SystemExit(0)
    raise SystemExit(main())
