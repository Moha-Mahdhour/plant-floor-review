"""Fold per-chunk annotations into one timeline the dashboard can open.

Does what the model cannot do reliably on its own:
  * converts chunk-relative offsets into absolute seconds and wall-clock time
  * stitches continuation-flagged events across chunk boundaries
  * repairs or rejects malformed events instead of letting them skew charts
  * records coverage and a throughput series

merge() is pure: manifest and annotations in, timeline document out.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .project import Project
from .stations import FALLBACK_STATION, Station, load_stations
from .taxonomy import EVENT_TYPES, FALLBACK_TYPE, is_loss
from .timecode import at, iso

MIN_DURATION = 5.0         # seconds; shorter events are annotation noise
STITCH_TOLERANCE = 90.0    # seconds of real-time gap still treated as continuous

Annotation = Mapping[str, Any] | str   # parsed JSON, or raw text that failed to parse


def clean_event(ev: Mapping[str, Any], chunk: Mapping[str, Any], station_ids: set[str],
                problems: list[str]) -> dict[str, Any] | None:
    """Validate one raw event and lift it to absolute time. None means rejected."""
    try:
        t0, t1 = float(ev["t_start"]), float(ev["t_end"])
    except (KeyError, TypeError, ValueError):
        problems.append(f"{chunk['id']}: event with no usable t_start/t_end")
        return None
    limit = chunk["duration"] + 2
    t0, t1 = max(0.0, min(t0, limit)), max(0.0, min(t1, limit))
    if t1 < t0:
        t0, t1 = t1, t0
    if t1 - t0 < MIN_DURATION:
        t1 = t0 + MIN_DURATION

    station = ev.get("station", FALLBACK_STATION)
    if station not in station_ids:
        problems.append(f"{chunk['id']}: unknown station '{station}' -> {FALLBACK_STATION}")
        station = FALLBACK_STATION
    etype = ev.get("type", FALLBACK_TYPE)
    if etype not in EVENT_TYPES:
        problems.append(f"{chunk['id']}: unknown type '{etype}' -> {FALLBACK_TYPE}")
        etype = FALLBACK_TYPE
    try:
        sev = int(ev.get("severity", 2))
    except (TypeError, ValueError):
        sev = 2
    try:
        conf = float(ev.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5

    out = {
        "abs_start": round(chunk["abs_start"] + t0, 2),
        "abs_end": round(chunk["abs_start"] + t1, 2),
        "station": station, "type": etype,
        "severity": min(5, max(1, sev)), "confidence": min(1.0, max(0.0, conf)),
        "label": str(ev.get("label", ""))[:200],
        "cause": (ev.get("cause") or "unspecified")[:60],
        "chunks": [chunk["id"]],
        "_open": bool(ev.get("continues_into_next")),
        "_cont": bool(ev.get("continues_from_previous")),
    }
    for k in ("actors", "items"):
        if isinstance(ev.get(k), (int, float)):
            out[k] = int(ev[k])
    return out


def merge(manifest: Mapping[str, Any], annotations: Mapping[str, Annotation], stations: Sequence[Station], *,
          min_confidence: float = 0.0, site: str = "Plant", generated: str | None = None) -> tuple[dict, list[str]]:
    station_ids = {s.id for s in stations}
    start = datetime.fromisoformat(manifest["recording_start"])
    events, problems, coverage, throughput = [], [], [], []
    open_by_key: dict[tuple[str, str], dict] = {}
    annotated = 0

    for chunk in manifest["chunks"]:
        span = {"abs_start": chunk["abs_start"], "abs_end": chunk["abs_end"]}
        data = annotations.get(chunk["id"])
        if data is None:
            coverage.append({**span, "state": "not_annotated"})
            continue
        if isinstance(data, str):
            problems.append(f"{chunk['id']}: invalid JSON")
            coverage.append({**span, "state": "bad_json"})
            continue
        annotated += 1
        coverage.append({**span, "state": data.get("coverage", "clear")})
        counts = data.get("counts") or {}
        if counts:
            throughput.append({"abs_start": chunk["abs_start"],
                               **{k: int(counts.get(k, 0) or 0) for k in ("items_in", "items_out", "customers")}})

        seen_open = set()
        for raw in data.get("events", []):
            ev = clean_event(raw, chunk, station_ids, problems)
            if ev is None or ev["confidence"] < min_confidence:
                continue
            key = (ev["station"], ev["type"])
            prior = open_by_key.get(key)
            if ev["_cont"] and prior and ev["abs_start"] - prior["abs_end"] <= STITCH_TOLERANCE:
                prior["abs_end"] = max(prior["abs_end"], ev["abs_end"])
                prior["severity"] = max(prior["severity"], ev["severity"])
                prior["confidence"] = round((prior["confidence"] + ev["confidence"]) / 2, 3)
                prior["chunks"].append(chunk["id"])
                if "items" in ev:
                    prior["items"] = max(prior.get("items", 0), ev["items"])
                if ev["_open"]:
                    seen_open.add(key)
                else:
                    open_by_key.pop(key, None)
                continue
            events.append(ev)
            if ev["_open"]:
                open_by_key[key] = ev
                seen_open.add(key)
        for key in [k for k in open_by_key if k not in seen_open]:   # not re-reported: it ended
            open_by_key.pop(key, None)

    events.sort(key=lambda e: e["abs_start"])
    for i, ev in enumerate(events):
        ev["id"] = f"e{i:05d}"
        ev["duration"] = round(ev["abs_end"] - ev["abs_start"], 1)
        ev["clock_start"] = iso(at(start, ev["abs_start"]))
        ev["spans"] = len(ev["chunks"])
        ev.pop("_open", None)
        ev.pop("_cont", None)

    doc = {
        "meta": {
            "site": site, "recording_start": manifest["recording_start"],
            "total_seconds": manifest["total_seconds"], "kept_seconds": manifest.get("kept_seconds"),
            "chunks_total": len(manifest["chunks"]), "chunks_annotated": annotated,
            "generated": generated or iso(datetime.now()), "min_confidence": min_confidence,
        },
        "stations": [s.as_dict() for s in stations],
        "activity": manifest.get("activity", []),
        "coverage": coverage, "throughput": throughput, "events": events,
    }
    return doc, problems


def load_annotations(folder: Path, chunk_ids: Sequence[str]) -> dict[str, Annotation]:
    out: dict[str, Annotation] = {}
    for cid in chunk_ids:
        f = folder / f"{cid}.json"
        if f.exists():
            text = f.read_text()
            try:
                out[cid] = json.loads(text)
            except json.JSONDecodeError:
                out[cid] = text
    return out


def lost_hours(doc: Mapping[str, Any]) -> float:
    return sum(e["duration"] for e in doc["events"] if is_loss(e["type"])) / 3600


def build_parser(p: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    p = p or argparse.ArgumentParser(description="Merge chunk annotations into data/events.json.")
    p.add_argument("--root", default=".", help="project folder (default: current directory)")
    p.add_argument("--manifest", default="chunks/manifest.json")
    p.add_argument("--annotations", default="annotations")
    p.add_argument("--out", default="data/events.json")
    p.add_argument("--min-confidence", type=float, default=0.0, help="drop events the model was less sure of")
    p.add_argument("--site", default="Plant", help="site name shown in the dashboard")
    return p


def run(args: argparse.Namespace) -> int:
    project = Project.at(args.root)
    man_path = project.resolve(args.manifest)
    if not man_path.exists():
        print(f"error: no manifest at {man_path} - run the prep step first")
        return 1
    manifest = json.loads(man_path.read_text())
    anns = load_annotations(project.resolve(args.annotations), [c["id"] for c in manifest["chunks"]])
    doc, problems = merge(manifest, anns, load_stations(project.stations_file),
                          min_confidence=args.min_confidence, site=args.site)
    out = project.resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1))
    print(f"chunks annotated : {doc['meta']['chunks_annotated']}/{doc['meta']['chunks_total']}")
    print(f"events           : {len(doc['events'])}")
    print(f"time lost        : {lost_hours(doc):.1f} h across all stations")
    if problems:
        print(f"\n{len(problems)} problem(s) repaired:")
        for p in problems[:15]:
            print("  -", p)
        if len(problems) > 15:
            print(f"  ... and {len(problems) - 15} more")
    print(f"\nwrote {out} - open app/index.html and load it")
    return 0


def main(argv: list[str] | None = None, root: str | Path | None = None) -> int:
    args = build_parser().parse_args(argv)
    if root is not None and args.root == ".":
        args.root = str(root)
    return run(args)
