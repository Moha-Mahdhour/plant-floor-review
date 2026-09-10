"""Everything that shells out to ffmpeg/ffprobe.

Errors raise FFmpegError instead of exiting the process, so the pipeline
can be driven from the CLI, tests, or other code.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

from .plan import Sample, Source

VIDEO_EXT = frozenset({".mp4", ".mov", ".mkv", ".avi", ".m4v", ".mpg", ".mpeg", ".ts", ".dav"})
FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

_FRAME = re.compile(r"frame:\d+\s+pts:\d+\s+pts_time:([\d.]+)")
_YAVG = re.compile(r"YAVG=([\d.]+)")


class FFmpegError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
    if missing:
        raise FFmpegError(f"{' and '.join(missing)} not found on PATH")


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True)


def collect_inputs(target: str | Path) -> list[Path]:
    """One file, or every video in a directory sorted by name (name them chronologically)."""
    p = Path(target)
    if p.is_file():
        return [p]
    if p.is_dir():
        files = sorted(q for q in p.iterdir() if q.suffix.lower() in VIDEO_EXT)
        if not files:
            raise FFmpegError(f"no video files in {p}")
        return files
    raise FFmpegError(f"input not found: {target}")


def probe_duration(path: Path) -> float:
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)])
    try:
        return float(r.stdout.strip())
    except ValueError as exc:
        raise FFmpegError(f"could not read duration of {path}: {r.stderr.strip() or 'no output'}") from exc


def has_drawtext() -> bool:
    r = _run(["ffmpeg", "-hide_banner", "-filters"])
    return bool(re.search(r"^\s*\S+\s+drawtext\s", r.stdout or "", re.M))


def pick_font() -> str | None:
    """A usable font for the burned-in clock, or None if ffmpeg cannot draw text.

    The clock is a convenience for people scrubbing clips; timing comes from
    the manifest and chunk filenames, so builds without libfreetype degrade
    cleanly.
    """
    if not has_drawtext():
        return None
    return next((f for f in FONT_CANDIDATES if os.path.exists(f)), None)


def parse_signalstats(lines: Iterable[str]) -> list[Sample]:
    """Pair each frame's pts_time with the YAVG value printed after it."""
    samples, pending = [], None
    for line in lines:
        m = _FRAME.match(line)
        if m:
            pending = float(m.group(1))
            continue
        m = _YAVG.search(line)
        if m and pending is not None:
            samples.append((pending, float(m.group(1))))
            pending = None
    return samples


def motion_profile(path: Path, sample_period: float) -> list[Sample]:
    """Mean inter-frame difference, one value per sample_period seconds.

    ffmpeg decodes, downscales, differences and averages in C, so a 36 h
    recording profiles in minutes.
    """
    vf = (f"fps=1/{sample_period},scale=64:36,format=gray,tblend=all_mode=difference,signalstats,"
          f"metadata=print:key=lavfi.signalstats.YAVG:file=-")
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-vf", vf, "-an", "-f", "null", "-"]
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as proc:
        return parse_signalstats(proc.stdout)


def cut_chunk(chunk: dict, source: Source, out_path: Path, *, fps: float, width: int, crf: int,
              font: str | None, clock_epoch: int) -> tuple[bool, str]:
    """Export one chunk, downscaled and low-fps, optionally with the wall clock burned in."""
    filters = [f"fps={fps}", f"scale={width}:-2"]
    if font:
        filters.append(
            f"drawtext=fontfile={font}:"
            f"text='%{{pts\\:localtime\\:{clock_epoch}\\:%Y-%m-%d %H\\\\\\:%M\\\\\\:%S}}  {chunk['id']}':"
            f"x=8:y=8:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=6")
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", str(chunk["source_offset"]), "-i", str(source.path),
           "-t", str(chunk["duration"]), "-vf", ",".join(filters), "-an", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
    r = _run(cmd)
    return r.returncode == 0, r.stderr.strip()
