"""Reusable workflow presets and explicit per-run provider selection."""

import json
from .workflows import check_count, inspect_flow, validate_mapping
from .storage import uid


class GenerationMixin:
    def image_config(self, task):
        self.require_account()
        config = self.store.image_defaults(self.account)
        override = config.get("tasks", {}).get(task, {})
        if override.get("connection_override", bool(override.get("connection_id"))):
            config = dict(config, **override)
        return config

    def workflow_presets(self):
        self.require_account()
        config = self.store.image_defaults(self.account)
        rows = list(config.get("presets", []))
        # Older per-node workflows remain usable, without overwriting user edits.
        sources = [("legacy-default", "旧版默认工作流", config)]
        sources += [
            ("legacy-" + k, "旧版 · " + k, v)
            for k, v in config.get("tasks", {}).items()
        ]
        for identity, name, v in sources:
            if v.get("workflow", "").strip():
                try:
                    info = inspect_flow(v["workflow"])
                    m = json.loads(v.get("mapping", "{}"))
                    rows.append(
                        dict(
                            id=identity,
                            name=name,
                            connection_id=v.get(
                                "connection_id",
                                config.get("connection_id", "image-default"),
                            ),
                            workflow=v["workflow"],
                            mapping=v.get("mapping", "{}"),
                            reference_count=sum(k.startswith("reference_") for k in m),
                            legacy=True,
                            warnings=info["warnings"],
                        )
                    )
                except (ValueError, TypeError):
                    pass
        for row in rows:
            try:
                check_count(row["workflow"], row["mapping"], row["reference_count"])
                row["validation_error"] = ""
            except (ValueError, KeyError, TypeError) as error:
                row["validation_error"] = str(error)
        return rows

    def save_workflow_preset(self, data, delete=False):
        self.require_account()
        self.guard()
        config = self.store.image_defaults(self.account)
        presets = config.get("presets", [])
        identity = data.get("id") or uid()
        if delete:
            if identity.startswith("legacy-"):
                raise ValueError("旧版预设请在原配置中清除工作流")
            config["presets"] = [r for r in presets if r["id"] != identity]
        else:
            name = str(data.get("name", "")).strip()
            if not name or len(name) > 100:
                raise ValueError("请输入1—100字的预设名称")
            cid = data.get("connection_id")
            if not any(
                c["id"] == cid and c["kind"] == "comfy"
                for c in self.store.connections(self.account)
            ):
                raise ValueError("请先选择 ComfyUI 连接")
            flow, mapping = validate_mapping(data["workflow"], data["mapping"])
            count = data.get("reference_count", 0)
            if type(count) != int or not 0 <= count <= 64:
                raise ValueError("参考图数量应为0—64")
            check_count(flow, mapping, count)
            item = dict(
                id=identity if not identity.startswith("legacy-") else uid(),
                name=name,
                connection_id=cid,
                reference_count=count,
                workflow=json.dumps(flow, ensure_ascii=False),
                mapping=json.dumps(mapping, ensure_ascii=False),
                default=bool(data.get("default")),
            )
            if item["default"]:
                for p in presets:
                    if p["connection_id"] == cid and p["reference_count"] == count:
                        p["default"] = False
            config["presets"] = [p for p in presets if p["id"] != identity] + [item]
        self.store.save_image_defaults(self.account, config, self.secrets())

    def generation_options(self, asset=None, plan=""):
        self.require_project()
        obj = (
            next((a for a in self.project.assets() if a["id"] == asset), None)
            if asset
            else None
        )
        if asset and not obj:
            raise ValueError("资产不存在")
        task = obj["kind"] if obj else "illustration"
        config = self.image_config(task)
        count = len(self.render_bundle(plan, asset)["references"])
        rows = []
        presets = self.workflow_presets()
        for c in self.store.connections(self.account):
            if c["kind"] == "image_api":
                rows.append(
                    dict(
                        id=c["id"],
                        connection_id=c["id"],
                        name=c["name"],
                        kind=c["kind"],
                        available=True,
                        warning="仅文生图，使用参考图需明确接受文字回退"
                        if count
                        else "",
                        preferred=c["id"] == config.get("connection_id"),
                    )
                )
            elif c["kind"] == "comfy":
                available = [p for p in presets if p["connection_id"] == c["id"]]
                for p in available:
                    error = ""
                    try:
                        check_count(p["workflow"], p["mapping"], count)
                    except (ValueError, KeyError, TypeError) as e:
                        error = str(e)
                    rows.append(
                        dict(
                            id=c["id"] + ":" + p["id"],
                            connection_id=c["id"],
                            preset_id=p["id"],
                            name=c["name"] + " / " + p["name"],
                            kind="comfy",
                            available=not error,
                            warning=error,
                            reference_count=p["reference_count"],
                            preferred=c["id"] == config.get("connection_id")
                            and p["id"] == config.get("preset_id"),
                            default=bool(p.get("default")),
                        )
                    )
                if not available:
                    rows.append(
                        dict(
                            id=c["id"],
                            connection_id=c["id"],
                            name=c["name"],
                            kind="comfy",
                            available=False,
                            warning="尚未配置有效工作流预设",
                        )
                    )
        eligible = [
            r
            for r in rows
            if r["available"] and r["connection_id"] == config.get("connection_id")
        ]
        selected = next(
            (r["id"] for r in eligible if r.get("preferred")),
            next(
                (r["id"] for r in eligible if r.get("default")),
                eligible[0]["id"] if eligible else "",
            ),
        )
        return dict(options=rows, selected=selected, reference_count=count, task=task)

    def resolve_generation(self, task, count, selection=None):
        config = self.image_config(task)
        cid = (
            selection.get("connection_id")
            if selection
            else config.get("connection_id", "image-default")
        )
        c = next(
            (c for c in self.store.connections(self.account) if c["id"] == cid), None
        )
        if not c or c["kind"] not in ("comfy", "image_api"):
            raise ValueError("请配置有效图片连接")
        if c["kind"] == "comfy":
            presets = [
                p
                for p in self.workflow_presets()
                if p["connection_id"] == cid and p["reference_count"] == count
            ]
            preferred = (
                selection.get("preset_id") if selection else config.get("preset_id")
            )
            p = next((p for p in presets if p["id"] == preferred), None)
            if selection and preferred and not p:
                raise ValueError("预设已变化或参考图数量不符，请重新选择")
            p = p or next(
                (p for p in presets if p.get("default")),
                presets[0] if presets else None,
            )
            if p:
                config = dict(
                    config,
                    workflow=p["workflow"],
                    mapping=p["mapping"],
                    preset_id=p["id"],
                )
            check_count(
                config.get("workflow", "{}"), config.get("mapping", "{}"), count
            )
        return dict(config, connection_id=cid), c
