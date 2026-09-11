# Plant Floor Review

[![CI](https://github.com/Moha-Mahdhour/plant-floor-review/actions/workflows/ci.yml/badge.svg)](https://github.com/Moha-Mahdhour/plant-floor-review/actions/workflows/ci.yml)

Turn 36 hours of dry cleaning / laundry CCTV into a bottleneck analysis you can act on.

Raw footage is the wrong input for a video model: 36 h at 30 fps is ~3.9 million
frames, most of them an empty room. This tool does the boring reduction first,
hands your video model only the frames that can contain an answer, and folds the
replies back into one timeline you can open in a browser or read as a report.

![Plant Floor Review dashboard on the bundled synthetic dataset](docs/dashboard.png)

*Overview tab on the bundled synthetic dataset. The demo plant has a bottleneck planted at the shirt press, and the dashboard finds it: likely constraint, costliest station, and biggest single cause all point there.*

```
raw footage ──▶ plantfloor prep ──▶ chunks/ + manifest.json
                                        │
                                plantfloor prompts
                                        │
                                   ┌────▼────┐
                                   │  MODEL  │  one clip + one prompt per call
                                   └────┬────┘
                                        │  annotations/chunk_XXXX.json
                                 plantfloor merge
                                        │
                              data/events.json ──▶ app/index.html
                                        └────────▶ plantfloor report
```

Standard-library Python only; ffmpeg is needed for the `prep` step.

## Quick look, before you process anything

```bash
python -m plantfloor report --events demo     # the findings as Markdown
open app/index.html                           # the dashboard, demo data preloaded
```

Both use a synthetic 36 h plant with a story planted in it: the shirt press is
the constraint, assembly loses time hunting missing tickets, and a dryer fails on
day 2. You can check the tool actually finds what is there.

## Running it on real footage

Every step is a subcommand of `python -m plantfloor` (or `plantfloor` after
`pip install .`). The old `prep/prepare.py` and `ingest/*.py` scripts still work
and call the same code.

### 1. Reduce the footage

```bash
python -m plantfloor prep --input /path/to/raw --start "2026-09-01 06:00:00"
```

`--input` takes one file or a directory (files are joined in filename order, so
name them so they sort chronologically). `--start` is the wall-clock time of the
very first frame; everything downstream hangs off it, so get it right.

Three passes run:

1. **Scan**: ffmpeg measures inter-frame motion every 2 s across the whole
   recording. A 36 h file profiles in minutes because the arithmetic happens in
   C, not Python.
2. **Plan**: quiet stretches are dropped, active stretches are padded and cut
   into fixed chunks. No chunk ever spans two input files, and a short tail is
   only folded into a chunk from the same stretch of footage.
3. **Cut**: each chunk is re-encoded small (854 px, 2 fps, CRF 28) and named with
   its own start clock.

Add `--dry-run` first to see how much survives before you spend the encode time.

| Flag | Default | Effect |
|---|---|---|
| `--threshold` | 1.2 | Higher drops more footage. Raise it if the scan keeps empty rooms; lower it if quiet bench work gets dropped. |
| `--fps` | 2 | 1 is enough for queues and machine state. Use 3–4 only if you need hand-level detail. |
| `--chunk-len` | 300 | Shorter chunks cost more calls but localise events better. |
| `--width` | 854 | 640 is usually still readable and meaningfully cheaper. |
| `--pad` | 60 | Seconds kept either side of activity, so a chunk does not start mid-event. |

### 2. Build the prompts

```bash
python -m plantfloor prompts
```

Writes `annotations/_prompts/chunk_XXXX.txt` plus a `batch.jsonl` carrying the
clip path, system prompt, JSON schema and user prompt for every chunk. Send
**one chunk per call**, in order, with `prompts/system_prompt.md` as the system
prompt and `prompts/schema.json` as the response schema (use structured output
if your model supports it). Save each reply verbatim to
`annotations/chunk_XXXX.json`.

Re-running `prompts` after some replies exist folds the still-open events from
the previous chunk into the next prompt, which is what lets a 40-minute stall
spanning eight clips come back as one event instead of eight.

### 3. Merge

```bash
python -m plantfloor merge --site "Main St plant"
```

Converts chunk-relative offsets to absolute time, stitches continuations,
repairs or rejects malformed events, and writes `data/events.json`. It prints
every repair it made; a pile of "unknown station" warnings means the station ids
in your prompt do not match what the camera actually shows. `--min-confidence 0.5`
drops the model's own low-confidence guesses.

### 4. Read the result

```bash
python -m plantfloor report --out report.md   # shareable Markdown
open app/index.html                           # then "Open events.json"
```

In the dashboard, **Attach video** lets you click any annotation to seek
straight to that moment.

## Reading the dashboard

**Overview** — the headline numbers. *Likely constraint* is the station with the
most queue build-up; *costliest station* is where the most time is lost. They are
often different, and the difference is the point: the costliest station is
frequently a victim of the constraint, not the problem.

**Timeline** — every annotation on a station swimlane. Hatched bands are stretches
nobody annotated. Click a block for the detail panel.

**Stations** — the scorecard. The column that matters:

- **Blocked** = the station could not release work because the *next* step was
  full. Fix downstream.
- **Starved** = the station was ready but nothing arrived. Fix upstream.

A station with a large *blocked* number is not your problem station. The one
causing it is.

**Causes** — the Pareto. This is where you decide what to change on Monday. The
footer tells you how few causes account for 80% of the loss.

**Events** — everything, ranked by impact (minutes × severity), searchable.

## Adapting it to your plant

`prompts/stations.json` is the one file you should expect to edit. Ids are the
join key for every chart, so change them before you annotate, not after. If your
shop has two press lines, split `press_shirt` into `press_1` / `press_2` — the
dashboard picks up new stations automatically.

If the model keeps guessing the wrong station, the fix is usually a camera map:
add a labelled reference frame to the system prompt showing which zone is which.

## Project layout

| Module | Responsibility |
|---|---|
| `plantfloor/video/plan.py` | Pure planning: motion samples to active windows to chunks |
| `plantfloor/video/ffmpeg.py` | Probing, motion scan and clip export via ffmpeg |
| `plantfloor/prepare.py` | The scan / plan / cut pipeline and `manifest.json` |
| `plantfloor/prompts.py` | Per-chunk prompt rendering and `batch.jsonl` |
| `plantfloor/merge.py` | Pure merge: offsets, stitching, repairs, coverage |
| `plantfloor/metrics.py` | The dashboard's headline numbers, computed in Python |
| `plantfloor/report.py` | Markdown bottleneck report |
| `plantfloor/taxonomy.py` / `stations.py` | Event categories and the validated station catalog |
| `plantfloor/demo.py` | Synthetic 36 h dataset |
| `prompts/` | Analyst brief, output schema, **your plant's stations** |
| `app/index.html` | The dashboard, self-contained |

## Tests

```bash
python -m unittest discover -s tests -t .
```

No dependencies. The end-to-end test generates footage with ffmpeg and runs the
whole prep pipeline on it; it is skipped when ffmpeg is not installed and always
runs in CI. Other tests check that the schema, the dashboard and the Python
taxonomy agree, that the bundled demo matches its generator exactly, and that
the Python metrics reproduce the dashboard's numbers.

## Notes

- Everything runs locally. Only the chunk clips ever leave the machine, and only
  when you send them to the model.
- `prep` burns a wall-clock overlay into each clip when ffmpeg has `drawtext`.
  Some builds (including common Homebrew ones) ship without it; timing still
  comes from `manifest.json` and the chunk filenames.

## License

MIT
