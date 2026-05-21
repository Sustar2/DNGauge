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
import concurrent.futures
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QImage, QPixmap, QPainter, QTransform
from PyQt5.QtWidgets import (
    QApplication,
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
    QVBoxLayout,
    QWidget,
)

try:
    import rawpy
except Exception as e:
    raise RuntimeError("需要 rawpy 才能按 Shotwell RAW 链路解码") from e

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

DEFAULT_ADJUSTMENTS = {
    "exposure": 0,
    "contrast": 0,
    "saturation": 0,
    "temperature": 0,
    "tint": 0,
    "highlights": 0,
    "shadows": 0,
}


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
    def load(cls, path: str, target_size: Optional[tuple[int, int]] = None) -> tuple[np.ndarray, Optional[dict]]:
        ext = Path(path).suffix.lower()
        if ext in RAW_EXTS:
            return cls._load_raw(path, target_size=target_size)
        return cls._load_regular(path)

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
            raw_info = {"raw": raw_visible, "cfa": cfa_visible, "desc": str(desc)}

        return np.ascontiguousarray(rgb.astype(np.uint8, copy=False)), raw_info

    @staticmethod
    def _load_regular(path: str) -> tuple[np.ndarray, Optional[dict]]:
        arr = np.array(Image.open(path).convert("RGB"), dtype=np.uint8)
        return np.ascontiguousarray(arr), None


class SyncView(QGraphicsView):
    state_changed = pyqtSignal(object)
    pixel_picked = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
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
        if self.has_image():
            # Shotwell 逻辑：窗口变化时保持 interpolation 档位
            self._apply_zoom_from_interp()
        self._emit_state()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self._emit_state()

    def mousePressEvent(self, event):
        if self._probe_enabled and event.button() == Qt.LeftButton:
            self._pick_pixel(event.pos())
            event.accept()
            return
        super().mousePressEvent(event)

    def _emit_state(self):
        if self._suppress or not self.has_image():
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


class Pane(QWidget):
    state_changed = pyqtSignal(object)
    pixel_picked = pyqtSignal(object)

    def __init__(self, title: str):
        super().__init__()
        self.t = QLabel(title)
        self.p = QLabel("未加载")
        self.p.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.v = SyncView()
        self.base_rgb: Optional[np.ndarray] = None
        self.raw_info: Optional[dict] = None
        self.params = dict(DEFAULT_ADJUSTMENTS)
        self.render_request_id = 0

        lay = QVBoxLayout(self)
        lay.addWidget(self.t)
        lay.addWidget(self.p)
        lay.addWidget(self.v, 1)

        self.v.state_changed.connect(self.state_changed)
        self.v.pixel_picked.connect(self.pixel_picked)

    def set_baseline(self, path: str, rgb: np.ndarray, raw_info: Optional[dict] = None):
        self.p.setText(path)
        self.base_rgb = np.ascontiguousarray(rgb.astype(np.uint8, copy=False))
        self.raw_info = raw_info
        self.params = dict(DEFAULT_ADJUSTMENTS)
        self.render_current(reset_view=True)

    def render_current(self, reset_view: bool = False):
        if self.base_rgb is None:
            return
        out = apply_adjustments(self.base_rgb, self.params)
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

    def sample_raw_at(self, x: int, y: int) -> Optional[dict]:
        if self.raw_info is None or self.base_rgb is None:
            return None
        raw = self.raw_info.get("raw")
        cfa = self.raw_info.get("cfa")
        desc = self.raw_info.get("desc", "RGBG")
        if raw is None or cfa is None:
            return None
        h_rgb, w_rgb = self.base_rgb.shape[:2]
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


