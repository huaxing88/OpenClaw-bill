from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .models import ParseRecord


@dataclass
class XlsxExporter:
    cfg: dict[str, Any]

    def export(self, records: list[ParseRecord], out_business_xlsx: str, out_review_xlsx: str):
        review_cols = self.cfg.get("output", {}).get("review_columns", [])
        business_rows = [r.to_business_dict() for r in records]
        review_rows = [r.to_review_dict(review_cols) for r in records]


        def to_md(ds):
            if not ds: return ds
            ds = str(ds)
            if "-" in ds:
                parts = ds.split("-")
                if len(parts) >= 3:
                    return f"{int(parts[1])}月{int(parts[2])}日"
            return ds

        def inject_formulas(rows: list[dict]):
            for i, r in enumerate(rows):
                row_idx = i + 2 # Header is row 1
                import numpy as np
                # Ensure no "nan" strings break formulas
                for k in ["量/斤", "单价", "扣款/优惠", "其它费用"]:
                    if pd.isna(r.get(k)) or r.get(k) == "":
                        r[k] = None
                        
                if "日期" in r:
                    r["日期"] = to_md(r["日期"])

                # Excel coordinates: highly resilient formulas avoiding #VALUE!
                r["销售额"] = f'=IF(AND(ISNUMBER(F{row_idx}), ISNUMBER(G{row_idx})), F{row_idx}*G{row_idx}-SUM(H{row_idx}), "")'
                r["应收金额"] = f'=SUM(I{row_idx}, J{row_idx})'
                r["未收金额"] = f'=IF(L{row_idx}="挂账", SUM(K{row_idx}), 0)'
                r["已收金额"] = f'=IF(L{row_idx}="挂账", 0, SUM(K{row_idx}))'

        inject_formulas(business_rows)
        inject_formulas(review_rows)

        Path(out_business_xlsx).parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(out_business_xlsx, engine="openpyxl") as w:
            pd.DataFrame(business_rows).to_excel(w, index=False, sheet_name="Sheet1")

        with pd.ExcelWriter(out_review_xlsx, engine="openpyxl") as w:
            pd.DataFrame(review_rows).to_excel(w, index=False, sheet_name="Sheet1")
