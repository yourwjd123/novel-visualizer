"""Local ComfyUI graph inspection and exact-count workflow selection."""

import copy
import json
import re


def read_flow(value):
    flow = json.loads(value) if isinstance(value, str) else copy.deepcopy(value)
    if (
        not isinstance(flow, dict)
        or not flow
        or any(
            not isinstance(v, dict)
            or not isinstance(v.get("inputs"), dict)
            or not isinstance(v.get("class_type"), str)
            for v in flow.values()
        )
    ):
        raise ValueError("请导入 ComfyUI API 格式 JSON，不支持编辑器格式")
    return flow


def links(flow, value):
    if (
        isinstance(value, list)
        and len(value) == 2
        and str(value[0]) in flow
        and isinstance(value[1], int)
    ):
        return [str(value[0])]
    return []


def ancestors(flow, start):
    found = set()

    def visit(n):
        if n in found:
            return
        found.add(n)
        for v in flow[n]["inputs"].values():
            for parent in links(flow, v):
                visit(parent)

    visit(start)
    return found


def inspect_flow(value):
    flow = read_flow(value)
    outputs = [
        k for k, v in flow.items() if v["class_type"] in ("SaveImage", "PreviewImage")
    ]
    active = (
        set().union(*(ancestors(flow, n) for n in outputs)) if outputs else set(flow)
    )
    warnings = []
    if not outputs:
        warnings.append("未识别标准图片输出节点，请核对工作流")
    mapping, candidates = {}, {}
    samplers = [n for n in active if "sampler" in flow[n]["class_type"].lower()]
    positive = set()
    for n in active:
        for key in (
            ("positive", "conditioning")
            if flow[n]["class_type"] in ("BasicGuider", "CFGGuider") or n in samplers
            else ("positive",)
        ):
            for p in links(flow, flow[n]["inputs"].get(key)):
                positive |= ancestors(flow, p)
    # Known encoders only: unfamiliar custom nodes require review rather than guesses.
    encoders = [
        n
        for n in positive
        if flow[n]["class_type"]
        in (
            "CLIPTextEncode",
            "TextEncodeQwenImageEdit",
            "TextEncodeQwenImageEditPlus",
            "TextEncodeQwenImage21",
            "CLIPTextEncodeFlux",
        )
    ]
    text_targets = []

    def text_origin(n, key, seen=None):
        seen = set() if seen is None else seen
        if (n, key) in seen:
            return []
        seen.add((n, key))
        v = flow[n]["inputs"].get(key)
        upstream = links(flow, v)
        if not upstream:
            return [[n, key]] if isinstance(v, str) else []
        p = upstream[0]
        eligible = [
            k
            for k, v in flow[p]["inputs"].items()
            if k in ("text", "prompt", "value", "string")
            and (isinstance(v, str) or links(flow, v))
        ]
        return text_origin(p, eligible[0], seen) if len(eligible) == 1 else []

    for n in sorted(encoders):
        keys = [
            k for k in ("text", "prompt", "text_l", "text_g") if k in flow[n]["inputs"]
        ]
        for key in keys:
            text_targets += text_origin(n, key)

    def choose(field, options):
        unique = []
        for item in options:
            if item not in unique:
                unique.append(item)
        if len(unique) == 1:
            mapping[field] = unique[0]
        elif unique:
            candidates[field] = unique
            warnings.append(field + " 有多个入口，请手工选择")

    choose("prompt", text_targets)
    seeds = []
    noise_nodes = {
        p for n in samplers for p in links(flow, flow[n]["inputs"].get("noise"))
    }
    for n in sorted(set(samplers) | noise_nodes):
        for key in ("seed", "noise_seed"):
            if key not in flow[n]["inputs"]:
                continue
            parent = links(flow, flow[n]["inputs"][key])
            if not parent:
                seeds.append([n, key])
            else:
                p = parent[0]
                for k in ("seed", "value", "noise_seed"):
                    if k in flow[p]["inputs"] and not links(flow, flow[p]["inputs"][k]):
                        seeds.append([p, k])
                        break
    choose("seed", seeds)
    ref_slots = []
    for n in sorted(encoders):
        for key in flow[n]["inputs"]:
            if re.fullmatch(r"(?:images\.)?image(?:_\d+)?", key):
                parent = links(flow, flow[n]["inputs"][key])
                if parent:
                    loaded = sorted(
                        p
                        for p in ancestors(flow, parent[0])
                        if flow[p]["class_type"] == "LoadImage"
                    )
                    ref_slots.append((n, key, loaded))
    ref_slots.sort(
        key=lambda s: (
            s[0],
            int(re.search(r"(\d+)$", s[1]).group(1))
            if re.search(r"(\d+)$", s[1])
            else 0,
        )
    )
    if not ref_slots:
        latent_loaders = set()
        for n in samplers:
            for parent in links(flow, flow[n]["inputs"].get("latent_image")):
                latent_loaders |= {
                    p
                    for p in ancestors(flow, parent)
                    if flow[p]["class_type"] == "LoadImage"
                }
        if len(latent_loaders) == 1:
            ref_slots.append(("latent", "image", list(latent_loaders)))
        elif latent_loaders:
            warnings.append("潜空间含多个图片来源，请手工核对参考图用途")
    for i, (_, _, loaded) in enumerate(ref_slots, 1):
        choose("reference_" + str(i), [[n, "image"] for n in loaded])
    active_loaders = sorted(n for n in active if flow[n]["class_type"] == "LoadImage")
    mapped = {v[0] for k, v in mapping.items() if k.startswith("reference_")}
    leftovers = [n for n in active_loaders if n not in mapped]
    if leftovers:
        warnings.append(
            "存在未识别用途的图片输入："
            + "、".join(leftovers)
            + "；请核对旧图片与控制图"
        )
    if "prompt" not in mapping:
        warnings.append("未确定正面提示词入口，请手动填写")
    return dict(
        mapping=mapping,
        candidates=candidates,
        warnings=warnings,
        reference_count=len(ref_slots),
        active_nodes=sorted(active),
        image_nodes=active_loaders,
    )


