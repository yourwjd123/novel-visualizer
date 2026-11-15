"""Single-turn tasks, chapter candidates and explicit consultation/completion contexts."""

from __future__ import annotations

import copy
import json
from .prompts import parse_object, validate_assets, validate_scenes
from .storage import now, uid, write_json

COMPLETION_GUIDANCE = """只补全用户指定的空缺或简略字段，保留既有明确内容；不改人物身份、数量、动作或道具归属。只依赖所给章节梗概与目标全文，不假装读过章节原文。世界知识和视觉设计须标为视觉建议，不声称原文明确。资料不足可不提出修改。只输出 JSON：{\"changes\":[{\"field\":\"description\",\"value\":\"建议内容\",\"reason\":\"依据与不确定性\"}]}。资产可改 description、notes、attributes、states、missing；图像提示词只改 text。不得返回未请求字段；数组字段保留未涉及的已有项。"""


class TaskMixin:
    def chapter_summary(self):
        value = copy.deepcopy(
            self.project.config.get("chapter_summaries", {}).get(self.segment, {})
        )
        value["stale"] = bool(value and value.get("source_hash") != self.source_hash())
        return value

    def save_summary(self, text, manual=True):
        self.require_project()
        if not self.segment:
            raise ValueError("请先导入章节原文")
        if not isinstance(text, str) or len(text) > 20000:
            raise ValueError("章节梗概须为不超过 20000 字符的文本")
        old = self.project.config.setdefault("chapter_summaries", {}).get(
            self.segment, {}
        )
        if not manual and old.get("manual"):
            old["suggested_text"] = text
            self.project.config["chapter_summaries"][self.segment] = old
        else:
            self.project.config["chapter_summaries"][self.segment] = dict(
                text=text,
                source_hash=self.source_hash(),
                manual=manual,
                revision=old.get("revision", 0) + 1,
                updated=now(),
            )
        self.project.save_config()
        write_json(
            self.project.path
            / "02_文本与解析/分段正文"
            / (self.segment + "_梗概.json"),
            self.project.config["chapter_summaries"][self.segment],
        )

    def prepare_single(
        self,
        node,
        message,
        asset=None,
        attachments=(),
        *,
        mode="task",
        target=None,
        fields=None,
        paragraph_range=None,
        reference="",
    ):
        self.require_project()
        self.guard()
        if not self.segment:
            raise ValueError("请先导入章节原文")
        if mode not in ("task", "consult", "complete"):
            raise ValueError("任务模式无效")
        if reference and (not isinstance(reference, str) or len(reference) > 50000):
            raise ValueError("本轮引用过长")
        params = self.parameters(node)
        target = copy.deepcopy(target or {})
        fields = fields or []
        if mode == "complete" and (
            target.get("segment", self.segment) != self.segment
            or target.get("project", self.project.meta["id"]) != self.project.meta["id"]
        ):
            raise ValueError("补全编辑目标已切换")
        settings = self.store.settings(self.account)
        summary = self.chapter_summary()
        if mode in ("consult", "complete"):
            if summary.get("stale"):
                raise ValueError(
                    "原文已变化，请更新章节梗概后再咨询或补全；不会改用章节全文"
                )
            # Exactly the user prefix in system; no built-in task/common/project rules.
            params["system"] = params.get("preface", "")
            params["context_verbatim"] = True
            params["template"] = dict(
                id=mode,
                format="text",
                name="自由咨询" if mode == "consult" else "AI补全",
                version="1",
            )
            context = "【本章内容梗概】\n" + (
                summary.get("text") or "暂无章节梗概；请明确资料不足，不假装读过原文。"
            )
            scope = ("consult_" if mode == "consult" else "complete_") + self.segment
            if mode == "complete":
                allowed = (
                    {"text"}
                    if target.get("type") == "prompt"
                    else {"description", "notes", "attributes", "states", "missing"}
                )
                if not fields or not set(fields) <= allowed:
                    raise ValueError("请选择允许补全的字段；情节卡不支持补全")
                if target.get("type") not in ("asset", "prompt"):
                    raise ValueError("补全目标类型无效")
                guidance = (
                    self.store.node_defaults(self.account)
                    .get(str(node), {})
                    .get("completion_guidance")
                    or settings.get("completion_guidance")
                    or COMPLETION_GUIDANCE
                )
                context += (
                    "\n【当前编辑对象全文】\n"
                    + json.dumps(target, ensure_ascii=False)
                    + "\n【固定补全指导】\n"
                    + guidance
                    + "\n【仅允许修改的字段】\n"
                    + json.dumps(fields, ensure_ascii=False)
                )
            message = message.strip() or (
                "请针对所选字段提供补全建议。" if mode == "complete" else ""
            )
            if not message:
                raise ValueError("请输入本轮咨询问题")
            if reference:
                message += "\n【用户本轮明确引用的上一条回答】\n" + reference
            attachments = ()
        else:
            scope = self.scope(node, asset)
            if node == 1 and not asset:
                paragraphs = self.project.paragraphs(self.segment)
                a, b = paragraph_range or [1, len(paragraphs)]
                if (
                    type(a) is not int
                    or type(b) is not int
                    or not 1 <= a <= b <= len(paragraphs)
                ):
                    raise ValueError("章节解析段落范围无效")
                paragraph_range = [a, b]
                context = "【当前章节原文范围】\n" + "\n\n".join(
                    f"[段落 {p['number']}] {p['text']}" for p in paragraphs[a - 1 : b]
                )
                index = [
                    dict(id=r["id"], name=r["name"], kind=r["kind"])
                    for r in self.project.assets()
                    if r["name"] in context
                ]
                for item in index:
                    previous = next(
                        a for a in self.project.assets() if a["id"] == item["id"]
                    )
                    effective = self.project.effective_asset(previous, self.segment)
                    item["当前适用状态"] = {
                        k: effective.get(k)
                        for k in ("description", "states", "selected_variant")
                    }
                context += "\n【匹配的已有资产索引，仅供去重】\n" + json.dumps(
                    index, ensure_ascii=False
                )
            else:
                context = self.context(node, asset)
            message = message.strip() or "请完成当前节点任务，仅输出约定结果。"
        data = self.project.load_node(scope, node)
        # Full local archive is separate from what is sent on each request.
        current = dict(
            role="user", content=message, time=now(), attachments=list(attachments)
        )
        data["messages"].append(current)
        data.update(status="运行中", params=params)
        self.project.secrets = self.secrets()
        self.project.save_node(scope, node, data)
        paths = [self.file(p) for p in sorted(set(attachments))]
        job = dict(
            id=uid(),
            kind="自由咨询"
            if mode == "consult"
            else "AI补全"
            if mode == "complete"
            else params["template"]["name"],
            created=now(),
            status="running",
            node=node,
            segment=self.segment,
            scene=self.scene,
            scope=scope,
            asset=asset,
            mode=mode,
            target=target,
            fields=fields,
            paragraph_range=paragraph_range,
            source_hash=self.source_hash(),
            params=params,
            context=context,
            messages=[current],
            attachments=list(attachments),
            phase="等待模型响应",
            request_summary=dict(
                history_turns=1,
                stored_turns=len(data["messages"]),
                attachments=len(paths),
                estimated_input_tokens=max(
                    1, int((len(params["system"]) + len(context) + len(message)) * 0.8)
                ),
            ),
        )
        self.project.save_job(job)
        return job, data, paths, self.key(params["connection_id"])

    def process_task_output(self, job, text, *, repaired=False):
        if job["segment"] != self.segment:
            raise ValueError("请先切换到该任务对应章节")
        if job.get("source_hash") != self.source_hash():
            raise ValueError("原文已变化，旧输出不会自动应用")
        if job.get("finish_reason") == "length" and not repaired:
            raise ValueError(
                "接口报告长度限制：输出可能截断。请核对实际输出上限、服务限制和推理用量；不会自动重试或猜测补全。"
            )
        mode = job.get("mode", "task")
        if mode == "consult":
            return
        if mode == "complete":
            changes = parse_object(text, expected="changes").get("changes")
            if not isinstance(changes, list):
                raise ValueError("补全输出需要 changes 数组")
            seen_fields = set()
            for change in changes:
                if (
                    not isinstance(change, dict)
                    or change.get("field") not in job["fields"]
                ):
                    raise ValueError("补全结果包含未允许修改的字段")
                if change["field"] in seen_fields:
                    raise ValueError("补全结果同一字段重复，请保留一份修改")
                seen_fields.add(change["field"])
                if change["field"] in ("attributes", "states", "missing"):
                    if not isinstance(change.get("value"), list):
                        raise ValueError("结构化补全字段必须为数组")
                    if change["field"] == "attributes":
                        for value in change["value"]:
                            if (
                                not isinstance(value, dict)
                                or not isinstance(value.get("name"), str)
                                or not isinstance(value.get("value"), str)
                            ):
                                raise ValueError("补全属性必须包含 name/value")
                            value["source"] = "视觉建议"
                            value["evidence"] = []
                elif not isinstance(change.get("value"), str):
                    raise ValueError("补全文本字段必须为文本")
                change["source"] = "AI建议"
            job["changes"] = changes
            return
        if job["node"] == 0:
            parsed = parse_object(text, expected="scenes")
            rows = validate_scenes(parsed, len(self.project.paragraphs(self.segment)))
            self.save_split(rows)
            summary = parsed.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                summary = "\n".join(
                    r["title"] + "：" + r.get("summary", "") for r in rows
                )
            self.save_summary(summary, manual=False)
            job["result_count"] = len(rows)
        elif job["node"] == 1:
            parsed = parse_object(text, expected="assets")
            if isinstance(parsed.get("assets"), list):
                for row in parsed["assets"]:
                    if not isinstance(row, dict):
                        continue
                    for attribute in row.get("attributes", []):
                        if isinstance(attribute, dict) and "evidence_refs" in attribute:
                            refs = attribute["evidence_refs"]
                            evidence = row.get("evidence", [])
                            if not isinstance(refs, list) or any(
                                type(i) is not int or i < 0 or i >= len(evidence)
                                for i in refs
                            ):
                                raise ValueError("属性证据引用索引无效")
                            attribute["evidence"] = [
                                copy.deepcopy(evidence[i]) for i in refs
                            ]
            rows = (
                validate_assets(parsed, len(self.project.paragraphs(self.segment)))
                if parsed.get("assets") != []
                else []
            )
            a, b = job.get("paragraph_range") or [
                1,
                len(self.project.paragraphs(self.segment)),
            ]
            paragraphs = self.project.paragraphs(self.segment)
            for row in rows:
                occurrences = row.get("appearances", [])
                if not isinstance(occurrences, list) or any(
                    not isinstance(e, dict)
                    or type(e.get("paragraph")) is not int
                    or not isinstance(e.get("quote"), str)
                    or not e["quote"].strip()
                    for e in occurrences
                ):
                    raise ValueError("资产出现位置需要段落号和短证据")
                proofs = (
                    row.get("evidence", [])
                    + occurrences
                    + [
                        e
                        for v in row.get("attributes", [])
                        for e in v.get("evidence", [])
                    ]
                )
                for e in proofs:
                    if (
                        not a <= e["paragraph"] <= b
                        or e["quote"] not in paragraphs[e["paragraph"] - 1]["text"]
                    ):
                        raise ValueError("资产证据超出本批范围或摘录无法定位")
                    e["segment"] = self.segment
                first = min(
                    (e["paragraph"] for e in proofs),
                    default=row.get("first_paragraph", a),
                )
                if type(first) is not int or not a <= first <= b:
                    raise ValueError("首次出现位置超出本批范围")
                row.update(
                    id=uid(),
                    candidate=True,
                    job=job["id"],
                    segment=self.segment,
                    source_hash=self.source_hash(),
                    review="待审核",
                    first_paragraph=first,
                    priority=row.get("priority")
                    if row.get("priority") in ("核心", "重要", "建议", "可选择")
                    else "建议",
                )
                row["priority_reason"] = str(row.get("priority_reason", "待用户确定"))
            candidates = self.project.config.setdefault(
                "asset_candidates", {}
            ).setdefault(self.segment, [])
            # Re-validation replaces only pending rows from this job, not accepted assets.
            candidates[:] = [
                r
                for r in candidates
                if r.get("job") != job["id"] or r.get("accepted") or r.get("deleted")
            ]
            for row in rows:
                if not any(
                    r.get("job") == job["id"]
                    and r["name"] == row["name"]
                    and r["kind"] == row["kind"]
                    and r.get("accepted")
                    for r in candidates
                ):
                    candidates.append(row)
            self.project.save_config()
            write_json(
                self.project.path / "02_文本与解析" / (self.segment + "_资产候选.json"),
                candidates,
            )
            job["result_count"] = len(rows)
        else:
            self.project.config.setdefault("task_outputs", {}).setdefault(
                job["scope"], {}
            )[str(job["node"])] = dict(text=text, job=job["id"], status="待确认")
            self.project.save_config()

    def candidate_action(self, identity, action, data=None):
        self.require_project()
        self.guard()
        rows = self.project.config.get("asset_candidates", {}).get(self.segment, [])
        row = next((r for r in rows if r["id"] == identity), None)
        if not row or row.get("accepted"):
            raise ValueError("候选不存在或已处理")
        if action == "delete":
            row["deleted"] = True
        elif action == "restore":
            row["deleted"] = False
        elif action == "edit":
            patched = copy.deepcopy(row)
            for key in (
                "name",
                "kind",
                "description",
                "attributes",
                "states",
                "evidence",
                "missing",
                "notes",
                "priority",
                "priority_reason",
                "completion_annotations",
                "source",
                "first_paragraph",
                "appearances",
            ):
                if key in (data or {}):
                    patched[key] = copy.deepcopy(data[key])
            if patched.get("priority") not in ("核心", "重要", "建议", "可选择"):
                raise ValueError("建议等级无效")
            if not patched.get("name", "").strip():
                raise ValueError("候选名称不能为空")
            position = patched.get("first_paragraph")
            if type(position) is not int or not 1 <= position <= len(
                self.project.paragraphs(self.segment)
            ):
                raise ValueError("首次出现段落无效")
            row.update(patched)
        elif action == "approve":
            if row.get("deleted") or row.get("source_hash") != self.source_hash():
                raise ValueError("候选已删除或原文已变化，请重新核对")
            validate_assets(
                {"assets": [row]}, len(self.project.paragraphs(self.segment))
            )
            for e in (
                row.get("evidence", [])
                + row.get("appearances", [])
                + [e for v in row.get("attributes", []) for e in v.get("evidence", [])]
            ):
                if (
                    e["quote"]
                    not in self.project.paragraphs(self.segment)[e["paragraph"] - 1][
                        "text"
                    ]
                ):
                    raise ValueError("候选证据无法定位")
            existing = next(
                (
                    r
                    for r in self.project.assets()
                    if r["name"] == row["name"] and r["kind"] == row["kind"]
                ),
                None,
            )
            record = (
                copy.deepcopy(existing)
                if existing
                else {
                    k: v
                    for k, v in row.items()
                    if k not in ("id", "candidate", "job", "deleted", "accepted")
                }
            )
            record.setdefault("appearances", [])
            for e in row.get("evidence", []) + row.get("appearances", []) or [
                dict(paragraph=row["first_paragraph"], quote="")
            ]:
                appearance = dict(
                    segment=self.segment,
                    paragraph=e["paragraph"],
                    quote=e.get("quote", ""),
                )
                if appearance not in record["appearances"]:
                    record["appearances"].append(appearance)
            record.setdefault("chapter_levels", {})[self.segment] = dict(
                priority=row["priority"], reason=row["priority_reason"]
            )
            record["review"] = (existing or {}).get("review", "已确认")
            saved = self.project.save_asset(record)
            row["accepted"] = saved["id"]
            self.map_assets_to_scenes()
        else:
            raise ValueError("候选操作无效")
        self.project.save_config()
        write_json(
            self.project.path / "02_文本与解析" / (self.segment + "_资产候选.json"),
            rows,
        )

    def map_assets_to_scenes(self):
        for scene in self.project.scenes(self.segment):
            requirements = self.project.requirements(scene["id"])
            kept = [r for r in requirements if not r.get("auto_asset_link")]
            for asset in self.project.assets():
                evidence = asset.get("appearances", []) + asset.get("evidence", [])
                if any(
                    e.get("segment") == self.segment
                    and scene["start_paragraph"]
                    <= e.get("paragraph", 0)
                    <= scene["end_paragraph"]
                    for e in evidence
                ):
                    if not any(r.get("asset_id") == asset["id"] for r in kept):
                        previous = next(
                            (
                                r
                                for r in requirements
                                if r.get("asset_id") == asset["id"]
                            ),
                            {},
                        )
                        kept.append(
                            dict(
                                name=asset["name"],
                                kind=asset["kind"],
                                asset_id=asset["id"],
                                auto_asset_link=True,
                                slot=previous.get("slot", uid()),
                            )
                        )
            if kept != requirements:
                self.project.set_requirements(scene["id"], kept)

    def archive_asset(self, identity, restore=False):
        self.require_project()
        self.guard()
        asset = next(
            (
                r
                for r in self.project.assets(include_archived=True)
                if r["id"] == identity
            ),
            None,
        )
        if not asset:
            raise ValueError("资产不存在")
        asset["archived"] = not restore
        self.project.save_asset(asset)
        # Keep links to missing archives so scenes can show missing assets explicitly.
        if restore:
            self.map_assets_to_scenes()

    def paste_chapter(self, name, text, target=None, prepend=False):
        self.require_project()
        self.guard()
        if not target:
            return self.import_text(name, text)
        chapter = next((s for s in self.project.segments() if s["id"] == target), None)
        if not chapter:
            raise ValueError("目标章节不存在")
        if not text.strip():
            raise ValueError("正文不能为空")
        path = self.project.path / chapter["file"]
        old = path.read_text("utf-8")
        backup = (
            self.project.path
            / "02_文本与解析/分段正文"
            / (target + "_合并前_" + uid() + ".txt")
        )
        backup.write_text(old, "utf-8")
        path.write_text(
            (text + "\n\n" + old) if prepend else (old + "\n\n" + text), "utf-8"
        )
        if prepend:
            import re

            shift = len(list(re.finditer(r"\S.*?(?=\n\s*\n|\Z)", text, re.DOTALL)))
            for asset in self.project.assets(include_archived=True):
                changed = False
                for evidence in (
                    asset.get("evidence", [])
                    + asset.get("appearances", [])
                    + [
                        e
                        for attr in asset.get("attributes", [])
                        for e in attr.get("evidence", [])
                    ]
                ):
                    if evidence.get("segment") == target:
                        evidence["paragraph"] += shift
                        changed = True
                if changed:
                    self.project.save_asset(asset)
        self.segment = target
        self.scene = None
        for scene in self.project.scenes(target):
            self.project.invalidate(
                scene["id"], 0, "章节正文已合并，请重新核对情节和证据"
            )

    def chapter_action(self, identity, restore=False):
        self.require_project()
        self.guard()
        all_ids = {r["id"] for r in self.project.segments(include_archived=True)}
        if identity not in all_ids:
            raise ValueError("章节不存在")
        archived = self.project.config.setdefault("archived_chapters", [])
        if restore:
            if identity in archived:
                archived.remove(identity)
        elif identity not in archived:
            archived.append(identity)
        self.project.save_config()
        if self.segment == identity and not restore:
            remaining = self.project.segments()
            self.segment = remaining[0]["id"] if remaining else None
            self.scene = None

    def save_variant(self, identity, title, data, variant_id=None, image=""):
        self.require_project()
        self.guard()
        asset = next(a for a in self.project.assets() if a["id"] == identity)
        if not title.strip():
            raise ValueError("副卡名称不能为空")
        if image and not self.file(image).is_file():
            raise ValueError("副卡参考图不存在")
        if data.get("candidate") and data.get("source_hash") != self.source_hash():
            raise ValueError("候选原文已变化，请重新核对")
        variants = asset.setdefault("variants", [])
        old = next((v for v in variants if v["id"] == variant_id), None)
        variant = dict(
            id=variant_id or uid(),
            title=title,
            chapter=(old or {}).get("chapter", self.segment),
            confirmed=True,
            image=image,
            revision=(old or {}).get("revision", 0) + 1,
            updated=now(),
            data={
                k: copy.deepcopy(v)
                for k, v in data.items()
                if k in ("description", "attributes", "states", "notes", "missing")
            },
        )
        if old:
            variants[variants.index(old)] = variant
        else:
            variants.append(variant)
        self.project.save_asset(asset)
        self.select_variant(identity, variant["id"])
        return variant

    def select_variant(self, identity, variant, scene=None):
        self.require_project()
        self.guard()
        asset = next(a for a in self.project.assets() if a["id"] == identity)
        if variant not in ("auto", "base") and variant not in {
            v["id"] for v in asset.get("variants", [])
        }:
            raise ValueError("副卡不存在")
        if scene and not self.project.scene(scene):
            raise ValueError("情节不存在")
        key = "scene_variant_selections" if scene else "chapter_variant_selections"
        self.project.config.setdefault(key, {}).setdefault(scene or self.segment, {})[
            identity
        ] = variant
        self.project.save_config()
        for row in self.project.scenes(self.segment):
            if not scene or row["id"] == scene:
                self.project.invalidate(row["id"], 2, "采用的资产副卡已调整")
