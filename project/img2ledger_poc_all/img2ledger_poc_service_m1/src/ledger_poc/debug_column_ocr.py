from __future__ import annotations

import json
from pathlib import Path

from ledger_poc.config import load_rules
from ledger_poc.ocr import PaddleOcrEngine
from ledger_poc.column_ocr import recognize_by_columns


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--out", default="/home/user/workspace/column_ocr_debug.json")
    args = ap.parse_args()

    cfg = load_rules(args.rules)
    ocr = PaddleOcrEngine()
    blocks_by_col = recognize_by_columns(ocr, args.image, cfg)

    # keep it small: dump counts and first few texts per col
    summary = {}
    for k, blocks in blocks_by_col.items():
        summary[k] = {
            "count": len(blocks),
            "sample": [b["text"] for b in blocks[:15]],
        }

    Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
