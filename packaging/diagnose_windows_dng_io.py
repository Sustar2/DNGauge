#!/usr/bin/env python3
"""Diagnose PiDNG/rawpy file I/O behavior on Windows.

Usage:
    python packaging\diagnose_windows_dng_io.py
    python packaging\diagnose_windows_dng_io.py "C:\path\to\image.dng"
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
import platform
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
import rawpy
from pidng.core import DNGTags, RAW2DNG, Tag
from pidng.defs import (
    CalibrationIlluminant,
    CFAPattern,
    DNGVersion,
    Orientation,
    PhotometricInterpretation,
    PreviewColorSpace,
)


CCM = [
    [+6668, 10000],
    [-1588, 10000],
    [-857, 10000],
    [-5739, 10000],
    [+13898, 10000],
    [+1430, 10000],
    [-1378, 10000],
    [+2651, 10000],
    [+6036, 10000],
]


def make_test_raw(height: int = 3072, width: int = 4096) -> np.ndarray:
    """Create a non-black 12-bit RGGB frame with realistic dimensions."""
    x = np.linspace(0, 2200, width, dtype=np.float32)
    y = np.linspace(0, 900, height, dtype=np.float32)[:, None]
    raw = np.clip(512.0 + x + y, 256, 3836).astype(np.uint16)
    raw[0::2, 0::2] = np.clip(raw[0::2, 0::2] * 1.18, 256, 4095)
    raw[1::2, 1::2] = np.clip(raw[1::2, 1::2] * 0.90, 256, 4095)
    return np.ascontiguousarray(raw)


def write_test_dng(path: Path, storage_bits: int = 12) -> None:
    raw = make_test_raw()
    if storage_bits == 16:
        raw = np.ascontiguousarray(np.left_shift(raw, 4))
        black_level = 256 << 4
        white_level = 4095 << 4
    else:
        black_level = 256
        white_level = 4095
    tags = DNGTags()
    tags.set(Tag.ImageLength, raw.shape[0])
    tags.set(Tag.ImageWidth, raw.shape[1])
    if sys.platform == "win32":
        tags.set(Tag.RowsPerStrip, raw.shape[0])
    else:
        tags.set(Tag.TileLength, raw.shape[0])
        tags.set(Tag.TileWidth, raw.shape[1])
    tags.set(Tag.Orientation, Orientation.Horizontal)
    tags.set(Tag.PhotometricInterpretation, PhotometricInterpretation.Color_Filter_Array)
    tags.set(Tag.SamplesPerPixel, 1)
    tags.set(Tag.BitsPerSample, storage_bits)
    tags.set(Tag.CFARepeatPatternDim, [2, 2])
    tags.set(Tag.CFAPattern, CFAPattern.RGGB)
    tags.set(Tag.BlackLevel, black_level)
    tags.set(Tag.WhiteLevel, white_level)
    tags.set(Tag.ColorMatrix1, CCM)
    tags.set(Tag.CalibrationIlluminant1, CalibrationIlluminant.D65)
    tags.set(Tag.AsShotNeutral, [[500, 1000], [1000, 1000], [619, 1000]])
    tags.set(Tag.BaselineExposure, [[-150, 100]])
    tags.set(Tag.Make, "Camera Brand")
    tags.set(Tag.Model, "Camera Model")
    tags.set(Tag.DNGVersion, DNGVersion.V1_4)
    tags.set(Tag.DNGBackwardVersion, DNGVersion.V1_2)
    tags.set(Tag.PreviewColorSpace, PreviewColorSpace.sRGB)

    writer = RAW2DNG()
    writer.options(tags, path="", compress=False)
    generated = writer.convert(raw, filename=str(path))
    print(f"PiDNG returned: {generated!r}")
    print(f"Generated file: exists={path.is_file()}, size={path.stat().st_size if path.is_file() else 0}")


def postprocess(raw: rawpy.RawPy) -> np.ndarray:
    return raw.postprocess(
        use_camera_wb=True,
        use_auto_wb=False,
        output_color=rawpy.ColorSpace.sRGB,
        output_bps=8,
        no_auto_bright=True,
        gamma=(2.4, 12.92),
    )


def try_read(label: str, opener) -> bool:
    print(f"\n--- {label} ---")
    try:
        with opener() as raw:
            raw_pixels = np.asarray(raw.raw_image_visible)
            print(
                "imread: OK, "
                f"raw size={raw_pixels.shape}, dtype={raw_pixels.dtype}, "
                f"min={int(raw_pixels.min())}, max={int(raw_pixels.max())}, "
                f"mean={float(raw_pixels.mean()):.2f}"
            )
            print(f"white_level: {raw.white_level!r}")
            print(f"black_level_per_channel: {raw.black_level_per_channel!r}")
            print(f"camera_whitebalance: {raw.camera_whitebalance!r}")
            print(f"daylight_whitebalance: {raw.daylight_whitebalance!r}")
            print(f"color_matrix:\n{np.asarray(raw.color_matrix)}")
            rgb = postprocess(raw)
            print(
                "postprocess: OK, "
                f"shape={rgb.shape}, dtype={rgb.dtype}, "
                f"min={int(rgb.min())}, max={int(rgb.max())}, mean={float(rgb.mean()):.2f}"
            )
        if int(rgb.max()) == 0:
            print("RESULT: BLACK IMAGE")
            return False
        return True
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc!r}")
        traceback.print_exc()
        return False


def try_postprocess_variants(path: Path) -> None:
    variants = [
        ("default", {}),
        (
            "camera WB + auto brightness",
            {
                "use_camera_wb": True,
                "use_auto_wb": False,
                "output_color": rawpy.ColorSpace.sRGB,
                "output_bps": 8,
            },
        ),
        (
            "camera WB + no auto brightness (DNGauge)",
            {
                "use_camera_wb": True,
                "use_auto_wb": False,
                "output_color": rawpy.ColorSpace.sRGB,
                "output_bps": 8,
                "no_auto_bright": True,
                "gamma": (2.4, 12.92),
            },
        ),
        (
            "auto WB + auto brightness",
            {
                "use_camera_wb": False,
                "use_auto_wb": True,
                "output_color": rawpy.ColorSpace.sRGB,
                "output_bps": 8,
            },
        ),
        (
            "neutral user WB + raw color",
            {
                "use_camera_wb": False,
                "use_auto_wb": False,
                "user_wb": [1.0, 1.0, 1.0, 1.0],
                "output_color": rawpy.ColorSpace.raw,
                "output_bps": 8,
            },
        ),
    ]

    print("\n--- rawpy.postprocess parameter variants (path string) ---")
    for name, kwargs in variants:
        try:
            with rawpy.imread(str(path.resolve())) as raw:
                rgb = raw.postprocess(**kwargs)
            print(
                f"{name}: OK, min={int(rgb.min())}, max={int(rgb.max())}, "
                f"mean={float(rgb.mean()):.2f}"
            )
        except Exception as exc:
            print(f"{name}: FAILED: {type(exc).__name__}: {exc!r}")


def diagnose(path: Path, title: str) -> tuple[bool, bool]:
    resolved = path.resolve()
    print(f"\n========== {title} ==========")
    print(f"Path: {resolved}")
    print(f"Exists: {resolved.is_file()}")
    if not resolved.is_file():
        return False, False
    print(f"Size: {resolved.stat().st_size}")
    print(f"Path contains non-ASCII: {not str(resolved).isascii()}")

    by_path = try_read("rawpy.imread(path string)", lambda: rawpy.imread(str(resolved)))

    @contextmanager
    def open_via_python_file():
        # rawpy accepts a seekable binary file object. Python handles Windows
        # Unicode paths before LibRaw sees the stream.
        with open(resolved, "rb") as source:
            with rawpy.imread(source) as raw:
                yield raw

    by_file = try_read("rawpy.imread(Python binary file)", open_via_python_file)
    return by_path, by_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dng", nargs="?", help="Optional existing DNG that fails in DNGauge")
    args = parser.parse_args()

    print(f"Python: {sys.version}")
    print(f"Platform: {platform.platform()}")
    print(f"Executable: {sys.executable}")
    print(f"numpy: {np.__version__}")
    print(f"rawpy: {rawpy.__version__}")
    print(f"LibRaw: {getattr(rawpy, 'libraw_version', 'unknown')}")
    print(f"TEMP: {tempfile.gettempdir()}")
    print(f"TEMP contains non-ASCII: {not tempfile.gettempdir().isascii()}")

    with tempfile.TemporaryDirectory(prefix="dng_compare_io_") as temp_dir:
        generated_results = {}
        for storage_bits in (12, 16):
            generated_path = Path(temp_dir) / f"generated_test_{storage_bits}bit.dng"
            print(f"\nGenerating a representative 4096x3072 {storage_bits}-bit DNG...")
            try:
                write_test_dng(generated_path, storage_bits=storage_bits)
            except Exception as exc:
                print(f"PiDNG generation FAILED: {type(exc).__name__}: {exc!r}")
                traceback.print_exc()
                generated_results[storage_bits] = (False, False)
                continue
            generated_results[storage_bits] = diagnose(
                generated_path,
                f"GENERATED {storage_bits}-BIT TEMP DNG",
            )
            try_postprocess_variants(generated_path)

    supplied_result = None
    if args.dng:
        supplied_result = diagnose(Path(args.dng), "SUPPLIED DNG")

    print("\n========== SUMMARY ==========")
    for storage_bits, result in generated_results.items():
        print(f"Generated {storage_bits}-bit DNG (path, file object): {result}")
    if supplied_result is not None:
        print(f"Supplied DNG  (path, file object): {supplied_result}")
    print("Please copy the complete output above when reporting the result.")
    return 0 if any(any(result) for result in generated_results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
