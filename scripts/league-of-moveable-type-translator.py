#!/usr/bin/env python3
"""
The League of Moveable Type — FontGet Sources translator

- Lists font repositories from the GitHub org `theleagueof` (public API).
- For each family, loads the matching page on theleagueofmoveabletype.com and
  extracts the canonical license link (same link shown in the UI as
  "Open Font License"), which points at a GitHub blob under that repo.
- Resolves the license text URL on raw.githubusercontent.com. The League's
  pages often link to OFL.txt while the repository actually contains OFL.md;
  we follow the website intent but HEAD-check until a 200 is found.
- Download: prefer the latest GitHub Release .zip asset when present; otherwise
  the default-branch source archive from GitHub.

Optional Google Fonts deduplication: when ``DEDUPLICATE_GOOGLE_FONTS`` is True, families
whose GitHub repo id or normalized display name matches ``sources/google-fonts.json`` are
omitted. Default is False (small foundry catalog). ``--no-google-dedupe`` turns deduplication
off for one run when the module flag is True.

Set ``GITHUB_TOKEN`` when possible: it avoids anonymous GitHub API rate limits so the
org listing, ``releases/latest`` ZIP detection, and Contents API (per-repo OFL files)
all work. Without it, the script uses a built-in repo list and may fall back to The
League's shared ``theleagueof/licenses`` OFL text when a font repository does not ship
OFL.md/OFL.txt (some repos only include an FAQ file).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, cast
from urllib.parse import unquote

import requests

ORG = "theleagueof"
SITE = "https://www.theleagueofmoveabletype.com"
GITHUB_API = "https://api.github.com"

# When True, omit League families that already appear in ``sources/google-fonts.json``.
DEDUPLICATE_GOOGLE_FONTS = False


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


# Repo name -> last path segment on the League website (slug)
WEBSITE_SLUG: Dict[str, str] = {
    "league-script-number-one": "league-script",
}

SKIP_REPOS = {"fontship", "licenses"}

# Used when the GitHub org listing API is rate-limited without GITHUB_TOKEN.
_FALLBACK_REPO_NAMES: Tuple[str, ...] = (
    "blackout",
    "chunk",
    "fanwood",
    "goudy-bookletter-1911",
    "junction",
    "knewave",
    "league-gothic",
    "league-mono",
    "league-script-number-one",
    "league-spartan",
    "linden-hill",
    "orbitron",
    "ostrich-sans",
    "prociono",
    "raleway",
    "sniglet",
    "sorts-mill-goudy",
    "the-neue-black",
)

# When a font repo has no OFL file on GitHub, The League still publishes OFL text here.
LEAGUE_OFL_TEMPLATE_RAW = (
    "https://raw.githubusercontent.com/theleagueof/licenses/master/OFL.md"
)

# Blob URLs embedded in RSC/HTML; filename may end with stray backslash.
BLOB_PATTERN = re.compile(
    rf'https://github\.com/{re.escape(ORG)}/([a-z0-9_-]+)/blob/(main|master)/([^"\'\s<>]+)',
    re.IGNORECASE,
)

TITLE_PATTERN = re.compile(r"<title>([^<|]+)", re.IGNORECASE)


class LeagueTranslator:
    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; FontGet-Sources/1.0; "
                    "+https://github.com/Graphixa/FontGet-Sources)"
                ),
            }
        )
        token = (os.environ.get("GITHUB_TOKEN") or "").strip()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _github(self, path: str, params: Optional[Dict[str, str]] = None) -> Any:
        url = f"{GITHUB_API}{path}"
        r = self.session.get(
            url,
            params=params or {},
            timeout=60,
            headers={"Accept": "application/vnd.github+json"},
        )
        if r.status_code == 403:
            if "rate limit" in (r.text or "").lower():
                raise RuntimeError(
                    "GitHub API rate limited. Set GITHUB_TOKEN for higher limits."
                )
        r.raise_for_status()
        return r.json()

    def list_font_repos(self) -> List[Dict[str, Any]]:
        repos: List[Dict[str, Any]] = []
        try:
            page = 1
            while True:
                batch = self._github(
                    f"/orgs/{ORG}/repos",
                    {"per_page": "100", "page": str(page), "type": "all"},
                )
                if not isinstance(batch, list) or not batch:
                    break
                repos.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
        except RuntimeError as e:
            if "rate limit" not in str(e).lower():
                raise
            print(
                "Warning: GitHub org listing rate-limited; using built-in League repo list. "
                "Set GITHUB_TOKEN for live metadata.",
                file=sys.stderr,
            )
            return self._fallback_repo_rows()

        out = [r for r in repos if r.get("name") not in SKIP_REPOS]
        return sorted(out, key=lambda x: str(x.get("name", "")).lower())

    @staticmethod
    def _fallback_repo_rows() -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for name in _FALLBACK_REPO_NAMES:
            branch = "main" if name == "the-neue-black" else "master"
            rows.append({"name": name, "default_branch": branch, "description": ""})
        return rows

    @staticmethod
    def website_path(repo: str) -> str:
        slug = WEBSITE_SLUG.get(repo, repo)
        return f"/{slug}/"

    def fetch_website_html(self, repo: str) -> str:
        path = self.website_path(repo)
        url = f"{SITE}{path}"
        # Trailing slash matches how the site redirects.
        r = self.session.get(
            url,
            timeout=60,
            headers={
                "User-Agent": self.session.headers["User-Agent"],
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        r.raise_for_status()
        return r.text

    @staticmethod
    def display_name_from_html(html: str) -> Optional[str]:
        m = TITLE_PATTERN.search(html)
        if not m:
            return None
        return m.group(1).strip()

    def extract_license_blob(self, html: str, repo: str) -> Optional[Tuple[str, str, str]]:
        """
        Returns (blob_url, branch, filename) for this repo's OFL/LICENSE blob
        as linked from the League website (first matching in document order).
        """
        for m in BLOB_PATTERN.finditer(html):
            repo_in_url, branch, fname = m.group(1), m.group(2), m.group(3)
            fname = fname.rstrip("\\").strip()
            if repo_in_url != repo:
                continue
            upper = fname.upper()
            if not (upper.startswith("OFL") or upper.startswith("LICENSE")):
                continue
            blob_url = f"https://github.com/{ORG}/{repo}/blob/{branch}/{fname}"
            return (blob_url, branch, fname)
        return None

    @staticmethod
    def blob_to_raw(repo: str, branch: str, filename: str) -> str:
        enc = "/".join(requests.utils.quote(p, safe="") for p in filename.split("/"))
        return f"https://raw.githubusercontent.com/{ORG}/{repo}/{branch}/{enc}"

    def raw_get_ok(self, url: str) -> bool:
        """True if raw.githubusercontent.com (or other) returns 200 for a small GET."""
        try:
            r = self.session.get(
                url,
                timeout=30,
                stream=True,
                headers={"Accept": "*/*"},
            )
            ok = r.status_code == 200
            r.close()
            return ok
        except OSError:
            return False

    def try_resolve_license_from_website_hint(
        self, repo: str, branch: str, hinted_filename: str
    ) -> Optional[Tuple[str, str]]:
        """
        Returns (raw_url, filename) using the League website blob path, trying
        common OFL.md / OFL.txt / branch swaps.
        """
        hinted_filename = unquote(hinted_filename.strip())
        base = hinted_filename.rsplit(".", 1)[0] if "." in hinted_filename else hinted_filename
        ext = hinted_filename.rsplit(".", 1)[-1].lower() if "." in hinted_filename else ""

        try_names: List[str] = [hinted_filename]
        if ext == "txt":
            try_names.append(f"{base}.md")
        elif ext == "md":
            try_names.append(f"{base}.txt")

        for extra in ("OFL.md", "OFL.txt"):
            if extra not in try_names:
                try_names.append(extra)

        branches = [branch]
        if branch == "main":
            branches.append("master")
        else:
            branches.append("main")

        seen: List[str] = []
        for br in branches:
            for fn in try_names:
                if fn in seen:
                    continue
                seen.append(fn)
                raw = self.blob_to_raw(repo, br, fn)
                if self.raw_get_ok(raw):
                    return raw, fn
        return None

    def license_from_repo_contents_api(
        self, repo: str, branches: List[str]
    ) -> Optional[Tuple[str, str]]:
        """
        Use GitHub Contents API to find OFL / LICENSE files in the repo root.
        Returns (download_url, filename).
        """
        for br in branches:
            url = f"{GITHUB_API}/repos/{ORG}/{repo}/contents"
            r = self.session.get(
                url,
                params={"ref": br},
                timeout=60,
                headers={"Accept": "application/vnd.github+json"},
            )
            if r.status_code in (403, 429):
                return None
            if r.status_code == 404:
                continue
            if not r.ok:
                r.raise_for_status()
            data = cast(Any, r.json())
            if not isinstance(data, list):
                continue

            by_name = {
                str(item.get("name")): item
                for item in data
                if isinstance(item, dict) and item.get("type") == "file"
            }
            for candidate in ("OFL.md", "OFL.txt", "LICENSE", "LICENSE.txt", "COPYING"):
                item = by_name.get(candidate)
                if item and item.get("download_url"):
                    return str(item["download_url"]), candidate

            for name, item in sorted(by_name.items(), key=lambda x: x[0].lower()):
                nl = name.lower()
                if nl.startswith("ofl") or nl.startswith("license") or nl == "copying":
                    du = item.get("download_url")
                    if du:
                        return str(du), name
        return None

    def resolve_license_url(
        self, repo: str, branch: str, hinted_filename: str
    ) -> Tuple[str, str, str]:
        """
        Returns (license_raw_url, resolved_label, method) where method is one of
        website_raw | github_contents | league_ofl_template.
        """
        branches = [branch]
        if branch == "main":
            branches.append("master")
        else:
            branches.append("main")

        hinted = self.try_resolve_license_from_website_hint(repo, branch, hinted_filename)
        if hinted:
            return hinted[0], hinted[1], "website_raw"

        gh = self.license_from_repo_contents_api(repo, branches)
        if gh:
            return gh[0], gh[1], "github_contents"

        return LEAGUE_OFL_TEMPLATE_RAW, "OFL.md (League template)", "league_ofl_template"

    def latest_release_zip(self, repo: str) -> Optional[str]:
        url = f"{GITHUB_API}/repos/{ORG}/{repo}/releases/latest"
        r = self.session.get(
            url,
            timeout=60,
            headers={"Accept": "application/vnd.github+json"},
        )
        if r.status_code == 404:
            return None
        if r.status_code in (403, 429):
            return None
        r.raise_for_status()
        rel = r.json()
        assets = rel.get("assets") or []
        zips = [
            a
            for a in assets
            if isinstance(a, dict) and str(a.get("name", "")).lower().endswith(".zip")
        ]
        if not zips:
            return None
        return str(zips[0].get("browser_download_url") or "")

    def source_archive_zip(self, repo: str, default_branch: str) -> str:
        return (
            f"https://github.com/{ORG}/{repo}/archive/refs/heads/"
            f"{default_branch}.zip"
        )

    def translate(self, deduplicate_google_fonts: bool = False) -> Dict[str, Any]:
        print("Fetching The League of Moveable Type…")
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

        repo_list = self.list_font_repos()
        print(f"Found {len(repo_list)} repositories.")
        fonts: Dict[str, Any] = {}
        errors: List[str] = []
        skipped_google_overlap = 0

        for i, repo_obj in enumerate(repo_list, start=1):
            repo = str(repo_obj.get("name") or "")
            if not repo:
                continue

            try:
                default_branch = str(repo_obj.get("default_branch") or "master")
                description = (repo_obj.get("description") or "").strip()
                if len(description) > 1000:
                    description = description[:997] + "…"

                time.sleep(0.35)
                html = self.fetch_website_html(repo)
                display = self.display_name_from_html(html) or repo.replace("-", " ").title()

                if deduplicate_google_fonts:
                    candidate_ids = {repo, _font_id_from_family_name(display)}
                    if candidate_ids & google_ids:
                        skipped_google_overlap += 1
                        continue

                blob = self.extract_license_blob(html, repo)
                if blob:
                    _blob_url, branch, hinted_file = blob
                else:
                    branch = default_branch
                    hinted_file = "OFL.txt"
                    print(
                        f"  warning: {repo}: no OFL blob link on League page; "
                        f"using GitHub contents / template fallback",
                        file=sys.stderr,
                    )

                license_url, resolved_file, lic_method = self.resolve_license_url(
                    repo, branch, hinted_file
                )

                zip_url = self.latest_release_zip(repo)
                download_kind = "release_zip"
                if not zip_url:
                    zip_url = self.source_archive_zip(repo, default_branch)
                    download_kind = "github_archive"

                slug = WEBSITE_SLUG.get(repo, repo)
                website_url = f"{SITE}/{slug}/"

                fonts[repo] = {
                    "name": display[:100],
                    "family": display[:100],
                    "license": "SIL Open Font License 1.1",
                    "license_url": license_url,
                    "designer": "",
                    "foundry": "The League of Moveable Type",
                    "version": "",
                    "description": description,
                    "categories": ["Display"],
                    "tags": ["league", "open-source"],
                    "popularity": 50,
                    "metadata_url": f"https://github.com/{ORG}/{repo}",
                    "source_url": website_url,
                    "variants": [
                        {
                            "name": f"{display} (family)",
                            "weight": 400,
                            "style": "normal",
                            "subsets": ["latin"],
                            "files": {"zip": zip_url},
                        }
                    ],
                    "unicode_ranges": [],
                    "languages": [],
                    "sample_text": "The quick brown fox jumps over the lazy dog",
                }

                # Schema allows optional last_modified; omit if unknown.
                # Keep a non-schema comment via description suffix is ugly; skip.

                print(
                    f"Processing {i}/{len(repo_list)}: {repo} "
                    f"(license={resolved_file}, {lic_method}, {download_kind})"
                )

            except Exception as e:
                msg = f"{repo}: {e}"
                errors.append(msg)
                print(f"Warning: {msg}", file=sys.stderr)

        if errors:
            raise RuntimeError(
                "League translator finished with errors:\n" + "\n".join(errors)
            )

        if deduplicate_google_fonts and skipped_google_overlap:
            print(f"Skipped {skipped_google_overlap} families already in google-fonts.json.")

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "source_info": {
                "name": "The League of Moveable Type",
                "description": (
                    "Open-source fonts from The League; license URLs taken from "
                    "theleagueofmoveabletype.com (resolved to OFL text on GitHub)."
                ),
                "url": "https://www.theleagueofmoveabletype.com",
                "api_endpoint": "https://api.github.com/orgs/theleagueof/repos",
                "version": "1.0",
                "last_updated": now,
                "total_fonts": len(fonts),
            },
            "fonts": fonts,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build League of Moveable Type font JSON.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output path (default: sources/league-of-moveable-type.json next to repo root).",
    )
    parser.add_argument(
        "--no-google-dedupe",
        action="store_true",
        help="Do not omit fonts that match sources/google-fonts.json (when DEDUPLICATE_GOOGLE_FONTS is True).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    out = args.output or (repo_root / "sources" / "league-of-moveable-type.json")

    translator = LeagueTranslator()
    dedupe = DEDUPLICATE_GOOGLE_FONTS and not args.no_google_dedupe
    data = translator.translate(deduplicate_google_fonts=dedupe)

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {out} ({data['source_info']['total_fonts']} fonts).")


if __name__ == "__main__":
    main()
