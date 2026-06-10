#!/usr/bin/env python3
"""
Dual-image DNG/RAW compare viewer.
RAW rendering path follows Shotwell's GRaw defaults as closely as rawpy allows.

Reference (Shotwell source):
- src/photos/GRaw.vala::Processor.configure_for_rgb_display()
- src/photos/RawSupport.vala::RawReader
"""

import os
import sys
import tempfile
import concurrent.futures
import ctypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt5.QtGui import QIcon, QImage, QPixmap, QPainter, QTransform, QImageReader
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    import rawpy
except Exception as e:
    raise RuntimeError("需要 rawpy 才能按 Shotwell RAW 链路解码") from e

try:
    from pidng.core import RAW2DNG, DNGTags, Tag
    from pidng.defs import (
        CalibrationIlluminant,
        CFAPattern,
        DNGVersion,
        Orientation,
        PhotometricInterpretation,
        PreviewColorSpace,
    )
    PIDNG_AVAILABLE = True
except Exception:
    PIDNG_AVAILABLE = False

try:
    from PIL import Image
except Exception as e:
    raise RuntimeError("需要 Pillow 读取非 RAW 图片") from e

RAW_EXTS = {
    ".3fr", ".arw", ".srf", ".sr2", ".bay", ".crw", ".cr2", ".cr3", ".cap", ".iiq", ".eip",
    ".dcs", ".dcr", ".drf", ".k25", ".kdc", ".dng", ".erf", ".fff", ".mef", ".mos", ".mrw",
    ".nef", ".nrw", ".orf", ".ptx", ".pef", ".pxn", ".r3d", ".raf", ".raw", ".rw2", ".rwl",
    ".rwz", ".x3f", ".srw",
}
DROP_EXTS = RAW_EXTS | {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


def resource_path(name: str) -> str:
    candidates = []
    meipass_dir = getattr(sys, "_MEIPASS", None)
    if meipass_dir:
        candidates.append(Path(meipass_dir) / name)
    candidates.append(Path(sys.executable).resolve().parent / name)
    candidates.append(Path(__file__).resolve().parent / name)
    candidates.append(Path(__file__).resolve().parent / "packaging" / name)
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[0])


def configure_app_identity() -> None:
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DNGauge")
        except Exception:
            pass

DEFAULT_ADJUSTMENTS = {
    "exposure": 0,
    "contrast": 0,
    "saturation": 0,
    "temperature": 0,
    "tint": 0,
    "highlights": 0,
    "shadows": 0,
}

DNG_STYLE_CCM = np.array(
    [
        [0.6668, -0.1588, -0.0857],
        [-0.5739, 1.3898, 0.1430],
        [-0.1378, 0.2651, 0.6036],
    ],
    dtype=np.float32,
)

DNG_STYLE_CCM_RATIONALS = [
    [+6668, 10000],
    [-1588, 10000],
    [-857, 10000],
    [-5739, 10000],
    [13898, 10000],
    [+1430, 10000],
    [-1378, 10000],
    [+2651, 10000],
    [+6036, 10000],
]


def _slider_style() -> str:
    return """
        QSlider::groove:horizontal {
            height: 6px;
            background: #3a3a3a;
            border-radius: 3px;
            margin: 0 2px;
        }
        QSlider::handle:horizontal {
            width: 14px;
            height: 14px;
            margin: -5px 0;
            background: #888888;
            border-radius: 7px;
        }
        QSlider::handle:horizontal:hover {
            background: #aaaaaa;
        }
        QSlider::sub-page:horizontal {
            background: #4a6a9a;
            border-radius: 3px;
        }
    """


def _btn_style() -> str:
    return """
        QPushButton {
            background-color: #3a3a3a;
            color: #cccccc;
            border: 1px solid #4a4a4a;
            border-radius: 4px;
            padding: 6px 12px;
            font-size: 13px;
        }
        QPushButton:hover {
            background-color: #4a4a4a;
            border-color: #5a5a5a;
        }
        QPushButton:pressed {
            background-color: #555555;
        }
    """


def _btn_style_checked() -> str:
    return """
        QPushButton {
            background-color: #3a6a4a;
            color: white;
            border: 1px solid #4a7a5a;
            border-radius: 4px;
            padding: 6px 12px;
            font-size: 13px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #4a7a5a;
        }
    """


def _hermite_gamma(x, upper=1.0):
    r = np.zeros_like(x, dtype=np.float64)
    m = (x >= 0) & (x <= upper)
    xi = x[m] / upper
    r[m] = 6.0 * (xi * xi * xi - 2.0 * xi * xi + xi)
    return np.clip(r, 0.0, 1.0)


def _shadow_detail(v, param):
    if param <= 0:
        return v
    adj = min(param / 32.0, 1.0)
    shift = 0.5 * adj
    w = _hermite_gamma(v, 1.0)
    return w * (v + shift) + (1 - w) * v


def _highlight_detail(v, param):
    if param >= 0:
        return v
    adj = min(param / (-32.0), 1.0)
    shift = 0.5 * adj
    w = _hermite_gamma(1 - v, 1.0)
    return w * (v - shift) + (1 - w) * v


def _build_rgb_matrix(sw_exp, sw_ctr, sw_sat, sw_temp, sw_tint):
    m = np.eye(4, dtype=np.float64)
    if sw_temp != 0.0:
        ap = (sw_temp / 16) * 0.33
        mt = np.eye(4, dtype=np.float64)
        mt[2, 3] -= ap
        mt[1, 3] += ap / 2
        mt[0, 3] += ap / 2
        m = mt @ m
    if sw_tint != 0.0:
        ap = (sw_tint / 16) * 0.25
        mt = np.eye(4, dtype=np.float64)
        mt[2, 3] -= ap / 2
        mt[1, 3] += ap
        mt[0, 3] -= ap / 2
        m = mt @ m
    if sw_sat != 0.0:
        ap = (sw_sat / 16) + 1.0
        ot = 1 - ap
        t3 = 1 / 3
        ms = np.eye(4, dtype=np.float64)
        ms[0, :3] = [ot * t3 + ap, ot * t3, ot * t3]
        ms[1, :3] = [ot * t3, ot * t3 + ap, ot * t3]
        ms[2, :3] = [ot * t3, ot * t3, ot * t3 + ap]
        m = ms @ m
    if sw_exp != 0.0:
        adj = ((sw_exp + 16) / 32) + 0.5
        me = np.diag([adj, adj, adj, 1]).astype(np.float64)
        m = me @ m
    if sw_ctr != 0.0:
        ca = (sw_ctr / 16) * 0.5
        coe = 1 + ca
        off = ca / -2
        mc = np.eye(4, dtype=np.float64)
        mc[[0, 1, 2], [0, 1, 2]] = coe
        mc[[0, 1, 2], 3] = off
        m = mc @ m
    return m


def apply_adjustments(baseline_rgb: np.ndarray, params: dict) -> np.ndarray:
    img = baseline_rgb.astype(np.float32) / 255.0
    sw_exp = params.get("exposure", 0) * 16 / 100
    sw_ctr = params.get("contrast", 0) * 16 / 100
    sw_sat = params.get("saturation", 0) * 16 / 100
    sw_temp = params.get("temperature", 0) * 16 / 100
    sw_tint = params.get("tint", 0) * 16 / 100
    sw_sh = max(params.get("shadows", 0), 0) * 32 / 100
    sw_hl = min(params.get("highlights", 0), 0) * 32 / 100

    r, g, b = img[..., 0].copy(), img[..., 1].copy(), img[..., 2].copy()
    v = np.maximum(np.maximum(r, g), b)
    if sw_sh > 0:
        vn = _shadow_detail(v, sw_sh)
        sv = np.where(v > 1e-8, v, 1e-8)
        r *= vn / sv
        g *= vn / sv
        b *= vn / sv
        v = vn
    if sw_hl < 0:
        vn = _highlight_detail(v, sw_hl)
        sv = np.where(v > 1e-8, v, 1e-8)
        r *= vn / sv
        g *= vn / sv
        b *= vn / sv

    mat = _build_rgb_matrix(sw_exp, sw_ctr, sw_sat, sw_temp, sw_tint)
    ro = mat[0, 0] * r + mat[0, 1] * g + mat[0, 2] * b + mat[0, 3]
    go = mat[1, 0] * r + mat[1, 1] * g + mat[1, 2] * b + mat[1, 3]
    bo = mat[2, 0] * r + mat[2, 1] * g + mat[2, 2] * b + mat[2, 3]
    return np.clip(np.stack([ro, go, bo], axis=-1) * 255.0, 0, 255).astype(np.uint8)


def rgb_to_qimage(rgb: np.ndarray) -> QImage:
    if rgb.dtype != np.uint8:
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    if not rgb.flags["C_CONTIGUOUS"]:
        rgb = np.ascontiguousarray(rgb)
    h, w, _ = rgb.shape
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
    return qimg.copy()


def qimage_to_rgb_array(qimg: QImage) -> np.ndarray:
    img = qimg.convertToFormat(QImage.Format_RGB888)
    w = img.width()
    h = img.height()
    bpl = img.bytesPerLine()
    ptr = img.bits()
    ptr.setsize(h * bpl)
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, bpl)
    return np.ascontiguousarray(arr[:, : w * 3].reshape(h, w, 3))


def fit_dimensions(full_w: int, full_h: int, target_w: int, target_h: int) -> tuple[int, int]:
    if full_w <= 0 or full_h <= 0 or target_w <= 0 or target_h <= 0:
        return max(1, full_w), max(1, full_h)
    scale = min(target_w / float(full_w), target_h / float(full_h), 1.0)
    return max(1, int(round(full_w * scale))), max(1, int(round(full_h * scale)))


def raw_to_display_rgb(
    raw: np.ndarray,
    display_bits: Optional[int] = None,
    black_level: float = 0.0,
    white_level: Optional[float] = None,
    exposure_gain: float = 1.0,
) -> np.ndarray:
    arr = raw.astype(np.float32)
    if display_bits is not None and 1 <= int(display_bits) <= 16:
        hi_default = float((1 << int(display_bits)) - 1)
        lo = float(max(0.0, black_level))
        hi = float(hi_default if white_level is None else max(lo + 1.0, white_level))
        norm = np.clip((arr - lo) / max(1.0, (hi - lo)), 0.0, 1.0)
        norm = np.clip(norm * float(max(0.01, exposure_gain)), 0.0, 1.0)
    else:
        lo = float(np.percentile(arr, 1.0))
        hi = float(np.percentile(arr, 99.5))
        if hi <= lo:
            lo = float(arr.min())
            hi = float(arr.max()) if float(arr.max()) > lo else lo + 1.0
        norm = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
    g = (norm * 255.0).astype(np.uint8)
    return np.stack([g, g, g], axis=-1)


