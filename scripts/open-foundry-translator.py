#!/usr/bin/env python3
"""
Open Foundry → FontGet JSON via Nuxt ``__NUXT_DATA__`` (devalue).

Loads homepage slugs and ``/fonts/{slug}`` payloads; resolves download/repo URLs to
schema-valid assets (suffix match, GitHub release ZIP or archive, GitLab archive API).
Optional ``GITHUB_TOKEN`` / ``GITLAB_TOKEN``. Duplicate-per-instance ZIPs collapse to one variant.
``DEDUPLICATE_GOOGLE_FONTS`` drops overlaps with ``sources/google-fonts.json``; ``--no-google-dedupe`` disables when enabled.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, urlparse

import requests

GITHUB_API = "https://api.github.com"
GITLAB_API = "https://gitlab.com/api/v4"

DEDUPLICATE_GOOGLE_FONTS = True  # skip families already in sources/google-fonts.json


def _font_id_from_family_name(family_name: str) -> str:
	clean_name = re.sub(r"[^a-z0-9-]", "-", family_name.lower())
	clean_name = re.sub(r"-+", "-", clean_name).strip("-")
	return clean_name


def _load_google_font_family_ids(google_fonts_json: Path) -> Set[str]:
	"""Font ids from google-fonts.json keys and normalized family/name."""
	with open(google_fonts_json, encoding="utf-8") as f:
		data = json.load(f)
	ids: Set[str] = set()
	for key, entry in data.get("fonts", {}).items():
		ids.add(key)
		fam = (entry.get("family") or entry.get("name") or "").strip()
		if fam:
			ids.add(_font_id_from_family_name(fam))
	return ids

_GITHUB_REPO_RE = re.compile(
	r"^https?://(?:www\.)?github\.com/([^/]+)/([^/#?]+)",
	re.IGNORECASE,
)

# devalue sentinels (Rich-Harris/devalue)
_DE_UNDEFINED = -1
_DE_HOLE = -2
_DE_NAN = -3
_DE_POS_INF = -4
_DE_NEG_INF = -5
_DE_NEG_ZERO = -6


def _parse_nuxt_devalue(serialized: str) -> Any:
	"""Revive Nuxt ``__NUXT_DATA__`` JSON text (devalue flatten format)."""

	def _unwrap_reactive(inner: Any) -> Any:
		return inner

	revivers = {
		"ShallowReactive": _unwrap_reactive,
		"Reactive": _unwrap_reactive,
		"Ref": _unwrap_reactive,
		"ShallowRef": _unwrap_reactive,
	}

	values: List[Any] = json.loads(serialized)
	hydrated: Dict[int, Any] = {}

	def hydrate(index: int, standalone: bool = False) -> Any:
		if index == _DE_UNDEFINED:
			return None
		if index == _DE_NAN:
			return float("nan")
		if index == _DE_POS_INF:
			return float("inf")
		if index == _DE_NEG_INF:
			return float("-inf")
		if index == _DE_NEG_ZERO:
			return -0.0

		if standalone or not isinstance(index, int):
			raise ValueError("Invalid devalue reference")

		if index in hydrated:
			return hydrated[index]

		value = values[index]

		if value is None or isinstance(value, str) or isinstance(value, bool):
			hydrated[index] = value
			return hydrated[index]
		if isinstance(value, (int, float)) and not isinstance(value, bool):
			hydrated[index] = value
			return hydrated[index]

		if isinstance(value, list):
			if value and isinstance(value[0], str):
				type_tag = value[0]
				reviver = revivers.get(type_tag)
				if reviver is not None:
					i = value[1]
					if type(i) is not int:
						values.append(i)
						i = len(values) - 1
					hydrated[index] = reviver(hydrate(i))
					return hydrated[index]

				if type_tag == "Set":
					out: List[Any] = []
					for j in range(1, len(value)):
						out.append(hydrate(value[j]))
					hydrated[index] = out
					return hydrated[index]

				if type_tag == "Date":
					hydrated[index] = value[1]
					return hydrated[index]

				if type_tag == "Map":
					m: Dict[Any, Any] = {}
					for j in range(1, len(value), 2):
						m[hydrate(value[j])] = hydrate(value[j + 1])
					hydrated[index] = m
					return hydrated[index]

				if type_tag == "null":
					d_null: Dict[str, Any] = {}
					for j in range(1, len(value), 2):
						d_null[str(value[j])] = hydrate(value[j + 1])
					hydrated[index] = d_null
					return hydrated[index]

				if type_tag == "BigInt":
					hydrated[index] = int(value[1])
					return hydrated[index]

				if type_tag == "Object":
					wrapped = value[1]
					if type(wrapped) is not int:
						raise ValueError("Invalid Object wrapper in devalue payload")
					hydrated[index] = hydrate(wrapped)
					return hydrated[index]

				raise ValueError(f"Unsupported devalue type tag: {type_tag!r}")

			arr: List[Any] = [None] * len(value)
			hydrated[index] = arr
			for i, n in enumerate(value):
				if n == _DE_HOLE:
					continue
				arr[i] = hydrate(n)
			return arr

		obj: Dict[str, Any] = {}
		hydrated[index] = obj
		for key in value.keys():
			if key == "__proto__":
				raise ValueError("Invalid __proto__ key in payload")
			obj[key] = hydrate(value[key])
		return obj

	return hydrate(0)


def _extract_nuxt_payload(html: str) -> str:
	m = re.search(
		r'<script[^>]+id="__NUXT_DATA__"[^>]*>([\s\S]*?)</script>',
		html,
		re.IGNORECASE,
	)
	if not m:
		raise ValueError("No __NUXT_DATA__ script found in HTML")
	return m.group(1).strip()


def _files_from_distribution_url(url: str) -> Dict[str, str]:
	"""``files`` dict from URL suffix, or empty if invalid."""
	if not url or not isinstance(url, str):
		return {}
	url = url.strip()
	if not url:
		return {}
	try:
		path = urlparse(url).path or ""
	except Exception:
		path = ""
	pl = path.lower()

	if pl.endswith(".ttf"):
		return {"ttf": url}
	if pl.endswith(".otf"):
		return {"otf": url}
	if pl.endswith(".tar.xz"):
		return {"tar_xz": url}
	if pl.endswith(".zip"):
		return {"zip": url}
	return {}


def _parse_github_repo(url: str) -> Optional[Tuple[str, str]]:
	"""Parse ``github.com/{owner}/{repo}``, or None."""
	if not url or not isinstance(url, str):
		return None
	u = url.strip()
	if not u:
		return None
	if not u.startswith(("http://", "https://")):
		u = "https://" + u
	m = _GITHUB_REPO_RE.match(u)
	if not m:
		return None
	owner, repo = m.group(1), m.group(2)
	if owner.lower() in {"orgs", "sponsors", "settings", "apps"}:
		return None
	repo = repo.removesuffix(".git")
	return owner, repo


def _parse_gitlab_path(url: str) -> Optional[str]:
	"""GitLab project path ``group/.../repo`` for API, or None."""
	if not url or not isinstance(url, str):
		return None
	u = url.strip()
	if not u:
		return None
	if not u.startswith(("http://", "https://")):
		u = "https://" + u
	try:
		p = urlparse(u)
	except Exception:
		return None
	host = (p.netloc or "").lower()
	if host.startswith("www."):
		host = host[4:]
	if host != "gitlab.com":
		return None
	path = (p.path or "").strip("/")
	if "/-/" in path:
		path = path.split("/-/")[0].strip("/")
	parts = [x for x in path.split("/") if x]
	if len(parts) < 2:
		return None
	return "/".join(parts)


def _slugify_for_match(text: str) -> str:
	s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").lower()).strip("-")
	return re.sub(r"-+", "-", s)


def _pick_best_github_zip_asset(
	assets: List[Any], *, slug: str, family_name: str
) -> Optional[str]:
	"""Best matching ``.zip`` release asset URL."""
	zips: List[Tuple[str, str]] = []
	for a in assets:
		if not isinstance(a, dict):
			continue
		name = str(a.get("name") or "")
		if not name.lower().endswith(".zip"):
			continue
		bdu = a.get("browser_download_url")
		if isinstance(bdu, str) and bdu.strip():
			zips.append((name, bdu.strip()))
	if not zips:
		return None

	slug_l = (slug or "").lower()
	fam = _slugify_for_match(family_name)
	keywords = ("fonts", "otf", "ttf", "desktop")

	def sort_key(item: Tuple[str, str]) -> Tuple[int, str]:
		name, _ = item
		nl = name.lower()
		score = 0
		if slug_l and slug_l.replace("-", "") in nl.replace("-", "").replace("_", ""):
			score += 100
		elif slug_l and slug_l in nl:
			score += 100
		if fam and len(fam) > 2 and fam in nl.replace("_", "-"):
			score += 80
		for kw in keywords:
			if kw in nl:
				score += 10
		return (-score, nl)

	zips.sort(key=sort_key)
	return zips[0][1]


class OpenFoundryTranslator:
	INDEX_URL = "https://open-foundry.com/"
	FONT_PAGE_TMPL = "https://open-foundry.com/fonts/{slug}"

	def __init__(self) -> None:
		self._session = requests.Session()
		self._session.headers.update(
			{
				"User-Agent": (
					"FontGet-Sources-OpenFoundryTranslator/3.0 "
					"(+https://github.com/Graphixa/FontGet-Sources)"
				),
				"Accept": "text/html,application/xhtml+xml",
			}
		)
		token = (os.environ.get("GITHUB_TOKEN") or "").strip()
		if token:
			self._session.headers["Authorization"] = f"Bearer {token}"
		self._gitlab_token = (os.environ.get("GITLAB_TOKEN") or "").strip()
		self._github_zip_cache: Dict[Tuple[str, str], str] = {}
		self._gitlab_zip_cache: Dict[str, str] = {}
		self._github_rate_warned = False

	def _get_html(self, url: str) -> str:
		resp = self._session.get(url, timeout=30)
		resp.raise_for_status()
		return resp.text

	def _github_get_json(self, path: str) -> Any:
		url = f"{GITHUB_API}{path}"
		headers = {
			"Accept": "application/vnd.github+json",
			"User-Agent": self._session.headers.get("User-Agent", ""),
		}
		auth = self._session.headers.get("Authorization")
		if auth:
			headers["Authorization"] = auth
		r = self._session.get(url, headers=headers, timeout=60)
		if r.status_code == 403 and "rate limit" in (r.text or "").lower():
			if not self._github_rate_warned:
				print(
					"  Warning: GitHub API rate limited. Set GITHUB_TOKEN for higher limits.",
					file=sys.stderr,
				)
				self._github_rate_warned = True
			raise RuntimeError("github_rate_limited")
		if r.status_code in (403, 429):
			raise RuntimeError(f"github_http_{r.status_code}")
		if r.status_code == 404:
			return None
		r.raise_for_status()
		return r.json()

	def _github_resolve_zip(self, owner: str, repo: str, slug: str, family_name: str) -> str:
		key = (owner.lower(), repo.lower())
		if key in self._github_zip_cache:
			return self._github_zip_cache[key]

		zip_url = ""
		try:
			rel = self._github_get_json(f"/repos/{owner}/{repo}/releases/latest")
			if isinstance(rel, dict):
				assets = rel.get("assets") or []
				if isinstance(assets, list):
					picked = _pick_best_github_zip_asset(
						assets, slug=slug, family_name=family_name
					)
					if picked:
						zip_url = picked
			if not zip_url:
				repo_meta = self._github_get_json(f"/repos/{owner}/{repo}")
				if isinstance(repo_meta, dict):
					branch = str(repo_meta.get("default_branch") or "main")
					zip_url = (
						f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
					)
		except RuntimeError as e:
			msg = str(e)
			if msg == "github_rate_limited":
				return ""
			if msg.startswith("github_http_"):
				return ""
			raise
		except requests.RequestException:
			return ""

		self._github_zip_cache[key] = zip_url
		return zip_url

	def _gitlab_headers(self) -> Dict[str, str]:
		h: Dict[str, str] = {
			"User-Agent": str(self._session.headers.get("User-Agent") or ""),
		}
		if self._gitlab_token:
			h["PRIVATE-TOKEN"] = self._gitlab_token
		return h

	def _gitlab_resolve_zip(self, project_path: str) -> str:
		if project_path in self._gitlab_zip_cache:
			return self._gitlab_zip_cache[project_path]

		encoded = quote(project_path, safe="")
		meta_url = f"{GITLAB_API}/projects/{encoded}"
		r = self._session.get(meta_url, headers=self._gitlab_headers(), timeout=60)
		if r.status_code != 200:
			rel_url = f"{GITLAB_API}/projects/{encoded}/releases/permalink/latest"
			r2 = self._session.get(rel_url, headers=self._gitlab_headers(), timeout=60)
			zip_url = ""
			if r2.status_code == 200:
				try:
					data = r2.json()
				except Exception:
					data = {}
				if isinstance(data, dict):
					for link in data.get("assets", {}).get("links", []) or []:
						if not isinstance(link, dict):
							continue
						u = link.get("url") or link.get("direct_asset_url")
						if isinstance(u, str) and u.strip():
							try:
								pl = (urlparse(u.strip()).path or "").lower()
							except Exception:
								pl = ""
							if pl.endswith(".zip"):
								zip_url = u.strip()
								break
			self._gitlab_zip_cache[project_path] = zip_url
			return zip_url

		try:
			meta = r.json()
		except Exception:
			self._gitlab_zip_cache[project_path] = ""
			return ""
		branch = str(meta.get("default_branch") or "main")
		zip_url = f"{GITLAB_API}/projects/{encoded}/repository/archive.zip?sha={quote(branch)}"
		self._gitlab_zip_cache[project_path] = zip_url
		return zip_url

	def _resolve_distribution_url(
		self, url: str, *, slug: str, family_name: str
	) -> Dict[str, str]:
		direct = _files_from_distribution_url(url)
		if direct:
			return direct
		gh = _parse_github_repo(url)
		if gh:
			owner, repo = gh
			try:
				z = self._github_resolve_zip(owner, repo, slug, family_name)
			except (requests.RequestException, RuntimeError, ValueError, KeyError):
				z = ""
			if z:
				return {"zip": z}
			return {}
		gl = _parse_gitlab_path(url)
		if gl:
			z = self._gitlab_resolve_zip(gl)
			if z:
				return {"zip": z}
			return {}
		return {}

	def _parse_page(self, html: str) -> Dict[str, Any]:
		payload = _extract_nuxt_payload(html)
		root = _parse_nuxt_devalue(payload)
		if not isinstance(root, dict) or "data" not in root:
			raise ValueError("Unexpected Nuxt root shape")
		data = root["data"]
		if not isinstance(data, dict):
			raise ValueError("Unexpected Nuxt data shape")
		return data

	def discover_slugs(self) -> List[str]:
		html = self._get_html(self.INDEX_URL)
		data = self._parse_page(html)
		slugs: List[str] = []
		for key, block in data.items():
			if not key.startswith("of-font-hero-"):
				continue
			if isinstance(block, dict):
				slug = block.get("slug")
				if isinstance(slug, str) and slug.strip():
					slugs.append(slug.strip())
		seen = set()
		out: List[str] = []
		for s in slugs:
			if s not in seen:
				seen.add(s)
				out.append(s)
		return out

	def fetch_font_record(self, slug: str) -> Optional[Dict[str, Any]]:
		html = self._get_html(self.FONT_PAGE_TMPL.format(slug=slug))
		data = self._parse_page(html)
		key = f"font-{slug}-false"
		rec = data.get(key)
		return rec if isinstance(rec, dict) else None

	def _clean_id(self, value: str) -> str:
		clean = re.sub(r"[^a-z0-9-]", "-", value.lower())
		clean = re.sub(r"-+", "-", clean).strip("-")
		return clean

	def _normalize_category(self, category: str) -> str:
		if not category or not str(category).strip():
			return "Other"
		cleaned = str(category).replace("-", " ").replace("_", " ").strip()
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

	@staticmethod
	def _collapse_identical_file_variants(
		variants: List[Dict[str, Any]], *, family_name: str
	) -> List[Dict[str, Any]]:
		"""Merge variants that share identical ``files`` (one archive install)."""
		if len(variants) <= 1:
			return variants
		key0 = json.dumps(variants[0]["files"], sort_keys=True, ensure_ascii=False)
		if not all(
			json.dumps(v["files"], sort_keys=True, ensure_ascii=False) == key0
			for v in variants
		):
			return variants
		pkg = (family_name or "").strip() or "Regular"
		if len(pkg) > 100:
			pkg = pkg[:97] + "…"
		return [
			{
				"name": pkg,
				"weight": 400,
				"style": "normal",
				"subsets": ["latin"],
				"files": dict(variants[0]["files"]),
			}
		]

	def _pick_files(self, rec: Dict[str, Any], slug: str, family_name: str) -> Dict[str, str]:
		for key in ("downloadUrl", "projectUrl", "repositoryUrl"):
			raw = rec.get(key)
			if isinstance(raw, str) and raw.strip():
				files = self._resolve_distribution_url(
					raw.strip(), slug=slug, family_name=family_name
				)
				if files:
					return files
		return {}

	def _build_font(self, slug: str, rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
		name = rec.get("name") or slug
		if not isinstance(name, str):
			name = str(name)

		files = self._pick_files(rec, slug, name)
		if not files:
			return None

		instances = rec.get("instances") or []
		if not isinstance(instances, list) or not instances:
			return None

		variants: List[Dict[str, Any]] = []
		seen: set = set()
		for inst in instances:
			if not isinstance(inst, dict):
				continue
			weight = inst.get("weight")
			try:
				w = int(weight)
				if w < 100 or w > 900 or w % 100 != 0:
					continue
			except (TypeError, ValueError):
				continue
			style_raw = str(inst.get("style", "normal")).lower()
			style = "italic" if "italic" in style_raw or "oblique" in style_raw else "normal"
			if style not in ("normal", "italic", "oblique"):
				style = "normal"
			vname = inst.get("name")
			if not isinstance(vname, str) or not vname.strip():
				vname = f"{name} {w}"
			key = (w, style, tuple(sorted(files.items())))
			if key in seen:
				continue
			seen.add(key)
			variants.append(
				{
					"name": vname.strip(),
					"weight": w,
					"style": style,
					"subsets": ["latin"],
					"files": dict(files),
				}
			)

		if not variants:
			return None

		variants = self._collapse_identical_file_variants(variants, family_name=name)

		licence = rec.get("licence") or {}
		license_type = "Other"
		license_url = ""
		if isinstance(licence, dict):
			ln = licence.get("name")
			if isinstance(ln, str) and ln.strip():
				license_type = ln.strip()[:100]
			lu = licence.get("url")
			if isinstance(lu, str) and lu.strip():
				license_url = lu.strip()

		classification = rec.get("classification")
		categories: List[str] = []
		if isinstance(classification, str) and classification.strip():
			categories = [self._normalize_category(classification)]

		creators = rec.get("creator") or []
		designer_parts: List[str] = []
		if isinstance(creators, list):
			for c in creators:
				if isinstance(c, dict):
					nm = c.get("name")
					if isinstance(nm, str) and nm.strip():
						designer_parts.append(nm.strip())
		designer = ", ".join(designer_parts)[:200]

		font_id = self._clean_id(name)
		metadata_url = rec.get("repositoryUrl") or rec.get("projectUrl") or ""
		if not isinstance(metadata_url, str):
			metadata_url = ""
		source_url = self.FONT_PAGE_TMPL.format(slug=slug)

		desc = (rec.get("description") or "").strip() if isinstance(rec.get("description"), str) else ""
		if len(desc) > 1000:
			desc = desc[:997] + "…"

		return {
			"name": name[:100],
			"family": name[:100],
			"license": license_type,
			"license_url": license_url,
			"designer": designer,
			"foundry": "",
			"version": "",
			"description": desc,
			"categories": categories,
			"tags": [],
			"popularity": 0,
			"last_modified": datetime.utcnow().isoformat() + "Z",
			"metadata_url": metadata_url.strip(),
			"source_url": source_url,
			"variants": variants,
			"unicode_ranges": [],
			"languages": [],
			"sample_text": "The quick brown fox jumps over the lazy dog",
		}

	def translate(self, deduplicate_google_fonts: Optional[bool] = None) -> Dict[str, Any]:
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

		print("Fetching Open Foundry homepage…")
		slugs = self.discover_slugs()
		print(f"Discovered {len(slugs)} font slug(s) from homepage payload.")

		fonts: Dict[str, Any] = {}
		skipped_google_overlap = 0
		for i, slug in enumerate(slugs):
			if i:
				time.sleep(0.35)
			try:
				rec = self.fetch_font_record(slug)
			except Exception as ex:
				print(f"  skip {slug!r}: {ex}")
				continue
			if not rec:
				print(f"  skip {slug!r}: no font record in payload")
				continue
			built = self._build_font(slug, rec)
			if not built:
				print(
					f"  skip {slug!r}: no resolvable installable URL "
					"(direct suffix, GitHub release/archive, or GitLab archive)"
				)
				continue
			if deduplicate_google_fonts:
				fam = str(built.get("family") or built.get("name") or "")
				candidate_ids = {
					slug,
					_font_id_from_family_name(fam),
					self._clean_id(fam),
				}
				candidate_ids.discard("")
				if candidate_ids & google_ids:
					skipped_google_overlap += 1
					print(f"  skip {slug!r}: already in google-fonts.json")
					continue
			fid = self._clean_id(built["name"])
			base = fid
			n = 2
			while fid in fonts:
				fid = f"{base}-{n}"
				n += 1
			fonts[fid] = built
			print(f"  ok {slug!r} -> {fid}")

		source = {
			"source_info": {
				"name": "Open Foundry",
				"description": "Curated open-source fonts from Open Foundry (Nuxt SSR payload)",
				"url": "https://open-foundry.com",
				"api_endpoint": "https://open-foundry.com/",
				"version": "3.0",
				"last_updated": datetime.utcnow().isoformat() + "Z",
				"total_fonts": len(fonts),
			},
			"fonts": fonts,
		}
		if deduplicate_google_fonts and skipped_google_overlap:
			print(f"Skipped {skipped_google_overlap} families already in google-fonts.json.")
		print(f"Built {len(fonts)} font famil(ies) with validator-safe file URLs.")
		return source


def main() -> int:
	parser = argparse.ArgumentParser(
		description="Generate FontGet source JSON for Open Foundry."
	)
	parser.add_argument(
		"--no-google-dedupe",
		action="store_true",
		help="Do not exclude fonts whose slug or normalized family id matches sources/google-fonts.json.",
	)
	args = parser.parse_args()

	try:
		translator = OpenFoundryTranslator()
		dedupe = DEDUPLICATE_GOOGLE_FONTS and not args.no_google_dedupe
		source_data = translator.translate(deduplicate_google_fonts=dedupe)
		os.makedirs("sources", exist_ok=True)
		with open("sources/open-foundry.json", "w", encoding="utf-8") as f:
			json.dump(source_data, f, indent=2, ensure_ascii=False)
		n = source_data["source_info"]["total_fonts"]
		print(f"Wrote sources/open-foundry.json ({n} fonts).")
		return 0
	except Exception as e:
		print(f"Error: {e}")
		return 1


if __name__ == "__main__":
	raise SystemExit(main())
