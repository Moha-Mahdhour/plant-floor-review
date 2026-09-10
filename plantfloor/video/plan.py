"""Pure planning: motion samples in, chunk list out. No ffmpeg, no files.

Keeping this free of I/O is what makes the reduction logic testable: every
decision about which footage survives is made here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from ..timecode import at, clip_stamp, iso

Sample = tuple[float, float]          # (absolute seconds, mean motion)
Window = tuple[float, float]          # (absolute start, absolute end)


@dataclass(frozen=True)
class Source:
    """One input file placed on the recording's absolute timeline."""
    name: str
    path: Path
    duration: float
    abs_start: float

    @property
    def abs_end(self) -> float:
        return self.abs_start + self.duration


def lay_out(files: Iterable[tuple[str, Path, float]]) -> tuple[Source, ...]:
    """Place (name, path, duration) files back to back in the given order."""
    out, cursor = [], 0.0
    for name, path, duration in files:
        out.append(Source(name, Path(path), duration, cursor))
        cursor += duration
    return tuple(out)


def windows_from_samples(samples: Sequence[Sample], threshold: float, pad: float, min_gap: float) -> list[Window]:
    """Collapse per-sample motion into padded active windows (absolute seconds)."""
    hot = [t for t, v in samples if v >= threshold]
    if not hot:
        return []
    raw, start = [], hot[0]
    prev = hot[0]
    for t in hot[1:]:
        if t - prev > min_gap:
            raw.append((start, prev))
            start = t
        prev = t
    raw.append((start, prev))
    step = (samples[1][0] - samples[0][0]) if len(samples) > 1 else pad
    padded = [(max(0.0, a - pad), b + step + pad) for a, b in raw]
    merged = [list(padded[0])]
    for a, b in padded[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def source_for(sources: Sequence[Source], abs_t: float) -> Source | None:
    for s in sources:
        if s.abs_start <= abs_t < s.abs_end:
            return s
    return None


def split_at_sources(windows: Sequence[Window], sources: Sequence[Source]) -> list[tuple[float, float, Source]]:
    """Clip each window to the files it overlaps, so no piece crosses a file boundary.

    Also drops padding that runs past the end of the recording.
    """
    segments = []
    for a, b in windows:
        for s in sources:
            lo, hi = max(a, s.abs_start), min(b, s.abs_end)
            if hi - lo > 1.0:
                segments.append((lo, hi, s))
    return segments


def plan_chunks(windows: Sequence[Window], chunk_len: float, sources: Sequence[Source]) -> list[dict]:
    """Cut active footage into fixed-length chunks; fold a short tail into its neighbour.

    Every chunk lies inside a single source file. Previously a chunk was
    assigned to the file it started in and could run past that file's end,
    so ffmpeg cut a shorter clip than the manifest recorded and every
    timestamp in it drifted.
    """
    chunks: list[dict] = []
    idx = 0
    for seg_start, seg_end, src in split_at_sources(windows, sources):
        t = seg_start
        while t < seg_end - 1.0:
            end = min(t + chunk_len, seg_end)
            if end - t < chunk_len * 0.25 and chunks and chunks[-1]["source"] == src.name:
                chunks[-1]["abs_end"] = round(end, 2)
                chunks[-1]["duration"] = round(chunks[-1]["abs_end"] - chunks[-1]["abs_start"], 2)
                break
            chunks.append({
                "id": f"chunk_{idx:04d}",
                "abs_start": round(t, 2),
                "abs_end": round(end, 2),
                "duration": round(end - t, 2),
                "source": src.name,
                "source_offset": round(t - src.abs_start, 2),
            })
            idx += 1
            t = end
    return chunks


def finalize_chunks(chunks: list[dict], start: datetime) -> list[dict]:
    """Add wall-clock fields and the clip filename to each planned chunk."""
    for c in chunks:
        cs = at(start, c["abs_start"])
        c["clock_start"] = iso(cs)
        c["clock_end"] = iso(at(start, c["abs_end"]))
        c["file"] = f"{c['id']}__{clip_stamp(cs)}.mp4"
    return chunks
