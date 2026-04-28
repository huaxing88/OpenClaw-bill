from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Tuple

from .models import Line, ParseRecord


def normalize_text(s: str, cfg: dict[str, Any]) -> str:
    if s is None:
        return ""
    out = str(s)
    if cfg.get("normalize", {}).get("remove_spaces", True):
        out = re.sub(r"\s+", " ", out).strip()
    # unify symbols
    mults = cfg.get("normalize", {}).get("multiply_symbols", [])
    for m in mults:
        out = out.replace(m, "×")
    for e in cfg.get("normalize", {}).get("equals_symbols", []):
        out = out.replace(e, "=")
    # fullwidth colon etc
    out = out.replace(":", "：")
    return out


@dataclass
class RuleParser:
    cfg: dict[str, Any]
    last_customer: str | None = None

    def __post_init__(self):
        self.parsed_date = None
        seq_start = int(self.cfg.get("batch_defaults", {}).get("order_no_strategy", {}).get("seq_start", 6589))
        self.current_order_no = seq_start
        self._has_started_orders = False
        self.current_order_sum = 0.0

        self._formula_regexes: list[tuple[str, re.Pattern]] = []
        for item in self.cfg.get("patterns", {}).get("formula", []):
            self._formula_regexes.append((item.get("name", "formula"), re.compile(item["regex"])))
        self._subtotal_regexes: list[re.Pattern] = [
            re.compile(item["regex"]) for item in self.cfg.get("patterns", {}).get("subtotal", [])
        ]

    def _detect_payment(self, text: str) -> str | None:
        # 新版：优先使用 cfg.payment.method_map
        mp = (self.cfg.get("payment", {}) or {}).get("method_map", {})
        for k in sorted(mp.keys(), key=lambda x: len(x), reverse=True):
            if k and k in text:
                return mp[k]
        # 兼容旧 lexicons.payment_method
        lex = self.cfg.get("lexicons", {}).get("payment_method", {})
        for k in sorted(lex.keys(), key=lambda x: len(x), reverse=True):
            if k and k in text:
                return lex[k]
        return None

    def _alias_product(self, raw: str) -> str:
        lex = self.cfg.get("lexicons", {}).get("product_alias", {})
        # longest-first contains match
        for k in sorted(lex.keys(), key=lambda x: len(x), reverse=True):
            if k and k in raw:
                return lex[k]
        return raw.strip()

    def _extract_customer(self, text: str) -> str | None:
        strat = self.cfg.get("parsing", {}).get("customer", {}).get("strategy", "prefix_token")
        max_len = int(self.cfg.get("parsing", {}).get("customer", {}).get("max_len", 10))
        if strat == "prefix_token":
            # split by space
            token = text.strip().split(" ")[0] if text.strip() else ""
            token = token[:max_len]
            return token or None
        return None

    def _load_customer_name_list(self) -> list[str]:
        p = (self.cfg.get("customer_mapping", {}) or {}).get("name_list_path")
        if not p:
            return []
        from pathlib import Path
        rp = Path(p)
        # 支持相对路径（相对项目根：img2ledger_poc）
        if not rp.is_absolute():
            # 推断当前文件位于 src/ledger_poc/parse_rules.py
            project_root = Path(__file__).resolve().parents[2]
            rp = (project_root / rp).resolve()
        if not rp.exists():
            return []
        names = [x.strip() for x in rp.read_text(encoding="utf-8").splitlines()]
        return [n for n in names if n]

    def _load_product_name_list(self) -> list[str]:
        pc = self.cfg.get('product_column', {}) or {}
        p = pc.get('product_name_list_path')
        if not p:
            return []
        from pathlib import Path
        rp = Path(p)
        if not rp.is_absolute():
            project_root = Path(__file__).resolve().parents[2]
            rp = (project_root / rp).resolve()
        if not rp.exists():
            return []
        names = [x.strip() for x in rp.read_text(encoding='utf-8').splitlines()]
        return [n for n in names if n]

    @staticmethod
    def _levenshtein(a: str, b: str) -> int:
        # simple DP, strings are short (<= 20)
        if a == b:
            return 0
        if not a:
            return len(b)
        if not b:
            return len(a)
        la, lb = len(a), len(b)
        dp = list(range(lb + 1))
        for i in range(1, la + 1):
            prev = dp[0]
            dp[0] = i
            for j in range(1, lb + 1):
                cur = dp[j]
                cost = 0 if a[i - 1] == b[j - 1] else 1
                dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + cost)
                prev = cur
        return dp[lb]

    def _clean_product_text(self, raw: str) -> str:
        s = (raw or '').strip().replace(' ', '')
        # remove obvious formula fragments if leaked
        s = re.sub(r"\d+(?:\.\d+)?[x×X]\d+(?:\.\d+)?[=＝]\d+(?:\.\d+)?", "", s)
        # drop numbers and units that often pollute product
        s = re.sub(r"\d+(?:\.\d+)?", "", s)
        s = re.sub(r"(?:只|支|个|斤|两|条)", "", s)
        # keep only CJK and hyphen
        s = "".join([ch for ch in s if ('\u4e00' <= ch <= '\u9fff') or ch == '-'])
        return s.strip('-')

    def _map_product(self, raw: str) -> str:
        pc = self.cfg.get('product_column', {}) or {}
        if not pc.get('enabled', False):
            return self._alias_product(raw)

        names = self._load_product_name_list()
        if not names:
            return self._alias_product(raw)

        match_strategy = pc.get('match_strategy', 'contains_longest_then_edit_distance')
        edit_max = int(pc.get('edit_distance_max', 2))

        raw = (raw or '').replace(' ', '')
        cand = self._clean_product_text(raw)

        # 1) contains-longest on raw (most robust)
        if 'contains' in match_strategy:
            for n in sorted(names, key=lambda x: len(x), reverse=True):
                if n and n in raw:
                    return n
            # fallback contains on cleaned candidate
            for n in sorted(names, key=lambda x: len(x), reverse=True):
                if cand and n and (n in cand or cand in n):
                    return n

        # 2) edit-distance on cleaned candidate
        if 'edit' in match_strategy and cand:
            best = None
            best_d = 10**9
            for n in names:
                d = self._levenshtein(cand, n)
                if d < best_d:
                    best_d, best = d, n
            if best is not None and best_d <= edit_max:
                return best

        return (cand or raw) if pc.get('keep_raw_if_not_found', True) else ''

    def _map_customer(self, raw: str) -> str:
        alias = self.cfg.get("overrides", {}).get("customer_alias", {})
        for k in sorted(alias.keys(), key=lambda x: len(x), reverse=True):
            if k and k in raw:
                return alias[k]
                
        cm = self.cfg.get("customer_mapping", {}) or {}
        if not cm.get("enabled", False):
            return raw
        if raw == "散客":
            return raw
        names = self._load_customer_name_list()
        if not names:
            return raw
        strat = cm.get("match_strategy", "contains_longest")
        if strat == "contains_longest":
            # 长名称优先，包含匹配
            for n in sorted(names, key=lambda x: len(x), reverse=True):
                if n in raw or raw in n:
                    return n
        return raw if cm.get("keep_raw_if_not_found", True) else ""

    def _extract_customer_from_blocks(self, line: Line, img_w: int | None = None, img_h: int | None = None) -> str | None:
        """从左侧列抽取客户名；如果左侧列为空，则返回 None（用于继承上一条客户）。"""
        if not line.blocks:
            return None

        max_len = int(self.cfg.get("parsing", {}).get("customer", {}).get("max_len", 10))
        stop = {"Mo","Tu","We","Wo","Th","Fr","Sa","Su","Memo","No.","Date"}

        def has_digit(t: str) -> bool:
            return any(ch.isdigit() for ch in t)

        def has_cjk(t: str) -> bool:
            return any('\u4e00' <= ch <= '\u9fff' for ch in t)

        # 新版：按列切分（默认使用 layout.column_x_splits）
        splits = (self.cfg.get("layout", {}) or {}).get("column_x_splits") or [0.20, 0.52, 0.86]
        col1 = splits[0]
        # 若传入 img_w，用相对阈值；否则 fallback 为旧阈值 260
        x_thr = int((img_w or 1280) * float(col1))
        header_ignore_y = float((self.cfg.get("layout", {}) or {}).get("header_ignore_y", 0.12))
        y_thr = int((img_h or 1707) * header_ignore_y)

        cands = []
        for b in line.blocks:
            x1, y1, x2, y2 = b["bbox"]
            t = str(b["text"]).strip()
            if not t or t in stop:
                continue
            if y2 < y_thr:
                continue
            if x1 >= x_thr:
                continue
            if len(t) > max_len:
                continue
            if not has_cjk(t):
                continue
            # 允许“苏州刘总”这种含数字？（一般不含），这里仍排除数字
            if has_digit(t):
                continue
            cands.append(b)

        if not cands:
            return None

        best = max(cands, key=lambda b: b.get("confidence", 0.0))
        cand = str(best["text"]).strip()[:max_len]
        return self._map_customer(cand) if cand else None

    def _extract_product_and_qty_from_blocks(self, line: Line, img_w: int | None = None) -> Tuple[str | None, float | None]:
        """Extract product and qty(只) from the 2nd column blocks.

        M1 improvement:
        - Extract qty via regex and strip it from product text.
        - Apply product dictionary fuzzy match (contains-longest then edit-distance).
        """
        if not line.blocks:
            return None, None

        splits = (self.cfg.get("layout", {}) or {}).get("column_x_splits") or [0.20, 0.52, 0.86]
        x1_thr = int((img_w or 1280) * float(splits[0]))
        x2_thr = int((img_w or 1280) * float(splits[1]))

        texts = []
        for b in sorted(line.blocks, key=lambda b: b["bbox"][0]):
            x1 = b["bbox"][0]
            if x1_thr <= x1 < x2_thr:
                t = str(b["text"]).strip()
                # 过滤常见的大括号、方括号，防止把合并括号误识为品名的一部分
                t = re.sub(r"[\{\}\[\]\(\)【】]", "", t).strip()
                if not t:
                    continue
                texts.append(t)

        if not texts:
            return None, None

        raw_spaced = " ".join(texts)

        # qty extraction: support 18只 / 18支(常见误识) / 18个
        qty = None
        mqty = re.search(r"(?:^|\s)(\d+(?:\.\d+)?)\s*(?:只|支|个)", raw_spaced)
        if mqty:
            try:
                qty = float(mqty.group(1))
            except Exception:
                pass
            raw_spaced = raw_spaced[: mqty.start()] + raw_spaced[mqty.end() :]
            
        if qty is None:
            # Fallback for handwriting issue where '只' is recognized as '2'
            # Look for suffix 2 at end of string or space
            m2 = re.search(r"(\d+)2(?:\s|$)", raw_spaced)
            if m2:
                val_str = m2.group(1)
                # Heuristic: if combined with size like "14162", take the last 2 digits
                qty_str = val_str[-2:] if len(val_str) >= 3 else val_str
                try:
                    qty = float(qty_str)
                except Exception:
                    pass
                raw_spaced = raw_spaced[: m2.start()] + " " + raw_spaced[m2.end() :]

        # 重新清理出最终品名词
        raw = raw_spaced.replace(" ", "")
        if re.fullmatch(r"[0-9.]+", raw):
            raw = ""
        else:
            raw = self._clean_product_text(raw)
        raw = raw.strip("-，,;；")
        if not raw:
            return None, qty

        prod = self._map_product(raw)
        return (prod if prod else None), qty

    def _extract_product_from_blocks(self, line: Line, img_w: int | None = None) -> str | None:
        prod, _ = self._extract_product_and_qty_from_blocks(line, img_w=img_w)
        return prod

    def _extract_product_region(self, text: str, customer: str | None, formula_span: tuple[int, int]) -> str | None:
        # get segment between customer token and formula start
        start = 0
        if customer and text.startswith(customer):
            start = len(customer)
        seg = text[start:formula_span[0]].strip()
        # remove obvious qty tokens like "1只" "2只" etc
        seg = re.sub(r"\d+(?:\.\d+)?\s*只", "", seg)
        seg = seg.strip(" -，,;；")
        if not seg:
            return None
        return self._alias_product(seg)

    def parse_line(self, line: Line, sale_date: str | None = None, img_w: int | None = None, img_h: int | None = None, image_bgr=None) -> list[ParseRecord]:
        raw = line.text
        text = normalize_text(raw, self.cfg)

        # check for date header like "24/3" indicating March 24th
        mdat = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", text)
        if mdat and len(text) < 10:
            day, month = int(mdat.group(1)), int(mdat.group(2))
            if month > 12 and day <= 12:
                month, day = day, month
            self.parsed_date = f"2026-{month:02d}-{day:02d}"
            return []
            
        effective_date = self.parsed_date or sale_date
        if not effective_date:
            import datetime
            effective_date = datetime.datetime.today().strftime('%Y-%m-%d')

        # subtotal line
        for rg in self._subtotal_regexes:
            m = rg.search(text)
            if m:
                # ignore subtotal in PoC (not exported as record)
                return []

        payment = self._detect_payment(text)
        # 基于列的客户提取：若本行客户为空，则继承上一条客户（左大括号/缩进场景）
        customer = self._extract_customer_from_blocks(line, img_w=img_w, img_h=img_h)
        if customer is None:
            customer = self.last_customer
        else:
            self.last_customer = customer
            if getattr(self, "_has_started_orders", False):
                self.current_order_no += 1
                self.current_order_sum = 0.0
            self._has_started_orders = True

        records: list[ParseRecord] = []

        matches: list[tuple[str, re.Match]] = []
        for name, rg in self._formula_regexes:
            for m in rg.finditer(text):
                # 针对极其宽泛的无乘号容错模式，强加数学逻辑验证：不仅需包含金额，且乘积误差不得离谱
                if "fallback" in name.lower() or "no_x" in name.lower():
                    j_str = m.groupdict().get("jin")
                    p_str = m.groupdict().get("price")
                    a_str = m.groupdict().get("amount")
                    if not j_str or not p_str or not a_str:
                        continue
                    try:
                        if abs(float(j_str) * float(p_str) - float(a_str)) > max(float(p_str), 100.0):
                            continue # 偏差离谱，说明是被错认为售价和重量的干扰数据
                    except:
                        continue
                matches.append((name, m))
        matches.sort(key=lambda x: x[1].start())

        if not matches:
            # no formula -> ignore in V1
            return []

        for _, m in matches:
            jin = float(m.group("jin")) if m.groupdict().get("jin") else None
            price = float(m.group("price")) if m.groupdict().get("price") else None
            # 新规则：销售额优先用算式推导（避免 OCR 在等号右侧多识别位数）
            amt_ocr = float(m.group("amount")) if m.groupdict().get("amount") else None
            amt = None
            discount = None
            if jin is not None and price is not None:
                calc = jin * price
                # User requires taking decimal part as positive discount ALWAYS
                sales_int = int(calc)
                frac = calc - sales_int
                if frac > 1e-6:
                    discount = round(frac, 2)  # MUST BE POSITIVE for exported formula =F*G-H
                amt = sales_int
            if amt is None:
                amt = amt_ocr
                
            self.current_order_sum += (amt or 0.0)

            # 第二列 = 品名 + 只数
            prod2, qty2 = self._extract_product_and_qty_from_blocks(line, img_w=img_w)
            prod = prod2 or self._extract_product_region(text, customer, (m.start(), m.end()))

            # qty/只: prefer 2nd-column extraction; fallback to prefix regex
            prefix = re.sub(r"[\{\}\[\]\(\)【】]", "", text[: m.start()])
            qty = qty2
            if qty is None:
                mqty = re.search(r"(\d+(?:\.\d+)?)\s*(?:只|支|个)", prefix)
                if mqty:
                    qty = float(mqty.group(1))
                else:
                    m2 = re.search(r"(\d+)2\s*$", prefix)
                    if m2:
                        val_str = m2.group(1)
                        qty_str = val_str[-2:] if len(val_str) > 2 else val_str
                        try:
                            qty = float(qty_str)
                        except Exception:
                            pass

            flags: list[str] = []
            conf = 0.7
            if prod is None:
                flags.append("MISSING_PRODUCT")
                conf -= 0.15
            if jin is None:
                flags.append("MISSING_WEIGHT")
                conf -= 0.2
            # 常见打勾已付和挂账兜底
            if payment is None:
                if any(tok in raw for tok in ["√", "收", "v", "V"]):
                    payment = "微信"  # 红勾默认微信
                    flags.append('PAYMENT_DEFAULTED_BY_CHECKMARK')
                else:
                    payment = "挂账"
                    
            # 提取同行可能附带在最右侧的大括号聚合总计进行对账核对
            rem = None
            m_brace = re.search(r"[\}\]】\)\>]\s*([1-9]\d{2,}(?:\.\d+)?)", raw)
            if m_brace:
                subt = float(m_brace.group(1))
                if abs(self.current_order_sum - subt) > 5.0:
                    rem = f"核对异常:累计{self.current_order_sum}实标{subt}"
                else:
                    rem = f"核对平账({subt})"
            
            remark = rem

            rec = ParseRecord(
                sale_date=effective_date,
                order_no=str(self.current_order_no),
                customer_name=customer,
                product=prod,
                qty_units=qty,
                weight_jin=jin,
                unit_price=price,
                discount=discount,
                sales_amount=amt,
                other_fee=None,
                receivable=(amt + (discount or 0.0)) if (discount is not None) else amt,
                pay_method=payment,
                receipt_date=sale_date,
                unpaid=0.0 if payment else amt,
                paid=amt if payment else 0.0,
                remark=remark,
                ocr_raw_line=raw,
                parse_confidence=max(0.0, min(1.0, conf)),
                validation_flags=flags,
            )
            records.append(rec)

        return records
