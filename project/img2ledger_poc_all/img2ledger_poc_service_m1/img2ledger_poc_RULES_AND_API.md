# 解析规则库与接口约定（V1）

本目录用于“手写账本图片 → 明细表（Excel）”解析规则的可配置化落地。

## 1. 规则库文件

### 1.1 `rules/default.yml`
用于通用解析规则（符号规范化、常见正则、收款方式词典、字段默认策略等）。

建议结构：
```yml
version: 1

normalize:
  multiply_symbols: ["x", "X", "×"]
  equals_symbols: ["=", "＝"]
  colon_symbols: [":", "："]
  remove_spaces: true

excel:
  date_origin: "excel_1900"   # 用于将 Excel 序列号 ↔ 日期

batch_defaults:
  receipt_date_strategy: "same_as_sale_date"  # or manual
  order_no_strategy:
    type: "date_prefix_seq"  # date_prefix_seq | seq_only
    seq_start: 10000

fields:
  amount_tolerance: 2
  amount_rounding: "int"      # int | 2dp
  receivable_strategy: "same_as_sales"  # same_as_sales | sales_minus_discount

patterns:
  formula:
    # 斤×单价=金额
    - name: "jin_price_amount"
      regex: "(?P<jin>\\d+(?:\\.\\d+)?)\\s*[x×X]\\s*(?P<price>\\d+(?:\\.\\d+)?)\\s*[=＝]\\s*(?P<amount>\\d+(?:\\.\\d+)?)"

  subtotal:
    - name: "subtotal"
      regex: "(?:小计|合计|总计)\\s*[：:]\\s*(?P<subtotal>\\d+(?:\\.\\d+)?)"

lexicons:
  payment_method:
    "现金": "现金"
    "微信": "微信"
    "支付宝": "支付宝"
    "银行卡": "银行卡"
    "收": "微信"  # 视你的习惯可改：红勾“收”默认按微信/已收
    "支": "现金"  # 示例

  product_alias:
    "龙": "澳纽龙-沃龙"
    "直虾": "澳纽龙-直虾"
    "帝王": "帝王蟹"

parsing:
  customer:
    # 行首客户名提取：默认取行首到第一个空格/分隔符
    strategy: "prefix_token"
    max_len: 8

  product:
    strategy: "between_customer_and_formula"

  ratio_token:
    enabled: true
    semantics_default: "units_over_jin"  # units_over_jin | jin_over_units | unknown

output:
  review_columns:
    - ocr_raw_line
    - parse_confidence
    - validation_flags
```

### 1.2 `rules/dataset_2603.yml`
用于 2603 数据集的“日期-图片匹配”、以及对特定客户/品名/记法的覆盖规则。

建议结构：
```yml
extends: "default.yml"

dataset:
  name: "2603销售明细表"
  images_glob: "dataset_2603/**/3-*.jpg"

  # 图片名 → 日期（用于生成输出日期字段与对齐人工表）
  filename_date_map:
    "3-19": "2026-03-19"
    "3-20": "2026-03-20"
    "3-21": "2026-03-21"
    "3-22": "2026-03-22"
    "3-23": "2026-03-23"
    "3-24": "2026-03-24"
    "3-25": "2026-03-25"
    "3-26": "2026-03-26"
    "3-27": "2026-03-27"
    "3-28": "2026-03-28"
    "3-29": "2026-03-29"

overrides:
  ratio_semantics_by_customer:
    "散客": "units_over_jin"

  product_alias:
    "黑包": "黑全包"  # 示例
```

## 2. 接口约定

### 2.1 OCR 引擎接口 `IOcrEngine`
- 输入：图片路径
- 输出：文本块列表（含 bbox 与置信度）

```python
class OcrBlock(TypedDict):
    text: str
    bbox: list[float]  # [x1,y1,x2,y2] or 4 points
    confidence: float

class IOcrEngine(Protocol):
    def recognize(self, image_path: str) -> list[OcrBlock]:
        ...
```

### 2.2 解析主入口 `LedgerParser`
```python
class ParseResult(TypedDict):
    records: list[dict]           # 一行一个 record，字段名对齐 Excel
    debug: dict                   # 中间产物（行聚类、类型、置信度）

class LedgerParser:
    def parse_document(self, image_path: str, sale_date: str | None = None) -> ParseResult:
        ...
```

### 2.3 导出接口
```python
class Exporter:
    def export(self, records: list[dict], out_business_xlsx: str, out_review_xlsx: str):
        ...
```

## 3. PoC 目录结构约定
见项目根目录 `README.md`。

### 1.3 `rules/ledger_handwrite_v1.yml`
专门适配「每日销售图片」这种 4 列手写账单（客户 | 品名+只数 | 斤×单价=金额 | 收款方式/红勾）的规则文件。

关键参数：
- `layout.column_x_splits`：按图片宽度比例切 3 条竖线，形成 4 列。
  - 例：`[0.20, 0.52, 0.86]` 表示：
    - 0~0.20：客户名
    - 0.20~0.52：品名 + 量/只
    - 0.52~0.86：量/斤 + 单价 + 销售额（算式）
    - 0.86~1.00：收款方式/红勾
- `business_rules.discount_from_fractional_part`：启用「斤×单价 的小数部分作为扣款/优惠」的业务规则（写入负数）。
- `payment.red_checkmark_means_paid`：启用「红色打勾代表已付款」的兜底识别；当只有勾、没有“微/支/现”等字时，使用 `checkmark_default_method`。
- `skip_pages.red_summary_skip`：用于处理类似 `3-27-2.jpg` 的底部红色汇总干扰。
  - `bottom_ratio`：取图片底部多少比例区域做红色像素检测
  - `red_pixel_ratio_thresh`：红色像素占比阈值，超过则执行 `action`
  - `action: crop_top`：只保留上半部分（裁掉底部红色汇总）
- `customer_mapping`：客户名映射（优先从固定名单中做“包含匹配/最长优先”），提升 OCR 误识别下的稳定性。

> 注：如果你的拍照角度/纸张位置变化较大，优先微调 `layout.column_x_splits` 与 `layout.header_ignore_y`。
