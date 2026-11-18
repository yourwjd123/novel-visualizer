"""Editable confirmed results, archival deletion and safe replacement copies."""

from pathlib import Path
import copy
import shutil
from .storage import write_json, redact, uid, now


class ResultsMixin:
    def upgrade_result_sources(self):
        self.require_project()
        rows = self.project.final_results()
        changed = False
        import hashlib

        for r in rows:
            if (
                r.get("source_path")
                or r.get("source_checked")
                or r.get("source") == "用户替换"
            ):
                continue
            job = next(
                (j for j in self.project.jobs() if j["id"] == r.get("job")), None
            )
            r["source_checked"] = True
            changed = True
            if not job or not self.file(r["file"]).is_file():
                continue
            candidates = [p for p in job.get("results", []) if self.file(p).is_file()]

            def digest_file(path):
                with path.open("rb") as stream:
                    return hashlib.file_digest(stream, "sha256").digest()

            digest = digest_file(self.file(r["file"]))
            matched = [p for p in candidates if digest_file(self.file(p)) == digest]
            if len(matched) == 1:
                r["source_path"] = matched[0]
                changed = True
        if changed:
            write_json(
                self.project.path / "06_最终成果/成果索引.json",
                redact(rows, self.secrets()),
            )

    def result_scenes(self):
        self.require_project()
        return [
            dict(id=s["id"], title=s["title"], segment=c["id"], chapter=c["name"])
            for c in self.project.segments()
            for s in self.project.scenes(c["id"])
        ]

    def result_edit(self, data, replacement=None):
        self.require_project()
        self.guard()
        rows = self.project.final_results()
        record = next((r for r in rows if r["id"] == data["id"]), None)
        if not record:
            raise ValueError("成果不存在或已删除")
        title = str(data.get("title", record["title"])).strip()
        if not title or len(title) > 200:
            raise ValueError("标题须为1—200字")
        description = str(data.get("description", record.get("description", "")))
        if len(description) > 10000:
            raise ValueError("说明不能超过10000字")
        scene_id = data.get("scene", record["scene"])
        scene = self.project.scene(scene_id)
        if (
            not scene
            or scene.get("archived")
            or scene["segment"] not in {c["id"] for c in self.project.segments()}
        ):
            raise ValueError("请选择当前小说中的有效情节")
        before = copy.deepcopy(record)
        if replacement:
            replacement = Path(replacement)
            if not self.reader_thumbnail(replacement):
                raise ValueError("替换图片无法读取")
            target = (
                self.project.path
                / "06_最终成果"
                / ("替换图片_" + uid() + replacement.suffix.lower())
            )
            shutil.copyfile(replacement, target)
            record["file"] = target.relative_to(self.project.path).as_posix()
            record["source"] = "用户替换"
            record["source_path"] = ""
        record.update(
            title=title,
            description=description,
            scene=scene_id,
            segment=scene["segment"],
            updated=now(),
        )
        write_json(
            self.project.path
            / "06_最终成果/编辑记录"
            / (record["id"] + "_" + uid() + ".json"),
            redact(dict(previous=before, current=record), self.secrets()),
        )
        write_json(
            self.project.path / "06_最终成果/成果索引.json",
            redact(rows, self.secrets()),
        )
        return record

    def results_delete(self, ids, restore=False):
        self.require_project()
        self.guard()
        if not isinstance(ids, list) or not ids:
            raise ValueError("请先选择成果")
        rows = self.project.final_results()
        path = self.project.path / "06_最终成果/已删除成果.json"
        archived = (
            __import__("json").loads(path.read_text("utf-8")) if path.exists() else []
        )
        source = archived if restore else rows
        if any(i not in {r["id"] for r in source} for i in ids):
            raise ValueError("部分成果已变化，请刷新")
        if restore:
            incoming = [r for r in archived if r["id"] in ids]
            if any(r["id"] == v["id"] for r in rows for v in incoming):
                raise ValueError("成果ID冲突，恢复已停止")
            rows.extend(dict(r, restored=now()) for r in incoming)
            archived = [r for r in archived if r["id"] not in ids]
        else:
            archived = [r for r in archived if r["id"] not in ids] + [
                dict(r, deleted=now()) for r in rows if r["id"] in ids
            ]
            rows = [r for r in rows if r["id"] not in ids]
        write_json(path, redact(archived, self.secrets()))
        write_json(
            self.project.path / "06_最终成果/成果索引.json",
            redact(rows, self.secrets()),
        )

    def result_trash(self):
        self.require_project()
        import json

        path = self.project.path / "06_最终成果/已删除成果.json"
        return json.loads(path.read_text("utf-8")) if path.exists() else []