def validate_mapping(value, mapping):
    flow = read_flow(value)
    mapping = json.loads(mapping) if isinstance(mapping, str) else mapping
    if not isinstance(mapping, dict) or "prompt" not in mapping:
        raise ValueError("必须映射 prompt 字段")
    active = set(inspect_flow(flow)["active_nodes"])
    for field, pair in mapping.items():
        if field not in ("prompt", "seed") and not re.fullmatch(
            r"reference_[1-9]\d*", field
        ):
            raise ValueError("不支持的映射字段：" + field)
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("映射格式无效：" + field)
        n, k = map(str, pair)
        if n not in active or k not in flow[n]["inputs"]:
            raise ValueError("映射未连接有效输出或字段不存在：" + field)
        if field == "prompt" and (
            not isinstance(flow[n]["inputs"][k], str)
            or k
            in (
                "negative_prompt",
                "image",
                "filename_prefix",
                "unet_name",
                "clip_name",
                "vae_name",
            )
        ):
            raise ValueError("正面提示词应映射到文本输入，不可覆盖模型、图片或负面字段")
        if field == "seed" and type(flow[n]["inputs"][k]) is not int:
            raise ValueError("种子应映射到实际整数输入，请追踪上游种子节点")
        if field.startswith("reference_") and (
            flow[n]["class_type"] != "LoadImage" or k != "image"
        ):
            raise ValueError("参考图必须映射到 LoadImage 的 image 输入")
    refs = sorted(int(k.split("_")[1]) for k in mapping if k.startswith("reference_"))
    if refs != list(range(1, len(refs) + 1)):
        raise ValueError("参考图编号必须从1开始连续")
    if len({tuple(v) for k, v in mapping.items() if k.startswith("reference_")}) != len(
        refs
    ):
        raise ValueError("不同参考图不能覆盖同一个输入")
    return flow, mapping


def check_count(value, mapping, count):
    flow, mapping = validate_mapping(value, mapping)
    refs = {tuple(v) for k, v in mapping.items() if k.startswith("reference_")}
    if len(refs) != count:
        raise ValueError(
            f"本次 {count} 张参考图，工作流映射为 {len(refs)} 张，请选择数量一致的预设"
        )
    info = inspect_flow(flow)
    loaders = {(n, "image") for n in info["image_nodes"]}
    if loaders != refs:
        raise ValueError(
            "工作流仍有未覆盖的有效图片输入，可能沿用旧图；请清理或单独配置工作流"
        )
    if info["reference_count"] and info["reference_count"] != count:
        raise ValueError("编码器参考图槽位数量与本次输入不一致，请检查连接")
    return flow, mapping
