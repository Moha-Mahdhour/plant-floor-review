"""Render one ready-to-send prompt per chunk, plus a batch.jsonl for runners.

Each prompt carries the chunk's real start time and the events still open
at the end of the previous chunk, which is what lets merging stitch a
long stall spanning many clips back into one event.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .project import Project
from .stations import Station, load_stations

FIRST_CHUNK = "(nothing - this is the first chunk)"
NOT_ANNOTATED = "(nothing - the previous chunk has not been annotated yet)"
BAD_JSON = "(previous chunk annotation is not valid JSON)"
NOTHING_OPEN = "(nothing was still open)"


def template_body(template: str) -> str:
    """Drop the leading <!-- ... --> comment that documents the template."""
    return template.split("-->", 1)[-1].strip() if template.lstrip().startswith("<!--") else template.strip()


def station_list(stations: Sequence[Station]) -> str:
    return "\n".join(f"- {s.id} = {s.name}" for s in stations)


def open_events_text(previous: Mapping[str, Any] | str | None) -> str:
    """Summarize events the previous chunk flagged as continuing into this one.

    `previous` is the parsed annotation, the raw text if it failed to parse,
    or None if that chunk has no annotation yet.
    """
    if previous is None:
        return NOT_ANNOTATED
    if isinstance(previous, str):
        return BAD_JSON
    still_open = [e for e in previous.get("events", []) if e.get("continues_into_next")]
    if not still_open:
        return NOTHING_OPEN
    return "\n".join(f"- {e.get('station', '?')}: {e.get('type', '?')} - {e.get('label', '')}" for e in still_open)


def render_chunk_prompt(template: str, chunk: Mapping[str, Any], *, fps: float, stations: str, open_events: str) -> str:
    start = datetime.fromisoformat(chunk["clock_start"])
    values = {
        "chunk_id": chunk["id"], "duration": str(int(chunk["duration"])), "fps": f"{fps:g}",
        "clock_start": start.strftime("%Y-%m-%d %H:%M:%S"), "weekday": start.strftime("%A"),
        "station_list": stations, "open_events": open_events,
    }
    body = template_body(template)
    for key, value in values.items():
        body = body.replace("{{" + key + "}}", value)
    leftover = re.findall(r"\{\{(\w+)\}\}", body)
    if leftover:
        raise ValueError(f"template has unknown placeholders: {sorted(set(leftover))}")
    return body


def _read_annotation(path: Path) -> Mapping[str, Any] | str | None:
    if not path.exists():
        return None
    text = path.read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def build_prompts(project: Project, out_dir: Path | None = None) -> list[dict[str, Any]]:
    manifest = json.loads(project.manifest.read_text())
    stations = station_list(load_stations(project.stations_file))
    system = (project.prompts_dir / "system_prompt.md").read_text()
    schema = json.loads((project.prompts_dir / "schema.json").read_text())
    template = (project.prompts_dir / "chunk_prompt.md").read_text()
    out_dir = out_dir or project.annotations_dir / "_prompts"
    out_dir.mkdir(parents=True, exist_ok=True)

    batch, chunks = [], manifest["chunks"]
    for i, c in enumerate(chunks):
        open_events = FIRST_CHUNK if i == 0 else open_events_text(
            _read_annotation(project.annotations_dir / f"{chunks[i - 1]['id']}.json"))
        body = render_chunk_prompt(template, c, fps=manifest.get("fps", 2), stations=stations, open_events=open_events)
        (out_dir / f"{c['id']}.txt").write_text(body)
        video = os.path.relpath(project.manifest.parent / c["file"], project.root)
        batch.append({"chunk_id": c["id"], "video": video, "system": system, "schema": schema, "prompt": body})
    (out_dir / "batch.jsonl").write_text("\n".join(json.dumps(b) for b in batch))
    return batch


def build_parser(p: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    p = p or argparse.ArgumentParser(description="Render one prompt per chunk.")
    p.add_argument("--root", default=".", help="project folder (default: current directory)")
    p.add_argument("--out", default=None, help="prompt folder (default: annotations/_prompts)")
    return p


def run(args: argparse.Namespace) -> int:
    project = Project.at(args.root)
    out = project.resolve(args.out) if args.out else None
    batch = build_prompts(project, out)
    target = out or project.annotations_dir / "_prompts"
    print(f"{len(batch)} prompt(s) -> {target}\nbatch file          -> {target / 'batch.jsonl'}")
    print("\nSave each reply as annotations/<chunk_id>.json, then run the merge step.")
    return 0


def main(argv: list[str] | None = None, root: str | Path | None = None) -> int:
    args = build_parser().parse_args(argv)
    if root is not None and args.root == ".":
        args.root = str(root)
    return run(args)
