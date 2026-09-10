#!/usr/bin/env python3
"""
build_prompts.py - render one ready-to-send prompt per chunk.

Writes annotations/_prompts/<chunk_id>.txt next to a batch.jsonl you can feed to
whatever runner you use. Each prompt carries the chunk's real start time and the
events still open from the previous chunk, so a stall spanning many clips gets
stitched back into one event at merge time.

  python3 ingest/build_prompts.py
  python3 ingest/build_prompts.py --carry annotations   # re-render using replies so far
"""
import argparse, json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_open_events(ann_dir, chunk_id, stations):
    """Events flagged as still running at the end of the previous chunk."""
    prev = ann_dir / f"{chunk_id}.json"
    if not prev.exists():
        return "(nothing - this is the first chunk, or the previous chunk has not been annotated yet)"
    try:
        data = json.loads(prev.read_text())
    except json.JSONDecodeError:
        return "(previous chunk annotation is not valid JSON)"
    open_ev = [e for e in data.get("events", []) if e.get("continues_into_next")]
    if not open_ev:
        return "(nothing was still open)"
    return "\n".join(
        f"- {e.get('station','?')}: {e.get('type','?')} - {e.get('label','')}" for e in open_ev
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="chunks/manifest.json")
    ap.add_argument("--annotations", default="annotations")
    ap.add_argument("--out", default="annotations/_prompts")
    args = ap.parse_args()

    manifest = json.loads((ROOT / args.manifest).read_text())
    stations = json.loads((ROOT / "prompts/stations.json").read_text())["stations"]
    system = (ROOT / "prompts/system_prompt.md").read_text()
    schema = (ROOT / "prompts/schema.json").read_text()
    tmpl = (ROOT / "prompts/chunk_prompt.md").read_text()

    station_list = "\n".join(f"- {s['id']} = {s['name']}" for s in stations)
    ann_dir = ROOT / args.annotations
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    batch = []
    chunks = manifest["chunks"]
    for i, c in enumerate(chunks):
        start = datetime.fromisoformat(c["clock_start"])
        prev_id = chunks[i - 1]["id"] if i else None
        body = (tmpl.split("-->", 1)[-1].strip()
                .replace("{{chunk_id}}", c["id"])
                .replace("{{duration}}", str(int(c["duration"])))
                .replace("{{fps}}", str(manifest.get("fps", 2)))
                .replace("{{clock_start}}", start.strftime("%Y-%m-%d %H:%M:%S"))
                .replace("{{weekday}}", start.strftime("%A"))
                .replace("{{station_list}}", station_list)
                .replace("{{open_events}}",
                         load_open_events(ann_dir, prev_id, stations) if prev_id
                         else "(nothing - this is the first chunk)"))
        (out_dir / f"{c['id']}.txt").write_text(body)
        batch.append({
            "chunk_id": c["id"],
            "video": f"chunks/{c['file']}",
            "system": system,
            "schema": json.loads(schema),
            "prompt": body,
        })

    (out_dir / "batch.jsonl").write_text("\n".join(json.dumps(b) for b in batch))
    print(f"{len(batch)} prompt(s) -> {out_dir}")
    print(f"batch file          -> {out_dir/'batch.jsonl'}")
    print("\nSave each reply as annotations/<chunk_id>.json, then run ingest/merge.py")


if __name__ == "__main__":
    main()