def dng_style_linear_rgb_to_srgb(
    rgb: np.ndarray,
    black_level: float,
    white_level: float,
    exposure_gain: float,
    wb: tuple[float, float, float],
) -> np.ndarray:
    lo = float(max(0.0, black_level))
    hi = float(max(lo + 1.0, white_level))
    arr = np.clip((rgb - lo) / max(1.0, hi - lo), 0.0, 1.0)
    arr = np.clip(arr * float(max(0.01, exposure_gain)), 0.0, 1.0)
    gains = np.array(wb, dtype=np.float32)
    gains = np.where(gains > 1e-6, gains, 1.0)
    arr *= gains.reshape(1, 1, 3)
    arr = arr @ DNG_STYLE_CCM.T
    arr *= np.float32(2.0 ** -1.5)
    arr = np.clip(arr, 0.0, 1.0)
    srgb = np.where(arr <= 0.0031308, arr * 12.92, 1.055 * np.power(arr, 1.0 / 2.4) - 0.055)
    return np.clip(srgb * 255.0, 0, 255).astype(np.uint8)


def _pattern_to_pidng(pattern: str):
    if not PIDNG_AVAILABLE:
        return None
    return {
        "RGGB": CFAPattern.RGGB,
        "BGGR": CFAPattern.BGGR,
        "GRBG": CFAPattern.GRBG,
        "GBRG": CFAPattern.GBRG,
    }.get(str(pattern).upper(), CFAPattern.RGGB)


def _wb_to_as_shot_neutral(wb_enabled: bool, wb: tuple[float, float, float]):
    if not wb_enabled:
        return [[1000, 1000], [1000, 1000], [1000, 1000]]
    gains = np.array(wb, dtype=np.float64)
    gains = np.where(gains > 1e-6, gains, 1.0)
    neutral = 1.0 / gains
    neutral = np.clip(neutral, 1e-6, 64.0)
    return [[int(round(v * 1000.0)), 1000] for v in neutral.tolist()]


def _plain_raw_temp_dng_to_rgb(
    raw: np.ndarray,
    pattern: str,
    bit: int,
    black_level: float,
    white_level: float,
    wb_enabled: bool,
    wb: tuple[float, float, float],
) -> Optional[np.ndarray]:
    if not PIDNG_AVAILABLE:
        return None

    bits_per_sample = max(1, min(16, int(bit)))
    tag_white = int(max(1.0, min(float((1 << bits_per_sample) - 1), float(white_level))))
    tag_black = int(max(0.0, min(float(tag_white - 1), float(black_level))))

    tags = DNGTags()
    tags.set(Tag.ImageLength, int(raw.shape[0]))
    tags.set(Tag.ImageWidth, int(raw.shape[1]))
    tags.set(Tag.TileLength, int(raw.shape[0]))
    tags.set(Tag.TileWidth, int(raw.shape[1]))
    tags.set(Tag.Orientation, Orientation.Horizontal)
    tags.set(Tag.PhotometricInterpretation, PhotometricInterpretation.Color_Filter_Array)
    tags.set(Tag.SamplesPerPixel, 1)
    tags.set(Tag.BitsPerSample, bits_per_sample)
    tags.set(Tag.CFARepeatPatternDim, [2, 2])
    tags.set(Tag.CFAPattern, _pattern_to_pidng(pattern))
    tags.set(Tag.BlackLevel, tag_black)
    tags.set(Tag.WhiteLevel, tag_white)
    tags.set(Tag.ColorMatrix1, DNG_STYLE_CCM_RATIONALS)
    tags.set(Tag.CalibrationIlluminant1, CalibrationIlluminant.D65)
    tags.set(Tag.AsShotNeutral, _wb_to_as_shot_neutral(wb_enabled, wb))
    tags.set(Tag.BaselineExposure, [[-150, 100]])
    tags.set(Tag.Make, "Camera Brand")
    tags.set(Tag.Model, "Camera Model")
    tags.set(Tag.DNGVersion, DNGVersion.V1_4)
    tags.set(Tag.DNGBackwardVersion, DNGVersion.V1_2)
    tags.set(Tag.PreviewColorSpace, PreviewColorSpace.sRGB)

    fd, tmp_path = tempfile.mkstemp(prefix="dng_compare_", suffix=".dng", dir="/tmp")
    os.close(fd)
    try:
        writer = RAW2DNG()
        writer.options(tags, path="", compress=False)
        writer.convert(raw, filename=tmp_path)
        rgb, _raw_info = ShotwellRawDecoder._load_raw(tmp_path, target_size=None)
        return rgb
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


def render_plain_raw_with_matrix(
    raw: np.ndarray,
    pattern: str,
    black_level: float,
    white_level: float,
    exposure_gain: float,
    wb_enabled: bool,
    wb: tuple[float, float, float],
    prefer_temp_dng: bool = True,
    bit: Optional[int] = None,
) -> np.ndarray:
    if prefer_temp_dng and PIDNG_AVAILABLE:
        rgb = _plain_raw_temp_dng_to_rgb(
            raw,
            pattern=pattern,
            bit=(bit if bit is not None else int(np.ceil(np.log2(max(2.0, float(white_level) + 1.0))))),
            black_level=black_level,
            white_level=white_level,
            wb_enabled=wb_enabled,
            wb=wb,
        )
        if rgb is not None:
            return rgb

    linear_rgb, _cfa = ShotwellRawDecoder._demosaic_bilinear_linear(raw, pattern)
    gains = wb if wb_enabled else (1.0, 1.0, 1.0)
    return dng_style_linear_rgb_to_srgb(
        linear_rgb,
        black_level=black_level,
        white_level=white_level,
        exposure_gain=exposure_gain,
        wb=gains,
    )


def render_raw_all_source_rgb(
    base_rgb: np.ndarray,
    raw_info: Optional[dict],
    display_bits: int,
    black_level: float,
    white_level: float,
    exposure_gain: float,
    wb_enabled: bool,
    wb: tuple[float, float, float],
) -> np.ndarray:
    if raw_info is None:
        return base_rgb
    if raw_info.get("plain_raw"):
        raw = raw_info.get("raw")
        pattern = raw_info.get("pattern", "RGGB")
        if raw is not None:
            return render_plain_raw_with_matrix(
                raw,
                str(pattern).upper(),
                black_level=black_level,
                white_level=white_level,
                exposure_gain=exposure_gain,
                wb_enabled=wb_enabled,
                wb=wb,
                bit=int(raw_info.get("bit", display_bits)),
            )
    src = base_rgb
    if wb_enabled:
        src = apply_wb_rgb(src, wb)
    return apply_levels_exposure_rgb(src, display_bits, black_level, white_level, exposure_gain)


def raw_channel_to_display_rgb(
    raw: np.ndarray,
    cfa: np.ndarray,
    desc: str,
    mode: str,
    display_bits: Optional[int] = None,
    black_level: float = 0.0,
    white_level: Optional[float] = None,
    exposure_gain: float = 1.0,
) -> np.ndarray:
    mode = mode.upper()
    if mode == "ALL":
        return raw_to_display_rgb(raw, display_bits, black_level, white_level, exposure_gain)

    h, w = raw.shape
    desc = desc or "RGBG"
    mask = np.zeros((h, w), dtype=bool)

    if mode in ("R", "B"):
        for i in range(min(len(desc), 8)):
            if desc[i].upper() == mode:
                mask |= (cfa == i)
    elif mode in ("G1", "G2"):
        gmask = np.zeros((h, w), dtype=bool)
        for i in range(min(len(desc), 8)):
            if desc[i].upper() == "G":
                gmask |= (cfa == i)
        yy = np.indices((h, w))[0]
        mask = gmask & ((yy % 2 == 0) if mode == "G1" else (yy % 2 == 1))
    else:
        return raw_to_display_rgb(raw, display_bits, black_level, white_level, exposure_gain)

    if not np.any(mask):
        return raw_to_display_rgb(raw, display_bits, black_level, white_level, exposure_gain)

    sel = np.zeros_like(raw, dtype=raw.dtype)
    sel[mask] = raw[mask]
    return raw_to_display_rgb(sel, display_bits, black_level, white_level, exposure_gain)


def apply_wb_rgb(rgb: np.ndarray, gains: tuple[float, float, float]) -> np.ndarray:
    r_gain, g_gain, b_gain = gains
    arr = rgb.astype(np.float32)
    arr[..., 0] *= float(r_gain)
    arr[..., 1] *= float(g_gain)
    arr[..., 2] *= float(b_gain)
    return np.clip(arr, 0, 255).astype(np.uint8)


def apply_levels_exposure_rgb(
    rgb: np.ndarray, bit: int, black_level: float, white_level: float, exposure_gain: float
) -> np.ndarray:
    maxv = float((1 << max(1, min(16, int(bit)))) - 1)
    lo = float(max(0.0, black_level)) / maxv
    hi = float(max(black_level + 1.0, white_level)) / maxv
    arr = rgb.astype(np.float32) / 255.0
    arr = np.clip((arr - lo) / max(1e-6, (hi - lo)), 0.0, 1.0)
    arr = np.clip(arr * float(max(0.01, exposure_gain)), 0.0, 1.0)
    return (arr * 255.0).astype(np.uint8)


def fast_preview_adjust(base_rgb: np.ndarray, params: dict) -> np.ndarray:
    """快速预览：先降采样计算，再放大回原尺寸。"""
    h, w = base_rgb.shape[:2]
    pixels = h * w
    if pixels <= 1_200_000:
        return apply_adjustments(base_rgb, params)
    step = 2 if pixels <= 8_000_000 else 3
    small = base_rgb[::step, ::step]
    out_small = apply_adjustments(small, params)
    out = out_small.repeat(step, axis=0).repeat(step, axis=1)
    return out[:h, :w]


@dataclass
class ViewState:
    zoom: float
    x_ratio: float
    y_ratio: float


