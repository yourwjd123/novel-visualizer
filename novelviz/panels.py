"""System panels and the movable assistant; work pages contain no provider editors."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .components import ConnectionDialog, DropEdit, NodeForm, btn, text_label
from .providers import bind_workflow
from .storage import NODES, Store, redact


def scroll(w):
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setWidget(w)
    return s


class FloatingAssistant(QDialog):
    def __init__(self, win):
        super().__init__(win, Qt.Tool)
        self.win = win
        self.setWindowTitle("AI 助手 · 对话与定稿")
        self.setMinimumSize(390, 390)
        self.resize(530, 680)

    def closeEvent(self, event):
        self.win.save_draft(silent=True)
        self.win.persist_assistant_geometry()
        event.ignore()
        self.hide()

    def hideEvent(self, event):
        if hasattr(self.win, "assistant"):
            self.win.persist_assistant_geometry()
        super().hideEvent(event)

    def restore_position(self):
        value = self.win.settings.get("assistant_geometry", "")
        if value:
            self.restoreGeometry(QByteArray.fromBase64(value.encode()))
        else:
            self.move(
                self.win.mapToGlobal(self.win.rect().topRight())
                + self.win.assistant_offset()
            )
        screen = self.screen().availableGeometry()
        self.resize(
            min(self.width(), screen.width()), min(self.height(), screen.height())
        )
        self.move(
            max(screen.left(), min(self.x(), screen.right() - self.width())),
            max(screen.top(), min(self.y(), screen.bottom() - self.height())),
        )


class AccountDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.selected_store = win.store
        self.account_id = None
        self.setWindowTitle("选择 / 创建本地账户")
        self.resize(530, 450)
        l = QVBoxLayout(self)
        l.addWidget(
            text_label("选择账户后才读取个人项目和模型设置。完成后继续刚才的操作。")
        )
        self.root_label = text_label(str(win.store.root))
        l.addWidget(self.root_label)
        l.addWidget(btn("选择数据根目录", self.choose_root))
        self.list = QListWidget()
        l.addWidget(self.list, 1)
        l.addWidget(btn("使用所选账户", self.use_existing))
        self.name = QLineEdit()
        self.name.setPlaceholderText("新账户名称")
        l.addWidget(self.name)
        row = QHBoxLayout()
        row.addWidget(btn("取消", self.reject))
        row.addWidget(btn("创建并进入", self.create))
        l.addLayout(row)
        self.reload()

    def reload(self):
        self.list.clear()
        for a in self.selected_store.accounts:
            item = QListWidgetItem(a["name"])
            item.setData(Qt.UserRole, a["id"])
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def choose_root(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择账户与项目数据根目录", str(self.selected_store.root)
        )
        if path:
            try:
                self.selected_store = Store(path, create_default=False)
                self.root_label.setText(path)
                self.reload()
            except Exception as e:
                QMessageBox.warning(self, "目录不可用", str(e))

    def use_existing(self):
        item = self.list.currentItem()
        if item:
            self.account_id = item.data(Qt.UserRole)
            self.accept()

    def create(self):
        try:
            self.account_id = self.selected_store.create_account(self.name.text())["id"]
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "无法创建账户", str(e))


class SettingsPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.loading = False
        self.node = win.node
        self.form = None
        self.saved_language = None
        self.saved_image = None
        l = QVBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)
        l.addWidget(text_label("统一设置 · 各任务独立配置，密钥按账户安全保存"))
        self.categories = QTabWidget()
        l.addWidget(self.categories, 1)
        language = QWidget()
        ll = QVBoxLayout(language)
        self.nodes = QComboBox()
        for i in (0, 1, 5, 2, 3, 4, 6, 7):
            self.nodes.addItem(NODES[i], i)
        self.nodes.setCurrentIndex(self.nodes.findData(self.node))
        ll.addWidget(self.nodes)
        self.form_host = QWidget()
        self.form_layout = QVBoxLayout(self.form_host)
        ll.addWidget(scroll(self.form_host), 1)
        ll.addWidget(btn("保存此节点的语言模型配置与提示词", self.save_language))
        self.categories.addTab(language, "语言模型配置")
        image = QWidget()
        il = QVBoxLayout(image)
        il.addWidget(
            text_label("图片模型配置独立于语言模型。ComfyUI API 工作流与映射在此维护。")
        )
        row = QHBoxLayout()
        row.addWidget(win.image_connections, 1)
        row.addWidget(btn("编辑配置 / 密钥", self.edit_image))
        row.addWidget(btn("新增图片模型配置", self.new_image))
        il.addLayout(row)
        il.addWidget(text_label("任务：场景插图生成（图片编辑 API 暂未实现）"))
        image_fields = QWidget()
        f = QFormLayout(image_fields)
        f.addRow("API 工作流", win.workflow)
        f.addRow(btn("导入 API 格式 JSON", self.import_workflow))
        f.addRow("节点映射", win.mapping)
        f.addRow("Seed", win.seed)
        f.addRow("输出尺寸（兼容 API）", win.image_size)
        self.generation_rules = DropEdit()
        self.generation_rules.setPlaceholderText(
            "图片模型的默认生成约束，附加到本次提示词；不会伪装成 LLM system 参数。"
        )
        self.generation_rules.setMaximumHeight(100)
        f.addRow("默认生成约束", self.generation_rules)
        self.generation_rules.filesDropped.connect(
            lambda paths: win.append_text_files(paths, self.generation_rules)
        )
        il.addWidget(scroll(image_fields), 1)
        il.addWidget(btn("保存图片模型配置与工作流", self.save_image))
        self.categories.addTab(image, "图片模型配置")
        for widget in (
            win.image_connections,
            win.workflow,
            win.mapping,
            win.seed,
            win.image_size,
        ):
            widget.show()
        appearance = QWidget()
        f = QFormLayout(appearance)
        self.theme = QComboBox()
        self.theme.addItems(["明亮", "暗色", "跟随系统"])
        self.font = QSpinBox()
        self.font.setRange(11, 24)
        self.background = QLineEdit()
        self.opacity = QSpinBox()
        self.opacity.setRange(0, 60)
        self.confirm_attachments = QCheckBox("真实调用含附件时提示确认（包括历史附件）")
        self.rules = DropEdit()
        self.rules.setMaximumHeight(140)
        self.rules.filesDropped.connect(
            lambda paths: win.append_text_files(paths, self.rules)
        )
        for title, w in [
            ("主题", self.theme),
            ("字号", self.font),
            ("自定义背景", self.background),
            ("背景可见度 %", self.opacity),
            ("附件确认", self.confirm_attachments),
            ("当前项目补充规则", self.rules),
        ]:
            f.addRow(title, w)
        f.addRow(btn("选择背景图片", self.choose_background))
        f.addRow(btn("恢复默认外观", self.reset_appearance))
        f.addRow(btn("保存外观与项目规则", self.save_appearance))
        self.categories.addTab(scroll(appearance), "外观与项目规则")
        transfer = QWidget()
        tl = QVBoxLayout(transfer)
        tl.addWidget(
            text_label(
                "导出包含语言/图片模型配置和模板，排除密钥；导入生成新配置 ID，需重新填写服务地址和凭据。"
            )
        )
        tl.addWidget(btn("导出账户设置", self.export_settings))
        tl.addWidget(btn("导入账户设置", self.import_settings))
        tl.addWidget(btn("打开数据根目录", lambda: win.reveal_path(win.store.root)))
        tl.addStretch()
        self.categories.addTab(transfer, "导入与导出")
        self.nodes.currentIndexChanged.connect(self.node_changed)
        self.reload()

    def reload(self):
        self.loading = True
        self.load_node(self.nodes.currentData())
        self.win.reload_image_connections()
        self.load_image()
        s = self.win.settings
        self.theme.setCurrentIndex(["light", "dark", "system"].index(s["theme"]))
        self.font.setValue(s["font_size"])
        self.background.setText(s["background"])
        self.opacity.setValue(s["background_opacity"])
        self.confirm_attachments.setChecked(s["confirm_attachments"])
        self.rules.setPlainText(
            self.win.project.config.get("rules", "") if self.win.project else ""
        )
        self.loading = False

    def load_node(self, node):
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.node = node
        self.form = NodeForm(self.win, node, self.win.node_parameters(node))
        self.form_layout.addWidget(self.form)
        self.saved_language = (
            self.form.value() if self.form.selected_connection() else None
        )

    def node_changed(self, *_):
        if self.loading:
            return
        new = self.nodes.currentData()
        if not self.settle_language():
            self.nodes.blockSignals(True)
            self.nodes.setCurrentIndex(self.nodes.findData(self.node))
            self.nodes.blockSignals(False)
            return
        self.load_node(new)

    def language_dirty(self):
        try:
            return self.form.value() != self.saved_language
        except Exception:
            return True

    def settle_language(self):
        if not self.language_dirty():
            return True
        choice = QMessageBox.question(
            self,
            "未保存的节点设置",
            "保存当前节点的语言模型配置与提示词吗？",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if choice == QMessageBox.Cancel:
            return False
        if choice == QMessageBox.Save:
            return self.save_language()
        return True

    def save_language(self):
        try:
            params = self.form.value()
            self.win.store.save_node_default(
                self.win.account, self.node, params, self.win.known_secrets()
            )
            if self.win.project:
                self.win.project.config.setdefault("connections", {})[
                    str(self.node)
                ] = params["connection_id"]
                self.win.project.save_config()
            self.saved_language = copy.deepcopy(params)
            self.win.refresh_runtime_parameters()
            self.win.status.setText(
                "已保存 " + NODES[self.node] + " 的独立语言模型配置和提示词"
            )
            return True
        except Exception as e:
            self.win.error(e)
            return False

    def image_data(self):
        w = self.win
        return dict(
            connection_id=w.image_connections.currentData(),
            workflow=w.workflow.toPlainText(),
            mapping=w.mapping.toPlainText(),
            seed=w.seed.value(),
            size=w.image_size.currentText(),
            generation_rules=self.generation_rules.toPlainText(),
        )

    def load_image(self):
        data = self.win.image_parameters()
        w = self.win
        w.image_connections.blockSignals(True)
        w.image_connections.setCurrentIndex(
            w.image_connections.findData(data.get("connection_id", "image-default"))
        )
        w.image_connections.blockSignals(False)
        w.workflow.setPlainText(data.get("workflow", ""))
        w.mapping.setPlainText(data.get("mapping", '{\n  "prompt": ["6", "text"]\n}'))
        w.seed.setValue(data.get("seed", 42))
        w.image_size.setCurrentText(data.get("size", "1024x1024"))
        self.generation_rules.setPlainText(data.get("generation_rules", ""))
        self.saved_image = self.image_data()

    def save_image(self):
        try:
            data = self.image_data()
            profile = next(
                (
                    c
                    for c in self.win.store.connections(self.win.account)
                    if c["id"] == data["connection_id"]
                ),
                None,
            )
            if not profile:
                raise ValueError("请选择图片模型配置")
            if data["mapping"].strip():
                mapping = json.loads(data["mapping"])
            else:
                mapping = {}
            if profile["kind"] == "comfy" and data["workflow"].strip():
                bind_workflow(
                    json.loads(data["workflow"]),
                    mapping,
                    dict(prompt="执行前校验", seed=data["seed"]),
                )
            if not isinstance(mapping, dict):
                raise ValueError("节点映射必须是JSON对象")
            self.win.store.save_image_defaults(
                self.win.account, data, self.win.known_secrets()
            )
            if self.win.project:
                self.win.project.config["image_connection"] = data["connection_id"]
                self.win.project.save_config()
            self.saved_image = copy.deepcopy(data)
            self.win.image_defaults_cache = copy.deepcopy(data)
            self.win.refresh_model_summary()
            self.win.status.setText("已保存独立图片模型配置、工作流及默认约束")
            return True
        except Exception as e:
            self.win.error(e)
            return False

    def settle(self):
        if not self.settle_language():
            return False
        if self.image_data() != self.saved_image:
            choice = QMessageBox.question(
                self,
                "未保存的图片设置",
                "保存图片模型配置与工作流吗？",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if choice == QMessageBox.Cancel:
                return False
            if choice == QMessageBox.Save and not self.save_image():
                return False
            if choice == QMessageBox.Discard:
                self.load_image()
        if self.language_dirty():
            self.load_node(self.node)
        return True

    def edit_image(self):
        cid = self.win.image_connections.currentData()
        profile = next(
            (c for c in self.win.store.connections(self.win.account) if c["id"] == cid),
            None,
        )
        if profile:
            d = ConnectionDialog(self.win, profile)
            if d.exec():
                self.win.reload_image_connections(cid)

    def new_image(self):
        d = ConnectionDialog(self.win, kind="image_api")
        if d.exec():
            self.win.reload_image_connections(d.profile["id"])

    def import_workflow(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 ComfyUI API 工作流", "", "JSON (*.json)"
        )
        if path:
            try:
                flow = json.loads(Path(path).read_text("utf-8"))
                self.win.workflow.setPlainText(
                    json.dumps(flow, ensure_ascii=False, indent=2)
                )
                if self.win.project:
                    self.win.project.add_attachment(path)
            except Exception as e:
                self.win.error(e)

    def choose_background(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "背景图片", "", "图片 (*.png *.jpg *.jpeg *.webp)"
        )
        if path:
            self.background.setText(path)

    def reset_appearance(self):
        self.theme.setCurrentIndex(0)
        self.font.setValue(14)
        self.background.clear()
        self.opacity.setValue(18)

    def save_appearance(self):
        try:
            s = copy.deepcopy(self.win.settings)
            s.update(
                theme=["light", "dark", "system"][self.theme.currentIndex()],
                font_size=self.font.value(),
                background_opacity=self.opacity.value(),
                confirm_attachments=self.confirm_attachments.isChecked(),
                background=self.background.text(),
            )
            if s["background"]:
                import shutil

                source = Path(s["background"])
                if QPixmap(str(source)).isNull():
                    raise ValueError("背景图片无法读取")
                dest = (
                    self.win.store.account_dir(self.win.account)
                    / "界面资源"
                    / ("背景" + source.suffix.lower())
                )
                if source.resolve() != dest.resolve():
                    shutil.copy2(source, dest)
                s["background"] = str(dest)
            self.win.store.save_settings(
                self.win.account, redact(s, self.win.known_secrets())
            )
            self.win.settings = s
            if self.win.project:
                self.win.project.config["rules"] = self.rules.toPlainText()
                self.win.project.save_config()
            self.win.apply_theme()
            self.win.refresh_runtime_parameters()
            self.win.status.setText("已保存外观和项目规则")
        except Exception as e:
            self.win.error(e)

    def export_settings(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出账户设置", "账户设置.json", "JSON (*.json)"
        )
        if path:
            try:
                self.win.store.export_settings(
                    self.win.account, path, self.win.known_secrets()
                )
                self.win.status.setText("已导出无密钥设置")
            except Exception as e:
                self.win.error(e)

    def import_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入账户设置", "", "JSON (*.json)")
        if path:
            try:
                self.win.store.import_settings(self.win.account, path)
                self.win.settings = self.win.store.settings(self.win.account)
                self.reload()
                self.win.apply_theme()
                self.win.refresh_runtime_parameters()
            except Exception as e:
                self.win.error(e)
