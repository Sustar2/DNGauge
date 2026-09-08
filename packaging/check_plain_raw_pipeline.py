#!/usr/bin/env python3
"""Smoke-test the cross-platform plain-RAW temporary-DNG render path."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shotwell_compare import PIDNG_AVAILABLE, _plain_raw_temp_dng_to_rgb


def main() -> None:
    if not PIDNG_AVAILABLE:
        raise RuntimeError("PiDNG is unavailable; plain RAW would use the color-shifting fallback renderer")

    raw = np.full((64, 64), 512, dtype=np.uint16)
    raw[0::2, 0::2] = 700
    raw[1::2, 1::2] = 700
    rgb = _plain_raw_temp_dng_to_rgb(
        raw,
        pattern="RGGB",
        bit=10,
        black_level=0,
        white_level=1023,
        wb_enabled=False,
        wb=(1.0, 1.0, 1.0),
    )
    if rgb is None or rgb.shape != (64, 64, 3) or rgb.dtype != np.uint8:
        raise RuntimeError("plain RAW temporary-DNG pipeline returned an invalid RGB image")

    print(f"plain RAW pipeline: ok (temp={tempfile.gettempdir()})")


if __name__ == "__main__":
    main()
