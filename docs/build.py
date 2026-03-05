#!/usr/bin/env python3
"""
build.py - Render the Bagpiper demo page from config.yaml + Jinja2 template.

New config format:
  models:
    - id: bagpiper_st_356k
      name: "Bagpiper-Edit (ST)"
      color: "#DD8452"
      expdir: /path/to/exp/{task}   # {task} replaced with subsection id

  sections:
    - id: speech
      subsections:
        - id: transcription_del
          metadata: docs/metadata/transcription_del.jsonl
          samples:
            - id: "1089-134686-0033"
              models: [bagpiper_base, bagpiper_st_356k, cosyvoice3]

Metadata JSONL fields: id, text, edit_prompt, audio_caption,
                       target_audio_caption, audio_path

Multiple model IDs sharing the same name are merged into one column.
Source column is always prepended first.
Old list-of-entries sample format is supported for backward compat.
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
from collections import OrderedDict
from pathlib import Path
import uuid

import soundfile as sf
import yaml
from jinja2 import Environment, FileSystemLoader


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def copy_audio(src: Path, dst: Path, max_duration: float | None = None) -> None:
    if max_duration is not None:
        info = sf.info(str(src))
        if info.duration > max_duration:
            data, sr = sf.read(str(src), dtype="float32",
                               frames=int(max_duration * info.samplerate))
            sf.write(str(dst), data, sr)
            return
    os.system(f"cp {src} {dst}; chmod +w {dst}")


def find_audio_in_dir(directory: str, sample_id: str) -> "Path | None":
    """Glob directory for any audio file whose stem starts with sample_id."""
    d = Path(directory)
    if not d.is_dir():
        return None
    for ext in ("wav", "flac", "mp3", "ogg"):
        for pat in (f"{sample_id}.{ext}", f"{sample_id}_*.{ext}"):
            matches = sorted(d.glob(pat))
            if matches:
                return matches[0]
    return None


# ---------------------------------------------------------------------------
# Metadata / config
# ---------------------------------------------------------------------------

def load_metadata_jsonl(path) -> "dict[str, dict]":
    result = {}
    p = Path(path)
    if not p.exists():
        return result
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in rec:
                result[str(rec["id"])] = rec
    return result


def load_config(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Sample format helpers (old list-of-entries OR new dict format)
# ---------------------------------------------------------------------------

def _sample_id(sample) -> str:
    if isinstance(sample, dict):
        return str(sample.get("id", "unknown"))
    if isinstance(sample, list):
        for e in sample:
            if isinstance(e, dict) and e.get("type") == "id":
                return str(e.get("value", "unknown"))
    return "unknown"


def _sample_models(sample) -> "list[str]":
    """Return requested non-source model IDs."""
    if isinstance(sample, dict):
        raw = sample.get("models", [])
        if raw and isinstance(raw[0], dict):
            return [r["model"] for r in raw
                    if r.get("model") and r["model"] != "source"]
        return [m for m in raw if m != "source"]
    if isinstance(sample, list):
        return [e["model"] for e in sample
                if isinstance(e, dict) and e.get("type") == "audio"
                and e.get("model") and e["model"] != "source"]
    return []


def _get_field(sample, field: str) -> str:
    if isinstance(sample, dict):
        return str(sample.get(field, "") or "")
    aliases = {
        "instruction": "instruction", "edit_prompt": "instruction",
        "text": "text",
        "audio_caption": "source_caption", "source_caption": "source_caption",
        "target_audio_caption": "target_caption", "target_caption": "target_caption",
    }
    type_name = aliases.get(field, field)
    if isinstance(sample, list):
        for e in sample:
            if isinstance(e, dict) and e.get("type") == type_name:
                return str(e.get("value", "") or "")
    return ""


def _get_explicit_src(sample, model_id: str) -> "str | None":
    if isinstance(sample, dict):
        for m in sample.get("models", []):
            if isinstance(m, dict) and m.get("model") == model_id:
                return m.get("src")
        return None
    if isinstance(sample, list):
        for e in sample:
            if isinstance(e, dict) and e.get("type") == "audio" and e.get("model") == model_id:
                return e.get("src")
    return None


# ---------------------------------------------------------------------------
# Audio resolution + copy
# ---------------------------------------------------------------------------

def resolve_audio(model, sample_id, meta_rec, sub_id,
                  output_dir, sec_id, max_duration, copied, skipped,
                  sample=None, task_key=None, task_dir=None, task_name=None) -> "str | None":
    model_id = model["id"]

    explicit = _get_explicit_src(sample, model_id) if sample is not None else None
    if explicit:
        raw = explicit
    elif model_id == "source":
        raw = meta_rec.get("audio_path") or meta_rec.get("src") or ""
    else:
        expdir_tpl = model.get("expdir", "")
        if not expdir_tpl:
            skipped[0] += 1
            return None
        expdir = (expdir_tpl
                  .replace("{task_key}", task_key if task_key is not None else sub_id)
                  .replace("{task_dir}", task_dir if task_dir is not None else f"speech_edit/{sub_id}")
                  .replace("{task_name}", task_name if task_name is not None else sub_id)
                  .replace("{task}", sub_id))
        found = find_audio_in_dir(expdir, sample_id)
        raw = str(found) if found else None

    if not raw:
        skipped[0] += 1
        return None

    src = Path(raw)

    if not src.is_absolute():
        if str(src).startswith("audios/"):
            return str(src)
        abs_candidate = output_dir / src
        if abs_candidate.exists():
            return str(src)
        skipped[0] += 1
        return None

    if not src.exists():
        print(f"  WARNING not found: {src}")
        skipped[0] += 1
        return None

    basename = uuid.uuid5(uuid.NAMESPACE_OID, f"{sample_id}-{model_id}").hex
    rel_dst = Path("audios") / sec_id / sub_id / f"{basename}.wav"
    rel_dst.parent.mkdir(parents=True, exist_ok=True)
    copy_audio(src, rel_dst, max_duration)
    copied[0] += 1
    return str(rel_dst)


# ---------------------------------------------------------------------------
# HTML utilities
# ---------------------------------------------------------------------------

H = _html.escape


def _td(inner: str, cls: str = "") -> str:
    a = f' class="{cls}"' if cls else ""
    return f"<td{a}>{inner}</td>"


def _th(inner: str, cls: str = "") -> str:
    a = f' class="{cls}"' if cls else ""
    return f"<th{a}>{inner}</th>"


def _player(rel: "str | None") -> str:
    if not rel:
        return '<span class="no-audio">-</span>'
    return (f'<audio controls preload="none">'
            f'<source src="{H(rel)}" type="audio/wav" /></audio>')


# ---------------------------------------------------------------------------
# Build subsection table HTML
# ---------------------------------------------------------------------------

def build_subsection_html(subsection, sec_id, all_models,
                           output_dir, config_dir, max_duration,
                           copied, skipped) -> str:
    sub_id = subsection.get("id", "misc")
    task_key = subsection.get("expdir_key", sub_id)
    task_name = subsection.get("task_name", sub_id)
    task_base = subsection.get("task_base", "speech_edit")
    task_dir = f"{task_base}/{task_name}"
    samples_cfg = subsection.get("samples") or []
    if not samples_cfg:
        return ""

    # Load metadata
    metadata = {}
    meta_path = subsection.get("metadata")
    if meta_path:
        mp = Path(meta_path)
        if not mp.is_absolute():
            mp = output_dir / mp  # relative to repo root (demo/)
        metadata = load_metadata_jsonl(mp)

    model_by_id = {m["id"]: m for m in all_models}
    source_model = model_by_id.get(
        "source", {"id": "source", "name": "Source", "color": "#6c757d"})

    # Collect non-source model IDs used across subsection, in order of first appearance
    seen_mid: set = set()
    used_mids = []
    for s in samples_cfg:
        for mid in _sample_models(s):
            if mid not in seen_mid and mid in model_by_id:
                seen_mid.add(mid)
                used_mids.append(mid)

    # Deduplicate by name -> ordered column list
    col_name_to_mids: OrderedDict = OrderedDict()
    for mid in used_mids:
        name = model_by_id[mid]["name"]
        col_name_to_mids.setdefault(name, [])
        if mid not in col_name_to_mids[name]:
            col_name_to_mids[name].append(mid)

    def _any_field(field, meta_keys):
        for s in samples_cfg:
            if _get_field(s, field):
                return True
            m = metadata.get(_sample_id(s), {})
            if any(m.get(k) for k in meta_keys):
                return True
        return False

    has_instruction = _any_field("instruction", ["edit_prompt", "instruction"])
    has_text = _any_field("text", ["text"])
    has_src_cap = _any_field("audio_caption", ["audio_caption", "source_caption"])
    has_tgt_cap = _any_field("target_audio_caption", ["target_audio_caption", "target_caption"])

    # Header
    lines = ['<div class="table-responsive">', '<table class="sample-table">',
             "<thead><tr>"]
    if has_text:
        lines.append(_th("Original Text", "sticky-col"))
    if has_instruction:
        lines.append(_th("Edit Prompt", "sticky-col"))
    badge = f'<span class="model-badge" style="background:{source_model["color"]};"></span>'
    if has_src_cap:
        lines.append(_th("Original Caption"))
    if has_tgt_cap:
        lines.append(_th("Edited Caption"))
    lines.append(_th(f'{badge}{source_model["name"]}'))
    for col_name, mids in col_name_to_mids.items():
        rep = model_by_id[mids[0]]
        badge = f'<span class="model-badge" style="background:{rep["color"]}"></span>'
        lines.append(_th(f'{badge}{col_name}'))
    lines.append("</tr></thead><tbody>")

    # Data rows
    for row_idx, sample in enumerate(samples_cfg, 1):
        sid = _sample_id(sample)
        meta = metadata.get(sid, {})

        instruction = (_get_field(sample, "instruction") or _get_field(sample, "edit_prompt")
                       or meta.get("edit_prompt") or meta.get("instruction") or "")
        text = _get_field(sample, "text") or meta.get("text") or ""
        src_cap = (_get_field(sample, "audio_caption") or _get_field(sample, "source_caption")
                   or meta.get("audio_caption") or meta.get("source_caption") or "")
        tgt_cap = (_get_field(sample, "target_audio_caption") or _get_field(sample, "target_caption")
                   or meta.get("target_audio_caption") or meta.get("target_caption") or "")

        requested_mids = set(_sample_models(sample))

        lines.append("<tr>")
        if has_text:
            lines.append(_td(H(text), "text-col sticky-col"))
        if has_instruction:
            lines.append(_td(
                f'<div class="caption-box">{H(instruction)}</div>' if instruction else "",
                "caption-col sticky-col"))

        if has_src_cap:
            lines.append(_td(
                f'<div class="caption-box">{H(src_cap)}</div>' if src_cap else "",
                "caption-col"))
        if has_tgt_cap:
            lines.append(_td(
                f'<div class="caption-box">{H(tgt_cap)}</div>' if tgt_cap else "",
                "caption-col"))

        src_url = resolve_audio(source_model, sid, meta, sub_id,
                                output_dir, sec_id, max_duration, copied, skipped, sample,
                                task_key=task_key, task_dir=task_dir, task_name=task_name)
        lines.append(_td(_player(src_url)))

        for col_name, mids in col_name_to_mids.items():
            chosen = next((m for m in mids if m in requested_mids), None)
            if chosen is None:
                lines.append(_td('<span class="no-audio">-</span>'))
                continue
            url = resolve_audio(model_by_id[chosen], sid, meta, sub_id,
                                output_dir, sec_id, max_duration, copied, skipped, sample,
                                task_key=task_key, task_dir=task_dir, task_name=task_name)
            lines.append(_td(_player(url)))

        lines.append("</tr>")

    lines.append("</tbody></table></div>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Build entry point
# ---------------------------------------------------------------------------

def build(config_path: str, output_path: str, template_dir=None) -> str:
    cfg = load_config(config_path)
    config_dir = Path(config_path).resolve().parent
    output_dir = Path(output_path).resolve().parent
    max_duration = cfg.get("max_duration")
    all_models = cfg.get("models", [])

    copied, skipped = [0], [0]

    # Build deduplicated model-description list (collapse same-name models)
    seen_names: set = set()
    model_descriptions = []
    for m in all_models:
        name = m.get("name", "")
        if name not in seen_names:
            seen_names.add(name)
            model_descriptions.append({
                "name": name,
                "color": m.get("color", "#666"),
                "description": m.get("description", ""),
            })
    cfg["model_descriptions"] = model_descriptions

    for section in cfg.get("sections", []):
        sec_id = section.get("id", "misc")
        for sub in section.get("subsections", []):
            sub["_table_html"] = build_subsection_html(
                sub, sec_id, all_models, output_dir, config_dir,
                max_duration, copied, skipped)

    print(f"  Copied {copied[0]} audio file(s), skipped {skipped[0]}")

    if template_dir is None:
        template_dir = str(Path(__file__).parent / "templates")

    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    html_out = env.get_template("index.html").render(**cfg)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_out)
    return output_path


def main():
    p = argparse.ArgumentParser(description="Build Bagpiper demo page")
    p.add_argument("-c", "--config",
                   default="../../conf/demo.yaml")
    p.add_argument("-o", "--output",
                   default="./index.html")
    p.add_argument("-t", "--template-dir", default=None)
    args = p.parse_args()
    print(f"Built -> {build(args.config, args.output, args.template_dir)}")


if __name__ == "__main__":
    main()
