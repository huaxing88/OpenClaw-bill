from __future__ import annotations

import cv2
import numpy as np


def red_pixel_ratio(img_bgr, bottom_ratio: float = 0.45) -> float:
    """Estimate red pixel ratio in bottom part of image."""
    h, w = img_bgr.shape[:2]
    y0 = int(h * (1 - bottom_ratio))
    crop = img_bgr[y0:, :, :]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # red ranges in HSV
    lower1 = np.array([0, 80, 80])
    upper1 = np.array([10, 255, 255])
    lower2 = np.array([160, 80, 80])
    upper2 = np.array([180, 255, 255])
    mask = cv2.inRange(hsv, lower1, upper1) | cv2.inRange(hsv, lower2, upper2)
    return float(mask.mean() / 255.0)


def maybe_crop_top_if_red_summary(img_bgr, cfg: dict):
    sp = (cfg.get('skip_pages', {}) or {}).get('red_summary_skip', {})
    if not sp.get('enabled', False):
        return img_bgr, False
    br = float(sp.get('bottom_ratio', 0.45))
    thr = float(sp.get('red_pixel_ratio_thresh', 0.10))
    action = sp.get('action', 'crop_top')

    ratio = red_pixel_ratio(img_bgr, bottom_ratio=br)
    if ratio < thr:
        return img_bgr, False

    if action == 'skip':
        return img_bgr, True

    # crop top (keep upper part)
    h = img_bgr.shape[0]
    y1 = int(h * (1 - br))
    return img_bgr[:y1, :, :].copy(), False
