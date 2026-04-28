from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import ParseRecord


@dataclass
class Validator:
    cfg: dict[str, Any]

    def validate(self, rec: ParseRecord) -> ParseRecord:
        tol = float(self.cfg.get("fields", {}).get("amount_tolerance", 2))
        rounding = self.cfg.get("fields", {}).get("amount_rounding", "int")

        if rec.weight_jin is not None and rec.unit_price is not None and rec.sales_amount is not None:
            calc = rec.weight_jin * rec.unit_price
            if rounding == "int":
                calc = round(calc)
            else:
                calc = round(calc, 2)
            if abs(calc - rec.sales_amount) > tol:
                rec.validation_flags.append("AMOUNT_MISMATCH")
                rec.parse_confidence = max(0.0, rec.parse_confidence - 0.2)
        return rec
