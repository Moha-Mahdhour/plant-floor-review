#!/usr/bin/env python3
"""
prepare.py - turn 36h of raw plant footage into the smallest set of clips that
still answers "where do we lose time?", ready to hand to a video model.

Three passes:
  1. SCAN   cheap motion profile of the whole recording (ffmpeg does the math)
  2. PLAN   drop dead air, keep active windows, cut them into fixed chunks
  3. CUT    export each chunk downscaled, low-fps, with wall-clock burned in

The burned-in clock is the important part: it lets the model report absolute
timestamps that survive chunking, so annotations line up with the real day.

Usage
  python3 prep/prepare.py --input raw/ --start "2026-09-01 06:00:00"
  python3 prep/prepare.py --input day1.mp4 --start "2026-09-01 06:00" --dry-run
"""

import argparse, json, os, re, shutil, subprocess, sys, time
from datetime import datetime, timedelta
from pathlib import Path

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".mpg", ".mpeg", ".ts", ".dav"}

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def probe_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)])
    try:
        return float(r.stdout.strip())
    except ValueError:
        die(f"could not read duration of {path}")


def collect_inputs(target):
    p = Path(target)
    if p.is_file():
        return [p]
    if p.is_dir():
        files = sorted(q for q in p.iterdir() if q.suffix.lower() in VIDEO_EXT)
        if not files:
            die(f"no video files in {p}")
        return files
    die(f"input not found: {target}")


def has_drawtext():
    r = run(["ffmpeg", "-hide_banner", "-filters"])
    return bool(re.search(r"^\s*\S+\s+drawtext\s", r.stdout or "", re.M))


def pick_font():
    """Return a usable font path, or None if this ffmpeg cannot draw text.

    Burned-in clocks are a convenience for humans scrubbing the clips. The
    authoritative timing comes from the manifest and the chunk filename, so a
    build without libfreetype degrades cleanly instead of failing.
    """
    if not has_drawtext():
        return None
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return f
    return None


# ---------------------------------------------------------------- pass 1: scan

def motion_profile(path, sample_period):
    """Mean inter-frame difference, one number per `sample_period` seconds.

    ffmpeg does the decoding, downscaling, differencing and averaging in C, so a
    36h file profiles in minutes rather than hours.
    """
    vf = (f"fps=1/{sample_period},scale=64:36,format=gray,"
          f"tblend=all_mode=difference,signalstats,"
          f"metadata=print:key=lavfi.signalstats.YAVG:file=-")
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path),
           "-vf", vf, "-an", "-f", "null", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    samples, pending_t = [], None
    for line in proc.stdout:
        m = re.match(r"frame:\d+\s+pts:\d+\s+pts_time:([\d.]+)", line)
        if m:
            pending_t = float(m.group(1))
            continue
        m = re.search(r"YAVG=([\d.]+)", line)
        if m and pending_t is not None:
            samples.append((pending_t, float(m.group(1))))
            pending_t = None
    proc.wait()
    return samples


