from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ledger_poc.config import load_rules
from ledger_poc.layout import LineClusterer
from ledger_poc.ocr import PaddleOcrEngine
from ledger_poc.column_ocr import recognize_by_columns
from ledger_poc.image_filters import maybe_crop_top_if_red_summary
from ledger_poc.parse_rules import RuleParser
from ledger_poc.validate import Validator
from ledger_poc.export_xlsx import XlsxExporter
from ledger_poc.compare_two_predictions import export_compare_xlsx

import threading
from concurrent.futures import ThreadPoolExecutor


# Project layout: img2ledger_poc/src/ledger_poc_web/main.py
# parents[1] -> .../img2ledger_poc/src
APP_ROOT = Path(__file__).resolve().parents[1]
STORAGE_ROOT = (APP_ROOT / ".." / "web_storage").resolve()
UPLOAD_DIR = STORAGE_ROOT / "uploads"
OUTPUT_DIR = STORAGE_ROOT / "outputs"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="img2ledger API", version="0.1")

# --- OCR Singletons ---
# PaddleOCR initialization is expensive on CPU. Keep singleton instances per language.
_OCR_LOCK = threading.Lock()
_OCR_ENGINES: dict[str, PaddleOcrEngine] = {}


def get_ocr_engine(lang: str) -> PaddleOcrEngine:
    with _OCR_LOCK:
        eng = _OCR_ENGINES.get(lang)
        if eng is None:
            eng = PaddleOcrEngine(lang=lang)
            _OCR_ENGINES[lang] = eng
        return eng

# Serve downloadable files
app.mount("/downloads", StaticFiles(directory=str(OUTPUT_DIR)), name="downloads")


