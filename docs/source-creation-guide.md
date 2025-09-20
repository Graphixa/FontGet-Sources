# FontGet Source Creation Guide

This guide explains how to create new font sources for FontGet. Each source must follow the FontGet Source Schema to ensure compatibility.

## Quick Start

1. **Choose your source**: Identify the font provider (API, GitHub repo, etc.)
2. **Create translator script**: Write a Python script to fetch and transform data
3. **Validate your output**: Use the validation tool to ensure compliance
4. **Set up automation**: Create GitHub Actions workflow for updates

## Source Structure

Each source file must contain:

```json
{
  "source_info": {
    "name": "Your Source Name",
    "description": "Brief description",
    "url": "https://your-source.com",
    "version": "1.0",
    "last_updated": "2024-01-15T10:30:00Z"
  },
  "fonts": {
    "yourprefix.fontname": {
      "name": "Font Display Name",
      "family": "Font Family",
      "license": "License Type",
      "variants": [...]
    }
  }
}
```

## Font ID Convention

Use this format: `{source_prefix}.{font_name}`

- **source_prefix**: Short identifier (3-8 characters)
- **font_name**: Lowercase, hyphenated font name

Examples:
- `google.roboto`
- `nerd.fira-code`
- `squirrel.opensans`

## Required Fields

### Source Info
- `name`: Human-readable source name
- `description`: Brief description
- `url`: Main website URL
- `version`: Schema version (e.g., "1.0")
- `last_updated`: ISO 8601 timestamp

### Font Data
- `name`: Display name
- `family`: Font family name
- `license`: License type
- `variants`: Array of font variants

### Variant Data
- `name`: Variant name (e.g., "Regular", "Bold")
- `weight`: Numeric weight (100-900)
- `style`: "normal", "italic", or "oblique"
- `files`: Object with format URLs

## File Formats

Only include these formats for local installation:
- `ttf`: TrueType fonts
- `otf`: OpenType fonts
- `fon`: Windows fonts

**Do NOT include**: WOFF, WOFF2 (web-only formats)

## Example Translator Script

```python
#!/usr/bin/env python3
"""
Example source translator for Your Font Source
"""

import json
import requests
from datetime import datetime
from typing import Dict, List, Any

def fetch_font_data(api_key: str = None) -> Dict[str, Any]:
    """Fetch font data from your source API."""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    response = requests.get("https://api.yoursource.com/fonts", headers=headers)
    response.raise_for_status()
    return response.json()

def transform_font(font_data: Dict[str, Any]) -> Dict[str, Any]:
    """Transform API data to FontGet format."""
    return {
        "name": font_data["display_name"],
        "family": font_data["family_name"],
        "license": font_data["license_type"],
        "license_url": font_data.get("license_url"),
        "designer": font_data.get("designer"),
        "foundry": font_data.get("foundry"),
        "version": font_data.get("version", "1.0"),
        "description": font_data.get("description", ""),
        "categories": font_data.get("categories", []),
        "tags": font_data.get("tags", []),
        "popularity": font_data.get("popularity_score"),
        "last_modified": font_data.get("last_modified"),
        "metadata_url": font_data.get("metadata_url"),
        "source_url": font_data.get("source_url"),
        "variants": transform_variants(font_data.get("variants", [])),
        "unicode_ranges": font_data.get("unicode_ranges", []),
        "languages": font_data.get("languages", []),
        "sample_text": font_data.get("sample_text", "")
    }

def transform_variants(variants_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Transform variant data to FontGet format."""
    transformed = []
    for variant in variants_data:
        files = {}
        if variant.get("ttf_url"):
            files["ttf"] = variant["ttf_url"]
        if variant.get("otf_url"):
            files["otf"] = variant["otf_url"]
        
        transformed.append({
            "name": variant["name"],
            "weight": variant["weight"],
            "style": variant["style"],
            "subsets": variant.get("subsets", []),
            "files": files
        })
    return transformed

def main():
    """Main translation function."""
    # Get API key from environment
    api_key = os.getenv("YOUR_SOURCE_API_KEY")
    
    # Fetch data
    raw_data = fetch_font_data(api_key)
    
    # Transform data
    fonts = {}
    for font in raw_data["fonts"]:
        font_id = f"yourprefix.{font['name'].lower().replace(' ', '-')}"
        fonts[font_id] = transform_font(font)
    
    # Create source structure
    source_data = {
        "source_info": {
            "name": "Your Source Name",
            "description": "Description of your source",
            "url": "https://yoursource.com",
            "version": "1.0",
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "total_fonts": len(fonts)
        },
        "fonts": fonts
    }
    
    # Write output
    with open("sources/your-source.json", "w", encoding="utf-8") as f:
        json.dump(source_data, f, indent=2, ensure_ascii=False)
    
    print(f"Generated source with {len(fonts)} fonts")

if __name__ == "__main__":
    main()
```

## GitHub Actions Workflow

Create `.github/workflows/update-your-source.yml`:

```yaml
name: Update Your Source
on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM
  workflow_dispatch:  # Manual trigger

jobs:
  update-your-source:
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      - name: Install dependencies
        run: |
          pip install requests jsonschema
      - name: Update Your Source
        run: |
          python scripts/your-source-translator.py
        env:
          YOUR_SOURCE_API_KEY: ${{ secrets.YOUR_SOURCE_API_KEY }}
      - name: Validate sources
        run: |
          python schemas/validate-sources.py sources/your-source.json
      - name: Commit changes
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"
          git add sources/your-source.json
          git commit -m "Update Your Source data" || exit 0
          git push
```

## Validation

Always validate your source before committing:

```bash
python schemas/validate-sources.py sources/your-source.json
```

## Best Practices

1. **Consistent naming**: Use lowercase, hyphenated font names
2. **Complete metadata**: Include all available information
3. **Error handling**: Handle API failures gracefully
4. **Rate limiting**: Respect API rate limits
5. **Testing**: Test with real data before deploying
6. **Documentation**: Document any special requirements

## Common Issues

### Schema Violations
- Missing required fields
- Invalid font ID format
- Incorrect data types
- Invalid URLs

### Data Quality
- Inconsistent naming
- Missing variants
- Broken download links
- Incomplete metadata

## Getting Help

- Check the schema: `schemas/font-source-schema.json`
- Use validation tool: `python schemas/validate-sources.py`
- Review examples: `examples/`
- Open an issue for questions
