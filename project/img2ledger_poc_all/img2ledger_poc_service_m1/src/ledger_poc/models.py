from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict


class OcrBlock(TypedDict):
    text: str
    bbox: list[float]  # [x1,y1,x2,y2]
    confidence: float


@dataclass
class Line:
    line_id: int
    y_center: float
    text: str
    blocks: list[OcrBlock]


@dataclass
class ParseRecord:
    sale_date: str | None
    order_no: str | None
    customer_name: str | None
    product: str | None
    qty_units: float | None
    weight_jin: float | None
    unit_price: float | None
    discount: float | None
    sales_amount: float | None
    other_fee: float | None
    receivable: float | None
    pay_method: str | None
    receipt_date: str | None
    unpaid: float | None
    paid: float | None
    remark: str | None

    # audit
    ocr_raw_line: str
    parse_confidence: float
    validation_flags: list[str]

    def to_business_dict(self) -> dict[str, Any]:
        return {
            "日期": self.sale_date,
            "单号": self.order_no,
            "客户名称": self.customer_name,
            "品名": self.product,
            "量/只": self.qty_units,
            "量/斤": self.weight_jin,
            "单价": self.unit_price,
            "扣款/优惠": self.discount,
            "销售额": self.sales_amount,
            "其它费用": self.other_fee,
            "应收金额": self.receivable,
            "收款方式": self.pay_method,
            "收款日期": self.receipt_date,
            "未收金额": self.unpaid,
            "已收金额": self.paid,
            "备注": self.remark,
        }

    def to_review_dict(self, review_cols: list[str]) -> dict[str, Any]:
        d = self.to_business_dict()
        if "ocr_raw_line" in review_cols:
            d["ocr_raw_line"] = self.ocr_raw_line
        if "parse_confidence" in review_cols:
            d["parse_confidence"] = self.parse_confidence
        if "validation_flags" in review_cols:
            d["validation_flags"] = ",".join(self.validation_flags)
        return d