@app.get("/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat() + "Z"}


@app.post("/v1/parse")
async def parse_ledger(
    file: UploadFile = File(...),
    rules_path: str = Form("rules/dataset_2603.yml"),
    sale_date: Optional[str] = Form(None),
    lang: str = Form("ch"),
    mode: str = Form("single"),  # single | compare
    start_order_no: Optional[int] = Form(None),
):
    """Upload a ledger image and return Excel download links.

    - file: jpg/png
    - rules_path: path relative to project root (img2ledger_poc/) or absolute
    - sale_date: optional override YYYY-MM-DD
    - start_order_no: optional override for first order number
    """

    # Resolve rules path
    project_root = (APP_ROOT / "..").resolve()
    rp = Path(rules_path)
    if not rp.is_absolute():
        rp = (project_root / rp).resolve()

    job_id = uuid.uuid4().hex[:12]
    suffix = Path(file.filename or "upload.jpg").suffix or ".jpg"
    upload_path = UPLOAD_DIR / f"{job_id}{suffix}"

    content = await file.read()
    upload_path.write_bytes(content)

    cfg = load_rules(str(rp))
    if start_order_no is not None:
        cfg.setdefault("batch_defaults", {}).setdefault("order_no_strategy", {})["seq_start"] = start_order_no

    overrides = (cfg.get("overrides", {}) or {})
    if "product_alias" in overrides:
        cfg.setdefault("lexicons", {}).setdefault("product_alias", {})
        cfg["lexicons"]["product_alias"].update(overrides["product_alias"])

    def run_once(cfg_local: dict, out_subdir: Path, ocr: PaddleOcrEngine):
        clusterer = LineClusterer()
        parser = RuleParser(cfg_local)
        validator = Validator(cfg_local)

        import cv2
        im = cv2.imread(str(upload_path))
        if im is None:
            h, w = (None, None)
            lines = []
        else:
            im2, should_skip = maybe_crop_top_if_red_summary(im, cfg_local)
            if should_skip:
                return [], (im.shape[1], im.shape[0])
            h, w = (im2.shape[0], im2.shape[1])
            layout = (cfg_local.get('layout', {}) or {})
            strategy = layout.get('strategy', 'v2_whole_ocr')
            if strategy == 'column_ocr':
                blocks_by_col = recognize_by_columns(ocr, str(upload_path), cfg_local)
                anchor_col = layout.get('anchor_col', 'formula')
                min_anchor = int(layout.get('min_anchor_blocks', 5))
                if len(blocks_by_col.get(anchor_col, []) or []) < min_anchor:
                    blocks = ocr.recognize(str(upload_path), cfg=cfg_local)
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
                blocks = ocr.recognize(str(upload_path), cfg=cfg_local)
                lines = clusterer.cluster(blocks)

        records = []
        for line in lines:
            recs = parser.parse_line(line, sale_date=sale_date, img_w=w, img_h=h)
            for r in recs:
                records.append(validator.validate(r))

        out_subdir.mkdir(parents=True, exist_ok=True)
        exporter = XlsxExporter(cfg_local)
        exporter.export(
            records,
            out_business_xlsx=str(out_subdir / "business.xlsx"),
            out_review_xlsx=str(out_subdir / "review.xlsx"),
        )
        return records, (w, h)

    out_dir = OUTPUT_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    mode = (mode or 'single').strip().lower()
    base = f"/downloads/{job_id}"

    # get singleton engine
    ocr_singleton = get_ocr_engine(lang)

    if mode != 'compare':
        records, _ = run_once(cfg, out_dir, ocr_singleton)
        return JSONResponse(
            {
                "job_id": job_id,
                "mode": "single",
                "records": len(records),
                "files": {
                    "business_xlsx": f"{base}/business.xlsx",
                    "review_xlsx": f"{base}/review.xlsx",
                },
            }
        )

    # compare mode
    engine_a_dir = out_dir / "engine_a"
    engine_b_dir = out_dir / "engine_b"

    # engine_a uses cfg as-is
    # In compare mode we run two pipelines in parallel.
    # Use two OCR instances to avoid potential thread-safety issues.
    ocr_a = get_ocr_engine(lang)
    ocr_b = PaddleOcrEngine(lang=lang)  # lightweight compared to double parsing; avoids shared state

    def job_a():
        return run_once(cfg, engine_a_dir, ocr_a)

    # engine_b baseline: override layout to be conservative
    cfg_b = dict(cfg)
    cfg_b_layout = dict((cfg.get('layout', {}) or {}))
    cfg_b_layout['strategy'] = 'v2_whole_ocr'
    auto = dict((cfg_b_layout.get('auto_splits', {}) or {}))
    auto['enabled'] = False
    cfg_b_layout['auto_splits'] = auto
    cfg_b['layout'] = cfg_b_layout

    def job_b():
        return run_once(cfg_b, engine_b_dir, ocr_b)

    with ThreadPoolExecutor(max_workers=2) as ex:
        fa = ex.submit(job_a)
        fb = ex.submit(job_b)
        (records_a, _wha) = fa.result()
        (records_b, _whb) = fb.result()

    # build compare.xlsx (A vs B)
    compare_path = out_dir / 'compare.xlsx'
    export_compare_xlsx(
        business_a_path=str(engine_a_dir / 'business.xlsx'),
        business_b_path=str(engine_b_dir / 'business.xlsx'),
        out_xlsx_path=str(compare_path),
        engine_a_name='engine_a',
        engine_b_name='engine_b',
    )

    return JSONResponse(
        {
            "job_id": job_id,
            "mode": "compare",
            "records": {"engine_a": len(records_a), "engine_b": len(records_b)},
            "files": {
                "engine_a_business_xlsx": f"{base}/engine_a/business.xlsx",
                "engine_a_review_xlsx": f"{base}/engine_a/review.xlsx",
                "engine_b_business_xlsx": f"{base}/engine_b/business.xlsx",
                "engine_b_review_xlsx": f"{base}/engine_b/review.xlsx",
                "compare_xlsx": f"{base}/compare.xlsx",
            },
        }
    )
