"""Credential-free connection descriptors; credentials are separately account scoped."""

import copy
from .providers import endpoint

KINDS = {
    "demo": "演示（不联网）",
    "openai": "文本 / 视觉 · OpenAI 兼容",
    "comfy": "图像 · ComfyUI",
    "image_api": "图像 · OpenAI 兼容",
}
FIELDS = {
    "id",
    "name",
    "kind",
    "endpoint",
    "model",
    "vision",
    "max_tokens",
    "temperature",
    "legacy",
}


def clean_profile(data):
    if not isinstance(data, dict):
        raise ValueError("连接配置必须是对象")
    out = {k: copy.deepcopy(v) for k, v in data.items() if k in FIELDS}
    if not isinstance(out.get("id"), str) or not out["id"]:
        raise ValueError("连接缺少 ID")
    if out.get("kind") not in KINDS:
        raise ValueError("不支持的连接类型")
    if not isinstance(out.get("name"), str) or not out["name"].strip():
        raise ValueError("连接名称不能为空")
    if out["kind"] != "demo":
        out["endpoint"] = endpoint(out.get("endpoint", ""))
    else:
        out["endpoint"] = ""
    out["model"] = str(out.get("model", ""))
    out["vision"] = bool(out.get("vision", False))
    out["max_tokens"] = max(1, min(131072, int(out.get("max_tokens", 4096))))
    out["temperature"] = max(0.0, min(2.0, float(out.get("temperature", 0.7))))
    out["legacy"] = bool(out.get("legacy", False))
    return out


def defaults(settings):
    rows = []
    for i, name in enumerate(
        [
            "原文整理",
            "资产解析",
            "插图方案",
            "提示词定稿",
            "生成检查",
            "资产设定图",
            "图片审核",
            "全过程规划",
        ]
    ):
        rows.append(
            dict(
                id=f"node-{i}",
                name=name + " · 独立连接",
                kind="demo",
                endpoint="",
                model="",
                vision=i == 6,
                max_tokens=4096,
                temperature=0.7,
                legacy=False,
            )
        )
    rows.append(
        dict(
            id="image-default",
            name="图片生成 · 独立连接",
            kind="comfy",
            endpoint=settings["comfy_url"],
            model="",
            vision=False,
            max_tokens=4096,
            temperature=0.7,
            legacy=False,
        )
    )
    rows.append(
        dict(
            id="legacy-text",
            name="旧版文本连接（可选迁移）",
            kind=settings["provider"],
            endpoint=settings["endpoint"] if settings["provider"] != "demo" else "",
            model=settings["model"],
            vision=settings["vision"],
            max_tokens=settings["max_tokens"],
            temperature=settings["temperature"],
            legacy=True,
        )
    )
    return rows


def credential_id(account_id, connection_id):
    return account_id + ":connection:" + connection_id
