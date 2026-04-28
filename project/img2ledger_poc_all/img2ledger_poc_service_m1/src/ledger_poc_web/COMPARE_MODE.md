# 双引擎对比模式（Web API）设计说明

## 目标
在同一次上传解析中，同时运行：
- **PaddleOCR（主引擎）**：使用当前规则文件中的配置（默认 V4：`column_ocr + auto_splits` 等）
- **模拟对比引擎（Baseline）**：用同一套 PaddleOCR，但强制采用更“朴素/保守”的策略，作为对比基线

> 由于部署环境为 Linux CPU 且 `ocr_services-master` 无法运行，本阶段用“Baseline pipeline”模拟第二引擎，便于后续替换为真实第二引擎。

## API
### POST /v1/parse
新增表单字段：
- `mode`: `single` | `compare`（默认 single）
- `compare_engine`: `baseline`（预留扩展）

返回：
- single: 与现有一致
- compare: 增加 `files.engine_a`, `files.engine_b`, `files.compare_xlsx`

## 输出目录结构
`web_storage/outputs/{job_id}/`
- `engine_a/`
  - `business.xlsx`
  - `review.xlsx`
- `engine_b/`
  - `business.xlsx`
  - `review.xlsx`
- `compare.xlsx`（两引擎差异对照）

## 引擎定义
- engine_a：按 rules 原样执行
- engine_b（baseline）：在内存中覆盖 cfg：
  - `layout.strategy = v2_whole_ocr`
  - `layout.auto_splits.enabled = false`
  - 保留其他业务规则（折扣/客户映射/红汇总裁剪等）

## compare.xlsx内容
- `summary`：两引擎行数、匹配数、未匹配数
- `matched_diff`：按 `(量/斤, 单价, 销售额)` 模糊匹配后的字段对照（A vs B）
- `unmatched_a` / `unmatched_b`

