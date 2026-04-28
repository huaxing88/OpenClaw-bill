from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Merge b into a (recursive)."""
    out = dict(a)
    for k, v in b.items():
        if (
            k in out
            and isinstance(out[k], dict)
            and isinstance(v, dict)
        ):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_rules(rules_path: str) -> dict[str, Any]:
    rules_path = str(Path(rules_path))
    base_dir = str(Path(rules_path).parent)
    with open(rules_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # support extends
    if isinstance(cfg, dict) and "extends" in cfg:
        parent = cfg["extends"]
        parent_path = parent if os.path.isabs(parent) else str(Path(base_dir) / parent)
        parent_cfg = load_rules(parent_path)
        child_cfg = dict(cfg)
        child_cfg.pop("extends", None)
        cfg = deep_merge(parent_cfg, child_cfg)

    return cfg
