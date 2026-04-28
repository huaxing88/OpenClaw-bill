from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

from .config import load_rules
from .layout import LineClusterer
from .ocr import PaddleOcrEngine
from .column_ocr import recognize_by_columns
from .image_filters import maybe_crop_top_if_red_summary
from .parse_rules import RuleParser
from .validate import Validator
from .export_xlsx import XlsxExporter


def infer_sale_date_from_filename(path: str, cfg: dict) -> str | None:
    mp = (cfg.get("dataset", {}) or {}).get("filename_date_map", {})
    name = os.path.basename(path)
    for prefix, date_str in mp.items():
        if name.startswith(prefix):
            return date_str
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images_glob", required=True, help="Glob for input images")
    ap.add_argument("--rules", required=True, help="Rules yaml")
    ap.add_argument("--out_dir", required=True, help="Output directory")
    ap.add_argument("--lang", default="ch", help="PaddleOCR language")
    ap.add_argument("--start_order_no", type=int, default=None, help="Start sequence for order numbers")
    args = ap.parse_args()

    cfg = load_rules(args.rules)
    if args.start_order_no is not None:
        cfg.setdefault("batch_defaults", {}).setdefault("order_no_strategy", {})["seq_start"] = args.start_order_no

    # apply overrides.product_alias into lexicons.product_alias
    overrides = (cfg.get("overrides", {}) or {})
    if "product_alias" in overrides:
        cfg.setdefault("lexicons", {}).setdefault("product_alias", {})
        cfg["lexicons"]["product_alias"].update(overrides["product_alias"])

    image_paths = sorted(glob.glob(args.images_glob, recursive=True))
    if not image_paths:
        raise SystemExit(f"No images matched: {args.images_glob}")

    ocr = PaddleOcrEngine(lang=args.lang)
    clusterer = LineClusterer()
    parser = RuleParser(cfg)
    validator = Validator(cfg)

    all_records = []
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = out_dir / "records.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as jf:
        for img in image_paths:
            sale_date = infer_sale_date_from_filename(img, cfg)
            layout = (cfg.get('layout', {}) or {})
            strategy = layout.get('strategy', 'v2_whole_ocr')

            import cv2
            im = cv2.imread(img)
            if im is None:
                h, w = (None, None)
                lines = []
            else:
                # 如果启用红色汇总裁剪，保持 w/h 与 OCR 一致
                im2 = im
                if cfg is not None:
                    im2, should_skip = maybe_crop_top_if_red_summary(im, cfg)
                    if should_skip:
                        continue
                h, w = (im2.shape[0], im2.shape[1])

                if strategy == 'column_ocr':
                    blocks_by_col = recognize_by_columns(ocr, img, cfg)
                    anchor_col = layout.get('anchor_col', 'formula')
                    min_anchor = int(layout.get('min_anchor_blocks', 5))
                    if len(blocks_by_col.get(anchor_col, []) or []) < min_anchor:
                        # fallback to whole-image OCR if column split lost formulas
                        blocks = ocr.recognize(img, cfg=cfg)
                        lines = clusterer.cluster(blocks)
                    else:
                        lines = clusterer.cluster_by_anchor(
                            blocks_by_col,
                            anchor_col=anchor_col,
                            img_h=h,
                            header_ignore_y=float(layout.get('header_ignore_y', 0.0)),
                        anchor_header_ignore_y=float(layout.get('anchor_header_ignore_y', 0.04)),
                        )
                else:
                    blocks = ocr.recognize(img, cfg=cfg)
                    lines = clusterer.cluster(blocks)
            for line in lines:
                recs = parser.parse_line(line, sale_date=sale_date, img_w=w, img_h=h)
                for r in recs:
                    r = validator.validate(r)
                    all_records.append(r)
                    jf.write(json.dumps(r.to_review_dict(cfg.get("output", {}).get("review_columns", [])), ensure_ascii=False) + "\n")

    exporter = XlsxExporter(cfg)
    exporter.export(
        all_records,
        out_business_xlsx=str(out_dir / "business.xlsx"),
        out_review_xlsx=str(out_dir / "review.xlsx"),
    )

    print(f"Images: {len(image_paths)}")
    print(f"Records: {len(all_records)}")
    print(f"Wrote: {out_dir}")


if __name__ == "__main__":
    main()
