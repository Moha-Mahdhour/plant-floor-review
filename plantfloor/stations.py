"""The plant's station catalog (prompts/stations.json).

Station ids are the join key for every chart and every annotation, so the
catalog is validated up front: a duplicate id or a missing fallback
station would otherwise surface as silently wrong charts much later.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

KINDS = frozenset({"service", "prep", "manual", "machine", "other"})
FALLBACK_STATION = "floor"
_ID = re.compile(r"^[a-z][a-z0-9_]*$")


class StationError(ValueError):
    pass


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    order: int
    kind: str

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "order": self.order, "name": self.name, "kind": self.kind}


def parse_stations(raw: Sequence[Mapping[str, Any]]) -> tuple[Station, ...]:
    if not raw:
        raise StationError("station list is empty")
    out, seen = [], set()
    for i, s in enumerate(raw):
        sid = s.get("id")
        if not isinstance(sid, str) or not _ID.match(sid):
            raise StationError(f"station #{i + 1}: id {sid!r} must be lower_snake_case")
        if sid in seen:
            raise StationError(f"duplicate station id {sid!r}")
        seen.add(sid)
        kind = s.get("kind", "other")
        if kind not in KINDS:
            raise StationError(f"station {sid!r}: kind {kind!r} is not one of {sorted(KINDS)}")
        out.append(Station(sid, str(s.get("name") or sid), int(s.get("order", 99)), kind))
    if FALLBACK_STATION not in seen:
        raise StationError(f"a {FALLBACK_STATION!r} station is required; it catches events that cannot be placed")
    return tuple(sorted(out, key=lambda st: (st.order, st.id)))


def load_stations(path: str | Path) -> tuple[Station, ...]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StationError(f"station file not found: {path}") from exc
    return parse_stations(data.get("stations", []) if isinstance(data, dict) else data)
