#!/usr/bin/env python3
"""
make_demo.py - synthesise a realistic 36h dataset in the exact shape merge.py
produces, so the app can be evaluated before any real footage is processed.

The plant it simulates has a deliberate, findable story:
  * the shirt press is the constraint - it blocks spotting and starves QC
  * assembly loses a lot of time hunting for missing tickets
  * a dryer fails on day 2 and the effect cascades
Anything the dashboard says should match those facts.
"""
import json, random
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rng = random.Random(7)

START = datetime(2026, 9, 1, 6, 0, 0)
TOTAL_H = 36
OPEN_H, CLOSE_H = 7, 19

stations = json.loads((ROOT / "prompts/stations.json").read_text())["stations"]
events, throughput, coverage = [], [], []


def add(day, h, m, dur_min, station, etype, sev, conf, label, cause, **kw):
    t = (datetime(2026, 9, 1 + day, 0, 0) + timedelta(hours=h, minutes=m) - START).total_seconds()
    if t < 0 or t > TOTAL_H * 3600:
        return
    e = {"abs_start": round(t, 1), "abs_end": round(t + dur_min * 60, 1),
         "station": station, "type": etype, "severity": sev,
         "confidence": round(conf, 2), "label": label, "cause": cause,
         "chunks": [f"chunk_{int(t//300):04d}"]}
    e.update(kw)
    events.append(e)


def open_hours():
    for day in (0, 1):
        for h in range(OPEN_H, CLOSE_H):
            if day == 1 and h >= 18:
                continue
            yield day, h


# --- routine production ------------------------------------------------------
for day, h in open_hours():
    for st in ["counter", "tagging", "sorting", "spotting", "dryclean", "washers",
               "dryers", "press_shirt", "press_hand", "qc", "bagging", "assembly", "dispatch"]:
        load = {"press_shirt": 0.93, "assembly": 0.72, "spotting": 0.62, "qc": 0.55}.get(st, 0.5)
        if h in (12, 13):
            load *= 0.55
        mins = max(4, min(56, int(rng.gauss(load * 60, 7))))
        add(day, h, rng.randint(0, 4), mins, st, "work", 1, 0.9,
            f"Normal processing at {st}", "productive", actors=rng.randint(1, 2))

# --- the constraint: shirt press ---------------------------------------------
for day, h in open_hours():
    if h in (9, 10, 11, 14, 15, 16, 17):
        q = rng.randint(9, 26) + (6 if h in (10, 15) else 0)
        add(day, h, rng.randint(5, 25), rng.randint(14, 38), "press_shirt", "queue_buildup",
            4 if q > 18 else 3, 0.86,
            f"Shirt press backlog grows to ~{q} garments", "press_backlog", items=q)
        add(day, h, rng.randint(10, 40), rng.randint(8, 22), "spotting", "blockage",
            3, 0.74, "Spotting holds finished work - press rail full", "press_backlog")
        add(day, h, rng.randint(15, 45), rng.randint(10, 26), "qc", "starvation",
            3, 0.71, "QC waiting, nothing arriving from press", "press_backlog")

# --- assembly search waste ---------------------------------------------------
for day, h in open_hours():
    for _ in range(rng.randint(1, 3)):
        add(day, h, rng.randint(0, 50), rng.randint(3, 11), "assembly", "search",
            3, 0.68, "Operator searching conveyor for a missing ticket", "missing_ticket",
            actors=1)

# --- counter peaks -----------------------------------------------------------
for day, h in open_hours():
    if h in (8, 17, 18):
        add(day, h, rng.randint(0, 30), rng.randint(6, 18), "counter", "customer_wait",
            4 if h == 17 else 3, 0.8,
            f"{rng.randint(2,5)} customers queued, one clerk on counter", "understaffed_counter")

# --- lunch gap ---------------------------------------------------------------
for day in (0, 1):
    add(day, 13, 0, 45, "press_shirt", "unmanned", 4, 0.83,
        "Press unmanned over lunch while queue is still deep", "no_relief_cover")
    add(day, 13, 5, 35, "bagging", "unmanned", 2, 0.7, "Bagging bench empty over lunch", "no_relief_cover")

