from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from paddleocr import PaddleOCR

from .models import OcrBlock
from .image_filters import maybe_crop_top_if_red_summary


@dataclass
class PaddleOcrEngine:
    lang: str = "ch"
    use_angle_cls: bool = True

    def __post_init__(self):
        # PaddleOCR will download models at first run
        # PaddleOCR 3.x: show_log 参数可能不可用
        self._ocr = PaddleOCR(lang=self.lang, use_angle_cls=self.use_angle_cls)

    def recognize(self, image_path: str, cfg: dict | None = None) -> list[OcrBlock]:
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")

        # 跳过/裁剪底部红色汇总（如 3-27-2）
        if cfg is not None:
            img2, should_skip = maybe_crop_top_if_red_summary(img, cfg)
            if should_skip:
                return []
            img = img2

        # PaddleOCR 3.x predict 参数通常直接传入路径/URL。
        # 但我们可能做了裁剪，因此这里统一传 ndarray 给 predict（某些版本不支持）。
        # 为兼容，优先传路径；裁剪后用临时文件。
        if cfg is None:
            res = self._ocr.predict(image_path)
        else:
            import tempfile
            import os
            fd, tmp = tempfile.mkstemp(suffix='.jpg')
            os.close(fd)
            cv2.imwrite(tmp, img)
            res = self._ocr.predict(tmp)
            try:
                os.remove(tmp)
            except Exception:
                pass
        blocks: list[OcrBlock] = []
        # res: iterable of result objects; each contains 'dt_polys' and 'rec_text' etc
        # 兼容不同版本：尽量从字典/属性中取出
        # 将结果摊平成 blocks
        def pick(*vals):
            for v in vals:
                if v is None:
                    continue
                # numpy array: avoid `or` truthiness
                if isinstance(v, np.ndarray):
                    if v.size == 0:
                        continue
                    return v
                if isinstance(v, (list, tuple)):
                    if len(v) == 0:
                        continue
                    return v
                # other types (str/dict/etc)
                return v
            return []

        for page in res:
            # page 可能是 dict，也可能是对象
            if isinstance(page, dict):
                polys = pick(page.get('dt_polys'), page.get('rec_polys'), page.get('rec_boxes'), page.get('boxes'))
                texts = pick(page.get('rec_texts'), page.get('rec_text'), page.get('text'))
                scores = pick(page.get('rec_scores'), page.get('rec_score'), page.get('scores'))
            else:
                polys = pick(getattr(page, 'dt_polys', None), getattr(page, 'rec_polys', None), getattr(page, 'rec_boxes', None), getattr(page, 'boxes', None))
                texts = pick(getattr(page, 'rec_texts', None), getattr(page, 'rec_text', None), getattr(page, 'text', None))
                scores = pick(getattr(page, 'rec_scores', None), getattr(page, 'rec_score', None), getattr(page, 'scores', None))

            for box, text, conf in zip(polys, texts, scores):
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                x1, y1, x2, y2 = float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))
                blocks.append({"text": str(text), "bbox": [x1, y1, x2, y2], "confidence": float(conf)})
        return blocks
