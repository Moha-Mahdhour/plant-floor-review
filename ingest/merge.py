#!/usr/bin/env python3
"""Compatibility wrapper for `python -m plantfloor merge`; see plantfloor/merge.py."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from plantfloor.merge import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(root=ROOT))
