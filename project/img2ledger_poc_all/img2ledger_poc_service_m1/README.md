# img2ledger_poc（手写账本转表格 PoC）

本项目是“手写账本自动转表格”系统的 **可跑 PoC**，重点交付：
1) 一套可直接落地的 **解析规则库**（YAML）
2) 一套可运行的 **解析管线**（PaddleOCR → 行聚类 → 规则解析 → 校验 → 导出 Excel）

## 1. 数据集（你提供的 2603销售明细表.zip）
- 图片：`dataset_2603/**/3-*.jpg`
- 人工明细表：`dataset_2603/**/2603*.xlsx`（sheet: `3月销售明细`）

## 2. 快速开始

### 2.1 安装依赖
本环境已自带 `paddle`/`paddleocr`（如你本地没有，可 pip 安装）：

```bash
pip install -U paddleocr
```

### 2.2 运行：解析指定日期的图片并导出

```bash
cd img2ledger_poc

# 解析 3-21 的所有图片，输出到 outputs/
python -m ledger_poc.run \
  --images_glob "../dataset_2603/**/3-21*.jpg" \
  --rules "rules/dataset_2603.yml" \
  --out_dir "outputs/3-21"
```

输出：
- `outputs/3-21/business.xlsx`：业务版（模板字段）
- `outputs/3-21/review.xlsx`：校对版（含审计列）
- `outputs/3-21/records.jsonl`：每行一条 JSON（含 flags/confidence）

### 2.3 运行：与人工表“按日汇总对账”（PoC 级）
```bash
python scripts/evaluate_by_day.py \
  --gt_xlsx "../dataset_2603/**/2603*.xlsx" \
  --pred_jsonl "outputs/3-21/records.jsonl" \
  --day "2026-03-21"
```

[1m注意[0m：PoC 的评估默认按“日期-客户-品名”聚合对比金额（不做逐行严格对齐），用于快速验证规则是否大体正确。

## 3. Web API 服务（FastAPI）

### 3.1 启动服务

```bash
cd img2ledger_poc
pip install -r requirements.txt

export PYTHONPATH=$PWD/src
export DISABLE_MODEL_SOURCE_CHECK=True

uvicorn ledger_poc_web.main:app --host 0.0.0.0 --port 8000
```

### 3.2 上传图片并获取 Excel 下载链接

```bash
curl -X POST "http://127.0.0.1:8000/v1/parse" \
  -F "file=@../dataset_2603/**/3-20.jpg" \
  -F "rules_path=rules/dataset_2603.yml" \
  -F "sale_date=2026-03-20" \
  -F "lang=ch"
```

响应示例：
```json
{
  "job_id": "e3b1c44298fc",
  "records": 20,
  "files": {
    "business_xlsx": "/downloads/e3b1c44298fc/business.xlsx",
    "review_xlsx": "/downloads/e3b1c44298fc/review.xlsx"
  }
}
```

然后直接打开：
- `http://127.0.0.1:8000/downloads/<job_id>/business.xlsx`

[1m注意[0m：首次启动 PaddleOCR 会自动下载模型，耗时较长。

## 4. 目录结构

```
img2ledger_poc/
  src/ledger_poc/
    run.py                # CLI
    config.py             # 规则加载（支持 extends）
    ocr.py                # PaddleOCR 适配
    layout.py             # 行聚类
    parse_rules.py        # 规则解析器（正则+启发式）
    validate.py           # 校验与 flags
    export_xlsx.py        # 导出 business/review xlsx
    models.py             # 数据结构
  rules/
    default.yml
    dataset_2603.yml
  scripts/
    evaluate_by_day.py
  outputs/
```

## 4. 接口约定
见同目录文档：`../img2ledger_poc_RULES_AND_API.md`
