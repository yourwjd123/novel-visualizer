"""Editors and drop targets shared by the modular desktop workspace."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .connections import KINDS, clean_profile
from .prompts import VERSION, assemble, default_template
from .storage import DEFAULTS, read_document, redact, uid


def btn(text, fn):
    b = QPushButton(text)
    b.clicked.connect(fn)
    b.setCursor(Qt.PointingHandCursor)
    return b


def text_label(text):
    l = QLabel(text)
    l.setWordWrap(True)
    return l


def buttons(dialog, layout, save):
    b = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    b.button(QDialogButtonBox.Save).setText("保存")
    b.button(QDialogButtonBox.Cancel).setText("取消")
    b.accepted.connect(save)
    b.rejected.connect(dialog.reject)
    layout.addWidget(b)


class DropEdit(QPlainTextEdit):
    filesDropped = Signal(list)

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if paths:
                self.filesDropped.emit(paths)
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


class ConnectionDialog(QDialog):
    def __init__(self, win, profile=None, kind="demo"):
        super().__init__(win)
        self.win = win
        self.profile = copy.deepcopy(
            profile
            or dict(
                id="conn-" + uid(),
                name="新连接",
                kind=kind,
                endpoint="",
                model="",
                max_tokens=4096,
                temperature=0.7,
                vision=False,
            )
        )
        self.setWindowTitle("独立连接与密钥")
        self.resize(640, 600)
        l = QVBoxLayout(self)
        f = QFormLayout()
        l.addLayout(f)
        self.name = QLineEdit(self.profile["name"])
        self.kind = QComboBox()
        for k, v in KINDS.items():
            self.kind.addItem(v, k)
        self.kind.setCurrentIndex(self.kind.findData(self.profile["kind"]))
        self.url = QLineEdit(self.profile.get("endpoint", ""))
        self.model = QLineEdit(self.profile.get("model", ""))
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("留空保留此连接原密钥；不继承其他连接的密钥")
        self.persist = QCheckBox("保存到系统安全凭据库（否则仅本次会话）")
        self.clear = QCheckBox("删除此连接密钥")
        self.vision = QCheckBox("已验证支持图片输入")
        self.vision.setChecked(self.profile.get("vision", False))
        for title, w in [
            ("名称", self.name),
            ("接入协议", self.kind),
            ("服务地址", self.url),
            ("模型标识", self.model),
            ("此连接的 API 密钥", self.key),
            ("", self.persist),
            ("", self.clear),
            ("能力", self.vision),
        ]:
            f.addRow(title, w)
        l.addWidget(
            text_label(
                "文本连接填写基础 /v1 地址；图像兼容连接使用 /images/generations；ComfyUI 填写服务根地址。不同连接的密钥独立且不进入项目或导出。编辑复用连接会影响以后选择该连接的节点，可先“复制为独立连接”。"
            )
        )
        l.addStretch()
        buttons(self, l, self.save)

    def save(self):
        try:
            data = clean_profile(
                dict(
                    self.profile,
                    name=self.name.text().strip(),
                    kind=self.kind.currentData(),
                    endpoint=self.url.text().strip(),
                    model=self.model.text().strip(),
                    vision=self.vision.isChecked(),
                    legacy=bool(
                        self.profile.get("legacy")
                        and not self.key.text()
                        and not self.clear.isChecked()
                    ),
                )
            )
            if self.clear.isChecked():
                self.win.set_connection_key(data["id"], "", True)
            if self.key.text():
                self.win.set_connection_key(
                    data["id"], self.key.text(), self.persist.isChecked()
                )
            self.profile = self.win.store.save_connection(
                self.win.account, redact(data, self.win.known_secrets())
            )
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "无法保存连接", str(e))


class NodeForm(QWidget):
    def __init__(self, win, node, params):
        super().__init__()
        self.win = win
        self.node = node
        self.original = copy.deepcopy(params)
        l = QVBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)
        self.connection = QComboBox()
        self.connection.setMinimumContentsLength(8)
        self.connection.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        row = QHBoxLayout()
        row.addWidget(self.connection, 1)
        row.addWidget(btn("编辑连接 / 密钥", self.edit_connection))
        row.addWidget(btn("新建", self.new_connection))
        l.addLayout(row)
        self.connection_summary = text_label("")
        l.addWidget(self.connection_summary)
        self.copy_btn = btn("复制为独立连接", self.copy_connection)
        l.addWidget(self.copy_btn)
        f = QFormLayout()
        self.tokens = QSpinBox()
        self.tokens.setRange(1, 131072)
        self.tokens.setValue(params.get("max_tokens", 4096))
        self.temp = QDoubleSpinBox()
        self.temp.setRange(0, 2)
        self.temp.setSingleStep(0.1)
        self.temp.setValue(params.get("temperature", 0.7))
        f.addRow("最大输出 token", self.tokens)
        f.addRow("温度", self.temp)
        l.addLayout(f)
        self.templates = QComboBox()
        row = QHBoxLayout()
        row.addWidget(text_label("任务模板"))
        row.addWidget(self.templates, 1)
        l.addLayout(row)
        self.template_name = QLineEdit()
        self.output = QComboBox()
        for name, key in [
            ("自由文本", "text"),
            ("情节 JSON", "scenes"),
            ("资产 JSON", "assets"),
        ]:
            if (
                key == "text"
                or (node == 0 and key == "scenes")
                or (node == 1 and key == "assets")
            ):
                self.output.addItem(name, key)
        f = QFormLayout()
        f.addRow("模板名称", self.template_name)
        f.addRow("输出约定", self.output)
        l.addLayout(f)
        self.system = DropEdit()
        self.system.setMinimumHeight(240)
        self.system.filesDropped.connect(self.drop_template)
        l.addWidget(self.system, 1)
        row = QHBoxLayout()
        row.addWidget(btn("保存为账户模板", self.save_template))
        row.addWidget(btn("另存 / 新增模板", self.new_template))
        row.addWidget(btn("恢复内置默认", self.reset_template))
        l.addLayout(row)
        self.supplement = DropEdit()
        self.supplement.setPlaceholderText(
            "本节点补充要求，例如：画风、语言、忠实程度。可拖入 TXT/MD。"
        )
        self.supplement.setMaximumHeight(100)
        self.supplement.setPlainText(params.get("supplement", ""))
        self.supplement.filesDropped.connect(
            lambda paths: self.drop_text(paths, self.supplement)
        )
        l.addWidget(self.supplement)
        l.addWidget(btn("预览提示词（不发送）", lambda: win.preview_config_form(self)))
        self.reload_connections(params.get("connection_id", f"node-{node}"))
        self.reload_templates(
            params.get("template", {}).get(
                "id", params.get("template_id", default_template(node)["id"])
            )
        )
        snapshot = params.get("template")
        if snapshot:
            self.current = copy.deepcopy(snapshot)
            self.template_name.setText(snapshot["name"])
            self.system.setPlainText(snapshot["body"])
            self.output.setCurrentIndex(self.output.findData(snapshot["format"]))
        elif params.get("system") and not params.get("template_id"):
            # Preserve custom v0.1 instructions as an explicit supplement, not as a replacement of the new defaults.
            if params["system"] != DEFAULTS["system"]:
                self.supplement.setPlainText(params["system"])
        self.connection.currentIndexChanged.connect(self.connection_changed)
        self.templates.currentIndexChanged.connect(self.template_changed)

    def reload_connections(self, selected=None):
        self.connection.blockSignals(True)
        self.connection.clear()
        for c in self.win.store.connections(self.win.account):
            if c["kind"] in ("demo", "openai"):
                self.connection.addItem(c["name"], c["id"])
        self.connection.setCurrentIndex(self.connection.findData(selected))
        self.connection.blockSignals(False)
        self.connection_changed()

    def connection_changed(self, *_):
        c = self.selected_connection()
        self.connection_summary.setText(
            "连接不存在，请重新选择；不会自动切换。"
            if not c
            else f"{KINDS[c['kind']]} · {c['endpoint'] or '不联网'} · {c['model'] or '未设置模型'} · 密钥"
            + ("已配置" if self.win.connection_key(c["id"]) else "未配置")
        )

    def selected_connection(self):
        return next(
            (
                c
                for c in self.win.store.connections(self.win.account)
                if c["id"] == self.connection.currentData()
            ),
            None,
        )

    def edit_connection(self):
        c = self.selected_connection()
        if not c:
            return
        d = ConnectionDialog(self.win, c)
        if d.exec():
            self.reload_connections(d.profile["id"])

    def new_connection(self):
        d = ConnectionDialog(self.win)
        if d.exec():
            self.reload_connections(d.profile["id"])

    def copy_connection(self):
        c = self.selected_connection()
        if not c:
            return
        c = copy.deepcopy(c)
        c.update(id="conn-" + uid(), name=c["name"] + " · 副本", legacy=False)
        d = ConnectionDialog(self.win, c)
        if d.exec():
            self.reload_connections(d.profile["id"])

    def reload_templates(self, selected):
        self.templates.blockSignals(True)
        self.templates.clear()
        for t in self.win.store.templates(self.win.account, self.node):
            self.templates.addItem(t["name"], t)
        i = next(
            (
                i
                for i in range(self.templates.count())
                if self.templates.itemData(i)["id"] == selected
            ),
            0,
        )
        self.templates.setCurrentIndex(i)
        self.templates.blockSignals(False)
        self.template_changed()

    def template_changed(self, *_):
        t = self.templates.currentData()
        if not t:
            return
        self.current = copy.deepcopy(t)
        self.template_name.setText(t["name"])
        self.system.setPlainText(t["body"])
        self.output.setCurrentIndex(self.output.findData(t["format"]))

    def template_value(self):
        t = copy.deepcopy(self.current)
        t.update(
            name=self.template_name.text().strip(),
            body=self.system.toPlainText(),
            format=self.output.currentData(),
            version=VERSION,
        )
        if not t["name"] or not t["body"].strip():
            raise ValueError("模板名称和正文不能为空")
        return t

    def save_template(self):
        try:
            t = redact(self.template_value(), self.win.known_secrets())
            self.win.store.save_template(self.win.account, t)
            self.reload_templates(t["id"])
        except Exception as e:
            QMessageBox.warning(self, "模板未保存", str(e))

    def new_template(self):
        name, ok = QInputDialog.getText(
            self, "添加模板", "新模板名称", text=self.template_name.text() + " · 自定义"
        )
        if not ok:
            return
        try:
            t = self.template_value()
            t.update(id="custom-" + uid(), name=name, builtin=False)
            t = redact(t, self.win.known_secrets())
            self.win.store.save_template(self.win.account, t)
            self.reload_templates(t["id"])
        except Exception as e:
            QMessageBox.warning(self, "无法新增模板", str(e))

    def reset_template(self):
        t = default_template(self.node)
        self.win.store.reset_template(self.win.account, t["id"])
        self.reload_templates(t["id"])
        self.supplement.clear()

    def drop_text(self, paths, target):
        try:
            for p in paths:
                if Path(p).suffix.lower() not in (".txt", ".md"):
                    raise ValueError(
                        "提示词仅支持拖入 TXT/MD；图片请拖入对话框作为附件"
                    )
                target.insertPlainText(read_document(p))
        except Exception as e:
            QMessageBox.warning(self, "无法导入提示词", str(e))

    def drop_template(self, paths):
        self.drop_text(paths, self.system)

    def value(self):
        c = self.selected_connection()
        if not c:
            raise ValueError("节点连接缺失，请选择连接或手工填写最终方案")
        t = self.template_value()
        rules = self.win.project.config.get("rules", "") if self.win.project else ""
        return dict(
            connection_id=c["id"],
            provider="demo" if c["kind"] == "demo" else "openai",
            endpoint=c["endpoint"],
            model=c["model"],
            vision=c["vision"],
            max_tokens=self.tokens.value(),
            temperature=self.temp.value(),
            template=t,
            supplement=self.supplement.toPlainText(),
            system=assemble(t, self.supplement.toPlainText(), rules),
            template_id=t["id"],
        )


class SceneDialog(QDialog):
    def __init__(self, win, scene=None):
        super().__init__(win)
        self.win = win
        self.data = copy.deepcopy(scene or {})
        self.setWindowTitle("情节模块")
        self.resize(650, 590)
        l = QVBoxLayout(self)
        f = QFormLayout()
        l.addLayout(f)
        self.title = QLineEdit(self.data.get("title", ""))
        self.summary = DropEdit(self.data.get("summary", ""))
        self.summary.setMaximumHeight(110)
        self.summary.filesDropped.connect(
            lambda paths: win.append_text_files(paths, self.summary)
        )
        self.first = QSpinBox()
        self.last = QSpinBox()
        n = len(win.project.paragraphs(win.sid))
        self.first.setRange(1, max(1, n))
        self.last.setRange(1, max(1, n))
        self.first.setValue(self.data.get("start_paragraph", 1))
        self.last.setValue(self.data.get("end_paragraph", n))
        self.required = DropEdit()
        self.required.setPlaceholderText("每行：人物|沈青 或 场景|渡口 或 道具|旧铜灯")
        req = win.project.requirements(scene["id"]) if scene else []
        self.old_requirements = req
        self.required.setPlainText("\n".join(x["kind"] + "|" + x["name"] for x in req))
        for title, w in [
            ("标题", self.title),
            ("摘要", self.summary),
            ("起始段落", self.first),
            ("结束段落", self.last),
            ("画面需要的资产", self.required),
        ]:
            f.addRow(title, w)
        l.addWidget(
            text_label(
                "范围使用原文段落编号。调整既有情节会将下游确认方案标为需复核；历史版本保留。"
            )
        )
        buttons(self, l, self.accept)

    def value(self):
        rows = []
        for line in self.required.toPlainText().splitlines():
            if not line.strip():
                continue
            parts = line.split("|", 1)
            if len(parts) != 2:
                raise ValueError("资产需求格式应为 类型|名称")
            kind, name = (p.strip() for p in parts)
            old = next(
                (
                    r
                    for r in self.old_requirements
                    if r["name"] == name and r["kind"] == kind
                ),
                {},
            )
            rows.append(dict(old, kind=kind, name=name))
        return dict(
            self.data,
            segment=self.win.sid,
            title=self.title.text().strip(),
            summary=self.summary.toPlainText(),
            start_paragraph=self.first.value(),
            end_paragraph=self.last.value(),
            required_assets=rows,
        )


class AssetDialog(QDialog):
    def __init__(self, parent, data=None):
        super().__init__(parent)
        self.win = parent
        self.data = copy.deepcopy(data or {})
        self.setWindowTitle("共享资产档案")
        self.resize(740, 720)
        l = QVBoxLayout(self)
        form_widget = QWidget()
        f = QFormLayout(form_widget)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(form_widget)
        l.addWidget(area, 1)
        self.name = QLineEdit(self.data.get("name", ""))
        self.kind = QComboBox()
        self.kind.addItems(["人物", "场景", "道具"])
        self.kind.setCurrentText(self.data.get("kind", "人物"))
        if self.data.get("id"):
            self.kind.setEnabled(False)
        self.source = QComboBox()
        self.source.addItems(["原文明确", "AI 建议", "用户自定"])
        self.source.setCurrentText(self.data.get("source", "用户自定"))
        self.review = QComboBox()
        self.review.addItems(["待审核", "已确认", "已锁定"])
        self.review.setCurrentText(self.data.get("review", "待审核"))
        self.description = DropEdit(self.data.get("description", ""))
        self.description.setPlaceholderText(
            "档案、逐项证据、生效范围、服装状态、冲突与缺失信息"
        )
        self.description.filesDropped.connect(self.drop)
        self.details = DropEdit(
            json.dumps(
                {
                    k: self.data[k]
                    for k in (
                        "attributes",
                        "evidence",
                        "states",
                        "suggestions",
                        "conflicts",
                        "missing",
                        "existing_id",
                    )
                    if k in self.data
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        self.details.setMaximumHeight(120)
        self.details.filesDropped.connect(
            lambda paths: self.win.append_text_files(paths, self.details)
        )
        self.preview = QLabel("可拖入图片或点击添加参考图")
        self.preview.setMinimumHeight(120)
        self.preview.setAlignment(Qt.AlignCenter)
        self.pending_image = None
        for name, w in [
            ("名称", self.name),
            ("类型", self.kind),
            ("来源", self.source),
            ("审核", self.review),
            ("档案描述", self.description),
            ("属性 / 证据 / 状态 JSON", self.details),
            ("主参考图", self.preview),
        ]:
            f.addRow(name, w)
        row = QHBoxLayout()
        row.addWidget(btn("添加参考图", self.pick))
        row.addWidget(btn("移除主图", self.remove_image))
        l.addLayout(row)
        buttons(self, l, self.accept)
        self.refresh_image()

    def pick(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "资产参考图", "", "图片 (*.png *.jpg *.jpeg *.webp)"
        )
        if p:
            self.drop([p])

    def drop(self, paths):
        try:
            for p in paths:
                if Path(p).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    if QPixmap(p).isNull():
                        raise ValueError("图片无法读取")
                    self.pending_image = p
                elif Path(p).suffix.lower() in (".txt", ".md"):
                    self.description.insertPlainText(read_document(p))
                else:
                    raise ValueError("资产编辑支持 TXT/MD 和图片")
            self.refresh_image()
        except Exception as e:
            QMessageBox.warning(self, "附件未导入", str(e))

    def remove_image(self):
        self.pending_image = None
        self.data["image"] = ""
        self.refresh_image()

    def refresh_image(self):
        path = self.pending_image or (
            str(self.win.project.path / self.data["image"])
            if self.data.get("image")
            else ""
        )
        pix = QPixmap(path)
        if pix.isNull():
            self.preview.setText("未设置主参考图 · 可以将图片拖入档案框")
        else:
            self.preview.setPixmap(
                pix.scaled(300, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    def value(self):
        details = json.loads(self.details.toPlainText() or "{}")
        if not isinstance(details, dict):
            raise ValueError("结构化内容必须是JSON对象")
        for k in (
            "attributes",
            "evidence",
            "states",
            "suggestions",
            "conflicts",
            "missing",
            "existing_id",
        ):
            self.data.pop(k, None)
            if k in details:
                self.data[k] = details[k]
        self.data.update(
            name=self.name.text().strip(),
            kind=self.kind.currentText(),
            source=self.source.currentText(),
            review=self.review.currentText(),
            description=self.description.toPlainText(),
        )
        if not self.data["name"]:
            raise ValueError("资产名称不能为空")
        self.data.setdefault("id", uid())
        if self.pending_image:
            self.data["image"] = self.win.project.save_asset_image(
                self.data, self.pending_image
            )
        return self.data
