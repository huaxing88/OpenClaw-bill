from __future__ import annotations

"""Auto estimate column splits for the daily-ledger layout.

Goal
----
Given a photo of the ledger page, estimate 3 vertical split positions (ratios) to
separate 4 columns:
    customer | product+qty | formula(jin×price=amt) | payment

Why
---
Fixed `column_x_splits` works only when the camera framing is consistent.
For tilted/shifted photos, splits drift and cause cross-column pollution.

Method (V4 baseline)
-------------------
Use vertical projection over a binarized text mask:
1) grayscale + CLAHE for contrast
2) adaptive threshold (text = 1)
3) morphological open to remove noise
4) compute column-wise ink density
5) within windows around expected split ratios, find local minima

This method is fast, training-free, and robust enough to provide a good first
guess. It can be further improved with table-line detection if needed.
"""

from dataclasses import dataclass
from typing import List

import cv2
import numpy as np


@dataclass
class AutoSplitConfig:
    enabled: bool = False
    expected_splits: List[float] = None  # e.g. [0.20, 0.52, 0.86]
    search_window: float = 0.08  # +- ratio window
    smooth_kernel: int = 31


def _smooth_1d(x: np.ndarray, k: int) -> np.ndarray:
    k = int(k)
    if k <= 1:
        return x
    if k % 2 == 0:
        k += 1
    pad = k // 2
    xp = np.pad(x, (pad, pad), mode="edge")
    ker = np.ones(k, dtype=np.float32) / k
    return np.convolve(xp, ker, mode="valid")


def estimate_column_splits(
    img_bgr: np.ndarray,
    expected_splits: List[float] | None = None,
    search_window: float = 0.08,
    smooth_kernel: int = 31,
    center_penalty: float = 0.25,
) -> List[float]:
    """Estimate column split ratios.

    Args:
        img_bgr: BGR image (already cropped if needed)
        expected_splits: prior ratios for 3 splits
        search_window: search range around expected split
        smooth_kernel: smoothing kernel for projection

    Returns:
        list of 3 ratios in (0,1), sorted.
    """

    h, w = img_bgr.shape[:2]
    if expected_splits is None:
        expected_splits = [0.20, 0.52, 0.86]

    # 1) grayscale + contrast
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # 2) adaptive threshold (invert so text=1)
    bw = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 10
    )

    # 3) remove thin noise
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel, iterations=1)

    # 4) vertical projection
    ink = (bw > 0).astype(np.float32)
    proj = ink.mean(axis=0)  # 0..1, lower means more blank
    proj_s = _smooth_1d(proj, smooth_kernel)

    splits_px = []
    for s in expected_splits:
        cx = int(w * float(s))
        half = int(w * float(search_window))
        l = max(0, cx - half)
        r = min(w - 1, cx + half)
        seg = proj_s[l : r + 1]
        if seg.size == 0:
            splits_px.append(cx)
            continue

        # Prefer blank positions but penalize drifting too far from the expected center.
        # This stabilizes the customer split which is sensitive to small shifts.
        xs = np.arange(l, r + 1, dtype=np.float32)
        dist = np.abs(xs - float(cx)) / max(1.0, float(half))  # 0..1
        score = seg.astype(np.float32) + float(center_penalty) * dist
        idx = int(np.argmin(score))
        splits_px.append(l + idx)

    # sanitize & sort, also enforce increasing and avoid extreme edges
    splits_px = sorted(set(int(x) for x in splits_px))
    # if duplicates collapsed, fall back to expected
    if len(splits_px) != 3:
        splits_px = [int(w * float(s)) for s in expected_splits]

    # enforce monotonic with min gap
    min_gap = max(20, int(w * 0.03))
    fixed = [splits_px[0]]
    for x in splits_px[1:]:
        if x - fixed[-1] < min_gap:
            x = fixed[-1] + min_gap
        fixed.append(min(x, w - 20))

    # convert to ratios
    out = [max(0.02, min(0.98, x / w)) for x in fixed]
    out = sorted(out)
    return out
