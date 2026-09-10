"""Bottleneck metrics, computed exactly as the dashboard computes them.

  lost time          minutes in loss-category events (see taxonomy)
  likely constraint  station with the most queue build-up
  costliest station  station with the most lost minutes
  impact             minutes x severity
  vital few          causes whose running total stays within 80% of all loss

Having these in Python lets the report command and the tests check the same
numbers people see in the browser.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import ceil
from typing import Any, Callable, Iterable, Mapping, Sequence

from .taxonomy import is_loss

Event = Mapping[str, Any]


def minutes(e: Event) -> float:
    return e["duration"] / 60


def impact(e: Event) -> float:
    return minutes(e) * e["severity"]


@dataclass(frozen=True)
class Ranked:
    key: str
    minutes: float
    impact: float
    count: int


@dataclass(frozen=True)
class StationRow:
    station: str
    name: str
    work: float
    lost: float
    blocked: float
    starved: float
    queue: float
    impact: float
    events: int


@dataclass(frozen=True)
class Summary:
    site: str
    recording_start: datetime
    recorded_hours: float
    chunks_annotated: int
    chunks_total: int
    lost_minutes: float
    work_minutes: float
    constraint: Ranked | None
    costliest: Ranked | None
    top_cause: Ranked | None
    worst_hour: tuple[datetime, float] | None
    causes: list[Ranked] = field(default_factory=list)
    vital_few: int = 0
    stations: list[StationRow] = field(default_factory=list)

    @property
    def loss_share(self) -> float:
        total = self.lost_minutes + self.work_minutes
        return self.lost_minutes / total if total else 0.0


def rank(events: Iterable[Event], key: Callable[[Event], str]) -> list[Ranked]:
    groups: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        groups[key(e)].append(e)
    rows = [Ranked(k, sum(map(minutes, v)), sum(map(impact, v)), len(v)) for k, v in groups.items()]
    return sorted(rows, key=lambda r: -r.minutes)     # stable, like the dashboard


def loss_by_hour(losses: Sequence[Event], total_seconds: float, start: datetime) -> list[tuple[datetime, float]]:
    """Lost minutes overlapping each hour of the recording."""
    out = []
    for h in range(max(1, ceil(total_seconds / 3600))):
        a, b = h * 3600, (h + 1) * 3600
        v = sum(max(0.0, min(e["abs_end"], b) - max(e["abs_start"], a)) / 60 for e in losses)
        out.append((start + timedelta(seconds=a), v))
    return out


def vital_few(causes: Sequence[Ranked]) -> int:
    total = sum(c.minutes for c in causes)
    running, count = 0.0, 0
    for c in causes:
        running += c.minutes
        if running <= total * 0.8:
            count += 1
    return count or 1


def station_rows(events: Sequence[Event], names: Mapping[str, str]) -> list[StationRow]:
    by_station: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        by_station[e["station"]].append(e)
    rows = []
    for st, evs in by_station.items():
        of = lambda t: sum(minutes(e) for e in evs if e["type"] == t)
        losses = [e for e in evs if is_loss(e["type"])]
        rows.append(StationRow(st, names.get(st, st), of("work"), sum(map(minutes, losses)), of("blockage"),
                               of("starvation"), of("queue_buildup"), sum(map(impact, losses)), len(evs)))
    return sorted(rows, key=lambda r: -r.impact)


def summarize(doc: Mapping[str, Any], *, min_confidence: float = 0.0, min_severity: int = 1) -> Summary:
    meta = doc["meta"]
    events = [e for e in doc["events"] if e["confidence"] >= min_confidence and e["severity"] >= min_severity]
    losses = [e for e in events if is_loss(e["type"])]
    start = datetime.fromisoformat(meta["recording_start"])
    causes = rank(losses, lambda e: e["cause"])
    stations = rank(losses, lambda e: e["station"])
    queues = rank((e for e in events if e["type"] == "queue_buildup"), lambda e: e["station"])
    hours = loss_by_hour(losses, meta.get("total_seconds", 0), start)
    worst = max(hours, key=lambda hv: hv[1]) if losses else None
    names = {s["id"]: s["name"] for s in doc.get("stations", [])}
    return Summary(
        site=meta.get("site", ""), recording_start=start, recorded_hours=meta.get("total_seconds", 0) / 3600,
        chunks_annotated=meta.get("chunks_annotated", 0), chunks_total=meta.get("chunks_total", 0),
        lost_minutes=sum(map(minutes, losses)),
        work_minutes=sum(minutes(e) for e in events if e["type"] == "work"),
        constraint=queues[0] if queues else None, costliest=stations[0] if stations else None,
        top_cause=causes[0] if causes else None, worst_hour=worst,
        causes=causes, vital_few=vital_few(causes) if causes else 0, stations=station_rows(events, names),
    )
