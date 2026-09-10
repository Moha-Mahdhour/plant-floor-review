"""Markdown bottleneck report: the dashboard's findings as a shareable document."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from .metrics import Summary, impact, summarize
from .project import Project
from .taxonomy import is_loss


def fmt_minutes(m: float) -> str:
    """Same formatting as the dashboard: '45 min', '4.9 h', '28 h'."""
    if m >= 60:
        h = m / 60
        return f"{h:.1f} h" if h < 10 else f"{h:.0f} h"
    return f"{round(m)} min"


def _when(dt: datetime) -> str:
    return dt.strftime("%a %d %b %H:%M")


def _cause(name: str) -> str:
    return name.replace("_", " ")


def render_markdown(doc: Mapping[str, Any], s: Summary, *, top_events: int = 10) -> str:
    names = {st["id"]: st["name"] for st in doc.get("stations", [])}
    name = lambda sid: names.get(sid, sid)
    end = s.recording_start + timedelta(hours=s.recorded_hours)
    out = [f"# Bottleneck report: {s.site or 'plant'}", "",
           f"Recording {_when(s.recording_start)} to {_when(end)} ({s.recorded_hours:.0f} h), "
           f"{s.chunks_annotated} of {s.chunks_total} clips annotated.", ""]

    out += ["## Headline", "", "| | |", "|---|---|"]
    out.append(f"| Time lost | {fmt_minutes(s.lost_minutes)} ({100 * s.loss_share:.0f}% of observed station time) |")
    out.append(f"| Likely constraint | " + (f"{name(s.constraint.key)}: {fmt_minutes(s.constraint.minutes)} of queue build-up"
                                          if s.constraint else "no queue build-up recorded") + " |")
    out.append(f"| Costliest station | " + (f"{name(s.costliest.key)}: {fmt_minutes(s.costliest.minutes)} lost"
                                          if s.costliest else "none") + " |")
    out.append(f"| Biggest single cause | " + (f"{_cause(s.top_cause.key)}: {fmt_minutes(s.top_cause.minutes)} lost"
                                             if s.top_cause else "none") + " |")
    out.append(f"| Worst hour | " + (f"{_when(s.worst_hour[0])}: {fmt_minutes(s.worst_hour[1])} lost"
                                   if s.worst_hour else "none") + " |")
    out.append("")
    if s.constraint and s.costliest and s.constraint.key != s.costliest.key:
        out += [f"The costliest station is not the constraint. {name(s.costliest.key)} is likely losing time "
                f"*because of* {name(s.constraint.key)}; check its blocked and starved minutes below.", ""]

    out += ["## Where the time goes", "",
            "*Blocked* means the next step was full, so the fix is downstream. "
            "*Starved* means nothing arrived, so the fix is upstream.", "",
            "| Station | Lost | Blocked | Starved | Queue | Impact |", "|---|---:|---:|---:|---:|---:|"]
    for r in s.stations:
        if r.lost:
            out.append(f"| {r.name} | {fmt_minutes(r.lost)} | {fmt_minutes(r.blocked)} | {fmt_minutes(r.starved)} | "
                       f"{fmt_minutes(r.queue)} | {round(r.impact):,} |")
    out += ["", "Impact = minutes x severity.", ""]

    total = sum(c.minutes for c in s.causes)
    if s.causes:
        out += ["## Causes", "", f"{s.vital_few} cause{'s' if s.vital_few != 1 else ''} account for 80% of the "
                f"{fmt_minutes(total)} lost.", "", "| Cause | Lost | Share | Cumulative |", "|---|---:|---:|---:|"]
        running = 0.0
        for c in s.causes:
            running += c.minutes
            out.append(f"| {_cause(c.key)} | {fmt_minutes(c.minutes)} | {100 * c.minutes / total:.0f}% | "
                       f"{100 * running / total:.0f}% |")
        out.append("")

    losses = sorted((e for e in doc["events"] if is_loss(e["type"])), key=impact, reverse=True)[:top_events]
    if losses:
        out += [f"## Highest-impact events", "", "| When | Station | Type | Duration | Severity | What happened |",
                "|---|---|---|---:|---:|---|"]
        for e in losses:
            when = _when(s.recording_start + timedelta(seconds=e["abs_start"]))
            out.append(f"| {when} | {name(e['station'])} | {e['type'].replace('_', ' ')} | "
                       f"{fmt_minutes(e['duration'] / 60)} | {e['severity']} | {e['label']} |")
        out.append("")
    return "\n".join(out)


def build_parser(p: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    p = p or argparse.ArgumentParser(description="Write a Markdown bottleneck report.")
    p.add_argument("--root", default=".", help="project folder (default: current directory)")
    p.add_argument("--events", default="data/events.json", help="merged timeline, or 'demo' for the bundled demo")
    p.add_argument("--out", default=None, help="write to this file instead of stdout")
    p.add_argument("--min-confidence", type=float, default=0.0)
    p.add_argument("--top", type=int, default=10, help="number of highest-impact events to list")
    return p


def run(args: argparse.Namespace) -> int:
    project = Project.at(args.root)
    path = project.data_dir / "events.demo.json" if args.events == "demo" else project.resolve(args.events)
    if not path.exists():
        print(f"error: {path} not found - run the merge step (or use --events demo)", file=sys.stderr)
        return 1
    doc = json.loads(path.read_text())
    text = render_markdown(doc, summarize(doc, min_confidence=args.min_confidence), top_events=args.top)
    if args.out:
        out = project.resolve(args.out)
        out.write_text(text)
        print(f"wrote {out}")
    else:
        print(text)
    return 0


def main(argv: list[str] | None = None, root: str | Path | None = None) -> int:
    args = build_parser().parse_args(argv)
    if root is not None and args.root == ".":
        args.root = str(root)
    return run(args)
