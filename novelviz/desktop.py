"""Qt WebEngine host for the compiled React workspace (no local web server)."""

from __future__ import annotations

import argparse
import base64
import copy
import json
import queue
import shutil
import sys
import threading
import zipfile
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QSettings,
    QStandardPaths,
    QThread,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from .providers import (
    ProviderError,
    UnknownOutcome,
    bind_workflow,
    comfy_call,
    image_call,
    text_call,
    upload_comfy,
)
from .storage import (
    DEFAULTS,
    Project,
    Store,
    now,
    read_document,
    redact,
    safe_name,
    uid,
    write_json,
)
from .workspace import Workspace


class Worker(QThread):
    completed = Signal(object)
    failed = Signal(object)
    update = Signal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.cancel = threading.Event()

    def run(self):
        # Network I/O cannot be force-killed safely. Detach only the waiting UI;
        # the daemon never writes SQLite or emits Qt signals, and never resubmits.
        events = queue.Queue()

        def execute():
            try:
                events.put(
                    (
                        "result",
                        self.fn(
                            self.cancel, lambda data: events.put(("progress", data))
                        ),
                    )
                )
            except Exception as error:
                events.put(("error", error))

        threading.Thread(target=execute, daemon=True).start()
        while True:
            try:
                kind, value = events.get(timeout=0.1)
            except queue.Empty:
                if self.cancel.is_set():
                    self.failed.emit(
                        dict(
                            message="已停止本地等待；远端可能仍在执行或计费，请核查任务记录。不会自动重试。",
                            unknown=True,
                        )
                    )
                    return
                continue
            if kind == "progress":
                self.update.emit(value)
            elif kind == "result":
                self.completed.emit(value)
                return
            else:
                self.failed.emit(
                    dict(
                        message=str(value)
                        if isinstance(value, ProviderError)
                        else f"本地处理失败（{type(value).__name__}）；输入与任务已保留",
                        unknown=isinstance(value, UnknownOutcome),
                    )
                )
                return


