from __future__ import annotations

"""Column-based OCR utilities.

V3 strategy: split the ledger image into column ROIs first, then OCR each column
independently to reduce cross-column pollution (e.g., formulas leaking into product).

This module is intentionally self-contained and does NOT change the existing V2
pipeline unless wired in by the caller.

Key guarantees:
- Returned bboxes are mapped back to the ORIGINAL (possibly cropped) image coords.
- Column splits are relative ratios (0~1) against image width.

Typical usage:
    from ledger_poc.ocr import PaddleOcrEngine
    from ledger_poc.column_ocr import recognize_by_columns

    ocr = PaddleOcrEngine()
    blocks_by_col = recognize_by_columns(ocr, image_path, cfg)

"""

import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np

from .image_filters import maybe_crop_top_if_red_summary
from .models import OcrBlock
from .auto_column_splits import estimate_column_splits


@dataclass(frozen=True)
class ColumnRoi:
    """A column ROI in original image coordinates."""

    name: str
    x0: int
    y0: int
    x1: int
    y1: int


def _ensure_splits(splits: list[float] | None) -> list[float]:
    if not splits:
        return [0.20, 0.52, 0.86]
    out = [float(x) for x in splits]
    # ensure strictly increasing and within (0,1)
    out = [x for x in out if 0 < x < 1]
    out = sorted(out)
    if len(out) < 1:
        return [0.20, 0.52, 0.86]
    return out


def split_image_into_columns(
    img_bgr: np.ndarray,
    column_x_splits: list[float] | None,
    column_names: list[str] | None = None,
    margin_px: int = 12,
) -> list[Tuple[ColumnRoi, np.ndarray]]:
    """Split image into column ROIs.

    Args:
        img_bgr: Original image (BGR).
        column_x_splits: Relative x splits (0~1). For 4 columns, provide 3 splits.
        column_names: Optional names for each column.
        margin_px: Expand each ROI left/right by this many pixels (clipped).

    Returns:
        List of (ColumnRoi, roi_image_bgr) in left-to-right order.

    Notes:
        ROIs are in the coordinate system of the (possibly cropped) image passed in.
    """

    h, w = img_bgr.shape[:2]
    splits = _ensure_splits(column_x_splits)
    xs = [0] + [int(w * s) for s in splits] + [w]

    n_cols = len(xs) - 1
    if column_names is None or len(column_names) != n_cols:
        # Default 4-col ledger layout
        default = ["customer", "product", "formula", "payment"]
        column_names = default[:n_cols] + [f"col{i+1}" for i in range(len(default), n_cols)]

    out: list[Tuple[ColumnRoi, np.ndarray]] = []
    for i in range(n_cols):
        x0 = max(0, xs[i] - (margin_px if i > 0 else 0))
        x1 = min(w, xs[i + 1] + (margin_px if i < n_cols - 1 else 0))
        roi = img_bgr[:, x0:x1].copy()
        out.append((ColumnRoi(name=column_names[i], x0=x0, y0=0, x1=x1, y1=h), roi))

    return out


def _write_temp_image(img_bgr: np.ndarray) -> str:
    fd, tmp = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    cv2.imwrite(tmp, img_bgr)
    return tmp


def _map_blocks_to_original(blocks: list[OcrBlock], x_off: int, y_off: int) -> list[OcrBlock]:
    mapped: list[OcrBlock] = []
    for b in blocks:
        x1, y1, x2, y2 = b["bbox"]
        mapped.append(
            {
                "text": b["text"],
                "confidence": float(b.get("confidence", 0.0)),
                "bbox": [float(x1 + x_off), float(y1 + y_off), float(x2 + x_off), float(y2 + y_off)],
            }
        )
    return mapped


def recognize_by_columns(
    engine: Any,
    image_path: str,
    cfg: dict | None = None,
) -> Dict[str, List[OcrBlock]]:
    """Run OCR per column and return blocks grouped by column.

    Requirements on engine:
        engine must implement `recognize(image_path: str, cfg: dict|None=None) -> list[OcrBlock]`.

    This function will:
    1) read image
    2) (optional) crop/skip bottom red summary via existing filters
    3) split into columns
    4) OCR each ROI via engine
    5) map ROI bboxes back to the (cropped) image coordinates

    Returns:
        dict: {column_name: [OcrBlock, ...]}

    Important:
        If red_summary_skip.action == 'skip' and triggered, returns empty dict.
    """

    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Cannot read image: {image_path}")

    # Apply the same red-summary handling as V2 OCR, but operate on ndarray.
    if cfg is not None:
        img2, should_skip = maybe_crop_top_if_red_summary(img, cfg)
        if should_skip:
            return {}
        img = img2

    layout = (cfg or {}).get("layout", {}) or {}
    splits = layout.get("column_x_splits")
    margin_px = int(layout.get("column_margin_px", 12))
    names = layout.get("column_names")

    # V4: auto estimate splits to tolerate camera drift
    auto_cfg = (layout.get('auto_splits', {}) or {})
    if auto_cfg.get('enabled', False):
        splits = estimate_column_splits(
            img,
            expected_splits=auto_cfg.get('expected_splits') or splits,
            search_window=float(auto_cfg.get('search_window', 0.08)),
            smooth_kernel=int(auto_cfg.get('smooth_kernel', 31)),
            center_penalty=float(auto_cfg.get('center_penalty', 0.25)),
        )

    rois = split_image_into_columns(img, splits, column_names=names, margin_px=margin_px)

    blocks_by_col: Dict[str, List[OcrBlock]] = {}

    # We cannot pass ndarray to PaddleOCR predict reliably across versions,
    # so we write ROIs into temp files.
    for roi_meta, roi_img in rois:
        tmp = _write_temp_image(roi_img)
        try:
            blocks_roi: list[OcrBlock] = engine.recognize(tmp, cfg=None)
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass

        blocks_by_col[roi_meta.name] = _map_blocks_to_original(blocks_roi, x_off=roi_meta.x0, y_off=roi_meta.y0)

    return blocks_by_col