class Window(QMainWindow):
    load_done = pyqtSignal(object, object, object, object)   # pane, path, rgb, raw_info_or_error
    adjust_done = pyqtSignal(object, int, object)            # pane, request_id, rgb

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DNG_COMPARE - Shotwell RAW pipeline")
        self.resize(1500, 900)
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

        self.btn_l.clicked.connect(lambda: self._load_one(self.left))
        self.btn_r.clicked.connect(lambda: self._load_one(self.right))
        self.btn_mode.clicked.connect(self._toggle_mode)
        self.btn_adjust.clicked.connect(self._toggle_adjust_panel)
        self.btn_peek.pressed.connect(self._peek_right_on_left_start)
        self.btn_peek.released.connect(self._peek_right_on_left_end)
        self.btn_probe.clicked.connect(self._toggle_probe_mode)
        self.btn_probe_src.clicked.connect(self._toggle_probe_source)
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
        mid.addWidget(self.adj_container)

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.addLayout(top)
        lay.addLayout(mid, 1)
        lay.addWidget(self.pixel_info)
        self.setCentralWidget(root)
        self._update_adjust_panel_visibility()
        self._beautify_controls()

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
            self.btn_peek, self.btn_probe, self.btn_probe_src, self.btn_11, self.btn_fit, self.btn_link
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
            if right_render is not None:
                right_txt = (
                    f"右图 渲染后(x={right_render['x']}, y={right_render['y']}) "
                    f"R={right_render['r']} G={right_render['g']} B={right_render['b']} Gray={right_render['gray']}"
                )
            self.pixel_info.setText(f"{left_txt} || {right_txt} | 类型: uint8")
            return

        left_raw = self.left.sample_raw_at(left_render["x"], left_render["y"]) if left_render is not None else None
        right_raw = self.right.sample_raw_at(right_render["x"], right_render["y"]) if right_render is not None else None
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
        if pane.base_rgb is None:
            return
        pane.render_request_id += 1
        req_id = pane.render_request_id
        base = pane.base_rgb
        params = dict(pane.params)

        def task():
            return fast_preview_adjust(base, params) if preview else apply_adjustments(base, params)

        fut = self._executor.submit(task)

        def done_cb(f):
            try:
                out = f.result()
            except Exception:
                return
            self.adjust_done.emit(pane, req_id, out)

        fut.add_done_callback(done_cb)

    def _on_adjust_done(self, pane: Pane, request_id: int, out: np.ndarray):
        if request_id != pane.render_request_id:
            return
        pane.show_rendered_rgb(out, reset_view=False)

    def _toggle_link(self):
        self._link = not self._link
        self.btn_link.setText(f"同步·{'开' if self._link else '关'}")
        self._refresh_toggle_button_styles()

    def _sync(self, dst: Pane, s: ViewState):
        if self._single_view:
            return
        if not self._link or self._sync_lock or not dst.v.has_image():
            return
        self._sync_lock = True
        try:
            dst.v.apply_state(s)
        finally:
            self._sync_lock = False

    def _pick_file(self) -> Optional[str]:
        filt = (
            "Images (*.dng *.nef *.cr2 *.cr3 *.arw *.raf *.rw2 *.orf *.pef *.srw *.raw "
            "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp)"
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
        self.msg.setText(f"加载中: {os.path.basename(path)} ...")
        vp = pane.v.viewport().size()
        target = (vp.width(), vp.height())

        def task():
            return ShotwellRawDecoder.load(path, target_size=target)

        fut = self._executor.submit(task)

        def done_cb(f):
            try:
                rgb, raw_info = f.result()
                self.load_done.emit(pane, path, rgb, raw_info)
            except Exception as e:
                self.load_done.emit(pane, path, None, e)

        fut.add_done_callback(done_cb)

    def _on_load_done(self, pane: Pane, path: str, rgb: Optional[np.ndarray], raw_or_err):
        if rgb is None:
            self.msg.setText(f"加载失败: {raw_or_err}")
            return
        pane.set_baseline(path, rgb, raw_or_err)
        if pane is self.left:
            self.left_adj.set_values(dict(DEFAULT_ADJUSTMENTS))
        else:
            self.right_adj.set_values(dict(DEFAULT_ADJUSTMENTS))
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
    app = QApplication(sys.argv)
    w = Window()

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

    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
