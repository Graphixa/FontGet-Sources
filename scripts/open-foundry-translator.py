#!/usr/bin/env python3
"""
Open Foundry Translator for FontGet

Fetches font data from Open Foundry dataset and transforms it to FontGet format.
Data source: https://open-foundry.com/data/sheet.json
"""

import json
import os
import re
from datetime import datetime
from typing import Dict, List, Any, Optional

import requests


class OpenFoundryTranslator:
	def __init__(self) -> None:
		self.api_url = "https://open-foundry.com/data/sheet.json"

	def fetch(self) -> List[Dict[str, Any]]:
		resp = requests.get(self.api_url, timeout=15)
		resp.raise_for_status()
		data = resp.json()
		if not isinstance(data, list):
			raise ValueError("Unexpected Open Foundry response shape")
		return data

	def _clean_id(self, value: str) -> str:
		clean = re.sub(r"[^a-z0-9-]", "-", value.lower())
		clean = re.sub(r"-+", "-", clean).strip("-")
		return clean

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
			
			#Additional re-mappings to core 10 categories
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

	def _weight_from_info(self, weight: Any) -> int:
		try:
			w = int(weight)
			if 100 <= w <= 900:
				return w
		except Exception:
			pass
		# Fallback based on keywords in style
		return 400

	def _style_from_info(self, style: str) -> str:
		if not style:
			return "normal"
		style_l = style.lower()
		if "italic" in style_l or "oblique" in style_l:
			return "italic"
		return "normal"

	def _build_variant(self, family: str, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
		weight = self._weight_from_info(row.get("info-weight"))
		style = self._style_from_info(str(row.get("info-style", "")))
		weight_names = {
			100: "Thin", 200: "Extra Light", 300: "Light", 400: "Regular",
			500: "Medium", 600: "Semi Bold", 700: "Bold", 800: "Extra Bold", 900: "Black",
		}
		name = f"{family} {weight_names.get(weight, str(weight))}"
		if style == "italic":
			name += " Italic"

		files: Dict[str, str] = {}
		dl = row.get("font-download-link", "")
		if isinstance(dl, str) and dl:
			if dl.endswith((".ttf", ".otf")):
				files[dl.rsplit(".", 1)[-1].lower()] = dl
			elif dl.endswith((".zip", ".tar.gz", ".tar.xz")):
				# Provide archive as-is; CLI extracts
				ext = dl.split(".")[-1].lower()
				# Reconstruct full archive extension for tarballs
				if dl.endswith(".tar.gz"):
					ext = "tar.gz"
				elif dl.endswith(".tar.xz"):
					ext = "tar.xz"
				files[ext] = dl
		# If no direct file, skip creating a variant (no installable or archive reference)
		if not files:
			return None

		return {
			"name": name,
			"weight": weight,
			"style": style,
			"subsets": ["latin"],
			"files": files,
		}

	def translate(self) -> Dict[str, Any]:
		rows = self.fetch()
		# Group by family (font-name)
		families: Dict[str, List[Dict[str, Any]]] = {}
		for row in rows:
			family = row.get("font-name")
			if not family:
				continue
			families.setdefault(family, []).append(row)

		fonts: Dict[str, Any] = {}
		for family, items in families.items():
			font_id = self._clean_id(family)
			# Build variants
			variants: List[Dict[str, Any]] = []
			seen = set()
			for r in items:
				variant = self._build_variant(family, r)
				if not variant:
					continue
				key = (variant["weight"], variant["style"], tuple(sorted(variant["files"].items())))
				if key in seen:
					continue
				seen.add(key)
				variants.append(variant)
			if not variants:
				# Skip families with no usable download links
				continue

			license_type = items[0].get("info-license", "Other")
			license_url = items[0].get("info-license-link", "")
			classification = items[0].get("info-classification")
			categories: List[str] = []
			if classification:
				categories = [self._normalize_category(classification)]

			fonts[font_id] = {
				"name": family,
				"family": family,
				"license": license_type,
				"license_url": license_url,
				"designer": items[0].get("font-creator", ""),
				"foundry": items[0].get("font-foundry", ""),
				"version": str(items[0].get("info-version", "")),
				"description": items[0].get("info-about", ""),
				"categories": categories,
				"tags": [],
				"popularity": 0,
				"last_modified": datetime.utcnow().isoformat() + "Z",
				"metadata_url": items[0].get("font-open-source-link", ""),
				"source_url": items[0].get("font-found-link", items[0].get("font-open-source-link", "")),
				"variants": variants,
				"unicode_ranges": [],
				"languages": [],
				"sample_text": items[0].get("settings-text", "The quick brown fox jumps over the lazy dog"),
			}

		source = {
			"source_info": {
				"name": "Open Foundry",
				"description": "Curated open-source fonts from Open Foundry",
				"url": "https://open-foundry.com",
				"api_endpoint": self.api_url,
				"version": "1.0",
				"last_updated": datetime.utcnow().isoformat() + "Z",
				"total_fonts": len(fonts),
			},
			"fonts": fonts,
		}
		return source


def main() -> int:
	try:
		translator = OpenFoundryTranslator()
		source_data = translator.translate()
		os.makedirs("sources", exist_ok=True)
		with open("sources/open-foundry.json", "w", encoding="utf-8") as f:
			json.dump(source_data, f, indent=2, ensure_ascii=False)
		print(f"Successfully generated sources/open-foundry.json with {source_data['source_info']['total_fonts']} fonts")
		return 0
	except Exception as e:
		print(f"Error: {e}")
		return 1


if __name__ == "__main__":
	exit(main())
