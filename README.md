# FontGet Sources

This repository provides font data for the [Fontget](https://github.com/Graphixa/FontGet) CLI tool. It contains standardized information about fonts from popular sources, automatically updated daily.

A GitHub Actions workflow runs daily to fetch, transform, and sanitize data from each font API into [Fontget](https://github.com/Graphixa/FontGet) compatible source files.

## Font Sources

- **[Google Fonts](sources/google-fonts.json)**
- **[Nerd Fonts](sources/nerd-fonts.json)**
- **[Font Squirrel](sources/font-squirrel.json)**

## What's Inside

Each source file contains font information like:
- Font names and families
- Download URLs (direct files or archives)
- Font weights and styles
- License info
- Designer and foundry details

## For FontGet Users

[Fontget](https://github.com/Graphixa/FontGet) CLI tool automatically uses this data to find and install fonts. You can also fork this repository or use the data directly for your own font lookup needs.

## For Developers

- **[Schemas](schemas/)** - JSON validation rules
- **[Scripts](scripts/)** - Data update automation
- **[Sources](sources/)** - The actual font data files

Want to create a FontGet-compatible source to import into [Fontget](https://github.com/Graphixa/FontGet)? Check out the [JSON Schema](schemas/font-source-schema.json) and examine the [translator scripts](scripts/) for examples.

## Special Thanks

- **[Google Fonts](https://fonts.google.com/)** - For providing the Google Fonts API
- **[Font Squirrel](https://www.fontsquirrel.com/)** - For their free font collection and API
- **[Nerd Fonts](https://www.nerdfonts.com/)** - Created by [Ryan L McIntyre](https://github.com/ryanoasis) for developer-focused fonts