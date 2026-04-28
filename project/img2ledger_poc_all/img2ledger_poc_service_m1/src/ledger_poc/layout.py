from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .models import Line, OcrBlock


@dataclass
class LineClusterer:
    y_gap_ratio: float = 0.8  # threshold = median_height * ratio

    def cluster(self, blocks: List[OcrBlock]) -> List[Line]:
        if not blocks:
            return []

        # compute height
        heights = [b["bbox"][3] - b["bbox"][1] for b in blocks]
        heights_sorted = sorted(heights)
        median_h = heights_sorted[len(heights_sorted) // 2]
        thr = max(6.0, median_h * self.y_gap_ratio)

        # sort blocks by y center
        def y_center(b: OcrBlock) -> float:
            return (b["bbox"][1] + b["bbox"][3]) / 2

        blocks_sorted = sorted(blocks, key=lambda b: (y_center(b), b["bbox"][0]))

        lines: list[list[OcrBlock]] = []
        cur: list[OcrBlock] = []
        cur_y: float | None = None

        for b in blocks_sorted:
            yc = y_center(b)
            if cur and cur_y is not None and abs(yc - cur_y) > thr:
                lines.append(cur)
                cur = [b]
                cur_y = yc
            else:
                cur.append(b)
                cur_y = yc if cur_y is None else (cur_y * 0.7 + yc * 0.3)
        if cur:
            lines.append(cur)

        out: list[Line] = []
        for i, lbs in enumerate(lines):
            lbs_sorted = sorted(lbs, key=lambda x: x["bbox"][0])
            text = " ".join([x["text"] for x in lbs_sorted if str(x["text"]).strip()])
            yc = sum((x["bbox"][1] + x["bbox"][3]) / 2 for x in lbs_sorted) / len(lbs_sorted)
            out.append(Line(line_id=i, y_center=yc, text=text, blocks=lbs_sorted))
        return out

    def cluster_by_anchor(
        self,
        blocks_by_col: Dict[str, List[OcrBlock]],
        anchor_col: str = "formula",
        img_h: int | None = None,
        header_ignore_y: float = 0.0,
        anchor_header_ignore_y: float | None = None,
    ) -> List[Line]:
        """Cluster lines using one column (anchor) and stitch blocks from all columns.

        V3 strategy: use the formula column as the anchor to form line groups (because
        each detail row usually contains a formula like `斤×单价=金额`). Then, for each
        anchor line, collect blocks from other columns whose y-center is close enough.

        Args:
            blocks_by_col: output of column_ocr.recognize_by_columns()
            anchor_col: which column to use as line anchor

        Returns:
            List[Line] with `blocks` containing merged blocks from all columns.
        """

        anchor_blocks = list(blocks_by_col.get(anchor_col, []) or [])

        # Filter out header area blocks and non-formula noise
        if anchor_blocks:
            hy = header_ignore_y if anchor_header_ignore_y is None else anchor_header_ignore_y
            y_thr = int((img_h or 0) * float(hy)) if img_h else 0

            def looks_like_formula(t: str) -> bool:
                if not t:
                    return False
                has_digit = any(ch.isdigit() for ch in t)
                has_op = ('×' in t) or ('x' in t) or ('X' in t) or ('=' in t) or ('＝' in t)
                return has_digit and has_op

            anchor_blocks = [
                b
                for b in anchor_blocks
                if b["bbox"][3] >= y_thr and looks_like_formula(str(b.get("text", "")))
            ]
        # If anchor blocks are empty, fall back to clustering all blocks.
        if not anchor_blocks:
            merged = []
            for v in blocks_by_col.values():
                merged.extend(v)
            return self.cluster(merged)

        anchor_lines = self.cluster(anchor_blocks)

        # Re-compute threshold based on anchor blocks (same logic as cluster)
        heights = [b["bbox"][3] - b["bbox"][1] for b in anchor_blocks]
        heights_sorted = sorted(heights)
        median_h = heights_sorted[len(heights_sorted) // 2]
        thr = max(6.0, median_h * self.y_gap_ratio)

        def y_center(b: OcrBlock) -> float:
            return (b["bbox"][1] + b["bbox"][3]) / 2

        out: List[Line] = []
        for i, al in enumerate(anchor_lines):
            yc = al.y_center
            merged: List[OcrBlock] = []
            for col, blocks in blocks_by_col.items():
                for b in blocks:
                    if abs(y_center(b) - yc) <= thr:
                        merged.append(b)
            merged_sorted = sorted(
                merged,
                key=lambda b: (((b["bbox"][1] + b["bbox"][3]) / 2), b["bbox"][0]),
            )
            text = " ".join([str(x["text"]) for x in merged_sorted if str(x["text"]).strip()])
            out.append(Line(line_id=i, y_center=yc, text=text, blocks=merged_sorted))

        return out