# --- day 2 dryer failure cascade --------------------------------------------
add(1, 10, 20, 95, "dryers", "machine_stop", 5, 0.91,
    "Dryer 2 down, load left inside, technician called", "machine_breakdown", items=40)
add(1, 10, 35, 80, "washers", "blockage", 4, 0.84, "Washers holding wet loads, no dryer capacity", "machine_breakdown")
add(1, 11, 0, 70, "press_hand", "starvation", 4, 0.79, "Finishing idle waiting on dry goods", "machine_breakdown")
add(1, 11, 30, 55, "dispatch", "starvation", 3, 0.72, "Dispatch shelf empty, pickups delayed", "machine_breakdown")

# --- assorted ----------------------------------------------------------------
for day, h in open_hours():
    if rng.random() < 0.3:
        add(day, h, rng.randint(0, 45), rng.randint(4, 12), "floor", "transport",
            2, 0.6, "Cart moved the long way around a blocked aisle", "aisle_blocked")
    if rng.random() < 0.18:
        add(day, h, rng.randint(0, 45), rng.randint(5, 14), "qc", "rework",
            3, 0.75, "Garment returned to spotting after QC", "quality_fail")
    if rng.random() < 0.12:
        add(day, h, rng.randint(0, 45), rng.randint(6, 20), "dryclean", "changeover",
            2, 0.7, "Machine unload / reload changeover", "changeover")
add(0, 15, 12, 10, "floor", "safety", 4, 0.66, "Solvent spill near dry clean unit, aisle wet", "spill")
add(1, 9, 40, 10, "floor", "safety", 3, 0.6, "Hanger box stacked blocking fire exit", "blocked_exit")

# --- throughput + coverage ---------------------------------------------------
for i in range(TOTAL_H * 12):                       # every 5 min
    t = i * 300
    hh = (START + timedelta(seconds=t))
    openish = OPEN_H <= hh.hour < CLOSE_H
    day2_fail = hh.day == 2 and 10 <= hh.hour < 12
    if openish:
        base = rng.randint(2, 7)
        throughput.append({"abs_start": t,
                           "items_in": base + rng.randint(0, 3),
                           "items_out": max(0, base - (3 if day2_fail else rng.randint(0, 2))),
                           "customers": rng.randint(0, 3)})
    coverage.append({"abs_start": t, "abs_end": t + 300,
                     "state": "clear" if openish else "not_annotated"})

activity = []
for i in range(TOTAL_H * 30):                       # every 2 min
    t = i * 120
    hh = (START + timedelta(seconds=t))
    openish = OPEN_H <= hh.hour < CLOSE_H
    activity.append({"t": t, "motion": round(rng.uniform(2.5, 9.0) if openish else rng.uniform(0.0, 0.6), 2)})

for i, e in enumerate(sorted(events, key=lambda x: x["abs_start"])):
    e["id"] = f"e{i:05d}"
    e["duration"] = round(e["abs_end"] - e["abs_start"], 1)
    e["clock_start"] = (START + timedelta(seconds=e["abs_start"])).isoformat(timespec="seconds")
    e["spans"] = len(e["chunks"])
events.sort(key=lambda x: x["abs_start"])

out = {
    "meta": {"site": "Demo dry cleaning plant (synthetic)", "recording_start": START.isoformat(),
             "total_seconds": TOTAL_H * 3600, "kept_seconds": 24 * 3600,
             "chunks_total": TOTAL_H * 12, "chunks_annotated": 24 * 12,
             "generated": datetime.now().isoformat(timespec="seconds"),
             "demo": True, "min_confidence": 0.0},
    "stations": stations, "activity": activity, "coverage": coverage,
    "throughput": throughput, "events": events,
}
p = ROOT / "data/events.demo.json"
p.parent.mkdir(exist_ok=True)
p.write_text(json.dumps(out, indent=1))
print(f"{len(events)} events -> {p}  ({p.stat().st_size/1024:.0f} KB)")

# also emit a classic-script version so app/index.html works from file:// with no server
js = ROOT / "data/events.demo.js"
js.write_text("window.DEMO_DATA = " + json.dumps(out) + ";")
print(f"and         -> {js}")
