#!/usr/bin/env python3
"""Compatibility wrapper for `python -m plantfloor prep`; see plantfloor/prepare.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plantfloor.prepare import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
