"""Nạp cấu hình từ config/settings.yaml (nguyên tắc config-first).

- Truy cập bằng đường dẫn chấm: settings.get("crawl.rate_limit_s", 1.5)
- Bí mật tham chiếu qua ${ENV}: tự expand từ biến môi trường (không hard-code
  id/khóa trong repo).
- Luôn đọc UTF-8 (tránh lỗi cp1252 trên Windows).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:  # phụ thuộc tùy chọn để import offline không vỡ
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

DEFAULT_PATH = "config/settings.yaml"


def _expand(node: Any) -> Any:
    if isinstance(node, str):
        return os.path.expandvars(node)          # $VAR và ${VAR}
    if isinstance(node, dict):
        return {k: _expand(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand(v) for v in node]
    return node


class Settings:
    def __init__(self, data: dict):
        self._data = data or {}

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self._data
        for part in dotted.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def section(self, name: str) -> dict:
        v = self._data.get(name, {})
        return v if isinstance(v, dict) else {}

    def enabled_sources(self) -> list[dict]:
        return [s for s in self._data.get("sources", []) if s.get("enabled")]

    @property
    def raw(self) -> dict:
        return self._data


def load_settings(path: str | os.PathLike | None = None) -> Settings:
    p = Path(path or os.environ.get("TWMKT_CONFIG", DEFAULT_PATH))
    if yaml is None:
        raise RuntimeError("Cần cài PyYAML: pip install pyyaml")
    if not p.exists():
        raise FileNotFoundError(f"Không thấy file cấu hình: {p}")
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Settings(_expand(data))
