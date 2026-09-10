#!/usr/bin/env python3
"""
merge.py - fold per-chunk annotations into one timeline the app can open.

Does four things the model cannot do reliably on its own:
  * converts chunk-relative offsets into absolute seconds and wall-clock time
  * stitches continuation-flagged events across chunk boundaries
  * rejects malformed events instead of letting them poison the charts
  * carries a throughput series and a coverage record

  python3 ingest/merge.py
  python3 ingest/merge.py --min-confidence 0.4 --out data/events.json
"""
import argparse, json, sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TYPES = {"work", "idle", "unmanned", "queue_buildup", "blockage", "starvation",
         "machine_stop", "changeover", "rework", "search", "transport",
         "customer_wait", "break", "safety", "unknown"}

MIN_DURATION = 5.0        # seconds; anything shorter is annotation noise
STITCH_TOLERANCE = 90.0   # seconds of real-time gap still treated as continuous


def clean(ev, chunk, station_ids, problems):
    """Validate one raw event and lift it to absolute time. None = rejected."""
    try:
        t0 = float(ev["t_start"]); t1 = float(ev["t_end"])
    except (KeyError, TypeError, ValueError):
        problems.append(f"{chunk['id']}: event with no usable t_start/t_end"); return None

    dur_limit = chunk["duration"] + 2
    t0 = max(0.0, min(t0, dur_limit))
    t1 = max(0.0, min(t1, dur_limit))
    if t1 < t0:
        t0, t1 = t1, t0
    if t1 - t0 < MIN_DURATION:
        t1 = t0 + MIN_DURATION

    station = ev.get("station", "floor")
    if station not in station_ids:
        problems.append(f"{chunk['id']}: unknown station '{station}' -> floor")
        station = "floor"

    etype = ev.get("type", "unknown")
    if etype not in TYPES:
        problems.append(f"{chunk['id']}: unknown type '{etype}' -> unknown")
        etype = "unknown"

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
        "station": station,
        "type": etype,
        "severity": min(5, max(1, sev)),
        "confidence": min(1.0, max(0.0, conf)),
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="chunks/manifest.json")
    ap.add_argument("--annotations", default="annotations")
    ap.add_argument("--out", default="data/events.json")
    ap.add_argument("--min-confidence", type=float, default=0.0)
    ap.add_argument("--site", default="Dry cleaning plant")
    args = ap.parse_args()

    man_path = ROOT / args.manifest
    if not man_path.exists():
        sys.exit(f"no manifest at {man_path} - run prep/prepare.py first")
    manifest = json.loads(man_path.read_text())
    stations = json.loads((ROOT / "prompts/stations.json").read_text())["stations"]
    station_ids = {s["id"] for s in stations}
    start_dt = datetime.fromisoformat(manifest["recording_start"])
    ann_dir = ROOT / args.annotations

    events, problems, coverage, throughput = [], [], [], []
    open_by_key, annotated = {}, 0

    for chunk in manifest["chunks"]:
        f = ann_dir / f"{chunk['id']}.json"
        if not f.exists():
            coverage.append({"abs_start": chunk["abs_start"], "abs_end": chunk["abs_end"],
                             "state": "not_annotated"})
            continue
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError as e:
            problems.append(f"{chunk['id']}: invalid JSON ({e.msg})")
            coverage.append({"abs_start": chunk["abs_start"], "abs_end": chunk["abs_end"],
                             "state": "bad_json"})
            continue
        annotated += 1
        coverage.append({"abs_start": chunk["abs_start"], "abs_end": chunk["abs_end"],
                         "state": data.get("coverage", "clear")})

        counts = data.get("counts") or {}
        if counts:
            throughput.append({
                "abs_start": chunk["abs_start"],
                "items_in": int(counts.get("items_in", 0) or 0),
                "items_out": int(counts.get("items_out", 0) or 0),
                "customers": int(counts.get("customers", 0) or 0),
            })

        seen_open = set()
        for raw in data.get("events", []):
            ev = clean(raw, chunk, station_ids, problems)
            if ev is None or ev["confidence"] < args.min_confidence:
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
        # anything not re-reported has ended
        for key in [k for k in open_by_key if k not in seen_open]:
            open_by_key.pop(key, None)

    for i, ev in enumerate(sorted(events, key=lambda e: e["abs_start"])):
        ev["id"] = f"e{i:05d}"
        ev["duration"] = round(ev["abs_end"] - ev["abs_start"], 1)
        ev["clock_start"] = (start_dt + timedelta(seconds=ev["abs_start"])).isoformat(timespec="seconds")
        ev["spans"] = len(ev["chunks"])
        ev.pop("_open", None); ev.pop("_cont", None)

    events.sort(key=lambda e: e["abs_start"])
    out = {
        "meta": {
            "site": args.site,
            "recording_start": manifest["recording_start"],
            "total_seconds": manifest["total_seconds"],
            "kept_seconds": manifest.get("kept_seconds"),
            "chunks_total": len(manifest["chunks"]),
            "chunks_annotated": annotated,
            "generated": datetime.now().isoformat(timespec="seconds"),
            "min_confidence": args.min_confidence,
        },
        "stations": stations,
        "activity": manifest.get("activity", []),
        "coverage": coverage,
        "throughput": throughput,
        "events": events,
    }
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1))

    lost = sum(e["duration"] for e in events if e["type"] not in ("work", "break"))
    print(f"chunks annotated : {annotated}/{len(manifest['chunks'])}")
    print(f"events           : {len(events)}")
    print(f"non-productive   : {lost/3600:.1f} h across all stations")
    if problems:
        print(f"\n{len(problems)} problem(s) repaired:")
        for p in problems[:15]:
            print("  -", p)
        if len(problems) > 15:
            print(f"  ... and {len(problems)-15} more")
    print(f"\nwrote {out_path} - open app/index.html and load it")


if __name__ == "__main__":
    main()
