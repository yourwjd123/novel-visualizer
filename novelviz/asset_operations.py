"""Reversible local asset grouping and explicit, field-wise merge. No AI calls."""

import copy
import json
from .storage import uid, now, write_json, redact

VISUAL = [
    "description",
    "details",
    "attributes",
    "states",
    "notes",
    "missing",
    "evidence",
    "appearances",
    "source",
    "completion_annotations",
]
CONFIG_KEYS = [
    "scene_variant_selections",
    "chapter_variant_selections",
    "scene_cast_omissions",
    "asset_match_exclusions",
]


class AssetOperationsMixin:
    def _asset_pair(self, source, target):
        self.require_project()
        self.guard()
        assets = {a["id"]: a for a in self.project.assets()}
        if source == target or source not in assets or target not in assets:
            raise ValueError("请选择两个不同的有效资产")
        a, b = assets[source], assets[target]
        if a["kind"] != b["kind"]:
            raise ValueError("只能操作同类型资产")
        if a.get("review") == "已锁定" or b.get("review") == "已锁定":
            raise ValueError("请先解锁涉及的资产卡")
        return copy.deepcopy(a), copy.deepcopy(b)

    def _restore_asset_snapshot(self, snapshot):
        for asset in (snapshot["source"], snapshot["target"]):
            self.project.db.execute(
                "UPDATE assets SET data=? WHERE id=?",
                (json.dumps(asset, ensure_ascii=False), asset["id"]),
            )
        self.project.db.commit()
        self.project.config.update(copy.deepcopy(snapshot["config"]))
        for sid, rows in snapshot["scenes"].items():
            self.project.set_requirements(sid, rows)
        self.project.save_config()

    def recover_asset_operations(self):
        folder = self.project.path / "08_项目数据/资产操作记录"
        for path in folder.glob("*.json"):
            op = json.loads(path.read_text("utf-8"))
            if op.get("status") == "prepared":
                self._restore_asset_snapshot(op["before"])
                op["status"] = "rolled_back"
                write_json(path, op)
            elif op.get("status") == "restoring":
                self._restore_asset_snapshot(op["restore_backup"])
                op["status"] = "active"
                write_json(path, op)

    def asset_merge_preview(self, source, target):
        a, b = self._asset_pair(source, target)
        conflicts = []
        for key in ("description", "source", "notes"):
            if a.get(key) and b.get(key) and a[key] != b[key]:
                conflicts.append(dict(field=key, source=a[key], target=b[key]))
        for key, value in a.get("details", {}).items():
            if value and b.get("details", {}).get(key) and value != b["details"][key]:
                conflicts.append(
                    dict(field="details." + key, source=value, target=b["details"][key])
                )
        for category, identity, value_key in [
            ("attributes", "name", "value"),
            ("states", "range", "detail"),
        ]:
            for record in a.get(category, []):
                others = [
                    v
                    for v in b.get(category, [])
                    if v.get(identity) == record.get(identity)
                ]
                if others and any(
                    v.get(value_key) != record.get(value_key) for v in others
                ):
                    conflicts.append(
                        dict(
                            field=category + ":" + str(record.get(identity, "")),
                            source=str(record.get(value_key, "")),
                            target=" / ".join(
                                str(v.get(value_key, "")) for v in others
                            ),
                        )
                    )
        return dict(
            source=a,
            target=b,
            conflicts=conflicts,
            uses=sum(
                any(
                    r.get("asset_id") == source
                    for r in self.project.requirements(s["id"])
                )
                for c in self.project.segments()
                for s in self.project.scenes(c["id"])
            ),
        )

    def asset_operation(self, source, target, mode="variant", choices=None):
        a, b = self._asset_pair(source, target)
        if mode not in ("variant", "merge"):
            raise ValueError("资产操作无效")
        if mode == "variant" and a.get("variants"):
            raise ValueError("原卡已有副卡，请先整理其副卡；不创建多层嵌套")
        before = dict(
            source=copy.deepcopy(a),
            target=copy.deepcopy(b),
            config={
                k: copy.deepcopy(self.project.config.get(k, {})) for k in CONFIG_KEYS
            },
            scenes={},
        )
        variants = {}
        if mode == "variant":
            vid = uid()
            variants["base"] = vid
            b.setdefault("variants", []).append(
                dict(
                    id=vid,
                    title=a["name"],
                    chapter=self.segment,
                    confirmed=True,
                    auto_inherit=False,
                    image=a.get("image", ""),
                    images=copy.deepcopy(a.get("images", [])),
                    revision=1,
                    updated=now(),
                    origin_asset=source,
                    data={k: copy.deepcopy(a[k]) for k in VISUAL if k in a},
                )
            )
        else:
            preview = self.asset_merge_preview(source, target)
            choices = choices or {}
            if any(
                choices.get(c["field"]) not in ("source", "target")
                for c in preview["conflicts"]
            ):
                raise ValueError("请逐项选择冲突字段采用主卡或原卡")
            for key in ("description", "source", "notes"):
                if not b.get(key) or choices.get(key) == "source":
                    if key in a:
                        b[key] = copy.deepcopy(a[key])
            for key, value in a.get("details", {}).items():
                if (
                    not b.setdefault("details", {}).get(key)
                    or choices.get("details." + key) == "source"
                ):
                    b["details"][key] = value
            for key in (
                "attributes",
                "states",
                "missing",
                "evidence",
                "appearances",
                "completion_annotations",
            ):
                for value in a.get(key, []):
                    identity = (
                        "name"
                        if key == "attributes"
                        else "range"
                        if key == "states"
                        else None
                    )
                    if identity:
                        decision = choices.get(key + ":" + str(value.get(identity, "")))
                        if decision == "target":
                            continue
                        if decision == "source":
                            b[key] = [
                                v
                                for v in b.get(key, [])
                                if v.get(identity) != value.get(identity)
                            ]
                    if value not in b.setdefault(key, []):
                        b[key].append(copy.deepcopy(value))
            b["aliases"] = list(
                dict.fromkeys(b.get("aliases", []) + a.get("aliases", []) + [a["name"]])
            )
            for chapter, value in a.get("chapter_levels", {}).items():
                b.setdefault("chapter_levels", {}).setdefault(chapter, value)
            refs = a.get("images", []) + (
                [dict(id=uid(), path=a["image"])] if a.get("image") else []
            )
            for ref in refs:
                if ref["path"] not in {r["path"] for r in b.setdefault("images", [])}:
                    b["images"].append(ref)
            if not b.get("image") and a.get("image"):
                b["image"] = a["image"]
            for v in a.get("variants", []):
                moved = copy.deepcopy(v)
                moved["id"] = uid()
                moved["origin_asset"] = source
                variants[v["id"]] = moved["id"]
                b.setdefault("variants", []).append(moved)
        if mode == "variant":
            b["aliases"] = list(
                dict.fromkeys(
                    b.get("aliases", [])
                    + ([a["name"]] if a["name"] != b["name"] else [])
                )
            )
            for appearance in a.get("appearances", []):
                if appearance not in b.setdefault("appearances", []):
                    b["appearances"].append(copy.deepcopy(appearance))
            for chapter, value in a.get("chapter_levels", {}).items():
                b.setdefault("chapter_levels", {}).setdefault(
                    chapter, copy.deepcopy(value)
                )
        config = copy.deepcopy(before["config"])
        after_scenes = {}
        for c in self.project.segments(include_archived=True):
            for scene in self.project.scenes(c["id"]) + self.project.scenes(
                c["id"], archived=True
            ):
                sid = scene["id"]
                rows = self.project.requirements(sid)
                if not any(r.get("asset_id") == source for r in rows):
                    continue
                existing = any(r.get("asset_id") == target for r in rows)
                if existing and mode == "variant":
                    raise ValueError(
                        "情节“"
                        + scene["title"]
                        + "”同时关联两卡，请先调整关联再归入副卡"
                    )
                source_choice = (
                    config.get("scene_variant_selections", {})
                    .get(sid, {})
                    .get(source, "auto")
                )
                source_choice = (
                    config.get("chapter_variant_selections", {})
                    .get(c["id"], {})
                    .get(source, "auto")
                    if source_choice == "auto"
                    else source_choice
                )
                target_choice = (
                    config.get("scene_variant_selections", {})
                    .get(sid, {})
                    .get(target, "auto")
                )
                new_choice = (
                    variants.get(source_choice, "base")
                    if mode == "merge"
                    else variants["base"]
                )
                if existing and target_choice not in ("auto", new_choice):
                    raise ValueError(
                        "情节“" + scene["title"] + "”存在不同状态选择，请先核对"
                    )
                omitted = config.get("scene_cast_omissions", {}).get(sid, [])
                if existing and ((source in omitted) != (target in omitted)):
                    raise ValueError(
                        "情节“" + scene["title"] + "”两卡出镜设置不同，请先核对"
                    )
                before["scenes"][sid] = copy.deepcopy(rows)
                updated = []
                seen = set()
                for row in rows:
                    r = copy.deepcopy(row)
                    if r.get("asset_id") == source:
                        r.update(asset_id=target, name=b["name"])
                    if r.get("asset_id") and r["asset_id"] in seen:
                        continue
                    if r.get("asset_id"):
                        seen.add(r["asset_id"])
                    updated.append(r)
                after_scenes[sid] = updated
                config.setdefault("scene_variant_selections", {}).setdefault(
                    sid, {}
                ).pop(source, None)
                if not existing:
                    config["scene_variant_selections"][sid][target] = new_choice
        for key in ("scene_cast_omissions", "asset_match_exclusions"):
            for sid, ids in config.get(key, {}).items():
                config[key][sid] = list(
                    dict.fromkeys(target if x == source else x for x in ids)
                )
        for chapter, values in config.get("chapter_variant_selections", {}).items():
            values.pop(source, None)
        a.update(
            archived=True,
            archived_reason="归入副卡" if mode == "variant" else "合并资产",
            operation_target=target,
        )
        operation = dict(
            id=uid(),
            mode=mode,
            created=now(),
            source=source,
            target=target,
            variant_ids=variants,
            before=before,
            after=dict(source=a, target=b, config=config, scenes=after_scenes),
            status="prepared",
        )
        for v in b.get("variants", []):
            if v["id"] in variants.values():
                v["operation_id"] = operation["id"]
        path = (
            self.project.path / "08_项目数据/资产操作记录" / (operation["id"] + ".json")
        )
        write_json(path, redact(operation, self.secrets()))
        try:
            self.project.save_asset(a)
            self.project.save_asset(b)
            for sid, rows in after_scenes.items():
                self.project.set_requirements(sid, rows)
            self.project.config.update(config)
            self.project.save_config()
        except Exception:
            self.project.config.update(before["config"])
            for asset in (before["source"], before["target"]):
                self.project.db.execute(
                    "UPDATE assets SET data=? WHERE id=?",
                    (json.dumps(asset, ensure_ascii=False), asset["id"]),
                )
            self.project.db.commit()
            for sid, rows in before["scenes"].items():
                self.project.set_requirements(sid, rows)
            self.project.save_config()
            operation["status"] = "rolled_back"
            write_json(path, operation)
            raise
        operation["status"] = "active"
        write_json(path, redact(operation, self.secrets()))
        return dict(
            id=operation["id"],
            message="已归入副卡" if mode == "variant" else "已合并资产",
        )

    def asset_operations(self):
        self.require_project()
        return [
            dict(
                id=r["id"],
                mode=r["mode"],
                source=r["before"]["source"]["name"],
                target=r["before"]["target"]["name"],
                status=r["status"],
                created=r["created"],
            )
            for p in sorted(
                (self.project.path / "08_项目数据/资产操作记录").glob("*.json"),
                reverse=True,
            )
            for r in [json.loads(p.read_text("utf-8"))]
        ]

    def asset_operation_restore(self, identity, preview=False):
        self.require_project()
        self.guard()
        if identity not in {
            r["id"] for r in self.asset_operations() if r["status"] == "active"
        }:
            raise ValueError("操作不存在或已恢复")
        path = self.project.path / "08_项目数据/资产操作记录" / (identity + ".json")
        op = json.loads(path.read_text("utf-8"))
        assets = {a["id"]: a for a in self.project.assets(include_archived=True)}
        a = copy.deepcopy(assets[op["source"]])
        b = copy.deepcopy(assets[op["target"]])
        restore_backup = dict(
            source=copy.deepcopy(a),
            target=copy.deepcopy(b),
            config={
                k: copy.deepcopy(self.project.config.get(k, {})) for k in CONFIG_KEYS
            },
            scenes={},
        )
        if not a.get("archived"):
            raise ValueError("原卡已恢复，请刷新")
        if (
            b.get("archived")
            or b.get("review") == "已锁定"
            or a.get("review") == "已锁定"
        ):
            raise ValueError("请先恢复并解锁相关卡片")
        return_info = dict(
            source=a["name"],
            target=b["name"],
            scenes=len(op["before"]["scenes"]),
            note="恢复独立资产，保留后续编辑；已人工改变的关联不回滚。",
        )
        if preview:
            return return_info
        before = op["before"]
        after = op["after"]
        mapping = op["variant_ids"]
        moved = {
            v["id"]: v for v in b.get("variants", []) if v["id"] in mapping.values()
        }
        if op["mode"] == "variant":
            v = moved.get(mapping["base"])
            if v:
                a.update(copy.deepcopy(v.get("data", {})))
                if a["name"] != v["title"]:
                    a["aliases"] = list(
                        dict.fromkeys(a.get("aliases", []) + [a["name"]])
                    )
                a["name"] = v["title"]
                a["image"] = v.get("image", "")
                a["images"] = copy.deepcopy(v.get("images", a.get("images", [])))
        else:
            for variant in a.get("variants", []):
                current = moved.get(mapping.get(variant["id"]))
                if current:
                    variant.update(
                        {
                            k: copy.deepcopy(v)
                            for k, v in current.items()
                            if k not in ("id", "origin_asset")
                        }
                    )
            for key in ("description", "source", "notes", "image", "details"):
                if key == "details":
                    for field, value in after["target"].get("details", {}).items():
                        if b.get("details", {}).get(field) == value:
                            if field in before["target"].get("details", {}):
                                b["details"][field] = before["target"]["details"][field]
                            else:
                                b.get("details", {}).pop(field, None)
                elif b.get(key) == after["target"].get(key):
                    if key in before["target"]:
                        b[key] = copy.deepcopy(before["target"][key])
                    else:
                        b.pop(key, None)
            for key in (
                "aliases",
                "images",
                "attributes",
                "states",
                "missing",
                "evidence",
                "appearances",
                "completion_annotations",
            ):
                added = [
                    v
                    for v in after["target"].get(key, [])
                    if v not in before["target"].get(key, [])
                ]
                b[key] = [v for v in b.get(key, []) if v not in added]
                removed = [
                    v
                    for v in before["target"].get(key, [])
                    if v not in after["target"].get(key, [])
                ]
                for value in removed:
                    identity = (
                        "name"
                        if key == "attributes"
                        else "range"
                        if key == "states"
                        else None
                    )
                    if value not in b[key] and not (
                        identity
                        and any(v.get(identity) == value.get(identity) for v in b[key])
                    ):
                        b[key].append(copy.deepcopy(value))
        if op["mode"] == "variant":
            for key in ("aliases", "appearances"):
                added = [
                    value
                    for value in after["target"].get(key, [])
                    if value not in before["target"].get(key, [])
                ]
                b[key] = [value for value in b.get(key, []) if value not in added]
        for chapter, value in after["target"].get("chapter_levels", {}).items():
            if b.get("chapter_levels", {}).get(chapter) == value:
                if chapter in before["target"].get("chapter_levels", {}):
                    b["chapter_levels"][chapter] = copy.deepcopy(
                        before["target"]["chapter_levels"][chapter]
                    )
                else:
                    b.get("chapter_levels", {}).pop(chapter, None)
        b["variants"] = [
            v for v in b.get("variants", []) if v["id"] not in mapping.values()
        ]
        a.pop("archived_reason", None)
        a.pop("operation_target", None)
        a["archived"] = False
        for asset in (a, b):
            if asset.get("image") and asset["image"] not in {
                r["path"] for r in asset.get("images", [])
            }:
                asset.setdefault("images", []).append(
                    dict(id=uid(), path=asset["image"])
                )
        # Only replace slots still in the exact post-operation state; leave subsequent edits.
        updates = {}
        for sid, original in before["scenes"].items():
            current = self.project.requirements(sid)
            expected = after["scenes"][sid]
            untouched = current == expected
            state = (
                self.project.config.get("scene_variant_selections", {})
                .get(sid, {})
                .get(b["id"], "auto")
            )
            expected_state = (
                after["config"]
                .get("scene_variant_selections", {})
                .get(sid, {})
                .get(b["id"], "auto")
            )
            if untouched and state == expected_state:
                updates[sid] = copy.deepcopy(original)
                for row in updates[sid]:
                    if row.get("asset_id") == a["id"]:
                        row["name"] = a["name"]
        # Later scenes explicitly using the moved state must keep their appearance after detach.
        for c in self.project.segments(include_archived=True):
            for scene in self.project.scenes(c["id"]):
                sid = scene["id"]
                state = (
                    self.project.config.get("scene_variant_selections", {})
                    .get(sid, {})
                    .get(b["id"])
                )
                if state in mapping.values() and sid not in updates:
                    rows = self.project.requirements(sid)
                    for r in rows:
                        if r.get("asset_id") == b["id"]:
                            r.update(asset_id=a["id"], name=a["name"])
                    updates[sid] = rows
        restore_backup["scenes"] = {
            sid: self.project.requirements(sid) for sid in updates
        }
        op.update(status="restoring", restore_backup=restore_backup)
        write_json(path, redact(op, self.secrets()))
        try:
            self.project.save_asset(a)
            self.project.save_asset(b)
            for sid, rows in updates.items():
                self.project.set_requirements(sid, rows)
            for key in CONFIG_KEYS:
                current = self.project.config.setdefault(key, {})
                previous = before["config"].get(key, {})
                expected = after["config"].get(key, {})
                for entry, value in expected.items():
                    if current.get(entry) == value:
                        if entry in previous:
                            current[entry] = copy.deepcopy(previous[entry])
                        else:
                            current.pop(entry, None)
            # Remove dangling moved-state selections; keep user-selected other states.
            reverse = {v: k for k, v in mapping.items()}
            for key in ("scene_variant_selections", "chapter_variant_selections"):
                for entry, values in self.project.config.get(key, {}).items():
                    if values.get(b["id"]) in reverse:
                        value = values.pop(b["id"])
                        values[a["id"]] = reverse[value]
            self.project.save_config()
        except Exception:
            self._restore_asset_snapshot(restore_backup)
            op["status"] = "active"
            write_json(path, op)
            raise
        op.update(status="restored", restored=now())
        write_json(path, redact(op, self.secrets()))
        return return_info
