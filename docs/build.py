#!/usr/bin/env python3
"""
build.py — Render the Bagpiper demo page from config.yaml + Jinja2 template.

Usage:
    # Install deps once:
    pip install jinja2 pyyaml

    # Build:
    python build.py                         # default: config.yaml → docs/index.html
    python build.py -c my_config.yaml       # custom config
    python build.py -o out/index.html       # custom output path

The generated index.html is a self-contained static page (no server needed).
Open it directly in a browser or serve via GitHub Pages.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build(config_path: str, output_path: str, template_dir: str | None = None) -> str:
    cfg = load_config(config_path)

    if template_dir is None:
        template_dir = str(Path(__file__).parent / "templates")

    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=False,  # we trust our own YAML content; HTML is intentional
    )
    template = env.get_template("index.html")

    html = template.render(**cfg)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    # # Copy static asset dirs (audios/, assets/) into the output directory
    # out_dir = Path(output_path).parent
    # repo_root = Path(config_path).parent
    # for asset_dir in ("audios", "assets"):
    #     src = repo_root / asset_dir
    #     dst = out_dir / asset_dir
    #     if src.is_dir():
    #         if dst.exists():
    #             shutil.rmtree(dst)
    #         shutil.copytree(src, dst)

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Build Bagpiper demo page")
    parser.add_argument(
        "-c", "--config",
        default=str(Path(__file__).parent / "config.yaml"),
        help="Path to config.yaml (default: %(default)s)",
    )
    parser.add_argument(
        "-o", "--output",
        default=str(Path(__file__).parent / "index.html"),
        help="Output HTML path (default: %(default)s)",
    )
    parser.add_argument(
        "-t", "--template-dir",
        default=None,
        help="Directory containing Jinja2 templates (default: demo/templates/)",
    )
    args = parser.parse_args()

    out = build(args.config, args.output, args.template_dir)
    print(f"✓ Built demo page → {out}")


if __name__ == "__main__":
    main()