class Bridge(QObject):
    changed = Signal(str)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.workspace = Workspace(root)
        self.host = parent
        self.worker = None
        self.job = None

    @Slot(str, str, result=str)
    def invoke(self, operation, payload):
        try:
            data = json.loads(payload or "{}")
            if not isinstance(data, dict):
                raise ValueError("请求必须为对象")
            result = self.dispatch(operation, data)
            return json.dumps(dict(ok=True, data=result), ensure_ascii=False)
        except Exception as e:
            # Domain errors are ours; never echo arbitrary provider response bodies.
            message = (
                str(e)
                if isinstance(e, (ValueError, ProviderError, RuntimeError))
                else f"操作未完成（{type(e).__name__}）"
            )
            return json.dumps(
                dict(ok=False, error=redact(message, self.workspace.secrets())),
                ensure_ascii=False,
            )

    def confirm(self, title, message):
        return (
            QMessageBox.question(
                self.host,
                title,
                message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            == QMessageBox.Yes
        )

    def state(self):
        result = self.workspace.snapshot()
        result["system_dark"] = QApplication.styleHints().colorScheme().name == "Dark"
        return result

    def dispatch(self, op, d):
        w = self.workspace
        if d.get("_project") and op not in (
            "state",
            "login",
            "logout",
            "account_create",
            "project_open",
            "choose_root",
            "project_create",
        ):
            if not w.project or d["_project"] != w.project.meta["id"]:
                raise ValueError("项目已切换，已拒绝旧页面请求；原输入仍保留")
        if op == "state":
            return self.state()
        if op == "close_ready":
            w.guard()
            if self.host:
                self.host._closing = True
                QTimer.singleShot(0, self.host.close)
            return None
        if op == "account_create":
            w.guard()
            a = w.store.create_account(d["name"])
            w.login(a["id"])
        elif op == "login":
            w.login(d["id"])
        elif op == "logout":
            w.logout()
        elif op == "account_rename":
            w.require_account()
            w.store.rename_account(w.account, d["name"])
        elif op == "account_delete":
            w.require_account()
            w.guard()
            if not self.confirm(
                "归档删除账户",
                "将从账户列表移除此账户，资料保留在“已归档账户”。删除独立系统凭据。继续吗？",
            ):
                return None
            from . import credentials
            from .connections import credential_id

            for c in w.store.connections(w.account):
                slot = credential_id(w.account["id"], c["id"])
                if credentials.get_key(slot):
                    credentials.set_key(slot, "")
            account = w.account
            w.logout()
            w.store.delete_account(account)
        elif op == "choose_root":
            w.guard()
            path = QFileDialog.getExistingDirectory(
                self.host, "选择用户资料根目录", str(w.store.root)
            )
            if path:
                w.logout()
                w.store = Store(path, create_default=False)
                QSettings().setValue("data_root", path)
        elif op == "project_create":
            w.require_account()
            w.guard()
            p = w.store.create_project(w.account, d["name"])
            path = str(p.path)
            p.close()
            w.open_project(path)
        elif op == "project_open":
            w.open_project(d["path"])
        elif op == "select":
            w.set_selection(d.get("segment"), d.get("scene"))
        elif op == "import_text":
            w.import_text(d["name"], d["text"])
        elif op == "upload":
            return self.upload(d)
        elif op == "import_file":
            w.require_project()
            path, _ = QFileDialog.getOpenFileName(
                self.host, "导入原文", "", "文本 (*.txt *.md *.docx *.epub)"
            )
            if path:
                w.import_text(Path(path).stem, read_document(path), path)
        elif op == "save_split":
            w.save_split(d["rows"])
        elif op == "confirm_split":
            w.confirm_split(d["rows"])
        elif op == "set_depth":
            w.require_project()
            w.project.config["split_depth"] = str(d["depth"])
            w.project.save_config()
        elif op == "save_asset":
            return w.save_asset(d)
        elif op == "reference":
            w.reference_action(d["id"], d["path"], d["action"])
        elif op == "restore_reference":
            w.require_project()
            trash = w.project.config.get("image_trash", [])
            item = next(t for t in trash if t["id"] == d["id"])
            a = next(a for a in w.project.assets() if a["id"] == item["asset"])
            a.setdefault("images", []).append(item["reference"])
            a.setdefault("image", item["reference"]["path"])
            if not a["image"]:
                a["image"] = item["reference"]["path"]
            w.project.save_asset(a)
            w.project.config["image_trash"] = [t for t in trash if t["id"] != d["id"]]
            w.project.save_config()
        elif op == "trash":
            w.require_project()
            return [
                dict(t, thumbnail=w.image(t["reference"]["path"]))
                for t in w.project.config.get("image_trash", [])
            ]
        elif op == "gallery":
            w.require_project()
            return [
                dict(
                    asset=a["id"],
                    name=a["name"],
                    kind=a["kind"],
                    **r,
                    thumbnail=w.image(r["path"]),
                    primary=a.get("image") == r["path"],
                )
                for a in w.project.assets()
                for r in (
                    a.get("images")
                    or (
                        [dict(path=a["image"], id=a["image"], source="旧版参考图")]
                        if a.get("image")
                        else []
                    )
                )
            ]
        elif op == "requirements":
            w.require_project()
            w.project.set_requirements(w.scene, d["rows"])
        elif op == "scene_override":
            w.require_project()
            if d["asset"] not in {a["id"] for a in w.project.assets()}:
                raise ValueError("资产不存在")
            w.project.config.setdefault("scene_overrides", {}).setdefault(w.scene, {})[
                d["asset"]
            ] = str(d["text"])
            w.project.invalidate(w.scene, 2, "本情节资产状态已修改")
            w.project.save_config()
        elif op == "save_prompt":
            w.require_project()
            w.project.config.setdefault("image_prompt_drafts", {})[w.scene] = d["text"]
            w.project.save_config()
        elif op == "node_parameters":
            return w.parameters(self.node(d))
        elif op == "node_read":
            w.require_project()
            node = self.node(d)
            scope = w.scope(node, d.get("asset"))
            return dict(
                record=redact(w.project.load_node(scope, node), w.secrets()),
                parameters=w.parameters(node),
                context=redact(w.context(node, d.get("asset")), w.secrets()),
            )
        elif op == "save_chat":
            node = self.node(d)
            w.require_project()
            scope = self.resolve_scope(d, node)
            record = w.project.load_node(scope, node)
            record.update(draft=str(d.get("draft", "")), final=str(d.get("final", "")))
            w.project.save_node(scope, node, record)
        elif op == "apply_output":
            w.apply_output(self.node(d), d["text"], d.get("asset"), d.get("selected"))
        elif op == "send":
            return self.send(d)
        elif op == "generate":
            return self.generate(d)
        elif op == "stop":
            if self.worker and self.worker.isRunning():
                self.worker.cancel.set()
        elif op == "choose_result":
            w.select_result(d["path"], d.get("scene"))
        elif op == "candidate_to_reference":
            w.require_project()
            if not any(d["path"] in j.get("results", []) for j in w.project.jobs()):
                raise ValueError("候选图片不存在")
            w.add_reference(d["asset"], w.file(d["path"]))
        elif op == "image":
            return w.image(d["path"], large=True)
        elif op == "connection_save":
            w.save_connection(d["profile"], d.get("key"), bool(d.get("remember")))
        elif op == "node_settings":
            w.require_account()
            node = self.node(d)
            w.store.save_node_default(w.account, node, d["params"], w.secrets())
        elif op == "save_template":
            w.require_account()
            w.store.save_template(w.account, d["template"])
        elif op == "reset_template":
            from .prompts import default_template

            w.require_account()
            node = self.node(d)
            params = w.store.node_defaults(w.account).get(str(node), {})
            params["template"] = default_template(node)
            w.store.save_node_default(w.account, node, params, w.secrets())
        elif op == "image_settings":
            w.require_account()
            w.store.save_image_defaults(w.account, d, w.secrets())
        elif op == "settings":
            w.require_account()
            settings = w.store.settings(w.account)
            settings.update(
                {k: v for k, v in d.items() if k in DEFAULTS and k != "background"}
            )
            w.store.save_settings(w.account, redact(settings, w.secrets()))
            if w.project and "rules" in d:
                w.project.config["rules"] = d["rules"]
                w.project.save_config()
        elif op == "background":
            w.require_account()
            path, _ = QFileDialog.getOpenFileName(
                self.host, "选择背景图片", "", "图片 (*.png *.jpg *.jpeg *.webp)"
            )
            if path:
                from PySide6.QtGui import QImageReader

                size = QImageReader(path).size()
                if (
                    not size.isValid()
                    or size.width() * size.height() > 50_000_000
                    or Path(path).stat().st_size > 20 * 1024 * 1024
                ):
                    raise ValueError("背景图片过大或不可读取")
                dest = (
                    w.store.account_dir(w.account)
                    / "界面资源"
                    / ("背景" + Path(path).suffix.lower())
                )
                if Path(path).resolve() != dest.resolve():
                    shutil.copy2(path, dest)
                settings = w.store.settings(w.account)
                settings["background"] = str(dest)
                w.store.save_settings(w.account, settings)
        elif op == "reset_appearance":
            w.require_account()
            settings = w.store.settings(w.account)
            for k in ("theme", "font_size", "background", "background_opacity"):
                settings[k] = DEFAULTS[k]
            settings["theme"] = "system"
            w.store.save_settings(w.account, settings)
        elif op == "export_settings":
            w.require_account()
            path, _ = QFileDialog.getSaveFileName(
                self.host,
                "导出账户设置（不含密钥）",
                str(w.store.account_dir(w.account) / "通用导出/账户设置.json"),
                "JSON (*.json)",
            )
            if path:
                w.store.export_settings(w.account, path, w.secrets())
        elif op == "import_settings":
            w.require_account()
            path, _ = QFileDialog.getOpenFileName(
                self.host, "导入账户设置", "", "JSON (*.json)"
            )
            if path:
                w.store.import_settings(w.account, path)
        elif op == "export_text":
            w.require_project()
            node = self.node(d)
            data = w.project.load_node(self.resolve_scope(d, node), node)
            fmt = "txt" if d.get("format") == "txt" else "md"
            text = (
                data.get("final", "")
                if d.get("mode") == "final"
                else Project.transcript(data, fmt, d.get("mode") == "outputs")
            )
            if not text.strip():
                raise ValueError("没有可导出的文本")
            dest = (
                w.project.path
                / "07_导出"
                / (safe_name(d.get("name", "对话输出")) + "_" + uid() + "." + fmt)
            )
            dest.write_text(redact(text, w.secrets()), "utf-8")
            return dict(path=str(dest))
        elif op == "export_results":
            w.require_project()
            dest = w.project.path / "07_导出" / ("插图成果_" + uid())
            dest.mkdir()
            selected = d.get("selected")
            rows = [
                r
                for r in w.project.final_results()
                if selected is None or r["id"] in selected
            ]
            for i, row in enumerate(rows):
                src = w.file(row["file"])
                shutil.copy2(
                    src, dest / (f"{i + 1:03d}_" + safe_name(row["title"]) + src.suffix)
                )
            write_json(dest / "成果索引.json", rows)
            return dict(path=str(dest))
        elif op == "files":
            w.require_project()
            return [
                dict(
                    path=p.relative_to(w.project.path).as_posix(),
                    directory=p.is_dir(),
                    size=p.stat().st_size if p.is_file() else 0,
                )
                for p in sorted(w.project.path.rglob("*"))
                if not p.is_symlink()
            ][:4000]
        elif op == "reveal":
            w.require_account()
            if d.get("path"):
                target = w.file(d["path"])
            else:
                target = w.project.path if w.project else w.store.account_dir(w.account)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        elif op == "backup":
            return self.backup()
        elif op == "restore_backup":
            return self.restore()
        else:
            raise ValueError("不支持的操作")
        return None

    def resolve_scope(self, data, node):
        w = self.workspace
        w.require_project()
        if data.get("asset"):
            return w.scope(node, data["asset"])
        scope = data.get("scope") or w.scope(node)
        if node in (0, 7):
            if scope not in {s["id"] for s in w.project.segments()}:
                raise ValueError("原文片段已变化")
        elif not w.project.scene(scope):
            raise ValueError("情节不存在")
        return scope

    @staticmethod
    def node(data):
        node = data.get("node", 0)
        if type(node) is not int or not 0 <= node < 8:
            raise ValueError("节点无效")
        return node

    def upload(self, d):
        w = self.workspace
        w.require_project()
        raw = base64.b64decode(d["data"], validate=True)
        if len(raw) > 25 * 1024 * 1024:
            raise ValueError("单文件限 25 MB")
        name = safe_name(Path(d["name"]).name)
        ext = Path(name).suffix.lower()
        target = d.get("target", "attachment")
        permitted = (
            (".txt", ".md", ".docx", ".epub")
            if target == "text"
            else (".png", ".jpg", ".jpeg", ".webp")
            if target == "reference"
            else (".txt", ".md", ".docx", ".epub", ".png", ".jpg", ".jpeg", ".webp")
        )
        if ext not in permitted:
            raise ValueError("不支持此文件类型")
        dest = w.project.path / "01_原始资料/其他附件" / (uid() + "_" + name)
        dest.write_bytes(raw)
        if target == "text":
            try:
                w.import_text(Path(name).stem, read_document(dest), dest)
            finally:
                dest.unlink(missing_ok=True)
        elif target == "reference":
            try:
                w.add_reference(d["asset"], dest)
            finally:
                dest.unlink(missing_ok=True)
        else:
            return dict(
                path=dest.relative_to(w.project.path).as_posix(),
                name=name,
                size=len(raw),
            )
        return None

    def attachment_confirmation(self, params, paths):
        w = self.workspace
        if (
            params.get("provider") == "demo"
            or not paths
            or not w.store.settings(w.account)["confirm_attachments"]
        ):
            return True
        size = sum(p.stat().st_size for p in paths)
        return self.confirm(
            "确认本次附件",
            f"将发送 {len(paths)} 个附件，原始大小约 {size / 1024**2:.2f} MB（编码后可能更大）。\n目标：{params.get('endpoint', '')}\n\n附件包括当前请求使用的历史附件。继续吗？",
        )

    def send(self, d):
        w = self.workspace
        w.require_project()
        w.guard()
        node = self.node(d)
        record = w.project.load_node(w.scope(node, d.get("asset")), node)
        refs = set(d.get("attachments", [])) | {
            f for m in record["messages"] for f in m.get("attachments", [])
        }
        paths = [w.file(f) for f in refs]
        params = w.parameters(node)
        if (
            params["provider"] != "demo"
            and any(
                p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") for p in paths
            )
            and not params["vision"]
        ):
            raise ValueError("当前连接未声明视觉输入能力，请在设置中开启或移除图片")
        if not self.attachment_confirmation(params, paths):
            return dict(cancelled=True)
        job, _, paths, key = w.prepare_text(
            node, d["message"], d.get("asset"), d.get("attachments", [])
        )
        job["auto_split_candidates"] = bool(d.get("split"))

        def run(cancel, progress):
            return text_call(
                job["params"], job["messages"], job["context"], key, paths, cancel
            )

        self.start(job, run, text=True)
        return dict(job=job["id"])

    def generate(self, d):
        w = self.workspace
        w.require_project()
        w.guard()
        asset = next((a for a in w.project.assets() if a["id"] == d.get("asset")), None)
        if d.get("asset") and not asset:
            raise ValueError("目标资产不存在")
        task = asset["kind"] if asset else "illustration"
        config = w.store.image_defaults(w.account)
        if asset and not config.get("tasks", {}).get(task, {}).get("connection_id"):
            raise ValueError(
                "请先为此类资产参考图保存独立图片任务配置；不会借用插图连接"
            )
        config = dict(config, **config.get("tasks", {}).get(task, {}))
        cid = config.get("connection_id", "image-default")
        profile = next(
            (c for c in w.store.connections(w.account) if c["id"] == cid), None
        )
        if not profile or profile["kind"] not in ("comfy", "image_api"):
            raise ValueError("请在图片模型配置中为此任务选择图片 API 或 ComfyUI 连接")
        prompt = str(d.get("prompt", "")).strip()
        if not prompt:
            raise ValueError("请先填写并确认本次提示词")
        if config.get("generation_rules"):
            prompt += "\n\n【图片节点约束】\n" + config["generation_rules"]
        rows = w.project.scene_assets(w.scene) if w.scene and not asset else []
        issues = [r["name"] + "：" + r["problem"] for r in rows if r["problem"]]
        if not asset and not w.scene:
            raise ValueError("请先确认并选择情节")
        if not asset and not rows:
            issues.append("此情节尚未关联资产")
        if issues and not self.confirm(
            "缺失资产检查", "\n".join(issues) + "\n\n接受这些缺失并继续生成吗？"
        ):
            return dict(cancelled=True)
        if not asset:
            w.context(3)  # Validate the scene still matches its source.
        overrides = w.project.config.get("scene_overrides", {}).get(w.scene, {})
        if rows:
            prompt += "\n\n【本画面关联资产】\n" + "\n".join(
                (
                    r["name"]
                    + "（"
                    + r["kind"]
                    + "）："
                    + (
                        (r.get("asset") or {}).get(
                            "description", "档案缺失；依据用户已确认方案"
                        )
                    )
                    + (
                        "\n本情节状态：" + overrides[r["asset_id"]]
                        if r.get("asset_id") in overrides
                        else ""
                    )
                )
                for r in rows
            )
        key = w.key(cid)
        job = dict(
            id=uid(),
            kind="资产参考图" if asset else "场景插图",
            created=now(),
            status="running",
            segment=w.segment,
            scene=w.scene,
            asset=asset and asset["id"],
            prompt=prompt,
            connection=copy.deepcopy(profile),
            assets=copy.deepcopy(rows),
            accepted_missing=issues,
            overrides=copy.deepcopy(
                w.project.config.get("scene_overrides", {}).get(w.scene, {})
            ),
        )
        if w.scene:
            job["scene_snapshot"] = w.project.scene(w.scene)
        dest = w.project.path / "05_生成任务" / job["id"] / "候选图片"
        if profile["kind"] == "comfy":
            flow = json.loads(config.get("workflow", "{}"))
            mapping = json.loads(config.get("mapping", "{}"))
            refs = []
            reference_rows = [dict(asset=asset, name=asset["name"])] if asset else rows
            unmapped = []
            for i, row in enumerate(reference_rows):
                a = row.get("asset")
                if a and a.get("image") and w.file(a["image"]).exists():
                    field = "reference_" + str(i + 1)
                    if field in mapping:
                        refs.append((field, w.file(a["image"])))
                    else:
                        unmapped.append(a["name"])
            if unmapped and not self.confirm(
                "参考图未映射",
                "这些图片不会上传："
                + "、".join(unmapped)
                + "。继续仅使用文字和已映射图片吗？",
            ):
                return dict(cancelled=True)
            values = dict(prompt=prompt, seed=int(config.get("seed", 42)))
            bind_workflow(
                flow, mapping, dict(values, **{f: "pending.png" for f, _ in refs})
            )
            if not self.attachment_confirmation(profile, [p for _, p in refs]):
                return dict(cancelled=True)
            job.update(
                workflow=flow,
                mapping=mapping,
                reference_files=[
                    p.relative_to(w.project.path).as_posix() for _, p in refs
                ],
            )

            def run(cancel, progress):
                actual = dict(values)
                for field, path in refs:
                    if cancel.is_set():
                        raise UnknownOutcome("已停止上传等待；不会自动提交或重试")
                    actual[field] = upload_comfy(profile["endpoint"], path, key)
                bound = bind_workflow(flow, mapping, actual)
                progress(dict(submitted_workflow=bound))
                return comfy_call(
                    profile["endpoint"], bound, dest, cancel, progress, key
                )
        else:
            if (
                asset
                and asset.get("image")
                or any(r.get("asset", {}).get("image") for r in rows if r.get("asset"))
            ) and not self.confirm(
                "兼容接口能力",
                "当前兼容图片接口只支持文生图，不会发送参考图。是否接受后继续？",
            ):
                return dict(cancelled=True)
            size = config.get("size", "1024x1024")
            job["size"] = size

            def run(cancel, progress):
                return image_call(profile, prompt, size, dest, key, cancel)

        w.project.secrets = w.secrets()
        w.project.save_job(job)
        self.start(job, run, text=False)
        return dict(job=job["id"])

    def start(self, job, run, text):
        w = self.workspace
        w.busy = True
        self.job = job
        worker = Worker(run, self)
        self.worker = worker

        def progress(data):
            job.update(data)
            w.project.save_job(job)
            self.changed.emit(json.dumps(dict(type="progress", job=job["id"])))

        def finish(value=None, error=None):
            try:
                if not text and error is None:
                    if not value or any(
                        not w.image(Path(f).relative_to(w.project.path).as_posix())
                        for f in value
                    ):
                        raise UnknownOutcome(
                            "远端已返回，但图片不完整或无法读取；文件与任务已保留，请核查后再决定是否重试。"
                        )
                if text:
                    w.finish_text(job, value if error is None else None, error)
                    if error is None and job.get("auto_split_candidates"):
                        try:
                            from .prompts import parse_object, validate_scenes

                            rows = validate_scenes(
                                parse_object(value),
                                len(w.project.paragraphs(job["segment"])),
                            )
                            w.save_split(rows)
                        except ValueError as e:
                            job["validation_error"] = str(e)
                            w.project.save_job(job)
                else:
                    if error:
                        job.update(
                            status="unknown" if error.get("unknown") else "failed",
                            error=error["message"],
                        )
                    else:
                        job.update(
                            status="success",
                            results=[
                                Path(f).relative_to(w.project.path).as_posix()
                                for f in value
                            ],
                        )
                        if job.get("asset"):
                            for f in value:
                                w.add_reference(job["asset"], f)
                    w.project.save_job(job)
            except Exception as failure:
                error = dict(
                    message=str(failure)
                    if isinstance(failure, ProviderError)
                    else "本地结果落盘未完成，请检查磁盘与项目目录；不会自动重试。",
                    unknown=True,
                )
                job.update(status="unknown", error=error["message"])
                try:
                    w.project.save_job(job)
                except OSError:
                    pass
            finally:
                w.busy = False
                self.changed.emit(
                    json.dumps(dict(type="finished", job=job["id"], error=error))
                )

        worker.update.connect(progress)
        worker.completed.connect(lambda value: finish(value=value))
        worker.failed.connect(lambda error: finish(error=error))
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(
            lambda: setattr(self, "worker", None) if self.worker is worker else None
        )
        worker.start()
        self.changed.emit(json.dumps(dict(type="started", job=job["id"])))

    def backup(self):
        w = self.workspace
        w.require_project()
        w.guard()
        path, _ = QFileDialog.getSaveFileName(
            self.host,
            "项目备份（不含账户密钥）",
            str(w.store.root / (safe_name(w.project.meta["name"]) + "_备份.zip")),
            "ZIP (*.zip)",
        )
        if not path:
            return None
        dest = Path(path).resolve()
        if w.project.path in dest.parents:
            raise ValueError("备份请保存到当前项目之外")
        w.project.db.commit()
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
            for f in w.project.path.rglob("*"):
                if f.is_file() and not f.is_symlink():
                    archive.write(f, f.relative_to(w.project.path))
        return dict(path=str(dest))

    def restore(self):
        w = self.workspace
        w.require_account()
        w.guard()
        path, _ = QFileDialog.getOpenFileName(
            self.host, "恢复项目副本", "", "ZIP (*.zip)"
        )
        if not path:
            return None
        dest = w.store.account_dir(w.account) / "项目" / ("恢复副本_" + uid())
        try:
            with zipfile.ZipFile(path) as archive:
                if sum(i.file_size for i in archive.infolist()) > 4 * 1024**3:
                    raise ValueError("备份解压体积超过 4 GB")
                for i in archive.infolist():
                    target = (dest / i.filename).resolve()
                    if (
                        dest.resolve() not in target.parents
                        or (i.external_attr >> 16) & 0o170000 == 0o120000
                    ):
                        raise ValueError("备份含不安全路径或符号链接")
                if not {
                    "08_项目数据/project.json",
                    "08_项目数据/index.sqlite",
                }.issubset(archive.namelist()):
                    raise ValueError("不是本软件的备份")
                archive.extractall(dest)
            meta = json.loads((dest / "08_项目数据/project.json").read_text("utf-8"))
            meta.update(restored_from=meta["id"], id=uid())
            write_json(dest / "08_项目数据/project.json", meta)
            project = Project(dest)
            project.close()
            w.open_project(str(dest))
        except Exception:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        return None


class LocalPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        # Documents and model output are data, never navigation or executable pages.
        if not is_main_frame:
            return False
        expected = Path(__file__).parent / "web/index.html"
        return (
            url.isLocalFile()
            and Path(url.toLocalFile()).resolve() == expected.resolve()
        )


class Desktop(QMainWindow):
    def __init__(self, root):
        super().__init__()
        self.setWindowTitle("墨境 · 小说文本可视化 · v0.4.0-beta.1 测试版")
        self.bridge = Bridge(root, self)
        self.view = QWebEngineView(self)
        page = LocalPage(self.view)
        self.view.setPage(page)
        channel = QWebChannel(page)
        channel.registerObject("workspace", self.bridge)
        page.setWebChannel(channel)
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
        settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, False)
        self.setCentralWidget(self.view)
        self.setMinimumSize(640, 480)
        available = self.screen().availableGeometry()
        self.resize(
            min(1520, int(available.width() * 0.94)),
            min(1000, int(available.height() * 0.92)),
        )
        self.view.load(
            QUrl.fromLocalFile(str(Path(__file__).parent / "web/index.html"))
        )
        QApplication.styleHints().colorSchemeChanged.connect(
            lambda *_: self.bridge.changed.emit('{"type":"theme"}')
        )

    def closeEvent(self, event):
        if self.bridge.workspace.busy:
            QMessageBox.information(
                self, "任务仍在执行", "请先停止本地等待并等任务状态落盘，再关闭程序。"
            )
            event.ignore()
            return
        if not getattr(self, "_closing", False):
            event.ignore()

            def checked(has_handler):
                if not has_handler:
                    self._closing = True
                    self.close()

            self.view.page().runJavaScript(
                "typeof window.__novelvizRequestClose === 'function' ? (window.__novelvizRequestClose(), true) : false",
                checked,
            )
            return
        self.bridge.workspace.close()
        event.accept()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root")
    parser.add_argument("--choose-root", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--screenshot")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("NovelVisualizer")
    app.setOrganizationName("NovelStudio")
    q = QSettings()
    root = args.data_root or q.value("data_root", "")
    if args.choose_root:
        root = QFileDialog.getExistingDirectory(None, "选择用户资料根目录", str(root))
        if not root:
            return
    if not root:
        root = str(
            Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
            / "墨境用户资料"
        )
    q.setValue("data_root", root)
    if args.demo:
        from .demo import seed_visual_demo

        seed_visual_demo(Store(root))
    window = Desktop(root)
    window.show()
    if args.screenshot:
        QTimer.singleShot(
            4000, lambda: (window.grab().save(args.screenshot), app.quit())
        )
    sys.exit(app.exec())