class ShotwellRawDecoder:
    """Shotwell-like RAW decode, aligned to GRaw.configure_for_rgb_display()."""

    @staticmethod
    def _rawpy_kwargs(half_size: bool = False):
        k = {
            "bright": 1.0,
            "half_size": half_size,
            "use_auto_wb": True,
            "use_camera_wb": True,
            "output_color": getattr(rawpy.ColorSpace, "sRGB", None),
            "output_bps": 8,
            "no_auto_bright": True,
            "auto_bright_thr": 0.01,
            "gamma": (2.4, 12.92),
        }

        # GRaw: use_camera_matrix = EMBEDDED_COLOR_PROFILE (best-effort mapping)
        if "use_camera_matrix" in getattr(rawpy.Params, "__annotations__", {}) or hasattr(rawpy, "UseCameraMatrix"):
            k["use_camera_matrix"] = True

        # GRaw: user_flip = FROM_SOURCE
        uf = getattr(rawpy, "UserFlip", None)
        if uf is not None:
            for name in ("CameraDefault", "FromSource", "FROM_SOURCE"):
                if hasattr(uf, name):
                    k["user_flip"] = getattr(uf, name)
                    break

        # GRaw: user_qual = PPG
        da = getattr(rawpy, "DemosaicAlgorithm", None)
        if da is not None:
            for name in ("PPG", "AHD"):
                if hasattr(da, name):
                    k["demosaic_algorithm"] = getattr(da, name)
                    break

        # GRaw: highlight = CLIP
        hm = getattr(rawpy, "HighlightMode", None)
        if hm is not None:
            for name in ("Clip", "CLIP"):
                if hasattr(hm, name):
                    k["highlight_mode"] = getattr(hm, name)
                    break

        # Some rawpy versions reject None enum values.
        return {kk: vv for kk, vv in k.items() if vv is not None}

    @classmethod
    def load(
        cls,
        path: str,
        target_size: Optional[tuple[int, int]] = None,
        plain_raw_cfg: Optional[dict] = None
    ) -> tuple[np.ndarray, Optional[dict]]:
        ext = Path(path).suffix.lower()
        if ext == ".raw" and plain_raw_cfg is not None:
            return cls._load_plain_raw(path, plain_raw_cfg)
        if ext in RAW_EXTS:
            return cls._load_raw(path, target_size=target_size)
        return cls._load_regular(path, target_size=target_size)

    @staticmethod
    def _shift_with_zero(arr: np.ndarray, dy: int, dx: int) -> np.ndarray:
        h, w = arr.shape
        out = np.zeros_like(arr)
        ys = slice(max(0, dy), min(h, h + dy))
        yt = slice(max(0, -dy), min(h, h - dy))
        xs = slice(max(0, dx), min(w, w + dx))
        xt = slice(max(0, -dx), min(w, w - dx))
        out[ys, xs] = arr[yt, xt]
        return out

    @classmethod
    def _demosaic_bilinear(cls, raw: np.ndarray, pattern: str) -> np.ndarray:
        rgb, cfa = cls._demosaic_bilinear_linear(raw, pattern)
        lo = np.percentile(rgb, 1.0)
        hi = np.percentile(rgb, 99.5)
        if hi <= lo:
            hi = lo + 1.0
        rgb = np.clip((rgb - lo) / (hi - lo), 0.0, 1.0)
        rgb = (rgb * 255.0).astype(np.uint8)
        return rgb, cfa

    @classmethod
    def _demosaic_bilinear_linear(cls, raw: np.ndarray, pattern: str) -> tuple[np.ndarray, np.ndarray]:
        pattern = pattern.upper()
        idx = {"R": 0, "G": 1, "B": 2}
        p = [[idx[pattern[0]], idx[pattern[1]]], [idx[pattern[2]], idx[pattern[3]]]]
        h, w = raw.shape
        cfa = np.zeros((h, w), dtype=np.uint8)
        cfa[0::2, 0::2] = p[0][0]
        cfa[0::2, 1::2] = p[0][1]
        cfa[1::2, 0::2] = p[1][0]
        cfa[1::2, 1::2] = p[1][1]

        chans = []
        rf = raw.astype(np.float32)
        for ci in (0, 1, 2):
            m = (cfa == ci).astype(np.float32)
            v = rf * m
            s = np.zeros_like(rf, dtype=np.float32)
            c = np.zeros_like(rf, dtype=np.float32)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    s += cls._shift_with_zero(v, dy, dx)
                    c += cls._shift_with_zero(m, dy, dx)
            chans.append(s / np.maximum(c, 1e-6))

        rgb = np.stack(chans, axis=-1)
        return rgb, cfa

    @staticmethod
    def _unpack_mipi10(buf: np.ndarray, width: int, height: int) -> np.ndarray:
        stride = (width * 10 + 7) // 8
        need = stride * height
        if buf.size < need:
            raise ValueError("RAW10 数据长度不足")
        buf = buf[:need].reshape(height, stride)
        out = np.zeros((height, width), dtype=np.uint16)
        groups = width // 4
        for y in range(height):
            row = buf[y]
            for g in range(groups):
                b0, b1, b2, b3, b4 = row[g * 5:g * 5 + 5]
                x = g * 4
                out[y, x + 0] = (int(b0) << 2) | (int(b4) & 0x03)
                out[y, x + 1] = (int(b1) << 2) | ((int(b4) >> 2) & 0x03)
                out[y, x + 2] = (int(b2) << 2) | ((int(b4) >> 4) & 0x03)
                out[y, x + 3] = (int(b3) << 2) | ((int(b4) >> 6) & 0x03)
        return out

    @staticmethod
    def _unpack_mipi12(buf: np.ndarray, width: int, height: int) -> np.ndarray:
        stride = (width * 12 + 7) // 8
        need = stride * height
        if buf.size < need:
            raise ValueError("RAW12 数据长度不足")
        buf = buf[:need].reshape(height, stride)
        out = np.zeros((height, width), dtype=np.uint16)
        pairs = width // 2
        for y in range(height):
            row = buf[y]
            for p in range(pairs):
                b0, b1, b2 = row[p * 3:p * 3 + 3]
                x = p * 2
                out[y, x + 0] = (int(b0) << 4) | (int(b2) & 0x0F)
                out[y, x + 1] = (int(b1) << 4) | ((int(b2) >> 4) & 0x0F)
        return out

    @classmethod
    def _load_plain_raw(cls, path: str, cfg: dict) -> tuple[np.ndarray, Optional[dict]]:
        w = int(cfg["width"])
        h = int(cfg["height"])
        bit = int(cfg["bit"])
        pattern = str(cfg["pattern"]).upper()
        packing = str(cfg["packing"]).lower()
        if pattern not in {"RGGB", "BGGR", "GRBG", "GBRG"}:
            raise ValueError("Bayer pattern 仅支持 RGGB/BGGR/GRBG/GBRG")

        buf = np.fromfile(path, dtype=np.uint8)
        if packing == "mipi10":
            raw = cls._unpack_mipi10(buf, w, h)
        elif packing == "mipi12":
            raw = cls._unpack_mipi12(buf, w, h)
        elif packing == "u8":
            need = w * h
            if buf.size < need:
                raise ValueError("u8 RAW 数据长度不足")
            raw = buf[:need].reshape(h, w).astype(np.uint16)
        else:  # u16 / default
            u16 = np.fromfile(path, dtype="<u2")
            need = w * h
            if u16.size < need:
                raise ValueError("u16 RAW 数据长度不足")
            raw = u16[:need].reshape(h, w)

        mask = (1 << bit) - 1 if 1 <= bit <= 16 else 0xFFFF
        raw = (raw & mask).astype(np.uint16)
        _linear_rgb, cfa = cls._demosaic_bilinear_linear(raw, pattern)
        white_level = int(mask)
        rgb = render_plain_raw_with_matrix(
            raw,
            pattern=pattern,
            black_level=0,
            white_level=white_level,
            exposure_gain=1.0,
            wb_enabled=False,
            wb=(1.0, 1.0, 1.0),
            bit=bit,
        )
        raw_info = {
            "raw": raw,
            "cfa": cfa,
            "desc": "RGB",
            "bit": bit,
            "black_level": 0,
            "white_level": white_level,
            "pattern": pattern,
            "plain_raw": True,
        }
        return np.ascontiguousarray(rgb), raw_info

    @classmethod
    def _load_raw(cls, path: str, target_size: Optional[tuple[int, int]] = None) -> tuple[np.ndarray, Optional[dict]]:
        with rawpy.imread(path) as raw:
            # 为了与 Shotwell 在单图查看时的放大范围一致，这里固定用 full-size 解码。
            # 否则 half_size 会让源分辨率减半，导致“最大缩放看起来不够近”。 
            half_size = False
            rgb = raw.postprocess(**cls._rawpy_kwargs(half_size=half_size))
            raw_visible = np.ascontiguousarray(raw.raw_image_visible.copy())
            cfa_visible = np.ascontiguousarray(raw.raw_colors_visible.copy())
            desc = getattr(raw, "color_desc", b"RGBG")
            if isinstance(desc, bytes):
                try:
                    desc = desc.decode("ascii", errors="ignore")
                except Exception:
                    desc = "RGBG"
            wl = getattr(raw, "white_level", None)
            bit = int(np.ceil(np.log2(max(2, int(wl) + 1)))) if wl is not None else 16
            bit = max(1, min(16, bit))
            raw_info = {"raw": raw_visible, "cfa": cfa_visible, "desc": str(desc), "bit": bit}

        return np.ascontiguousarray(rgb.astype(np.uint8, copy=False)), raw_info

    @staticmethod
    def _load_regular(
        path: str, target_size: Optional[tuple[int, int]] = None
    ) -> tuple[np.ndarray, Optional[dict]]:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        full_size = reader.size()

        if target_size is not None and full_size.isValid():
            target_w = max(1, int(target_size[0]))
            target_h = max(1, int(target_size[1]))
            scaled_w, scaled_h = fit_dimensions(
                max(1, full_size.width()),
                max(1, full_size.height()),
                target_w,
                target_h,
            )

            if (full_size.width() > 9999 or full_size.height() > 9999) and (scaled_w < 100 or scaled_h < 100):
                prefetch_w, prefetch_h = fit_dimensions(
                    max(1, full_size.width()),
                    max(1, full_size.height()),
                    1000,
                    1000,
                )
                reader.setScaledSize(QSize(prefetch_w, prefetch_h))
                prefetched = reader.read()
                if not prefetched.isNull():
                    downsampled = prefetched.scaled(
                        scaled_w, scaled_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
                    )
                    return qimage_to_rgb_array(downsampled), None
                reader = QImageReader(path)
                reader.setAutoTransform(True)

            if (scaled_w, scaled_h) != (full_size.width(), full_size.height()):
                reader.setScaledSize(QSize(scaled_w, scaled_h))

        qimg = reader.read()
        if not qimg.isNull():
            return qimage_to_rgb_array(qimg), None

        with Image.open(path) as img:
            arr = np.array(img.convert("RGB"), dtype=np.uint8)
        return np.ascontiguousarray(arr), None


