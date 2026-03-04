# Bagpiper Demo Page

A YAML-driven demo page for comparing audio editing models.

## Quick start (local)

```bash
pip install jinja2 pyyaml
python build.py                # generates index.html
open index.html                # preview in browser
```

## Structure

```
demo/
├── config.yaml          # ← edit this to add samples / sections
├── build.py             # YAML → HTML renderer
├── templates/
│   └── index.html       # Jinja2 template
├── audios/              # audio files (wav/mp3), organised by category
│   ├── speech/
│   ├── audio/
│   └── creative/
├── assets/              # images, logos
└── .github/
    └── workflows/
        └── deploy.yml   # GitHub Actions: auto-build & deploy to Pages
```

## Adding samples

1. Put wav/mp3 files under `audios/` (matching paths in `config.yaml`)
2. Add entries to `config.yaml` under the appropriate subsection
3. Run `python build.py` to rebuild

## GitHub Pages deployment

Push to `main` branch → GitHub Actions builds and deploys automatically.

To enable:
1. Go to repo → Settings → Pages
2. Set Source to **GitHub Actions**
