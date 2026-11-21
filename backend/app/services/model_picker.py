"""
图生图的模型选择器。

## 为什么要有选择器

MiniMax-M3 能读图，MiniMax-M2.5 **不能**（`model-catalog.json` 里
`images=false`）。如果图生图固定用 M3，那么：

  · 用户在设置里换成 M2.5 后，图生图会静默失败（模型收不到图片）
  · 成本高的模型被所有用户默认使用

所以图生图**必须**让用户能选，而且选择器要**提前告知能力边界** ——
选了不支持图片的模型，选中时就该看到提示，而不是发出去才失败。

## 模型清单从哪来

不硬编码。`/api/models/image-capable` 读 networktopology 的
`lib/model-catalog.json`（同一份数据源），并按当前 provider 过滤。
如果读不到（服务未起），返回内置的保守默认并标记 `source: builtin`。

**保守默认的方向是"明确告诉用户不支持"**，不是"假装能行"。
"""

from __future__ import annotations

import json
import os
from typing import Any

# networktopology 仓库里的模型目录（相对路径由 MP_MODELS_CATALOG 覆盖）
DEFAULT_CATALOG = os.getenv(
    "MP_MODELS_CATALOG",
    r"C:\Users\gmche\Work\networktopology\lib\model-catalog.json",
)

# 读不到时的保守默认：只列明确支持图片的
BUILTIN_FALLBACK: list[dict[str, Any]] = [
    {"id": "MiniMax-M3", "name": "MiniMax-M3", "images": True, "note": "支持图片输入"},
    {"id": "MiniMax-M2.5", "name": "MiniMax-M2.5", "images": False, "note": "不支持图片输入"},
]


def load_catalog() -> tuple[list[dict[str, Any]], str]:
    """读模型目录。返回 (条目列表, 来源标记)。"""
    path = DEFAULT_CATALOG
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return list(BUILTIN_FALLBACK), "builtin"

    items: list[dict[str, Any]] = []
    # 目录可能是 list，也可能是 {provider: [models]} 或 {models: [...]}
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        raw = data.get("models") or []
        if not raw and "minimax" in data:
            raw = data["minimax"]
        elif not raw:
            # {provider: [ {...}, ... ]}
            for v in data.values():
                if isinstance(v, list):
                    raw.extend(v)
    else:
        raw = []

    for m in raw:
        if not isinstance(m, dict):
            continue
        mid = m.get("id") or m.get("name") or m.get("model")
        if not mid:
            continue
        items.append(
            {
                "id": mid,
                "name": m.get("name") or m.get("displayName") or mid,
                "images": bool(m.get("images") or m.get("supportsImages") or m.get("vision")),
                "note": m.get("note") or m.get("description") or "",
                "provider": m.get("provider") or "",
            }
        )

    if not items:
        return list(BUILTIN_FALLBACK), "builtin"
    return items, "catalog"


def image_capable_models() -> dict[str, Any]:
    """图生图可选的模型清单。

    返回**全部**模型并标出哪些支持图片 —— 前端要能显示"选这个不行"的
    提示，所以不能只返回可用的那部分。
    """
    items, source = load_catalog()
    for m in items:
        m["image_capable"] = bool(m.get("images"))
        if m["image_capable"]:
            m["image_note"] = m.get("note") or "支持图片输入"
        else:
            m["image_note"] = m.get("note") or "不支持图片输入，图生图不可用"
    return {
        "models": items,
        "source": source,
        "default": next((m["id"] for m in items if m["image_capable"]), None),
        "count_image_capable": sum(1 for m in items if m["image_capable"]),
    }


def can_handle_image(model_id: str | None) -> tuple[bool, str]:
    """检查某模型能不能读图。返回 (能不能, 原因)。

    **能力不足时明确说不行**，不要默默降级 —— 用户上传了图却得到一句
    "我看不清"，比直接报错更让人困惑。
    """
    if not model_id:
        return False, "未指定模型"
    items, _ = load_catalog()
    for m in items:
        if m["id"] == model_id:
            if m.get("images"):
                return True, ""
            return False, f"模型 {model_id} 不支持图片输入，无法做图生图"
    return False, f"模型 {model_id} 不在目录中，无法确认是否支持图片"