class SyncView(QGraphicsView):
    state_changed = pyqtSignal(object)
    pixel_picked = pyqtSignal(object)
    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        # Shotwell scaled_read() 最终 resize 使用 BILINEAR；这里用 Smooth 更接近
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene().addItem(self.item)
        self.overlay_item = QGraphicsPixmapItem()
        self.overlay_item.setTransformationMode(Qt.SmoothTransformation)
        self.overlay_item.setZValue(10)
        self.overlay_item.setVisible(False)
        self.scene().addItem(self.overlay_item)

        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        # 稳定性优先：避免大图高倍率时的高开销插值导致崩溃
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)

        self._suppress = False
        self._interp = 0.0
        self._probe_enabled = False
        self._in_resize = False
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._finish_resize_update)

        self.horizontalScrollBar().valueChanged.connect(self._emit_state)
        self.verticalScrollBar().valueChanged.connect(self._emit_state)

    def has_image(self):
        return not self.item.pixmap().isNull()

    def set_image(self, qimg: QImage, fit: bool = False):
        self.item.setPixmap(QPixmap.fromImage(qimg))
        self.scene().setSceneRect(self.item.boundingRect())
        self.overlay_item.setPos(0, 0)
        self.resetTransform()
        self._interp = 0.0
        if fit:
            self.fitInView(self.item, Qt.KeepAspectRatio)
        self._emit_state()

    def set_overlay_pixmap(self, pixmap: QPixmap):
        self.overlay_item.setPixmap(pixmap)
        self.overlay_item.setPos(0, 0)
        self.overlay_item.setVisible(True)

    def clear_overlay(self):
        self.overlay_item.setVisible(False)

    def set_probe_enabled(self, enabled: bool):
        self._probe_enabled = enabled
        if enabled:
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(Qt.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.unsetCursor()

    def set_initial_no_upscale_full_view(self):
        """
        初始显示策略：
        - 小图：保持 1:1（原始大小）
        - 大图：仅缩小到刚好全图可见（不放大）
        """
        if not self.has_image():
            return
        # Shotwell 默认最小缩放档（slider=0）
        self._interp = 0.0
        self._apply_zoom_from_interp()
        self._emit_state()

    def set_one_to_one(self):
        if not self.has_image():
            return
        self._interp = self._interp_for_zoom(1.0)
        self._apply_zoom_from_interp()
        self._emit_state()

    def fit_image(self):
        if not self.has_image():
            return
        self._interp = 0.0
        self._apply_zoom_from_interp()
        self._emit_state()

    def wheelEvent(self, event):
        if not self.has_image():
            return
        # Shotwell: 每格 0.1 的 interpolation 增量
        step = 0.1 if event.angleDelta().y() > 0 else -0.1
        self._interp = self._snap_interp(self._interp + step)
        self._apply_zoom_from_interp()
        self._emit_state()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # 避免窗口放大/全屏时触发大量同步事件导致卡死
        self._in_resize = True
        self._resize_timer.start(80)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self._emit_state()

    def mousePressEvent(self, event):
        if self._probe_enabled and event.button() == Qt.LeftButton:
            self._pick_pixel(event.pos())
            event.accept()
            return
        super().mousePressEvent(event)

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if not md or not md.hasUrls():
            event.ignore()
            return
        for url in md.urls():
            if not url.isLocalFile():
                continue
            p = url.toLocalFile()
            if os.path.isfile(p) and Path(p).suffix.lower() in DROP_EXTS:
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        md = event.mimeData()
        if not md or not md.hasUrls():
            event.ignore()
            return
        for url in md.urls():
            if not url.isLocalFile():
                continue
            p = url.toLocalFile()
            if os.path.isfile(p) and Path(p).suffix.lower() in DROP_EXTS:
                self.file_dropped.emit(p)
                event.acceptProposedAction()
                return
        event.ignore()

    def _emit_state(self):
        if self._suppress or self._in_resize or not self.has_image():
            return
        h = self.horizontalScrollBar()
        v = self.verticalScrollBar()
        xr = 0.0 if h.maximum() <= 0 else h.value() / h.maximum()
        yr = 0.0 if v.maximum() <= 0 else v.value() / v.maximum()
        self.state_changed.emit(ViewState(self.transform().m11(), xr, yr))

    def apply_state(self, s: ViewState):
        if not self.has_image():
            return
        self._suppress = True
        try:
            target = self._clamp_zoom(s.zoom)
            self._interp = self._interp_for_zoom(target)
            self._apply_zoom_from_interp()
            h = self.horizontalScrollBar()
            v = self.verticalScrollBar()
            if h.maximum() > 0:
                h.setValue(int(s.x_ratio * h.maximum()))
            if v.maximum() > 0:
                v.setValue(int(s.y_ratio * v.maximum()))
        finally:
            self._suppress = False

    def _snap_interp(self, interp: float) -> float:
        interp = max(0.0, min(1.0, interp))
        if interp < 0.03:
            return 0.0
        if interp > 0.97:
            return 1.0
        return interp

    def _min_factor(self) -> float:
        pix = self.item.pixmap()
        iw, ih = pix.width(), pix.height()
        vw, vh = self.viewport().width(), self.viewport().height()
        if iw <= 0 or ih <= 0 or vw <= 0 or vh <= 0:
            return 1.0
        min_factor = min(vw / float(iw), vh / float(ih))
        return min(1.0, min_factor)

    @staticmethod
    def _max_factor() -> float:
        # Shotwell ZoomState.compute_zoom_factors(): max_factor = 2.0
        return 2.0

    def _zoom_for_interp(self, interp: float) -> float:
        mn = self._min_factor()
        mx = self._max_factor()
        if mn <= 0:
            return 1.0
        return mn * ((mx / mn) ** interp)

    def _interp_for_zoom(self, zoom: float) -> float:
        mn = self._min_factor()
        mx = self._max_factor()
        zoom = self._clamp_zoom(zoom)
        if mn <= 0 or mx <= mn:
            return 0.0
        return self._snap_interp(np.log(zoom / mn) / np.log(mx / mn))

    def _clamp_zoom(self, zoom: float) -> float:
        mn = self._min_factor()
        mx = self._max_factor()
        return max(mn, min(mx, zoom))

    def _apply_zoom_from_interp(self):
        target = self._zoom_for_interp(self._interp)
        # 用绝对变换，避免反复 scale() 累积误差/极端比例导致的不稳定
        self.setTransform(QTransform.fromScale(target, target))

    def _pick_pixel(self, pos):
        if not self.has_image():
            return
        scene_pt = self.mapToScene(pos)
        x = int(scene_pt.x())
        y = int(scene_pt.y())

        src_item = self.overlay_item if self.overlay_item.isVisible() else self.item
        pm = src_item.pixmap()
        if pm.isNull():
            return
        if x < 0 or y < 0 or x >= pm.width() or y >= pm.height():
            return
        img = pm.toImage().convertToFormat(QImage.Format_RGB888)
        c = img.pixelColor(x, y)
        self.pixel_picked.emit({
            "x": x,
            "y": y,
            "r": c.red(),
            "g": c.green(),
            "b": c.blue(),
            "dtype": "uint8",
        })

    def _finish_resize_update(self):
        self._in_resize = False
        if self.has_image():
            # Shotwell 逻辑：窗口变化后保持同一缩放档位
            self._apply_zoom_from_interp()
        self._emit_state()


class Pane(QWidget):
    state_changed = pyqtSignal(object)
    pixel_picked = pyqtSignal(object)
    file_dropped = pyqtSignal(str)

    def __init__(self, title: str):
        super().__init__()
        self.t = QLabel(title)
        self.p = QLabel("未加载")
        self.p.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.v = SyncView()
        self.source_path: Optional[str] = None
        self.base_rgb: Optional[np.ndarray] = None
        self.raw_info: Optional[dict] = None
        self.params = dict(DEFAULT_ADJUSTMENTS)
        self.raw_channel_mode = "ALL"
        self.raw_display_bits = 16
        self.raw_black_level = 0
        self.raw_white_level = (1 << 16) - 1
        self.raw_exposure_gain = 1.0
        self.raw_wb_enabled = False
        self.raw_wb = (1.0, 1.0, 1.0)
        self.render_request_id = 0

        lay = QVBoxLayout(self)
        lay.addWidget(self.t)
        lay.addWidget(self.p)
        lay.addWidget(self.v, 1)

        self.v.state_changed.connect(self.state_changed)
        self.v.pixel_picked.connect(self.pixel_picked)
        self.v.file_dropped.connect(self.file_dropped)

    def set_baseline(self, path: str, rgb: np.ndarray, raw_info: Optional[dict] = None):
        self.source_path = path
        self.p.setText(path)
        self.base_rgb = np.ascontiguousarray(rgb.astype(np.uint8, copy=False))
        self.raw_info = raw_info
        if self.raw_info is not None:
            self.raw_display_bits = int(self.raw_info.get("bit", 16))
            maxv = (1 << max(1, min(16, int(self.raw_display_bits)))) - 1
            self.raw_black_level = int(self.raw_info.get("black_level", 0))
            self.raw_white_level = int(self.raw_info.get("white_level", maxv))
            self.raw_exposure_gain = 1.0
            self.raw_wb_enabled = False
            self.raw_wb = (1.0, 1.0, 1.0)
        self.params = dict(DEFAULT_ADJUSTMENTS)
        self.render_current(reset_view=True)

    def supports_raw_controls(self) -> bool:
        if self.raw_info is None:
            return False
        if not self.source_path:
            return False
        return Path(self.source_path).suffix.lower() != ".dng"

    def raw_controls_unavailable_reason(self) -> str:
        if self.supports_raw_controls():
            return ""
        if not self.source_path:
            return "未加载 RAW 图"
        ext = Path(self.source_path).suffix.lower()
        if ext:
            return f"{ext[1:].upper()} 不支持 RAW 调参"
        return "当前图像不支持 RAW 调参"

    def render_current(self, reset_view: bool = False):
        if self.base_rgb is None:
            return
        if self.raw_info is not None and self.raw_channel_mode != "ALL":
            raw = self.raw_info.get("raw")
            cfa = self.raw_info.get("cfa")
            desc = self.raw_info.get("desc", "RGBG")
            if raw is not None and cfa is not None:
                out = raw_channel_to_display_rgb(
                    raw, cfa, desc, self.raw_channel_mode, self.raw_display_bits,
                    self.raw_black_level, self.raw_white_level, self.raw_exposure_gain
                )
            else:
                out = apply_adjustments(self.base_rgb, self.params)
        else:
            src = render_raw_all_source_rgb(
                self.base_rgb,
                self.raw_info,
                self.raw_display_bits,
                self.raw_black_level,
                self.raw_white_level,
                self.raw_exposure_gain,
                self.raw_wb_enabled,
                self.raw_wb,
            )
            out = apply_adjustments(src, self.params)
        self.show_rendered_rgb(out, reset_view=reset_view)

    def show_rendered_rgb(self, out: np.ndarray, reset_view: bool = False):
        prev = None
        if not reset_view and self.v.has_image():
            h = self.v.horizontalScrollBar()
            v = self.v.verticalScrollBar()
            xr = 0.0 if h.maximum() <= 0 else h.value() / h.maximum()
            yr = 0.0 if v.maximum() <= 0 else v.value() / v.maximum()
            prev = ViewState(self.v.transform().m11(), xr, yr)
        self.v.set_image(rgb_to_qimage(out), fit=False)
        if reset_view or prev is None:
            self.v.set_initial_no_upscale_full_view()
        else:
            self.v.apply_state(prev)

    def sample_raw_at(self, x: int, y: int, disp_w: Optional[int] = None, disp_h: Optional[int] = None) -> Optional[dict]:
        if self.raw_info is None or self.base_rgb is None:
            return None
        raw = self.raw_info.get("raw")
        cfa = self.raw_info.get("cfa")
        desc = self.raw_info.get("desc", "RGBG")
        if raw is None or cfa is None:
            return None
        if disp_w is None or disp_h is None:
            h_rgb, w_rgb = self.base_rgb.shape[:2]
        else:
            w_rgb, h_rgb = int(disp_w), int(disp_h)
        h_raw, w_raw = raw.shape[:2]
        if w_rgb <= 0 or h_rgb <= 0 or w_raw <= 0 or h_raw <= 0:
            return None
        rx = int(round(x * (w_raw - 1) / max(1, w_rgb - 1)))
        ry = int(round(y * (h_raw - 1) / max(1, h_rgb - 1)))
        rx = max(0, min(w_raw - 1, rx))
        ry = max(0, min(h_raw - 1, ry))
        raw_val = int(raw[ry, rx])
        ci = int(cfa[ry, rx])
        ch = desc[ci] if 0 <= ci < len(desc) else f"C{ci}"
        return {"x": rx, "y": ry, "value": raw_val, "channel": ch, "dtype": str(raw.dtype)}

    def sample_raw_mode_at(
        self, x: int, y: int, mode: str, disp_w: Optional[int] = None, disp_h: Optional[int] = None
    ) -> Optional[dict]:
        mode = (mode or "ALL").upper()
        if mode == "ALL":
            return self.sample_raw_at(x, y, disp_w, disp_h)
        if self.raw_info is None:
            return None
        raw = self.raw_info.get("raw")
        cfa = self.raw_info.get("cfa")
        desc = self.raw_info.get("desc", "RGBG")
        if raw is None or cfa is None:
            return None

        if disp_w is None or disp_h is None:
            h_disp, w_disp = self.base_rgb.shape[:2]
        else:
            w_disp, h_disp = int(disp_w), int(disp_h)
        h_raw, w_raw = raw.shape[:2]
        if w_disp <= 0 or h_disp <= 0 or w_raw <= 0 or h_raw <= 0:
            return None
        rx = int(round(x * (w_raw - 1) / max(1, w_disp - 1)))
        ry = int(round(y * (h_raw - 1) / max(1, h_disp - 1)))
        rx = max(0, min(w_raw - 1, rx))
        ry = max(0, min(h_raw - 1, ry))

        mask = np.zeros((h_raw, w_raw), dtype=bool)
        if mode in ("R", "B"):
            for i in range(min(len(desc), 8)):
                if desc[i].upper() == mode:
                    mask |= (cfa == i)
        elif mode in ("G1", "G2"):
            gmask = np.zeros((h_raw, w_raw), dtype=bool)
            for i in range(min(len(desc), 8)):
                if desc[i].upper() == "G":
                    gmask |= (cfa == i)
            yy = np.indices((h_raw, w_raw))[0]
            mask = gmask & ((yy % 2 == 0) if mode == "G1" else (yy % 2 == 1))
        else:
            return self.sample_raw_at(x, y, disp_w, disp_h)

        if not np.any(mask):
            return None

        if not mask[ry, rx]:
            pts = np.argwhere(mask)
            if pts.size == 0:
                return None
            d2 = (pts[:, 0] - ry) * (pts[:, 0] - ry) + (pts[:, 1] - rx) * (pts[:, 1] - rx)
            k = int(np.argmin(d2))
            ry, rx = int(pts[k, 0]), int(pts[k, 1])

        return {"x": rx, "y": ry, "value": int(raw[ry, rx]), "channel": mode, "dtype": str(raw.dtype)}

    def sample_render_at(self, x: int, y: int) -> Optional[dict]:
        if self.base_rgb is None:
            return None
        pm = self.v.item.pixmap()
        if pm.isNull():
            return None
        w, h = pm.width(), pm.height()
        if w <= 0 or h <= 0:
            return None
        x = max(0, min(w - 1, int(x)))
        y = max(0, min(h - 1, int(y)))
        img = pm.toImage().convertToFormat(QImage.Format_RGB888)
        c = img.pixelColor(x, y)
        r, g, b = c.red(), c.green(), c.blue()
        gray = int(round(0.299 * r + 0.587 * g + 0.114 * b))
        return {"x": x, "y": y, "r": r, "g": g, "b": b, "gray": gray, "dtype": "uint8", "w": w, "h": h}


class AdjustPanel(QGroupBox):
    changed = pyqtSignal(dict)
    dragging_changed = pyqtSignal(bool)

    def __init__(self, title: str):
        super().__init__(title)
        self._sliders = {}
        self._updating = False
        self._dragging = False
        form = QFormLayout(self)
        specs = [
            ("exposure", "Exposure"),
            ("contrast", "Contrast"),
            ("saturation", "Saturation"),
            ("temperature", "Temperature"),
            ("tint", "Tint"),
            ("highlights", "Highlights"),
            ("shadows", "Shadows"),
        ]
        for key, label in specs:
            row = QWidget()
            hlay = QHBoxLayout(row)
            hlay.setContentsMargins(0, 0, 0, 0)
            s = QSlider(Qt.Horizontal)
            s.setRange(-100, 100)
            s.setValue(0)
            s.setStyleSheet(_slider_style())
            sb = QSpinBox()
            sb.setRange(-100, 100)
            sb.setValue(0)
            sb.setFixedWidth(72)
            s.valueChanged.connect(lambda val, k=key, spin=sb: self._on_slider(k, spin, val))
            sb.valueChanged.connect(lambda val, k=key, slider=s: self._on_spin(k, slider, val))
            s.sliderPressed.connect(self._on_slider_pressed)
            s.sliderReleased.connect(self._on_slider_released)
            hlay.addWidget(s, 1)
            hlay.addWidget(sb)
            form.addRow(label, row)
            self._sliders[key] = (s, sb)
        self.btn_reset = QPushButton("重置")
        self.btn_reset.setStyleSheet(_btn_style())
        self.btn_reset.clicked.connect(self.reset_values)
        form.addRow(self.btn_reset)

    def _on_slider(self, key: str, spin: QSpinBox, val: int):
        if spin.value() != val:
            spin.setValue(val)
        if not self._updating:
            self.changed.emit(self.values())

    def _on_spin(self, key: str, slider: QSlider, val: int):
        if slider.value() != val:
            slider.setValue(val)
        if not self._updating:
            self.changed.emit(self.values())

    def _on_slider_pressed(self):
        if not self._dragging:
            self._dragging = True
            self.dragging_changed.emit(True)

    def _on_slider_released(self):
        if self._dragging:
            self._dragging = False
            self.dragging_changed.emit(False)
        if not self._updating:
            self.changed.emit(self.values())

    def values(self):
        return {k: s.value() for k, (s, _v) in self._sliders.items()}

    def reset_values(self):
        self.set_values(dict(DEFAULT_ADJUSTMENTS))

    def set_values(self, params: dict):
        self._updating = True
        try:
            for k, (s, sb) in self._sliders.items():
                val = int(params.get(k, 0))
                s.setValue(val)
                sb.setValue(val)
        finally:
            self._updating = False
        self.changed.emit(self.values())


class RawAdjustPanel(QGroupBox):
    changed = pyqtSignal(str, dict)  # pane_id, {channel, bit, black, white, exposure, wb_enabled, wb_r, wb_g, wb_b}

    def __init__(self, parent=None):
        super().__init__("RAW 调参", parent)
        self._widgets = {}
        self._tabs = {}
        self._hints = {}
        self.setStyleSheet("""
            QWidget { color: #cccccc; background: #2d2d2d; }
            QComboBox, QSpinBox, QTabBar::tab {
                color: #cccccc;
                background-color: #3a3a3a;
                border: 1px solid #4a4a4a;
                border-radius: 4px;
                padding: 2px 6px;
            }
            QTabWidget::pane {
                border: none;
                background-color: #2d2d2d;
            }
            QTabBar::tab:selected {
                background-color: #2d2d2d;
                border-bottom: 2px solid #4a6a9a;
            }
        """)

        tabs = QTabWidget()
        tabs.addTab(self._build_tab("left"), "左图")
        tabs.addTab(self._build_tab("right"), "右图")
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)

    def _build_tab(self, pane_id: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        hint = QLabel("")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#999999; padding:2px 0 6px 0;")
        hint.setVisible(False)
        lay.addWidget(hint)
        form_wrap = QWidget()
        form = QFormLayout(form_wrap)
        ch = QComboBox()
        ch.addItems(["ALL", "R", "G1", "G2", "B"])
        bit = QSpinBox()
        bit.setRange(1, 16)
        bit.setValue(16)
        black = QSpinBox(); black.setRange(0, 65535); black.setValue(0)
        white = QSpinBox(); white.setRange(1, 65535); white.setValue(65535)
        exp = QDoubleSpinBox(); exp.setRange(0.01, 32.0); exp.setSingleStep(0.05); exp.setValue(1.0)
        wb_en = QCheckBox("启用 WB")
        wb_r = QDoubleSpinBox(); wb_r.setRange(0.1, 8.0); wb_r.setSingleStep(0.01); wb_r.setValue(1.0)
        wb_g = QDoubleSpinBox(); wb_g.setRange(0.1, 8.0); wb_g.setSingleStep(0.01); wb_g.setValue(1.0)
        wb_b = QDoubleSpinBox(); wb_b.setRange(0.1, 8.0); wb_b.setSingleStep(0.01); wb_b.setValue(1.0)
        ch.currentTextChanged.connect(lambda _v, pid=pane_id: self._emit(pid))
        bit.valueChanged.connect(lambda _v, pid=pane_id: self._emit(pid))
        black.valueChanged.connect(lambda _v, pid=pane_id: self._emit(pid))
        white.valueChanged.connect(lambda _v, pid=pane_id: self._emit(pid))
        exp.valueChanged.connect(lambda _v, pid=pane_id: self._emit(pid))
        wb_en.toggled.connect(lambda _v, pid=pane_id: self._emit(pid))
        wb_r.valueChanged.connect(lambda _v, pid=pane_id: self._emit(pid))
        wb_g.valueChanged.connect(lambda _v, pid=pane_id: self._emit(pid))
        wb_b.valueChanged.connect(lambda _v, pid=pane_id: self._emit(pid))
        form.addRow("Bayer 通道", ch)
        form.addRow("显示 Bit", bit)
        form.addRow("Black Level", black)
        form.addRow("White Level", white)
        form.addRow("Exposure Gain", exp)
        form.addRow("白平衡", wb_en)
        form.addRow("WB R", wb_r)
        form.addRow("WB G", wb_g)
        form.addRow("WB B", wb_b)
        lay.addWidget(form_wrap)
        self._widgets[pane_id] = {
            "channel": ch, "bit": bit, "black": black, "white": white, "exp": exp,
            "wb_en": wb_en, "wb_r": wb_r, "wb_g": wb_g, "wb_b": wb_b
        }
        self._tabs[pane_id] = w
        self._hints[pane_id] = hint
        return w

    def set_values(
        self, pane_id: str, channel: str, bit: int,
        black: int = 0, white: int = 65535, exposure: float = 1.0,
        wb_enabled: bool = False, wb_r: float = 1.0, wb_g: float = 1.0, wb_b: float = 1.0
    ):
        ws = self._widgets[pane_id]
        ws["channel"].setCurrentText(channel)
        ws["bit"].setValue(int(bit))
        ws["black"].setValue(int(max(0, min(65535, int(black)))))
        ws["white"].setValue(int(max(1, min(65535, int(white)))))
        ws["exp"].setValue(float(exposure))
        ws["wb_en"].setChecked(bool(wb_enabled))
        ws["wb_r"].setValue(float(wb_r))
        ws["wb_g"].setValue(float(wb_g))
        ws["wb_b"].setValue(float(wb_b))

    def _emit(self, pane_id: str):
        ws = self._widgets[pane_id]
        self.changed.emit(
            pane_id,
            {
                "channel": ws["channel"].currentText(),
                "bit": int(ws["bit"].value()),
                "black": int(ws["black"].value()),
                "white": int(ws["white"].value()),
                "exposure": float(ws["exp"].value()),
                "wb_enabled": bool(ws["wb_en"].isChecked()),
                "wb_r": float(ws["wb_r"].value()),
                "wb_g": float(ws["wb_g"].value()),
                "wb_b": float(ws["wb_b"].value()),
            }
        )

    def set_pane_enabled(self, pane_id: str, enabled: bool, reason: str = ""):
        tab = self._tabs.get(pane_id)
        if tab is not None:
            tab.setEnabled(bool(enabled))
        hint = self._hints.get(pane_id)
        if hint is not None:
            hint.setText(reason)
            hint.setVisible(bool(reason))


class RawLoadConfigDialog(QDialog):
    def __init__(self, parent=None, default_text: str = "4096,3072,10,RGGB,u16", filename: str = ""):
        super().__init__(parent)
        self.setWindowTitle("RAW 加载配置")
        self.resize(380, 260)
        self.setStyleSheet("""
            QDialog, QWidget { color: #000000; background: #ffffff; }
            QComboBox, QSpinBox, QPushButton, QLabel {
                color: #000000; background: #ffffff;
            }
        """)

        parts = [x.strip() for x in default_text.split(",")]
        w0, h0, b0, p0, k0 = 4096, 3072, 10, "RGGB", "u16"
        if len(parts) == 5:
            try:
                w0, h0, b0 = int(parts[0]), int(parts[1]), int(parts[2])
                p0, k0 = parts[3].upper(), parts[4].lower()
            except Exception:
                pass

        form = QFormLayout()
        tip = QLabel(f"文件: {filename}")
        form.addRow("文件", tip)

        self.sp_w = QSpinBox(); self.sp_w.setRange(1, 20000); self.sp_w.setValue(w0)
        self.sp_h = QSpinBox(); self.sp_h.setRange(1, 20000); self.sp_h.setValue(h0)
        self.sp_b = QSpinBox(); self.sp_b.setRange(1, 16); self.sp_b.setValue(max(1, min(16, b0)))
        self.cb_p = QComboBox(); self.cb_p.addItems(["RGGB", "BGGR", "GRBG", "GBRG"]); self.cb_p.setCurrentText(p0 if p0 in {"RGGB","BGGR","GRBG","GBRG"} else "RGGB")
        self.cb_k = QComboBox(); self.cb_k.addItems(["u16", "u8", "mipi10", "mipi12"]); self.cb_k.setCurrentText(k0 if k0 in {"u16","u8","mipi10","mipi12"} else "u16")

        form.addRow("Width", self.sp_w)
        form.addRow("Height", self.sp_h)
        form.addRow("Bit", self.sp_b)
        form.addRow("Bayer", self.cb_p)
        form.addRow("Packing", self.cb_k)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

    def get_cfg(self) -> dict:
        return {
            "width": int(self.sp_w.value()),
            "height": int(self.sp_h.value()),
            "bit": int(self.sp_b.value()),
            "pattern": self.cb_p.currentText().upper(),
            "packing": self.cb_k.currentText().lower(),
        }

    def get_cfg_text(self) -> str:
        c = self.get_cfg()
        return f"{c['width']},{c['height']},{c['bit']},{c['pattern']},{c['packing']}"


class Window(QMainWindow):
    load_done = pyqtSignal(object, object, object, object)   # pane, path, rgb, raw_info_or_error
    adjust_done = pyqtSignal(object, int, object)            # pane, request_id, rgb

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DNGauge - Shotwell RAW pipeline")
        self.resize(1500, 900)
        self.setAcceptDrops(True)
        self._apply_modern_theme()

        self.left = Pane("左图")
        self.right = Pane("右图")
        self.left_adj = AdjustPanel("左图调整")
        self.right_adj = AdjustPanel("右图调整")

        self._link = True
        self._sync_lock = False
        self._single_view = False

        self.left.state_changed.connect(lambda s: self._sync(self.right, s))
        self.right.state_changed.connect(lambda s: self._sync(self.left, s))
        self.left.pixel_picked.connect(lambda p, pane=self.left: self._on_pixel_picked("左图", pane, p))
        self.right.pixel_picked.connect(lambda p, pane=self.right: self._on_pixel_picked("右图", pane, p))
        self.left.file_dropped.connect(lambda path: self._load_path_into_pane(self.left, path))
        self.right.file_dropped.connect(lambda path: self._load_path_into_pane(self.right, path))
        self.left_adj.changed.connect(lambda p: self._on_adjust(self.left, p))
        self.right_adj.changed.connect(lambda p: self._on_adjust(self.right, p))
        self.left_adj.dragging_changed.connect(lambda f: self._on_adjust_dragging(self.left, f))
        self.right_adj.dragging_changed.connect(lambda f: self._on_adjust_dragging(self.right, f))

        self.btn_l = QPushButton("L↥")
        self.btn_r = QPushButton("R↥")
        self.btn_mode = QPushButton("布局·双")
        self.btn_adjust = QPushButton("调参·关")
        self.btn_peek = QPushButton("←")
        self.btn_probe = QPushButton("Locate·关")
        self.btn_probe_src = QPushButton("Value:显示(渲染)")
        self.btn_bayer = QPushButton("通道·--")
        self.btn_11 = QPushButton("100%")
        self.btn_fit = QPushButton("Fit")
        self.btn_link = QPushButton("同步·开")
        self.msg = QLabel("就绪")
        self.pixel_info = QLabel("LOCATE INFO: OFF")
        self._adjust_visible = False
        self._probe_enabled = False
        self._probe_source = "render"
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._adjust_timers = {}
        self._adjust_dragging = {}
        self._plain_raw_cfg_text = "4096,3072,10,RGGB,u16"
        self.raw_adj_panel = RawAdjustPanel(self)
        self.raw_adj_panel.changed.connect(self._on_raw_adjust_changed)

        self.btn_l.clicked.connect(lambda: self._load_one(self.left))
        self.btn_r.clicked.connect(lambda: self._load_one(self.right))
        self.btn_mode.clicked.connect(self._toggle_mode)
        self.btn_adjust.clicked.connect(self._toggle_adjust_panel)
        self.btn_peek.pressed.connect(self._peek_right_on_left_start)
        self.btn_peek.released.connect(self._peek_right_on_left_end)
        self.btn_probe.clicked.connect(self._toggle_probe_mode)
        self.btn_probe_src.clicked.connect(self._toggle_probe_source)
        self.btn_bayer.clicked.connect(self._cycle_bayer_mode)
        self.btn_11.clicked.connect(self._one_to_one)
        self.btn_fit.clicked.connect(self._fit_all)
        self.btn_link.clicked.connect(self._toggle_link)
        self.load_done.connect(self._on_load_done)
        self.adjust_done.connect(self._on_adjust_done)

        # 顶部功能区：按类别分组
        top = QHBoxLayout()

        grp_io = QGroupBox("输入")
        lay_io = QHBoxLayout(grp_io)
        lay_io.addWidget(self.btn_l)
        lay_io.addWidget(self.btn_r)

        grp_layout = QGroupBox("布局")
        lay_layout = QHBoxLayout(grp_layout)
        lay_layout.addWidget(self.btn_mode)
        lay_layout.addWidget(self.btn_link)
        lay_layout.addWidget(self.btn_peek)

        grp_adjust = QGroupBox("调参")
        lay_adjust = QHBoxLayout(grp_adjust)
        lay_adjust.addWidget(self.btn_adjust)

        grp_probe = QGroupBox("LOCATE")
        lay_probe = QHBoxLayout(grp_probe)
        lay_probe.addWidget(self.btn_probe)
        lay_probe.addWidget(self.btn_probe_src)
        lay_probe.addWidget(self.btn_bayer)

        grp_zoom = QGroupBox("视图")
        lay_zoom = QHBoxLayout(grp_zoom)
        lay_zoom.addWidget(self.btn_11)
        lay_zoom.addWidget(self.btn_fit)

        top.addWidget(grp_io)
        top.addWidget(grp_layout)
        top.addWidget(grp_adjust)
        top.addWidget(grp_probe)
        top.addWidget(grp_zoom)
        top.addStretch(1)
        top.addWidget(self.msg)

        mid = QHBoxLayout()
        mid.addWidget(self.left, 1)
        mid.addWidget(self.right, 1)
        self.adj_container = QWidget()
        adj_col = QVBoxLayout(self.adj_container)
        adj_col.setContentsMargins(0, 0, 0, 0)
        adj_col.addWidget(self.left_adj)
        adj_col.addWidget(self.right_adj)
        adj_col.addWidget(self.raw_adj_panel)
        mid.addWidget(self.adj_container)

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.addLayout(top)
        lay.addLayout(mid, 1)
        lay.addWidget(self.pixel_info)
        self.setCentralWidget(root)
        self._update_adjust_panel_visibility()
        self._beautify_controls()
        self.raw_adj_panel.set_values("left", "ALL", 16, 0, 65535, 1.0, False, 1.0, 1.0, 1.0)
        self.raw_adj_panel.set_values("right", "ALL", 16, 0, 65535, 1.0, False, 1.0, 1.0, 1.0)
        self._refresh_raw_controls_ui()

    def _apply_modern_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #2b2b2b; }
            QWidget { color: #cccccc; font-size: 13px; }
            QGroupBox {
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                margin-top: 10px;
                padding: 6px;
                background-color: #2d2d2d;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
                color: #cccccc;
            }
            QLabel { background: transparent; }
            QSpinBox {
                background-color: #3a3a3a;
                color: #cccccc;
                border: 1px solid #4a4a4a;
                border-radius: 4px;
                padding: 2px 6px;
            }
        """)

    def _beautify_controls(self):
        buttons = [
            self.btn_l, self.btn_r, self.btn_mode, self.btn_adjust,
            self.btn_peek, self.btn_probe, self.btn_probe_src, self.btn_bayer,
            self.btn_11, self.btn_fit, self.btn_link
        ]
        for b in buttons:
            b.setMinimumHeight(30)
            b.setStyleSheet(_btn_style())
        self._refresh_toggle_button_styles()
        self.msg.setStyleSheet("color:#999999; padding-left:8px;")
        self.pixel_info.setStyleSheet(
            "background:#2d2d2d; border:1px solid #3a3a3a; border-radius:4px; padding:8px; color:#cccccc;"
        )

    def _refresh_toggle_button_styles(self):
        self.btn_adjust.setStyleSheet(_btn_style_checked() if self._adjust_visible else _btn_style())
        self.btn_probe.setStyleSheet(_btn_style_checked() if self._probe_enabled else _btn_style())
        self.btn_link.setStyleSheet(_btn_style_checked() if self._link else _btn_style())

    def _primary_raw_pane(self) -> Optional[Pane]:
        if self.left.supports_raw_controls():
            return self.left
        if self.right.supports_raw_controls():
            return self.right
        return None

    def _refresh_raw_controls_ui(self):
        left_enabled = self.left.supports_raw_controls()
        right_enabled = self.right.supports_raw_controls()
        self.raw_adj_panel.set_pane_enabled("left", left_enabled, self.left.raw_controls_unavailable_reason())
        self.raw_adj_panel.set_pane_enabled("right", right_enabled, self.right.raw_controls_unavailable_reason())

        primary = self._primary_raw_pane()
        self.btn_bayer.setEnabled(primary is not None)
        if primary is None:
            self.btn_bayer.setText("通道·--")
        else:
            self.btn_bayer.setText(f"通道·{primary.raw_channel_mode}")

    def _toggle_mode(self):
        self._single_view = not self._single_view
        self.right.setVisible(not self._single_view)
        self.btn_r.setEnabled(not self._single_view)
        self.btn_link.setEnabled(not self._single_view)
        self.btn_mode.setText(f"布局·{'单' if self._single_view else '双'}")
        self._update_adjust_panel_visibility()

    def _toggle_adjust_panel(self):
        self._adjust_visible = not self._adjust_visible
        self.btn_adjust.setText(f"调参·{'开' if self._adjust_visible else '关'}")
        self._refresh_toggle_button_styles()
        self._update_adjust_panel_visibility()

    def _update_adjust_panel_visibility(self):
        self.adj_container.setVisible(self._adjust_visible)
        if not self._adjust_visible:
            return
        if self._single_view:
            self.left_adj.setVisible(True)
            self.right_adj.setVisible(False)
        else:
            self.left_adj.setVisible(True)
            self.right_adj.setVisible(True)

    def _peek_right_on_left_start(self):
        if not self.right.v.has_image() or not self.left.v.has_image():
            self.msg.setText("请先加载左右两张图")
            return
        right_pm = self.right.v.item.pixmap()
        if right_pm.isNull():
            return
        self.left.v.set_overlay_pixmap(right_pm)

    def _peek_right_on_left_end(self):
        self.left.v.clear_overlay()

    def _toggle_probe_mode(self):
        self._probe_enabled = not self._probe_enabled
        self.btn_probe.setText(f"Locate·{'开' if self._probe_enabled else '关'}")
        self._refresh_toggle_button_styles()
        self.left.v.set_probe_enabled(self._probe_enabled)
        self.right.v.set_probe_enabled(self._probe_enabled)
        if not self._probe_enabled:
            self.pixel_info.setText("LOCATE INFO: OFF")

    def _toggle_probe_source(self):
        self._probe_source = "raw" if self._probe_source == "render" else "render"
        self.btn_probe_src.setText(f"{'Value:RAW' if self._probe_source == 'raw' else 'Value:显示(渲染)'}")

    def _on_raw_adjust_changed(self, pane_id: str, params: dict):
        pane = self.left if pane_id == "left" else self.right
        if not pane.supports_raw_controls():
            return
        pane.raw_channel_mode = str(params.get("channel", "ALL")).upper()
        pane.raw_display_bits = int(params.get("bit", 16))
        pane.raw_black_level = int(params.get("black", 0))
        pane.raw_white_level = int(params.get("white", (1 << pane.raw_display_bits) - 1))
        pane.raw_exposure_gain = float(params.get("exposure", 1.0))
        pane.raw_wb_enabled = bool(params.get("wb_enabled", False))
        pane.raw_wb = (
            float(params.get("wb_r", 1.0)),
            float(params.get("wb_g", 1.0)),
            float(params.get("wb_b", 1.0)),
        )
        self._refresh_raw_controls_ui()
        if pane.base_rgb is not None:
            if pane.raw_channel_mode == "ALL":
                self._submit_adjust_render(pane, preview=False)
            else:
                pane.render_current(reset_view=False)

    def _cycle_bayer_mode(self):
        panes = [pane for pane in (self.left, self.right) if pane.supports_raw_controls()]
        if not panes:
            self._refresh_raw_controls_ui()
            return
        modes = ["ALL", "R", "G1", "G2", "B"]
        cur = panes[0].raw_channel_mode
        nxt = modes[(modes.index(cur) + 1) % len(modes)] if cur in modes else "ALL"
        for pane in panes:
            pane.raw_channel_mode = nxt
        if self.left.supports_raw_controls():
            self.raw_adj_panel.set_values(
                "left", self.left.raw_channel_mode, self.left.raw_display_bits,
                self.left.raw_black_level, self.left.raw_white_level, self.left.raw_exposure_gain,
                self.left.raw_wb_enabled, self.left.raw_wb[0], self.left.raw_wb[1], self.left.raw_wb[2]
            )
        if self.right.supports_raw_controls():
            self.raw_adj_panel.set_values(
                "right", self.right.raw_channel_mode, self.right.raw_display_bits,
                self.right.raw_black_level, self.right.raw_white_level, self.right.raw_exposure_gain,
                self.right.raw_wb_enabled, self.right.raw_wb[0], self.right.raw_wb[1], self.right.raw_wb[2]
            )
        self._refresh_raw_controls_ui()
        for pane in panes:
            if pane.base_rgb is not None:
                pane.render_current(reset_view=False)

    def _on_pixel_picked(self, pane_name: str, pane: Pane, p: dict):
        if not self._probe_enabled:
            return
        src_render = pane.sample_render_at(p["x"], p["y"])
        if src_render is None:
            return

        left_render = None
        right_render = None
        if pane is self.left:
            left_render = src_render
            if (not self._single_view) and self.right.base_rgb is not None:
                rx = int(round(src_render["x"] * (self.right.v.item.pixmap().width() - 1) / max(1, src_render["w"] - 1)))
                ry = int(round(src_render["y"] * (self.right.v.item.pixmap().height() - 1) / max(1, src_render["h"] - 1)))
                right_render = self.right.sample_render_at(rx, ry)
        else:
            right_render = src_render
            if (not self._single_view) and self.left.base_rgb is not None:
                lx = int(round(src_render["x"] * (self.left.v.item.pixmap().width() - 1) / max(1, src_render["w"] - 1)))
                ly = int(round(src_render["y"] * (self.left.v.item.pixmap().height() - 1) / max(1, src_render["h"] - 1)))
                left_render = self.left.sample_render_at(lx, ly)

        if self._probe_source == "render":
            left_txt = "左图: 无"
            right_txt = "右图: 无"
            if left_render is not None:
                left_txt = (
                    f"左图 渲染后(x={left_render['x']}, y={left_render['y']}) "
                    f"R={left_render['r']} G={left_render['g']} B={left_render['b']} Gray={left_render['gray']}"
                )
                if self.left.raw_info is not None:
                    if self.left.raw_channel_mode == "ALL":
                        lr = self.left.sample_raw_at(
                            left_render["x"], left_render["y"], left_render["w"], left_render["h"]
                        )
                    else:
                        lr = self.left.sample_raw_mode_at(
                            left_render["x"], left_render["y"], self.left.raw_channel_mode, left_render["w"], left_render["h"]
                        )
                    if lr is not None:
                        left_txt += f" [RAW域:{lr['channel']}={lr['value']}]"
            if right_render is not None:
                right_txt = (
                    f"右图 渲染后(x={right_render['x']}, y={right_render['y']}) "
                    f"R={right_render['r']} G={right_render['g']} B={right_render['b']} Gray={right_render['gray']}"
                )
                if self.right.raw_info is not None:
                    if self.right.raw_channel_mode == "ALL":
                        rr = self.right.sample_raw_at(
                            right_render["x"], right_render["y"], right_render["w"], right_render["h"]
                        )
                    else:
                        rr = self.right.sample_raw_mode_at(
                            right_render["x"], right_render["y"], self.right.raw_channel_mode, right_render["w"], right_render["h"]
                        )
                    if rr is not None:
                        right_txt += f" [RAW域:{rr['channel']}={rr['value']}]"
            self.pixel_info.setText(f"{left_txt} || {right_txt} | 类型: uint8")
            return

        left_raw = (
            self.left.sample_raw_mode_at(
                left_render["x"], left_render["y"], self.left.raw_channel_mode, left_render["w"], left_render["h"]
            )
            if left_render is not None else None
        )
        right_raw = (
            self.right.sample_raw_mode_at(
                right_render["x"], right_render["y"], self.right.raw_channel_mode, right_render["w"], right_render["h"]
            )
            if right_render is not None else None
        )
        left_txt = "左图 RAW原始: 不可用"
        right_txt = "右图 RAW原始: 不可用"
        if left_raw is not None:
            left_txt = (
                f"左图 RAW原始(x={left_raw['x']}, y={left_raw['y']}) "
                f"{left_raw['channel']}={left_raw['value']} 类型:{left_raw['dtype']}"
            )
        if right_raw is not None:
            right_txt = (
                f"右图 RAW原始(x={right_raw['x']}, y={right_raw['y']}) "
                f"{right_raw['channel']}={right_raw['value']} 类型:{right_raw['dtype']}"
            )
        self.pixel_info.setText(f"{left_txt} || {right_txt}")

    def _on_adjust(self, pane: Pane, params: dict):
        pane.params = dict(params)
        if pane.raw_channel_mode != "ALL":
            pane.render_current(reset_view=False)
            return
        dragging = self._adjust_dragging.get(pane, False)
        self._schedule_adjust_render(pane, debounce_ms=25 if dragging else 40, preview=dragging)

    def _on_adjust_dragging(self, pane: Pane, dragging: bool):
        self._adjust_dragging[pane] = dragging
        if not dragging:
            self._submit_adjust_render(pane, preview=False)

    def _schedule_adjust_render(self, pane: Pane, debounce_ms: int = 40, preview: bool = False):
        if pane.base_rgb is None:
            return
        timer = self._adjust_timers.get(pane)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda p=pane: self._submit_adjust_render(p, preview=self._adjust_dragging.get(p, False)))
            self._adjust_timers[pane] = timer
        timer.start(debounce_ms)

    def _submit_adjust_render(self, pane: Pane, preview: bool = False):
        if pane.base_rgb is None or pane.raw_channel_mode != "ALL":
            return
        pane.render_request_id += 1
        req_id = pane.render_request_id
        base = pane.base_rgb
        raw_info = pane.raw_info
        params = dict(pane.params)
        raw_display_bits = int(pane.raw_display_bits)
        raw_black_level = int(pane.raw_black_level)
        raw_white_level = int(pane.raw_white_level)
        raw_exposure_gain = float(pane.raw_exposure_gain)
        raw_wb_enabled = bool(pane.raw_wb_enabled)
        raw_wb = tuple(float(v) for v in pane.raw_wb)

        def task():
            src = render_raw_all_source_rgb(
                base,
                raw_info,
                raw_display_bits,
                raw_black_level,
                raw_white_level,
                raw_exposure_gain,
                raw_wb_enabled,
                raw_wb,
            )
            return fast_preview_adjust(src, params) if preview else apply_adjustments(src, params)

        fut = self._executor.submit(task)

        def done_cb(f):
            try:
                out = f.result()
            except Exception:
                return
            self.adjust_done.emit(pane, req_id, out)

        fut.add_done_callback(done_cb)

    def _on_adjust_done(self, pane: Pane, request_id: int, out: np.ndarray):
        if request_id != pane.render_request_id or pane.raw_channel_mode != "ALL":
            return
        pane.show_rendered_rgb(out, reset_view=False)

    def _toggle_link(self):
        self._link = not self._link
        self.btn_link.setText(f"同步·{'开' if self._link else '关'}")
        self._refresh_toggle_button_styles()

    def _sync(self, dst: Pane, s: ViewState):
        if self._single_view:
            return
        # 避免窗口 resize/fullscreen 过程中的双向联动风暴
        if self.left.v._in_resize or self.right.v._in_resize:
            return
        if not self._link or self._sync_lock or not dst.v.has_image():
            return
        self._sync_lock = True
        try:
            dst.v.apply_state(s)
        finally:
            self._sync_lock = False

    def _pick_file(self) -> Optional[str]:
        raw_patterns = " ".join(
            sorted({f"*{e}" for e in RAW_EXTS} | {f"*{e.upper()}" for e in RAW_EXTS})
        )
        img_patterns = "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp"
        filt = (
            f"RAW/Images ({raw_patterns} {img_patterns});;"
            f"RAW Only ({raw_patterns});;"
            f"Images Only ({img_patterns});;"
            "All Files (*)"
        )
        dlg = QFileDialog(self, "选择图片")
        dlg.setFileMode(QFileDialog.ExistingFile)
        dlg.setNameFilter(filt)
        # 使用 Qt 文件对话框，确保可控字体颜色
        dlg.setOption(QFileDialog.DontUseNativeDialog, True)
        dlg.setStyleSheet("""
            QFileDialog, QFileDialog QWidget {
                color: #000000;
                background: #ffffff;
            }
            QFileDialog QLineEdit, QFileDialog QComboBox, QFileDialog QListView, QFileDialog QTreeView {
                color: #000000;
                background: #ffffff;
                selection-color: #000000;
                selection-background-color: #cfe3ff;
            }
        """)
        if dlg.exec_():
            files = dlg.selectedFiles()
            if files:
                return files[0]
        return None

    def _load_one(self, pane: Pane):
        path = self._pick_file()
        if not path:
            return
        self._load_path_into_pane(pane, path)

    def _ask_plain_raw_cfg(self, path: str) -> Optional[dict]:
        dlg = RawLoadConfigDialog(self, default_text=self._plain_raw_cfg_text, filename=os.path.basename(path))
        if dlg.exec_() != QDialog.Accepted:
            return None
        try:
            cfg = dlg.get_cfg()
            self._plain_raw_cfg_text = dlg.get_cfg_text()
            return cfg
        except Exception:
            self.msg.setText("RAW 配置解析失败")
            return None

    def _raw_can_use_shotwell_pipeline(self, path: str) -> bool:
        """判断 .RAW 是否可被 rawpy/libraw 直接识别（可走 Shotwell-like 管线）。"""
        try:
            with rawpy.imread(path):
                return True
        except Exception:
            return False

    def _load_path_into_pane(self, pane: Pane, path: str):
        self.msg.setText(f"加载中: {os.path.basename(path)} ...")
        vp = pane.v.viewport().size()
        target = (vp.width(), vp.height())
        plain_raw_cfg = None
        if Path(path).suffix.lower() == ".raw":
            # 优先尝试 Shotwell-like (LibRaw) 解码；仅在不支持时回退到裸 RAW 配置
            if not self._raw_can_use_shotwell_pipeline(path):
                plain_raw_cfg = self._ask_plain_raw_cfg(path)
                if plain_raw_cfg is None:
                    return

        def task():
            return ShotwellRawDecoder.load(path, target_size=target, plain_raw_cfg=plain_raw_cfg)

        fut = self._executor.submit(task)

        def done_cb(f):
            try:
                rgb, raw_info = f.result()
                self.load_done.emit(pane, path, rgb, raw_info)
            except Exception as e:
                self.load_done.emit(pane, path, None, e)

        fut.add_done_callback(done_cb)

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if not md or not md.hasUrls():
            event.ignore()
            return
        for url in md.urls():
            if url.isLocalFile():
                ext = Path(url.toLocalFile()).suffix.lower()
                if ext in DROP_EXTS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        md = event.mimeData()
        if not md or not md.hasUrls():
            event.ignore()
            return
        files = []
        for url in md.urls():
            if not url.isLocalFile():
                continue
            p = url.toLocalFile()
            if os.path.isfile(p) and Path(p).suffix.lower() in DROP_EXTS:
                files.append(p)
        if not files:
            event.ignore()
            return

        # 单图模式：只加载左图
        if self._single_view:
            self._load_path_into_pane(self.left, files[0])
            event.acceptProposedAction()
            return

        # 双图模式：优先一左一右
        if len(files) >= 2:
            self._load_path_into_pane(self.left, files[0])
            self._load_path_into_pane(self.right, files[1])
        else:
            # 仅一个文件时，优先填充空的一侧
            if not self.left.v.has_image():
                self._load_path_into_pane(self.left, files[0])
            elif not self.right.v.has_image():
                self._load_path_into_pane(self.right, files[0])
            else:
                self._load_path_into_pane(self.left, files[0])
        event.acceptProposedAction()

    def _on_load_done(self, pane: Pane, path: str, rgb: Optional[np.ndarray], raw_or_err):
        if rgb is None:
            self.msg.setText(f"加载失败: {raw_or_err}")
            return
        pane.set_baseline(path, rgb, raw_or_err)
        if pane is self.left:
            self.raw_adj_panel.set_values(
                "left", self.left.raw_channel_mode, self.left.raw_display_bits,
                self.left.raw_black_level, self.left.raw_white_level, self.left.raw_exposure_gain,
                self.left.raw_wb_enabled, self.left.raw_wb[0], self.left.raw_wb[1], self.left.raw_wb[2]
            )
        else:
            self.raw_adj_panel.set_values(
                "right", self.right.raw_channel_mode, self.right.raw_display_bits,
                self.right.raw_black_level, self.right.raw_white_level, self.right.raw_exposure_gain,
                self.right.raw_wb_enabled, self.right.raw_wb[0], self.right.raw_wb[1], self.right.raw_wb[2]
            )
        if pane is self.left:
            self.left_adj.set_values(dict(DEFAULT_ADJUSTMENTS))
        else:
            self.right_adj.set_values(dict(DEFAULT_ADJUSTMENTS))
        self._refresh_raw_controls_ui()
        self.msg.setText(f"已加载: {os.path.basename(path)}")

    def _one_to_one(self):
        self.left.v.set_one_to_one()
        self.right.v.set_one_to_one()

    def _fit_all(self):
        self.left.v.fit_image()
        self.right.v.fit_image()

    def closeEvent(self, event):
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        super().closeEvent(event)


def main():
    configure_app_identity()
    app = QApplication(sys.argv)
    app.setApplicationName("DNGauge")
    if hasattr(app, "setApplicationDisplayName"):
        app.setApplicationDisplayName("DNGauge")
    if hasattr(app, "setDesktopFileName"):
        app.setDesktopFileName("DNGauge")
    app_icon = QIcon()
    for icon_path in (resource_path("DNGauge.png"), resource_path("DNGauge.ico")):
        if os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
            if not app_icon.isNull():
                app.setWindowIcon(app_icon)
                break
    w = Window()
    if not app_icon.isNull():
        w.setWindowIcon(app_icon)

    args = [a for a in sys.argv[1:] if os.path.isfile(a)]
    if len(args) >= 1:
        try:
            rgb, raw_info = ShotwellRawDecoder.load(args[0], target_size=None)
            w.left.set_baseline(args[0], rgb, raw_info)
            w.left_adj.set_values(dict(DEFAULT_ADJUSTMENTS))
        except Exception as e:
            w.msg.setText(f"左图加载失败: {e}")
    if len(args) >= 2:
        try:
            rgb, raw_info = ShotwellRawDecoder.load(args[1], target_size=None)
            w.right.set_baseline(args[1], rgb, raw_info)
            w.right_adj.set_values(dict(DEFAULT_ADJUSTMENTS))
        except Exception as e:
            w.msg.setText(f"右图加载失败: {e}")

    w._refresh_raw_controls_ui()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