def windows_from_samples(samples, threshold, pad, min_gap, offset):
    """Collapse per-sample motion into padded active windows (absolute seconds)."""
    hot = [t for t, v in samples if v >= threshold]
    if not hot:
        return []
    wins = []
    start = prev = hot[0]
    for t in hot[1:]:
        if t - prev > min_gap:
            wins.append((start, prev))
            start = t
        prev = t
    wins.append((start, prev))
    out, step = [], (samples[1][0] - samples[0][0]) if len(samples) > 1 else pad
    for a, b in wins:
        out.append((max(0.0, a - pad) + offset, b + step + pad + offset))
    merged = [list(out[0])]
    for a, b in out[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


# ---------------------------------------------------------------- pass 2: plan

def plan_chunks(windows, chunk_len, sources):
    chunks, idx = [], 0
    for w_start, w_end in windows:
        t = w_start
        while t < w_end - 1.0:
            end = min(t + chunk_len, w_end)
            if end - t < chunk_len * 0.25 and chunks:      # fold a runt into its neighbour
                chunks[-1]["abs_end"] = end
                chunks[-1]["duration"] = chunks[-1]["abs_end"] - chunks[-1]["abs_start"]
                break
            src = source_for(sources, t)
            if src is None:
                break
            chunks.append({
                "id": f"chunk_{idx:04d}",
                "abs_start": round(t, 2),
                "abs_end": round(end, 2),
                "duration": round(end - t, 2),
                "source": src["name"],
                "source_offset": round(t - src["abs_start"], 2),
            })
            idx += 1
            t = end
    return chunks


def source_for(sources, abs_t):
    for s in sources:
        if s["abs_start"] <= abs_t < s["abs_end"]:
            return s
    return None


# ----------------------------------------------------------------- pass 3: cut

def cut_chunk(chunk, sources, out_dir, args, font, epoch0):
    src = next(s for s in sources if s["name"] == chunk["source"])
    clock_epoch = int(epoch0 + chunk["abs_start"])
    label = chunk["id"]
    filters = [f"fps={args.fps}", f"scale={args.width}:-2"]
    if font:
        stamp = (f"drawtext=fontfile={font}:"
                 f"text='%{{pts\\:localtime\\:{clock_epoch}\\:%Y-%m-%d %H\\\\\\:%M\\\\\\:%S}}  {label}':"
                 f"x=8:y=8:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=6")
        filters.append(stamp)
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y",
           "-ss", str(chunk["source_offset"]), "-i", str(src["path"]),
           "-t", str(chunk["duration"]),
           "-vf", ",".join(filters),
           "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(args.crf),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           str(out_dir / chunk["file"])]
    r = run(cmd)
    return r.returncode == 0, r.stderr.strip()


# ------------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description="Prep plant footage for video-model annotation.")
    ap.add_argument("--input", required=True, help="video file or directory of files (sorted by name)")
    ap.add_argument("--start", required=True, help='wall clock of first frame, "YYYY-MM-DD HH:MM[:SS]"')
    ap.add_argument("--out", default="chunks", help="output directory")
    ap.add_argument("--chunk-len", type=float, default=300, help="chunk length in seconds (default 300)")
    ap.add_argument("--fps", type=float, default=2, help="output fps (default 2)")
    ap.add_argument("--width", type=int, default=854, help="output width (default 854)")
    ap.add_argument("--crf", type=int, default=28)
    ap.add_argument("--sample-period", type=float, default=2.0, help="motion sample every N sec")
    ap.add_argument("--threshold", type=float, default=1.2, help="motion threshold (0-255 mean diff)")
    ap.add_argument("--pad", type=float, default=60, help="seconds of padding around active windows")
    ap.add_argument("--min-gap", type=float, default=120, help="quiet seconds that split two windows")
    ap.add_argument("--dry-run", action="store_true", help="scan and plan, do not export")
    ap.add_argument("--limit", type=int, default=0, help="export only the first N chunks (smoke test)")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        die("ffmpeg not on PATH")

    try:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            start_dt = datetime.strptime(args.start, "%Y-%m-%d %H:%M")
        except ValueError:
            die('--start must look like "2026-09-01 06:00:00"')
    epoch0 = start_dt.timestamp()

    files = collect_inputs(args.input)
    sources, cursor = [], 0.0
    print(f"reading {len(files)} file(s)...")
    for f in files:
        d = probe_duration(f)
        sources.append({"name": f.name, "path": f, "duration": d,
                        "abs_start": cursor, "abs_end": cursor + d})
        cursor += d
    total = cursor
    print(f"total footage: {total/3600:.2f} h  ({start_dt} -> {start_dt + timedelta(seconds=total)})")

    print("\npass 1/3  motion scan")
    samples, t0 = [], time.time()
    for s in sources:
        prof = motion_profile(s["path"], args.sample_period)
        samples += [(t + s["abs_start"], v) for t, v in prof]
        print(f"  {s['name']}: {len(prof)} samples")
    if not samples:
        die("motion scan produced no samples - is the input readable?")
    samples.sort()
    print(f"  {len(samples)} samples in {time.time()-t0:.0f}s")

    windows = windows_from_samples(samples, args.threshold, args.pad, args.min_gap, 0.0)
    active = sum(b - a for a, b in windows)
    print("\npass 2/3  plan")
    print(f"  {len(windows)} active window(s), {active/3600:.2f} h kept "
          f"({100*active/total:.0f}% of footage, {(total-active)/3600:.2f} h of dead air dropped)")

    chunks = plan_chunks(windows, args.chunk_len, sources)
    for c in chunks:
        cs = start_dt + timedelta(seconds=c["abs_start"])
        c["clock_start"] = cs.isoformat(timespec="seconds")
        c["clock_end"] = (start_dt + timedelta(seconds=c["abs_end"])).isoformat(timespec="seconds")
        c["file"] = f"{c['id']}__{cs.strftime('%Y-%m-%d_%H%M%S')}.mp4"
    frames = sum(c["duration"] for c in chunks) * args.fps
    clen = (f"{args.chunk_len/60:.0f} min" if args.chunk_len >= 60 else f"{args.chunk_len:.0f} s")
    print(f"  {len(chunks)} chunks of {clen} -> ~{frames:,.0f} frames at {args.fps} fps")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "recording_start": start_dt.isoformat(timespec="seconds"),
        "total_seconds": round(total, 2),
        "kept_seconds": round(active, 2),
        "chunk_len": args.chunk_len, "fps": args.fps, "width": args.width,
        "sources": [{"name": s["name"], "duration": round(s["duration"], 2),
                     "abs_start": round(s["abs_start"], 2)} for s in sources],
        "activity": [{"t": round(t, 1), "motion": round(v, 3)} for t, v in samples],
        "windows": [{"abs_start": round(a, 2), "abs_end": round(b, 2)} for a, b in windows],
        "chunks": chunks,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"  wrote {out_dir/'manifest.json'}")

    if args.dry_run:
        print("\ndry run - no clips exported")
        return

    todo = chunks[: args.limit] if args.limit else chunks
    print(f"\npass 3/3  cut {len(todo)} chunk(s) -> {out_dir}")
    font = pick_font()
    if not font:
        print("  note: this ffmpeg has no drawtext filter - no burned-in clock.")
        print("        Timing still comes from manifest.json and the chunk filenames.")
    failed = 0
    for i, c in enumerate(todo, 1):
        ok, err = cut_chunk(c, sources, out_dir, args, font, epoch0)
        if not ok:
            failed += 1
            print(f"  [{i}/{len(todo)}] {c['id']} FAILED: {err.splitlines()[-1] if err else '?'}")
        elif i % 10 == 0 or i == len(todo):
            print(f"  [{i}/{len(todo)}] {c['id']} {c['clock_start']}")
    print(f"\ndone. {len(todo)-failed} clip(s) in {out_dir}/, {failed} failed.")


if __name__ == "__main__":
    main()
