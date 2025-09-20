# FontGet Sources

This repository contains standardized font source data for the FontGet CLI tool. Each source provides a consistent JSON format that FontGet can consume for font discovery and installation.

## Repository Structure

```
fontget-sources/
├── .github/
│   └── workflows/          # GitHub Actions for automated updates
├── sources/                # Source JSON files
│   ├── google-fonts.json
│   ├── nerd-fonts.json
│   └── font-squirrel.json
├── scripts/                # Source translators
│   ├── google-fonts-translator.py
│   ├── nerd-fonts-translator.py
│   └── font-squirrel-translator.py
├── schemas/                # JSON schemas and validation
│   ├── font-source-schema.json
│   ├── font-variant-schema.json
│   └── validate-sources.py
├── docs/                   # Documentation
│   ├── source-creation-guide.md
│   └── api-reference.md
└── examples/               # Example source files
    ├── minimal-source.json
    └── complete-source.json
```

## Source Format

Each source file follows the FontGet Source Schema (see `schemas/font-source-schema.json`). The schema ensures consistency across all sources and makes it easy for contributors to create new sources.

## Adding New Sources

1. Create a new translator script in `scripts/`
2. Add a GitHub Actions workflow in `.github/workflows/`
3. Follow the schema validation guidelines
4. Test your source with the validation tool

## Validation

All source files are validated against the JSON schema before being committed. Use the validation tool:

```bash
python schemas/validate-sources.py sources/your-source.json
```

## Contributing

See `docs/source-creation-guide.md` for detailed instructions on creating new font sources.
