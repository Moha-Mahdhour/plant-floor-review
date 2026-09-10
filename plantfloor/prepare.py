"""Reduce raw footage to the clips that can answer "where do we lose time?"

  1. SCAN  motion profile of the whole recording (ffmpeg does the math)
  2. PLAN  drop dead air, cut active footage into fixed chunks
  3. CUT   export each chunk downscaled and low-fps

Writes <out>/manifest.json, which every later step reads.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .timecode import at, parse_start
from .video.ffmpeg import (FFmpegError, collect_inputs, cut_chunk, motion_profile, pick_font,
                           probe_duration, require_ffmpeg)
from .video.plan import finalize_chunks, lay_out, plan_chunks, windows_from_samples


@dataclass(frozen=True)
class PrepOptions:
    chunk_len: float = 300
    fps: float = 2
    width: int = 854
    crf: int = 28
    sample_period: float = 2.0
    threshold: float = 1.2
    pad: float = 60
    min_gap: float = 120
    dry_run: bool = False
    limit: int = 0


def prepare(input_path: str | Path, start_text: str, out_dir: str | Path, opts: PrepOptions = PrepOptions(),
            log: Callable[[str], None] = print) -> dict:
    require_ffmpeg()
    start = parse_start(start_text)
    out_dir = Path(out_dir)

    files = collect_inputs(input_path)
    log(f"reading {len(files)} file(s)...")
    sources = lay_out((f.name, f, probe_duration(f)) for f in files)
    total = sources[-1].abs_end
    log(f"total footage: {total / 3600:.2f} h  ({start} -> {at(start, total)})")

    log("\npass 1/3  motion scan")
    t0, samples = time.time(), []
    for s in sources:
        profile = motion_profile(s.path, opts.sample_period)
        samples += [(t + s.abs_start, v) for t, v in profile]
        log(f"  {s.name}: {len(profile)} samples")
    if not samples:
        raise FFmpegError("motion scan produced no samples - is the input readable?")
    samples.sort()
    log(f"  {len(samples)} samples in {time.time() - t0:.0f}s")

    log("\npass 2/3  plan")
    windows = windows_from_samples(samples, opts.threshold, opts.pad, opts.min_gap)
    chunks = finalize_chunks(plan_chunks(windows, opts.chunk_len, sources), start)
    kept = sum(c["duration"] for c in chunks)
    log(f"  {len(windows)} active window(s), {kept / 3600:.2f} h kept "
        f"({100 * kept / total:.0f}% of footage, {(total - kept) / 3600:.2f} h of dead air dropped)")
    log(f"  {len(chunks)} chunk(s) -> ~{kept * opts.fps:,.0f} frames at {opts.fps} fps")

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "recording_start": start.isoformat(timespec="seconds"),
        "total_seconds": round(total, 2),
        "kept_seconds": round(kept, 2),
        "chunk_len": opts.chunk_len, "fps": opts.fps, "width": opts.width,
        "sources": [{"name": s.name, "duration": round(s.duration, 2), "abs_start": round(s.abs_start, 2)}
                    for s in sources],
        "activity": [{"t": round(t, 1), "motion": round(v, 3)} for t, v in samples],
        "windows": [{"abs_start": round(a, 2), "abs_end": round(b, 2)} for a, b in windows],
        "chunks": chunks,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    log(f"  wrote {out_dir / 'manifest.json'}")
    if opts.dry_run:
        log("\ndry run - no clips exported")
        return manifest

    todo = chunks[: opts.limit] if opts.limit else chunks
    log(f"\npass 3/3  cut {len(todo)} chunk(s) -> {out_dir}")
    font = pick_font()
    if not font:
        log("  note: this ffmpeg has no drawtext filter - no burned-in clock.\n"
            "        Timing still comes from manifest.json and the chunk filenames.")
    by_name, epoch0, failed = {s.name: s for s in sources}, start.timestamp(), 0
    for i, c in enumerate(todo, 1):
        ok, err = cut_chunk(c, by_name[c["source"]], out_dir / c["file"], fps=opts.fps, width=opts.width,
                            crf=opts.crf, font=font, clock_epoch=int(epoch0 + c["abs_start"]))
        if not ok:
            failed += 1
            log(f"  [{i}/{len(todo)}] {c['id']} FAILED: {err.splitlines()[-1] if err else '?'}")
        elif i % 10 == 0 or i == len(todo):
            log(f"  [{i}/{len(todo)}] {c['id']} {c['clock_start']}")
    log(f"\ndone. {len(todo) - failed} clip(s) in {out_dir}/, {failed} failed.")
    return manifest


def build_parser(p: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    p = p or argparse.ArgumentParser(description="Prep plant footage for video-model annotation.")
    p.add_argument("--input", required=True, help="video file or directory of files (sorted by name)")
    p.add_argument("--start", required=True, help='wall clock of first frame, "YYYY-MM-DD HH:MM[:SS]"')
    p.add_argument("--out", default="chunks", help="output directory")
    p.add_argument("--chunk-len", type=float, default=300, help="chunk length in seconds (default 300)")
    p.add_argument("--fps", type=float, default=2, help="output fps (default 2)")
    p.add_argument("--width", type=int, default=854, help="output width (default 854)")
    p.add_argument("--crf", type=int, default=28)
    p.add_argument("--sample-period", type=float, default=2.0, help="motion sample every N sec")
    p.add_argument("--threshold", type=float, default=1.2, help="motion threshold (0-255 mean diff)")
    p.add_argument("--pad", type=float, default=60, help="seconds of padding around active windows")
    p.add_argument("--min-gap", type=float, default=120, help="quiet seconds that split two windows")
    p.add_argument("--dry-run", action="store_true", help="scan and plan, do not export")
    p.add_argument("--limit", type=int, default=0, help="export only the first N chunks (smoke test)")
    return p


def run(args: argparse.Namespace) -> int:
    opts = PrepOptions(args.chunk_len, args.fps, args.width, args.crf, args.sample_period, args.threshold,
                       args.pad, args.min_gap, args.dry_run, args.limit)
    try:
        prepare(args.input, args.start, args.out, opts)
    except (FFmpegError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))
