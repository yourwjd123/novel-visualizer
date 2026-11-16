"""Local import estimates and external scene illustration candidates."""

import math
import re
import shutil
from .storage import now, uid
from .tasks import ASSET_ADVICE_DEFAULT


def token_range(text):
    # Heuristic, deliberately a range; no paid tokenizer request or model download.
    cjk = len(re.findall(r"[\u3400-\u9fff\uf900-\ufaff]", text))
    other = len(text) - cjk
    return [
        max(1, math.ceil(cjk * 0.7 + other / 5)),
        max(1, math.ceil(cjk * 1.8 + other / 2)),
    ]


class ImportMixin:
    def import_report(self, text):
        self.require_project()
        chapter = self.project.segment_text(self.segment)
        prefix = self.parameters(1, strict=False).get("preface", "")
        from .prompts import OUTPUT_SCHEMAS
        import json

        index = json.dumps(self.association_index(), ensure_ascii=False)
        advice = (
            self.store.settings(self.account).get("asset_advice_prompt")
            or ASSET_ADVICE_DEFAULT
        )
        build = self.parameters(1, strict=False)["system"]
        split = self.parameters(0, strict=False)["system"]
        if self.association_mode() == "ai":
            split = (
                split.replace(OUTPUT_SCHEMAS["scenes"], OUTPUT_SCHEMAS["scene_links"])
                + "\n"
                + index
            )
        paragraphs = "\n\n".join(
            f"[段落 {p['number']}] {p['text']}"
            for p in self.project.paragraphs(self.segment)
        )
        overhead = token_range(build + index)
        full = token_range(build + index + paragraphs)
        return dict(
            name=next(
                s["name"] for s in self.project.segments() if s["id"] == self.segment
            ),
            import_characters=len(re.sub(r"\s", "", text)),
            chapter_characters=len(re.sub(r"\s", "", chapter)),
            source=token_range(chapter),
            advice=token_range(prefix + advice + paragraphs + index),
            build=[overhead[0], full[1]],
            split=token_range(split + paragraphs),
            method="本地字符启发式估算，未使用模型专用分词器；包含前置/任务提示词和资产索引，不含输出、推理token、图片或供应商额外开销。正式建卡范围取决于勾选数量及相关段落，运行前以实际输入预估为准。",
        )

    def import_scene_image(self, path, name=None):
        self.require_project()
        self.guard()
        scene = self.project.scene(self.scene) if self.scene else None
        if not scene or scene.get("review", "已确认") != "已确认":
            raise ValueError("请先选择已确认情节")
        from PySide6.QtGui import QImageReader

        size = QImageReader(str(path)).size()
        if not size.isValid() or size.width() * size.height() > 100_000_000:
            raise ValueError("图片无法读取或尺寸过大")
        identity = uid()
        folder = self.project.path / "05_生成任务" / identity / "候选图片"
        folder.mkdir(parents=True)
        target = folder / ("用户导入" + path.suffix.lower())
        shutil.copyfile(path, target)
        relative = target.relative_to(self.project.path).as_posix()
        self.project.save_job(
            dict(
                id=identity,
                created=now(),
                status="success",
                node=4,
                kind="用户导入场景插图",
                source="用户导入",
                original_name=name or path.name,
                segment=self.segment,
                scene=self.scene,
                scope=self.scene,
                asset=None,
                results=[relative],
                scene_snapshot=scene,
            )
        )
        return dict(path=relative, source="用户导入")

    def scene_candidate(self, path, restore=False):
        self.require_project()
        self.guard()
        if not any(
            j.get("scene") == self.scene
            and not j.get("asset")
            and path in j.get("results", [])
            for j in self.project.jobs()
        ):
            raise ValueError("图片不属于当前情节候选")
        hidden = self.project.config.setdefault("hidden_scene_candidates", [])
        if restore:
            if path in hidden:
                hidden.remove(path)
        elif path not in hidden:
            hidden.append(path)
        self.project.save_config()
