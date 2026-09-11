"""python -m plantfloor <step>

  prep     reduce raw footage to annotated-ready chunks (needs ffmpeg)
  prompts  render one prompt per chunk for your video model
  merge    fold the model's replies into data/events.json
  report   write the bottleneck findings as Markdown
  demo     regenerate the bundled synthetic dataset
"""
from __future__ import annotations

import argparse
import sys

from . import __version__, demo, merge, prepare, prompts, report

STEPS = {
    "prep": (prepare, "reduce raw footage to chunks (needs ffmpeg)"),
    "prompts": (prompts, "render one prompt per chunk"),
    "merge": (merge, "merge annotations into data/events.json"),
    "report": (report, "write the bottleneck report as Markdown"),
    "demo": (demo, "regenerate the synthetic demo dataset"),
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="plantfloor", description="Turn plant-floor CCTV into a bottleneck analysis.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="step", required=True, metavar="step")
    for name, (module, help_text) in STEPS.items():
        module.build_parser(sub.add_parser(name, help=help_text, description=help_text))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    module, _ = STEPS[args.step]
    return module.run(args)


if __name__ == "__main__":
    sys.exit(main())
