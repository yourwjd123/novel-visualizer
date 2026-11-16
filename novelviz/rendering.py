"""Visual fields, numbered reference inputs and local, credential-free render packages."""

from __future__ import annotations
import copy
import hashlib
import json
import re
import shutil
from .storage import safe_name, now, redact, write_json, uid

FIELDS = {
    "人物": [
        ("face", "面容"),
        ("body", "体型"),
        ("appearance_state", "外观与状态"),
        ("background", "背景信息"),
        ("relationships", "关系"),
    ],
    "场景": [("scene_description", "场景描述"), ("plot_context", "相关情节")],
    "道具": [("shape", "外形描述"), ("plot_context", "相关情节")],
}
VISUAL_KEYS = {
    "人物": ("face", "body", "appearance_state"),
    "场景": ("scene_description",),
    "道具": ("shape",),
}


def visual_text(asset):
    details = asset.get("details")
    if isinstance(details, dict):
        labels = dict(FIELDS.get(asset.get("kind"), []))
        return "；".join(
            labels[k] + "：" + str(details[k])
            for k in VISUAL_KEYS.get(asset.get("kind"), ())
            if details.get(k)
        )
    return asset.get("description", "")


def validate_plan(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("请先填写并保存最终生图方案")
    if re.search(
        r"(?m)^\s*(?:#+\s*)?(?:\*\*)?(?:思考|分析过程|建议|推测|关键缺项|待确认|审核意见)(?:\*\*)?\s*(?:[:：]|$)",
        text,
    ) or any(word in text for word in ("建议采用", "可能是", "需要确认", "待用户确认")):
        raise ValueError(
            "生图方案含推测、建议或待确认内容；请移到备注后再保存/生成/导出"
        )


class RenderMixin:
    def review_assets(self, ids, status):
        self.require_project()
        self.guard()
        if status not in ("待确认", "已确认", "已锁定"):
            raise ValueError("审核状态无效")
        assets = {a["id"]: a for a in self.project.assets()}
        if any(i not in assets for i in ids):
            raise ValueError("资产已变化，请刷新")
        for identity in ids:
            asset = assets[identity]
            asset["review"] = status
            asset["content_review"] = "已核对" if status != "待确认" else "待核对"
            self.project.save_asset(asset)
        if status == "待确认":
            self.project.config.setdefault("asset_ready", {}).pop(self.segment, None)
            self.project.save_config()

    def render_state(self, asset=None, scene=None):
        self.require_project()
        scene = scene or self.scene
        if asset:
            main = next((a for a in self.project.assets() if a["id"] == asset), None)
            if not main:
                raise ValueError("资产不存在")
            effective = self.project.effective_asset(main, self.segment)
            rows = [
                dict(
                    asset=effective,
                    asset_id=main["id"],
                    name=main["name"],
                    kind=main["kind"],
                )
            ]
            key = "asset_" + asset + "_" + effective["selected_variant"]["id"]
            name = (
                main["name"]
                + "_"
                + effective.get("selected_variant", {}).get("title", "主卡")
                + "_设定图"
            )
        else:
            current = self.project.scene(scene) if scene else None
            if not current or current.get("archived"):
                raise ValueError("请选择情节")
            omitted = self.project.config.get("scene_cast_omissions", {}).get(scene, [])
            rows = [
                r
                for r in self.project.scene_assets(scene)
                if r.get("asset_id") not in omitted
            ]
            key = "scene_" + scene
            name = current["title"]
        refs = []
        for row in rows:
            obj = row.get("asset") or {}
            if obj.get("image") and self.file(obj["image"]).is_file():
                refs.append(
                    dict(
                        number=len(refs) + 1,
                        name=row["name"],
                        asset_id=obj["id"],
                        variant=obj.get("selected_variant", {}),
                        path=obj["image"],
                        thumbnail=self.image(obj["image"]),
                    )
                )
        fingerprint = hashlib.sha256(
            json.dumps(
                dict(
                    rows=rows,
                    refs=[
                        {k: v for k, v in r.items() if k != "thumbnail"} for r in refs
                    ],
                    overrides=self.project.config.get("scene_overrides", {}).get(
                        scene, {}
                    ),
                ),
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        saved = copy.deepcopy(self.project.config.get("render_plans", {}).get(key, {}))
        legacy = ""
        if not saved:
            if asset:
                legacy = self.project.load_node("asset_" + asset, 5).get("final", "")
            else:
                legacy = (
                    self.project.config.get("image_prompt_drafts", {}).get(scene, "")
                    or self.project.load_node(scene, 2).get("final", "")
                    or self.project.load_node(scene, 3).get("final", "")
                )
        return dict(
            key=key,
            name=name,
            rows=rows,
            references=refs,
            fingerprint=fingerprint,
            saved=saved,
            text=saved.get("text", legacy),
            stale=bool(saved and saved.get("fingerprint") != fingerprint),
        )

    def save_render_plan(
        self, text, asset=None, scene=None, name=None, annotations=None
    ):
        self.require_project()
        self.guard()
        validate_plan(text)
        state = self.render_state(asset, scene)
        entry = dict(
            text=text,
            name=name or state["name"],
            fingerprint=state["fingerprint"],
            updated=now(),
            annotations=annotations or [],
        )
        self.project.config.setdefault("render_plans", {})[state["key"]] = entry
        self.project.save_config()
        write_json(
            self.project.path / "02_文本与解析/生图方案" / (state["key"] + ".json"),
            entry,
        )
        return entry

    def render_bundle(self, text, asset=None, scene=None, text_fallback=False):
        validate_plan(text)
        state = self.render_state(asset, scene)
        valid_numbers = {r["number"] for r in state["references"]}
        used_numbers = {int(n) for n in re.findall(r"参考图\s*(\d+)", text)}
        if not used_numbers <= valid_numbers:
            raise ValueError("方案中的参考图编号没有对应文件，请核对参考图清单")
        task = state["rows"][0]["kind"] if asset else "illustration"
        config = self.store.image_defaults(self.account)
        custom = config.get("tasks", {}).get(task, {})
        preface = (
            custom.get("preface", "")
            if custom.get("preface_override")
            else config.get("preface", config.get("generation_rules", ""))
        )
        if text_fallback:
            text = re.sub(r"[（(]参考图\s*\d+[）)]", "", text)
            for ref in state["references"]:
                text = re.sub(
                    r"参考图\s*" + str(ref["number"]) + r"(?!\d)", ref["name"], text
                )
        numbers = (
            {}
            if text_fallback
            else {r["asset_id"]: r["number"] for r in state["references"]}
        )
        constraints = []
        overrides = (
            self.project.config.get("scene_overrides", {}).get(scene or self.scene, {})
            if not asset
            else {}
        )
        for row in state["rows"]:
            obj = row.get("asset") or {}
            label = row["name"] + (
                f"（参考图{numbers[obj['id']]}）" if obj.get("id") in numbers else ""
            )
            if not asset and obj.get("id") in numbers:
                constraints.append(label + "：仅参照参考图")
                continue
            description = visual_text(obj)
            if obj.get("id") in overrides:
                description += "；" + overrides[obj["id"]]
            constraints.append(label + "：" + description if description else label)
        final = "\n\n".join(
            part
            for part in (preface.strip(), text.strip(), "\n".join(constraints))
            if part
        )
        validate_plan(final)
        return dict(
            state=state,
            text=final,
            references=[] if text_fallback else state["references"],
        )

    def render_export_root(self, name, asset=None, scene=None):
        state = self.render_state(asset, scene)
        return (
            self.project.path
            / "09_生图素材"
            / ("资产图" if asset else "场景图")
            / safe_name(name or state["name"])
        )

    def render_export_options(self, name, asset=None, scene=None):
        root = self.render_export_root(name, asset, scene)
        versions = sorted(
            (
                p
                for p in root.glob("版本_*")
                if p.is_dir()
                and not p.is_symlink()
                and re.fullmatch(r"版本_\d{4,}", p.name)
            ),
            reverse=True,
        )
        return dict(
            root=str(root), versions=[dict(name=p.name, path=str(p)) for p in versions]
        )

    def export_render_bundle(
        self, text, name, asset=None, scene=None, mode="new", version=None
    ):
        self.require_project()
        self.guard()
        if mode not in ("new", "overwrite"):
            raise ValueError("导出方式无效")
        bundle = self.render_bundle(text, asset, scene)
        root = self.render_export_root(name, asset, scene)
        root.mkdir(parents=True, exist_ok=True)
        if mode == "overwrite":
            folder = self.file(version) if version else None
            if (
                not folder
                or folder.parent != root.resolve()
                or not folder.is_dir()
                or folder.is_symlink()
                or not re.fullmatch(r"版本_\d{4,}", folder.name)
            ):
                raise ValueError("请指定此方案已有的素材版本")
            manifest = folder / "素材清单.json"
            if manifest.is_symlink():
                raise ValueError("素材清单不能是符号链接")
            previous = (
                json.loads(manifest.read_text("utf-8")) if manifest.exists() else {}
            )
            if (
                previous.get("render_key", bundle["state"]["key"])
                != bundle["state"]["key"]
            ):
                raise ValueError("此目录属于另一份生图方案，请另存新版本")
        else:
            number = 1
            while (root / f"版本_{number:04d}").exists():
                number += 1
            folder = root / f"版本_{number:04d}"
            previous = {}
        stage = root / (".导出暂存_" + uid())
        backup = None
        try:
            if mode == "overwrite":
                shutil.copytree(folder, stage, symlinks=True)
            else:
                stage.mkdir()
            generated = ["生图方案.md", "使用说明.md", "素材清单.json"] + [
                r.get("exported", "") for r in previous.get("references", [])
            ]
            for relative in generated:
                if not relative:
                    continue
                path = stage / relative
                if stage.resolve() not in path.resolve().parents:
                    raise ValueError("旧素材清单路径无效")
                if path.is_file() or path.is_symlink():
                    path.unlink()
            old = stage / "参考图"
            if old.is_dir() and not old.is_symlink() and not any(old.iterdir()):
                old.rmdir()
            refs = []
            for ref in bundle["references"]:
                source = self.file(ref["path"])
                dest = stage / (
                    "参考图"
                    + str(ref["number"])
                    + "_"
                    + safe_name(ref["name"])
                    + source.suffix
                )
                if dest.is_symlink():
                    dest.unlink()
                shutil.copyfile(source, dest)
                refs.append(
                    {k: v for k, v in ref.items() if k != "thumbnail"}
                    | dict(exported=dest.name)
                )
            (stage / "生图方案.md").write_text(
                redact(bundle["text"], self.secrets()), encoding="utf-8"
            )
            instructions = (
                "参考图编号与文件：\n"
                + "\n".join(
                    f"参考图{r['number']}：{r['name']} — {r['exported']}" for r in refs
                )
                + "\n\n将同目录的生图方案.md及参考图片拖入目标产品。实际是否使用参考图取决于目标产品能力。本导出不调用模型，不包含密钥。"
            )
            (stage / "使用说明.md").write_text(instructions, encoding="utf-8")
            write_json(
                stage / "素材清单.json",
                redact(
                    dict(
                        created=now(),
                        render_key=bundle["state"]["key"],
                        references=refs,
                        rows=bundle["state"]["rows"],
                    ),
                    self.secrets(),
                ),
            )
            if mode == "overwrite":
                backup = root / (".覆盖前_" + uid())
                folder.rename(backup)
            try:
                stage.rename(folder)
            except OSError:
                if backup:
                    backup.rename(folder)
                    backup = None
                raise
            if backup:
                shutil.rmtree(backup)
            return dict(path=str(folder), references=len(refs))
        finally:
            if stage.exists():
                shutil.rmtree(stage)
