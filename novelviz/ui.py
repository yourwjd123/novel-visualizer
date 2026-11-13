from __future__ import annotations
import argparse
import copy
import html
import json
import shutil
import sys
import threading
import zipfile
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QThread, Signal, QUrl, QTimer
from PySide6.QtGui import QDesktopServices, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QFileDialog,
    QMessageBox,
    QInputDialog,
    QDialog,
    QFormLayout,
    QLineEdit,
    QTextEdit,
    QPlainTextEdit,
    QSpinBox,
    QCheckBox,
    QTabWidget,
    QDialogButtonBox,
    QScrollArea,
    QSplitter,
    QListWidget,
    QStackedWidget,
    QFrame,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QGridLayout,
    QTabBar,
    QLayout,
)
from .storage import Store, Project, NODES, read_document, uid, now, write_json, redact
from .providers import text_call, bind_workflow, comfy_call, UnknownOutcome, image_call
from .credentials import get_key, set_key


def button(text, fn, primary=False):
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(fn)
    if primary:
        b.setProperty("primary", True)
    return b


def label(text, kind=""):
    x = QLabel(text)
    x.setWordWrap(True)
    if kind:
        x.setObjectName(kind)
    return x


def scroll(widget):
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setFrameShape(QFrame.NoFrame)
    s.setWidget(widget)
    return s


def reveal(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))


class Worker(QThread):
    done = Signal(object)
    failed = Signal(str, bool)
    progress = Signal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.cancel = threading.Event()

    def run(self):
        try:
            self.done.emit(self.fn(self.cancel, self.progress.emit))
        except Exception as e:
            # Show controlled provider errors; avoid arbitrary raw response contents.
            from .providers import ProviderError

            self.failed.emit(
                str(e)
                if isinstance(e, ProviderError)
                else f"本地执行失败（{type(e).__name__}），输入已保留。",
                isinstance(e, UnknownOutcome),
            )


class Backdrop(QWidget):
    def __init__(self):
        super().__init__()
        self.pix = QPixmap()
        self.opacity = 0.18

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.pix.isNull():
            p = QPainter(self)
            p.setOpacity(self.opacity)
            pix = self.pix.scaled(
                self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            p.drawPixmap(
                (self.width() - pix.width()) // 2,
                (self.height() - pix.height()) // 2,
                pix,
            )


from .components import NodeForm, ConnectionDialog, SceneDialog, AssetDialog, DropEdit
from .connections import KINDS
from .prompts import parse_object, validate_scenes, validate_assets


class SettingsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.s = copy.deepcopy(win.settings)
        self.setWindowTitle("账户设置")
        self.resize(820, 720)
        l = QVBoxLayout(self)
        tabs = QTabWidget()
        l.addWidget(tabs)
        conn = QWidget()
        cl = QVBoxLayout(conn)
        cl.addWidget(
            label(
                "各节点独立选择连接；密钥在连接编辑器中分别设置。编辑复用连接会影响后续调用，复制连接不会复制密钥。",
                "muted",
            )
        )
        self.list = QListWidget()
        cl.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(button("新建连接", self.new_connection))
        row.addWidget(button("编辑 / 密钥", self.edit_connection))
        cl.addLayout(row)
        tabs.addTab(conn, "连接与密钥")
        self.reload()
        general = QWidget()
        f = QFormLayout(general)
        self.theme = QComboBox()
        self.theme.addItems(["明亮", "暗色", "跟随系统"])
        self.theme.setCurrentIndex(["light", "dark", "system"].index(self.s["theme"]))
        self.font = QSpinBox()
        self.font.setRange(11, 24)
        self.font.setValue(self.s["font_size"])
        self.bg = QLineEdit(self.s["background"])
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.bg)
        h.addWidget(button("选图片", self.choose_bg))
        self.opacity = QSpinBox()
        self.opacity.setRange(0, 60)
        self.opacity.setValue(self.s["background_opacity"])
        self.opacity.setSuffix(" %")
        self.attach = QCheckBox("真实调用含附件时确认（包括历史附件）")
        self.attach.setChecked(self.s["confirm_attachments"])
        self.sidebar = QCheckBox("显示侧边栏")
        self.sidebar.setChecked(self.s["sidebar_visible"])
        for name, w in [
            ("主题", self.theme),
            ("字号", self.font),
            ("背景", row),
            ("背景可见度", self.opacity),
            ("附件", self.attach),
            ("导航", self.sidebar),
        ]:
            f.addRow(name, w)
        f.addRow(button("一键恢复默认外观", self.reset_appearance))
        tabs.addTab(general, "外观与交互")
        project = QWidget()
        pl = QVBoxLayout(project)
        pl.addWidget(label("项目补充规则（和节点模板一起发送）"))
        self.rules = DropEdit(
            win.project.config.get("rules", "") if win.project else ""
        )
        self.rules.filesDropped.connect(
            lambda paths: win.append_text_files(paths, self.rules)
        )
        pl.addWidget(self.rules, 1)
        self.planner = QComboBox()
        self.planner.addItem("不启用规划接口", "")
        for c in win.store.connections(win.account):
            if c["kind"] in ("demo", "openai"):
                self.planner.addItem(c["name"], c["id"])
        chosen = (
            win.project.config.get("connections", {}).get("7", "")
            if win.project
            else ""
        )
        self.planner.setCurrentIndex(max(0, self.planner.findData(chosen)))
        pl.addWidget(label("可选全过程规划连接"))
        pl.addWidget(self.planner)
        tabs.addTab(project, "项目规则与规划")
        migration = QWidget()
        ml = QVBoxLayout(migration)
        ml.addWidget(
            label(
                "设置导出排除所有密钥和旧凭据引用，导入连接生成全新ID，不会借用当前账户已有密钥。服务地址及背景图片文件不共享。",
                "muted",
            )
        )
        ml.addWidget(button("导出已保存的设置与模板", self.export_settings))
        ml.addWidget(button("导入设置与模板", self.import_settings))
        ml.addWidget(
            button(
                "打开账户数据目录", lambda: reveal(win.store.account_dir(win.account))
            )
        )
        ml.addStretch()
        tabs.addTab(migration, "导入与导出")
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("保存")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)

    def reload(self):
        self.list.clear()
        for c in self.win.store.connections(self.win.account):
            self.list.addItem(c["name"] + "  /  " + KINDS[c["kind"]])
            self.list.item(self.list.count() - 1).setData(Qt.UserRole, c)

    def new_connection(self):
        d = ConnectionDialog(self.win)
        if d.exec():
            self.reload()

    def edit_connection(self):
        item = self.list.currentItem()
        if item:
            d = ConnectionDialog(self.win, item.data(Qt.UserRole))
            if d.exec():
                self.reload()

    def choose_bg(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "背景图片", "", "图片 (*.png *.jpg *.jpeg *.webp)"
        )
        if p:
            self.bg.setText(p)

    def reset_appearance(self):
        self.theme.setCurrentIndex(0)
        self.font.setValue(14)
        self.bg.clear()
        self.opacity.setValue(18)
        self.sidebar.setChecked(True)

    def save(self):
        try:
            self.s.update(
                theme=["light", "dark", "system"][self.theme.currentIndex()],
                font_size=self.font.value(),
                background=self.bg.text(),
                background_opacity=self.opacity.value(),
                confirm_attachments=self.attach.isChecked(),
                sidebar_visible=self.sidebar.isChecked(),
            )
            if self.s["background"]:
                src = Path(self.s["background"])
                if QPixmap(str(src)).isNull():
                    raise ValueError("背景图片无法读取")
                dest = (
                    self.win.store.account_dir(self.win.account)
                    / "界面资源"
                    / ("背景" + src.suffix.lower())
                )
                if src.resolve() != dest.resolve():
                    shutil.copy2(src, dest)
                self.s["background"] = str(dest)
            self.win.store.save_settings(
                self.win.account, redact(self.s, self.win.known_secrets())
            )
            self.win.settings = self.s
            if self.win.project:
                self.win.project.config["rules"] = self.rules.toPlainText()
                self.win.project.config.setdefault("connections", {})["7"] = (
                    self.planner.currentData()
                )
                self.win.project.save_config()
            self.win.apply_theme()
            self.accept()
        except Exception as e:
            self.win.error(e)

    def export_settings(self):
        p, _ = QFileDialog.getSaveFileName(
            self, "导出设置", "账户设置.json", "JSON (*.json)"
        )
        if p:
            try:
                self.win.store.export_settings(
                    self.win.account, p, self.win.known_secrets()
                )
                self.win.info("已导出保存的设置、连接定义和模板，不包含凭据")
            except Exception as e:
                self.win.error(e)

    def import_settings(self):
        p, _ = QFileDialog.getOpenFileName(self, "导入设置", "", "JSON (*.json)")
        if p:
            try:
                self.win.store.import_settings(self.win.account, p)
                self.accept()
            except Exception as e:
                self.win.error(e)


class Window(QMainWindow):
    def __init__(self, root):
        super().__init__()
        self.store = Store(root)
        self.account = self.store.accounts[0]
        self.settings = self.store.settings(self.account)
        self.project = None
        self.sid = None
        self.scene_id = None
        self.node = 0
        self.data = None
        self.busy = False
        self.worker = None
        self.session_keys = {}
        self.pending_attachments = []
        self.node_buttons = []
        self.setWindowTitle("墨境 · 小说智能可视化  |  基础测试版 0.2")
        self.resize(1440, 940)
        self.setMinimumSize(1080, 730)
        self.bg = Backdrop()
        self.setCentralWidget(self.bg)
        outer = QVBoxLayout(self.bg)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        top = QFrame()
        top.setObjectName("topbar")
        h = QHBoxLayout(top)
        h.setContentsMargins(24, 15, 24, 15)
        h.addWidget(button("☰", self.toggle_sidebar))
        h.addWidget(label("墨境  /  NOVEL STUDIO", "brand"))
        h.addStretch()
        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(130)
        self.account_combo.currentIndexChanged.connect(self.switch_account)
        h.addWidget(self.account_combo)
        h.addWidget(button("账户管理", self.manage_accounts))
        h.addWidget(button("⚙  设置", self.open_settings))
        outer.addWidget(top)
        body = QHBoxLayout()
        body.setSpacing(0)
        outer.addLayout(body, 1)
        side = QFrame()
        self.side = side
        side.setObjectName("sidebar")
        side.setFixedWidth(190)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(18, 25, 18, 20)
        sl.addWidget(label("创作空间", "eyebrow"))
        self.nav = []
        for i, t in enumerate(
            [
                "◈  片段工作台",
                "▤  原文阅读",
                "◇  共享资产库",
                "▧  插图生成",
                "◷  任务历史",
                "▱  项目文件",
            ]
        ):
            b = button(t, lambda checked=False, k=i: self.navigate(k))
            b.setProperty("nav", True)
            sl.addWidget(b)
            self.nav.append(b)
        sl.addStretch()
        sl.addWidget(label("每一步，由你确认。\n本地保存 · 模型自选", "muted"))
        body.addWidget(side)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(24, 20, 24, 15)
        cl.setSpacing(14)
        body.addWidget(center, 1)
        ph = QHBoxLayout()
        self.projects_combo = QComboBox()
        self.projects_combo.setMinimumWidth(230)
        self.projects_combo.currentIndexChanged.connect(self.switch_project)
        ph.addWidget(self.projects_combo, 1)
        ph.addWidget(button("＋ 新建项目", self.new_project))
        ph.addWidget(button("导入小说片段", self.import_segment, True))
        ph.addWidget(button("备份项目", self.backup))
        ph.addWidget(button("恢复备份", self.restore_backup))
        cl.addLayout(ph)
        self.pages = QStackedWidget()
        cl.addWidget(self.pages, 1)
        self.build_workbench()
        self.build_reader()
        self.build_assets()
        self.build_images()
        self.build_jobs()
        self.build_files()
        self.pages.widget(0).layout().removeWidget(self.stage_tabs)
        self.stage_tabs.setParent(center)
        cl.insertWidget(1, self.stage_tabs)
        self.status = label("就绪 · 数据保存在你选择的目录", "muted")
        cl.addWidget(self.status)
        self.reload_accounts()
        self.reload_projects()
        self.apply_theme()
        self.navigate(0)
        self.side.setVisible(self.settings["sidebar_visible"])
        QApplication.styleHints().colorSchemeChanged.connect(self.system_theme_changed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "pages"):
            QTimer.singleShot(0, self.fit_workbench)

    def fit_workbench(self):
        pass

    def info(self, t):
        QMessageBox.information(self, "墨境", t)

    def error(self, e):
        QMessageBox.warning(self, "操作未完成", str(e))

    def guard(self):
        if self.busy:
            self.info(
                "有任务正在执行。请等待完成，或停止等待后再切换账户、项目或片段。"
            )
            return False
        return True

    def require_project(self):
        if not self.project:
            self.info("请先新建或选择项目")
            return False
        return True

    def build_workbench(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(12)
        bar = QHBoxLayout()
        bar.addWidget(label("原文片段"))
        self.segments_combo = QComboBox()
        self.segments_combo.currentIndexChanged.connect(self.switch_segment)
        bar.addWidget(self.segments_combo, 2)
        bar.addWidget(label("当前情节"))
        self.scene_combo = QComboBox()
        self.scene_combo.currentIndexChanged.connect(self.switch_scene)
        bar.addWidget(self.scene_combo, 2)
        bar.addWidget(button("＋ 粘贴片段", self.paste_segment))
        l.addLayout(bar)
        self.stage_order = [0, 1, 5, 2, 3, 4, 6, 7]
        self.stage_tabs = QTabBar()
        self.stage_tabs.setExpanding(False)
        self.stage_tabs.setUsesScrollButtons(True)
        for i in self.stage_order:
            self.stage_tabs.addTab(NODES[i])
        self.stage_tabs.currentChanged.connect(
            lambda index: self.select_node(self.stage_order[index])
        )
        l.addWidget(self.stage_tabs)
        self.workspace_split = QSplitter(Qt.Horizontal)
        self.module_panel = QFrame()
        self.module_panel.setObjectName("panel")
        ml = QVBoxLayout(self.module_panel)
        ml.setContentsMargins(16, 16, 16, 16)
        self.module_title = label("情节模块", "section")
        ml.addWidget(self.module_title)
        self.module_tools = QHBoxLayout()
        self.depth = QComboBox()
        self.depth.addItems(["粗 · 主要事件", "中 · 连续场景", "细 · 插图瞬间"])
        self.depth.setCurrentIndex(1)
        self.module_tools.addWidget(self.depth)
        self.module_tools.addWidget(button("请求 AI 拆分", self.request_split, True))
        self.module_tools.addWidget(button("手工新增", self.add_scene))
        ml.addLayout(self.module_tools)
        self.scope_note = label("", "muted")
        ml.addWidget(self.scope_note)
        self.module_cards = QWidget()
        self.module_grid = QGridLayout(self.module_cards)
        self.module_grid.setContentsMargins(0, 0, 0, 0)
        self.module_grid.setAlignment(Qt.AlignTop)
        self.module_grid.setSizeConstraint(QLayout.SetMinimumSize)
        ml.addWidget(scroll(self.module_cards), 1)
        self.excerpt = QPlainTextEdit()
        self.excerpt.setReadOnly(True)
        self.excerpt.setVisible(False)
        self.include_text = QCheckBox("附带原文（情节节点仅发送当前情节范围）")
        self.include_text.setChecked(True)
        self.include_assets = QCheckBox("附带当前情节已关联的资产文字")
        self.include_assets.setChecked(True)
        self.include_refs = QCheckBox("附带关联资产主图（需视觉连接，发送前确认）")
        self.include_refs.setChecked(False)
        ml.addWidget(self.include_text)
        ml.addWidget(self.include_assets)
        ml.addWidget(self.include_refs)
        self.context_count = label("", "muted")
        ml.addWidget(self.context_count)
        self.workspace_split.addWidget(self.module_panel)
        right = QFrame()
        right.setObjectName("panel")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 16, 16, 16)
        title = QHBoxLayout()
        self.node_title = label("", "section")
        title.addWidget(self.node_title, 1)
        title.addWidget(button("预览输入", self.preview_input))
        title.addWidget(button("导出", self.export_text))
        rl.addLayout(title)
        self.tabs = QTabWidget()
        rl.addWidget(self.tabs, 1)
        chat = QWidget()
        chl = QVBoxLayout(chat)
        chl.setContentsMargins(0, 8, 0, 0)
        self.conversation = QTextEdit()
        self.conversation.setReadOnly(True)
        chl.addWidget(self.conversation, 1)
        self.message = DropEdit()
        self.message.setPlaceholderText(
            "补充要求，可拖入文本或图片作为本轮附件；发送前可预览实际输入。"
        )
        self.message.setMinimumHeight(75)
        self.message.setMaximumHeight(110)
        self.message.filesDropped.connect(self.drop_chat_files)
        chl.addWidget(self.message)
        self.model_badge = label("", "muted")
        chl.addWidget(self.model_badge)
        self.attachment_label = label("未附加文件", "muted")
        chl.addWidget(self.attachment_label)
        row = QHBoxLayout()
        row.addWidget(button("＋ 附件", self.add_attachments))
        row.addWidget(button("清除本轮附件", self.clear_attachments))
        row.addStretch()
        self.retry_btn = button("重试失败", self.retry_text)
        row.addWidget(self.retry_btn)
        self.stop = button("停止等待", self.cancel_task)
        row.addWidget(self.stop)
        self.send = button("发送", self.send_message, True)
        row.addWidget(self.send)
        chl.addLayout(row)
        self.tabs.addTab(chat, "讨论")
        final_page = QWidget()
        fl = QVBoxLayout(final_page)
        self.final = DropEdit()
        self.final.setPlaceholderText(
            "人工定稿，或采用模型输出。情节/资产结构化候选可在校验后预览入库。"
        )
        self.final.textChanged.connect(self.final_changed)
        self.final.filesDropped.connect(self.drop_final_files)
        fl.addWidget(self.final, 1)
        row = QHBoxLayout()
        row.addWidget(button("采用最近输出", self.use_last))
        row.addWidget(button("保存草稿", self.save_draft))
        self.confirm_btn = button("确认方案", self.confirm_final, True)
        row.addWidget(self.confirm_btn)
        fl.addLayout(row)
        self.structured_btn = button(
            "校验并预览结构化结果", self.preview_structured, True
        )
        fl.addWidget(self.structured_btn)
        self.tabs.addTab(final_page, "方案与入库")
        self.param_host = QWidget()
        self.param_layout = QVBoxLayout(self.param_host)
        self.tabs.addTab(scroll(self.param_host), "连接 · 提示词")
        self.workspace_split.addWidget(right)
        self.workspace_split.setSizes([560, 640])
        self.workspace_split.setChildrenCollapsible(False)
        l.addWidget(self.workspace_split, 1)
        self.pages.addWidget(page)

    def drop_original_files(self, paths):
        if self.busy or not self.require_project():
            return
        try:
            self.save_draft(silent=True)
            for path in paths:
                sid = self.project.add_segment(
                    Path(path).stem, read_document(path), path
                )
            self.data = None
            self.reload_segments(sid)
        except Exception as e:
            self.error(e)

    def build_reader(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.addWidget(label("原文阅读", "hero"))
        l.addWidget(
            label(
                "外部修改正文后，点击重新读取。确认方案和历史任务仍保留原版本。",
                "muted",
            )
        )
        row = QHBoxLayout()
        row.addWidget(button("重新读取文件", self.refresh_text))
        row.addWidget(button("打开正文文件", self.open_segment_file))
        row.addStretch()
        l.addLayout(row)
        self.reader = DropEdit()
        self.reader.filesDropped.connect(self.drop_original_files)
        self.reader.setReadOnly(True)
        l.addWidget(self.reader, 1)
        self.pages.addWidget(page)

    def build_assets(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.addWidget(label("项目共享资产", "hero"))
        l.addWidget(
            label(
                "按人物、场景、道具分类；卡片可编辑，主图自动生成缩略图。修改共享资产将提示下游复核。",
                "muted",
            )
        )
        row = QHBoxLayout()
        row.addWidget(button("＋ 新建资产", self.add_asset, True))
        row.addStretch()
        l.addLayout(row)
        self.asset_categories = QTabBar()
        for name in ("全部", "人物", "场景", "道具"):
            self.asset_categories.addTab(name)
        self.asset_categories.currentChanged.connect(lambda _: self.refresh_assets())
        l.addWidget(self.asset_categories)
        self.asset_cards = QWidget()
        self.asset_grid = QGridLayout(self.asset_cards)
        self.asset_grid.setAlignment(Qt.AlignTop)
        self.asset_grid.setSizeConstraint(QLayout.SetMinimumSize)
        l.addWidget(scroll(self.asset_cards), 1)
        self.pages.addWidget(page)

    def build_images(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.addWidget(label("场景插图工作区", "hero"))
        self.image_scope_label = label("先选择情节。", "muted")
        l.addWidget(self.image_scope_label)
        row = QHBoxLayout()
        self.image_connections = QComboBox()
        self.image_connections.currentIndexChanged.connect(
            self.image_connection_changed
        )
        row.addWidget(self.image_connections, 1)
        row.addWidget(button("配置图片连接 / 密钥", self.edit_image_connection))
        row.addWidget(button("新建图片连接", self.new_image_connection))
        row.addWidget(button("生成前讨论 / 检查", lambda: self.navigate(0)))
        l.addLayout(row)
        split = QSplitter(Qt.Horizontal)
        assets = QWidget()
        al = QVBoxLayout(assets)
        al.addWidget(label("本场景资产 · 点击可编辑", "section"))
        self.image_assets = QWidget()
        self.image_asset_grid = QGridLayout(self.image_assets)
        self.image_asset_grid.setAlignment(Qt.AlignTop)
        self.image_asset_grid.setSizeConstraint(QLayout.SetMinimumSize)
        al.addWidget(scroll(self.image_assets), 1)
        al.addWidget(button("管理关联资产", lambda: self.navigate(0)))
        split.addWidget(assets)
        controls = QWidget()
        ll = QVBoxLayout(controls)
        self.comfy_prompt = DropEdit()
        self.comfy_prompt.setPlaceholderText("填写最终提示词；拖入TXT/MD可插入文字")
        self.comfy_prompt.setMinimumHeight(100)
        self.comfy_prompt.filesDropped.connect(self.drop_image_prompt)
        ll.addWidget(self.comfy_prompt)
        ll.addWidget(button("载入已确认提示词", self.load_confirmed_prompt))
        self.image_size = QComboBox()
        self.image_size.addItems(["1024x1024", "1536x1024", "1024x1536"])
        ll.addWidget(self.image_size)
        self.workflow = DropEdit()
        self.workflow.setPlaceholderText("ComfyUI API 格式 JSON")
        self.workflow.filesDropped.connect(self.drop_workflow)
        ll.addWidget(button("导入 API 工作流", self.import_workflow))
        ll.addWidget(self.workflow, 1)
        self.mapping = DropEdit('{\n  "prompt": ["6", "text"]\n}')
        self.mapping.setMaximumHeight(100)
        ll.addWidget(
            label("映射：prompt、seed、reference_1… → [节点ID, 输入名]", "muted")
        )
        ll.addWidget(self.mapping)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2147483647)
        self.seed.setValue(42)
        ll.addWidget(self.seed)
        self.generate_btn = button("提交图片任务", self.generate_image, True)
        ll.addWidget(self.generate_btn)
        ll.addWidget(button("停止等待", self.cancel_task))
        split.addWidget(controls)
        preview = QWidget()
        pl = QVBoxLayout(preview)
        self.image = label("图片将在这里显示", "imagePreview")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(200, 180)
        pl.addWidget(self.image, 1)
        self.image_list = QComboBox()
        self.image_list.currentIndexChanged.connect(self.show_image)
        pl.addWidget(self.image_list)
        pl.addWidget(button("选为最终成果", self.choose_result))
        pl.addWidget(button("用作当前资产参考图", self.result_as_asset_image))
        pl.addWidget(button("打开图片目录", self.open_image_folder))
        split.addWidget(preview)
        split.setSizes([340, 450, 380])
        l.addWidget(split, 1)
        self.pages.addWidget(page)

    def build_jobs(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.addWidget(label("任务历史", "hero"))
        l.addWidget(
            label(
                "失败不自动重试，超时不自动切换。停止等待不代表远端停止执行或停止计费。",
                "muted",
            )
        )
        self.job_tree = QTreeWidget()
        self.job_tree.setHeaderLabels(["时间", "任务", "状态", "模型 / 远端 ID"])
        self.job_tree.header().setSectionResizeMode(3, QHeaderView.Stretch)
        l.addWidget(self.job_tree, 1)
        row = QHBoxLayout()
        row.addWidget(button("查看任务快照", self.open_job))
        row.addWidget(button("查询 ComfyUI 远端历史", self.query_remote))
        row.addStretch()
        l.addLayout(row)
        self.pages.addWidget(page)

    def build_files(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.addWidget(label("项目文件", "hero"))
        l.addWidget(
            label(
                "文件按用途保存，可随时打开。对话 JSON、数据库与索引由软件管理；外部文本修改可在原文页重新读取。",
                "muted",
            )
        )
        row = QHBoxLayout()
        row.addWidget(button("刷新目录", self.refresh_files))
        row.addWidget(button("保存其他附件", self.archive_attachment))
        row.addWidget(
            button("打开项目文件夹", lambda: self.project and reveal(self.project.path))
        )
        row.addWidget(button("打开选中文件", self.open_selected_file))
        row.addStretch()
        l.addLayout(row)
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(["目录 / 文件", "大小"])
        self.file_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.file_tree.itemDoubleClicked.connect(lambda *_: self.open_selected_file())
        l.addWidget(self.file_tree, 1)
        self.pages.addWidget(page)

    def navigate(self, i):
        self.pages.setCurrentIndex(i)
        for j, b in enumerate(self.nav):
            b.setProperty("active", i == j)
            b.style().unpolish(b)
            b.style().polish(b)
        if i == 2:
            self.refresh_assets()
        if i == 4:
            self.refresh_jobs()
        if i == 5:
            self.refresh_files()
        if i == 3:
            self.refresh_image_assets()

    def reload_accounts(self):
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        for a in self.store.accounts:
            self.account_combo.addItem(a["name"], a["id"])
        self.account_combo.setCurrentIndex(
            next(
                (
                    i
                    for i, a in enumerate(self.store.accounts)
                    if a["id"] == self.account["id"]
                ),
                0,
            )
        )
        self.account_combo.blockSignals(False)

    def switch_account(self, index):
        if index < 0:
            return
        if not self.guard():
            self.reload_accounts()
            return
        self.save_draft(silent=True)
        self.account = self.store.accounts[index]
        self.settings = self.store.settings(self.account)
        self.reload_projects()
        self.apply_theme()
        self.side.setVisible(self.settings["sidebar_visible"])

    def manage_accounts(self):
        if not self.guard():
            return
        action, ok = QInputDialog.getItem(
            self,
            "账户管理",
            "操作",
            ["创建账户", "修改账户名称", "删除当前账户（资料归档）"],
            0,
            False,
        )
        if not ok:
            return
        try:
            self.save_draft(silent=True)
            if action.startswith("删除"):
                if len(self.store.accounts) == 1:
                    self.info("至少保留一个账户")
                    return
                if (
                    QMessageBox.question(
                        self,
                        "删除账户",
                        "账户资料归档保留，并删除各连接的系统凭据。继续吗？",
                    )
                    != QMessageBox.Yes
                ):
                    return
                from .connections import credential_id

                for c in self.store.connections(self.account):
                    slot = credential_id(self.account["id"], c["id"])
                    if get_key(slot):
                        set_key(slot, "")
                    self.session_keys.pop(slot, None)
                if get_key(self.account["id"]):
                    set_key(self.account["id"], "")
                self.session_keys.pop(self.account["id"], None)
                self.store.delete_account(self.account)
                self.account = self.store.accounts[0]
            else:
                name, ok = QInputDialog.getText(
                    self,
                    "账户名称",
                    "名称",
                    text="" if action.startswith("创建") else self.account["name"],
                )
                if not ok:
                    return
                if action.startswith("创建"):
                    self.account = self.store.create_account(name)
                else:
                    self.store.rename_account(self.account, name)
            self.settings = self.store.settings(self.account)
            self.reload_accounts()
            self.reload_projects()
            self.apply_theme()
            self.side.setVisible(self.settings["sidebar_visible"])
        except Exception as e:
            self.error(e)

    def open_settings(self):
        if not self.guard():
            return
        self.save_draft(silent=True)
        SettingsDialog(self).exec()
        self.settings = self.store.settings(self.account)
        if self.project:
            self.project.secrets = self.known_secrets()
        self.apply_theme()
        self.side.setVisible(self.settings["sidebar_visible"])
        self.show_node()

    def reload_projects(self, select=None):
        self.projects_combo.blockSignals(True)
        self.projects_combo.clear()
        for p in self.store.projects(self.account):
            try:
                meta = json.loads(p.read_text("utf-8"))
                self.projects_combo.addItem(meta["name"], str(p.parent.parent))
            except Exception:
                pass
        if select:
            for i in range(self.projects_combo.count()):
                if self.projects_combo.itemData(i) == str(select):
                    self.projects_combo.setCurrentIndex(i)
        self.projects_combo.blockSignals(False)
        self.switch_project(self.projects_combo.currentIndex())

    def switch_project(self, i):
        if not self.guard():
            self.projects_combo.blockSignals(True)
            for n in range(self.projects_combo.count()):
                if self.project and self.projects_combo.itemData(n) == str(
                    self.project.path
                ):
                    self.projects_combo.setCurrentIndex(n)
            self.projects_combo.blockSignals(False)
            return
        self.save_draft(silent=True)
        if self.project:
            self.project.close()
        self.project = None
        self.sid = None
        self.scene_id = None
        self.data = None
        self.clear_attachments()
        self.image_list.clear()
        self.image.setText("图片将在这里显示")
        self.workflow.clear()
        self.comfy_prompt.clear()
        if i >= 0:
            try:
                self.project = Project(self.projects_combo.itemData(i))
                self.project.secrets = self.known_secrets()
            except Exception as e:
                self.error(e)
        self.reload_segments()
        self.refresh_assets()
        self.refresh_jobs()
        self.refresh_files()
        self.reload_image_connections()
        if self.project:
            for j in reversed(self.project.jobs()):
                for rel in j.get("results", []):
                    path = self.project.path / rel
                    if path.exists():
                        self.image_list.addItem(path.name, str(path))

    def new_project(self):
        if not self.guard():
            return
        name, ok = QInputDialog.getText(self, "新建项目", "项目名称")
        if ok:
            try:
                p = self.store.create_project(self.account, name)
                path = p.path
                p.close()
                self.reload_projects(path)
            except Exception as e:
                self.error(e)

    def reload_segments(self, select=None):
        self.segments_combo.blockSignals(True)
        self.segments_combo.clear()
        if self.project:
            for s in self.project.segments():
                self.segments_combo.addItem(s["name"], s["id"])
        if select:
            i = self.segments_combo.findData(select)
            self.segments_combo.setCurrentIndex(i)
        self.segments_combo.blockSignals(False)
        self.switch_segment(self.segments_combo.currentIndex())

    def switch_segment(self, i):
        if not self.guard():
            self.segments_combo.blockSignals(True)
            self.segments_combo.setCurrentIndex(self.segments_combo.findData(self.sid))
            self.segments_combo.blockSignals(False)
            return
        self.save_draft(silent=True)
        self.sid = self.segments_combo.itemData(i) if i >= 0 else None
        self.scene_id = None
        self.comfy_prompt.clear()
        self.data = None
        self.clear_attachments()
        self.reload_scenes()
        self.refresh_text()
        self.show_node()
        self.refresh_image_assets()

    def paste_segment(self):
        if not self.guard() or not self.require_project():
            return
        d = QDialog(self)
        d.setWindowTitle("添加小说片段")
        d.resize(650, 500)
        l = QVBoxLayout(d)
        name = QLineEdit()
        name.setPlaceholderText("片段名称，例如：第一章 · 夜渡")
        text = QPlainTextEdit()
        text.setPlaceholderText("粘贴本段原文。后续片段仍共享当前项目资产。")
        l.addWidget(name)
        l.addWidget(text)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("添加")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        l.addWidget(bb)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        if d.exec() == QDialog.Accepted:
            try:
                self.save_draft(silent=True)
                sid = self.project.add_segment(
                    name.text() or "新片段", text.toPlainText()
                )
                self.data = None
                self.reload_segments(sid)
            except Exception as e:
                self.error(e)

    def import_segment(self):
        if not self.guard() or not self.require_project():
            return
        p, _ = QFileDialog.getOpenFileName(
            self, "导入小说片段", "", "小说文档 (*.txt *.md *.docx *.epub)"
        )
        if not p:
            return
        try:
            text = read_document(p)
            self.save_draft(silent=True)
            sid = self.project.add_segment(Path(p).stem, text, p)
            self.data = None
            self.reload_segments(sid)
            self.status.setText("已导入正文与原始文件副本 · 可继续导入下一片段")
        except Exception as e:
            self.error(e)

    def refresh_text(self):
        text = ""
        if self.project and self.sid:
            try:
                text = self.project.segment_text(self.sid)
            except Exception as e:
                self.error(e)
        self.excerpt.setPlainText(text)
        self.reader.setPlainText(text)
        self.context_count.setText(f"片段 {len(text):,} 字符 · 可预览实际发送资料")
        if hasattr(self, "module_grid"):
            self.render_modules()

    def open_segment_file(self):
        if self.project and self.sid:
            s = next(x for x in self.project.segments() if x["id"] == self.sid)
            reveal(self.project.path / s["file"])

    def select_node(self, n):
        if not self.guard():
            self.stage_tabs.blockSignals(True)
            self.stage_tabs.setCurrentIndex(self.stage_order.index(self.node))
            self.stage_tabs.blockSignals(False)
            return
        self.save_draft(silent=True)
        self.node = n
        self.clear_attachments()
        self.stage_tabs.blockSignals(True)
        self.stage_tabs.setCurrentIndex(self.stage_order.index(n))
        self.stage_tabs.blockSignals(False)
        self.show_node()
        self.navigate(3 if n == 4 else 0)
        if (
            n == 4
            and not self.comfy_prompt.toPlainText().strip()
            and self.project
            and self.scene_id
        ):
            d = self.project.load_node(self.scene_id, 3)
            if d["status"] == "已确认":
                self.comfy_prompt.setPlainText(d["final"])

    def show_node(self):
        self.data = (
            self.project.load_node(self.scope(), self.node)
            if self.project and self.sid
            else None
        )
        self.node_title.setText(NODES[self.node])
        self.final.blockSignals(True)
        self.final.setPlainText(self.data["final"] if self.data else "")
        self.final.blockSignals(False)
        self.message.setPlainText(self.data.get("draft", "") if self.data else "")
        self.pending_attachments = list(
            self.data.get("draft_attachments", []) if self.data else []
        )
        self.update_attachment_label()
        while self.param_layout.count():
            item = self.param_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        p = copy.deepcopy(self.data.get("params", {}) if self.data else {})
        if self.project:
            if str(self.node) in self.project.config.get("connections", {}):
                p["connection_id"] = self.project.config["connections"][str(self.node)]
            else:
                p.setdefault("connection_id", f"node-{self.node}")
            if (
                self.data
                and p.get("provider") == "openai"
                and not self.data.get("params", {}).get("connection_id")
                and str(self.node) not in self.project.config.get("connections", {})
            ):
                cid = "migrated-" + self.project.meta["id"] + "-" + str(self.node)
                if not any(
                    c["id"] == cid for c in self.store.connections(self.account)
                ):
                    self.store.save_connection(
                        self.account,
                        dict(
                            id=cid,
                            name="旧节点配置 · " + NODES[self.node],
                            kind="openai",
                            endpoint=p["endpoint"],
                            model=p.get("model", ""),
                            vision=p.get("vision", False),
                            legacy=True,
                        ),
                    )
                p["connection_id"] = cid
        self.param_form = NodeForm(self, self.node, p)
        self.param_layout.addWidget(self.param_form)
        self.model_badge.setText(self.param_form.connection_summary.text())
        self.render_chat()
        self.update_cards()
        self.render_modules()
        self.set_busy()
        self.structured_btn.setVisible(self.node in (0, 1))
        self.scope_note.setText(
            "当前片段"
            if self.node in (0, 7)
            else "当前情节：" + (self.scene_combo.currentText() or "未选择")
        )

    def final_changed(self):
        if self.data:
            self.data["final"] = self.final.toPlainText()
            if self.data["status"] == "已确认":
                self.data["status"] = "待确认"
            self.update_cards()

    def update_cards(self):
        for i, title in enumerate(NODES):
            scope = self.sid if i in (0, 7) else (self.scene_id or self.sid)
            d = (
                (self.data if i == self.node else self.project.load_node(scope, i))
                if self.project and self.sid
                else None
            )
            status = d["status"] if d else "未开始"
            self.stage_tabs.setTabText(
                self.stage_order.index(i),
                (
                    "● "
                    if status == "已确认"
                    else "◌ "
                    if status in ("需复核", "状态未知")
                    else ""
                )
                + title,
            )
            self.stage_tabs.setTabToolTip(self.stage_order.index(i), status)

    def render_chat(self):
        if not self.data:
            self.conversation.setHtml(
                '<p style="color:#84938e">创建项目并添加片段，开始你的第一次创作。</p>'
            )
            return
        pieces = []
        for m in self.data["messages"]:
            role = "你" if m["role"] == "user" else "模型"
            pieces.append(
                f"<p><b>{role}</b> <small>{html.escape(m.get('time', ''))}</small></p><p>{html.escape(m['content']).replace(chr(10), '<br>')}</p><hr>"
            )
        self.conversation.setHtml(
            "".join(pieces)
            or '<p style="color:#84938e">可以与模型多轮讨论，也可以直接输入最终方案。<br><br>演示模式不会发送网络请求。</p>'
        )
        self.conversation.verticalScrollBar().setValue(
            self.conversation.verticalScrollBar().maximum()
        )

    def save_draft(self, checked=False, silent=False):
        if not self.project or not self.sid or not self.data:
            return
        try:
            self.project.secrets = self.known_secrets()
            self.data.update(
                final=self.final.toPlainText(),
                draft=self.message.toPlainText(),
                draft_attachments=list(self.pending_attachments),
            )
            try:
                self.data["params"] = self.param_form.value()
                self.project.config.setdefault("connections", {})[str(self.node)] = (
                    self.data["params"]["connection_id"]
                )
                self.project.save_config()
            except Exception as e:
                if not silent:
                    self.error(str(e) + "；文本草稿仍会保存。")
            self.project.save_node(self.scope(), self.node, self.data)
            if not silent:
                self.status.setText("已保存草稿、独立连接绑定和提示词版本")
        except Exception as e:
            if not silent:
                self.error(e)

    def use_last(self):
        if not self.data:
            return
        m = next(
            (m for m in reversed(self.data["messages"]) if m["role"] == "assistant"),
            None,
        )
        if m:
            self.final.setPlainText(m["content"])
            self.tabs.setCurrentIndex(1)
        else:
            self.info("当前节点还没有模型输出，可直接手工输入方案。")

    def confirm_final(self):
        if not self.data or self.busy:
            return
        try:
            self.save_draft(silent=True)
            p = self.project.confirm(self.scope(), self.node, self.data)
            self.project.invalidate_dependents(self.scope(), self.node, self.sid)
            self.update_cards()
            self.status.setText(f"已确认 v{self.data['revision']}：{p.name}")
        except Exception as e:
            self.error(e)

    def add_attachments(self):
        if self.busy or not self.data:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "添加附件",
            "",
            "支持文件 (*.txt *.md *.docx *.epub *.png *.jpg *.jpeg *.webp)",
        )
        self.drop_chat_files(paths)

    def clear_attachments(self):
        self.pending_attachments = []
        if hasattr(self, "attachment_label"):
            self.attachment_label.setText("未附加文件")

    def context(self):
        if not self.project or not self.sid:
            return ""
        chunks = []
        scene = self.project.scene(self.scene_id) if self.scene_id else None
        ps = self.project.paragraphs(self.sid)
        if self.include_text.isChecked():
            chosen = (
                ps
                if self.node in (0, 7) or not scene
                else [
                    p
                    for p in ps
                    if scene["start_paragraph"] <= p["number"] <= scene["end_paragraph"]
                ]
            )
            chunks.append(
                "【原文；段落编号为证据定位】\n"
                + "\n\n".join(f"[段落 {p['number']}] {p['text']}" for p in chosen)
            )
        if scene and self.node not in (0, 7):
            chunks.append(
                "【情节模块】\n"
                + json.dumps(
                    {
                        k: v
                        for k, v in scene.items()
                        if k not in ("source_text", "start_offset", "end_offset")
                    },
                    ensure_ascii=False,
                )
            )
        if self.include_assets.isChecked():
            rows = self.project.scene_assets(self.scene_id) if scene else []
            chunks.append(
                "【当前情节关联资产与缺失项】\n" + json.dumps(rows, ensure_ascii=False)
            )
        if self.node == 0:
            chunks.append("【拆分深度】" + self.depth.currentText())
        if self.node == 7:
            chunks.append(
                "【真实项目状态】\n"
                + json.dumps(
                    dict(
                        scenes=self.project.scenes(self.sid),
                        assets=self.project.assets(),
                        jobs=[
                            {k: j.get(k) for k in ("id", "kind", "status")}
                            for j in self.project.jobs()
                        ],
                    ),
                    ensure_ascii=False,
                )
            )
        previous = {
            0: [],
            1: [],
            5: [1],
            2: [1, 5],
            3: [1, 5, 2],
            4: [1, 5, 2, 3],
            6: [1, 5, 2, 3, 4],
            7: [],
        }
        for n in previous.get(self.node, []):
            scope = self.scene_id or self.sid
            d = self.project.load_node(scope, n)
            if d["status"] == "已确认":
                chunks.append("【已确认 " + NODES[n] + "】\n" + d["final"])
        return "\n\n".join(chunks)

    def send_message(self):
        if not self.data or self.busy:
            return
        content = self.message.toPlainText().strip()
        if not content:
            self.info("请输入本轮要求")
            return
        try:
            params = self.param_form.value()
            context = self.context()
            rels = self.call_attachments()
            paths = [self.project.path / p for p in rels]
            if self.node not in (0, 7) and self.scene_id:
                import hashlib

                scene = self.project.scene(self.scene_id)
                if (
                    scene["source_hash"]
                    != hashlib.sha256(
                        self.project.segment_text(self.sid).encode()
                    ).hexdigest()
                ):
                    raise ValueError(
                        "原文在外部发生变化，请先编辑情节并核对段落范围后保存，再继续调用"
                    )
            if (
                paths
                and params["provider"] != "demo"
                and any(
                    p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
                    for p in paths
                )
                and not params["vision"]
            ):
                raise ValueError("此节点连接未声明视觉输入能力，请修改连接或移除图片")
            if not self.confirm_upload(params, paths):
                return
            self.project.secrets = self.known_secrets()
            self.data["messages"].append(
                dict(
                    role="user",
                    content=content,
                    time=now(),
                    attachments=list(self.pending_attachments),
                )
            )
            self.data.update(
                status="运行中", params=params, draft="", draft_attachments=[]
            )
            self.project.config.setdefault("connections", {})[str(self.node)] = params[
                "connection_id"
            ]
            self.project.save_config()
            self.project.save_node(self.scope(), self.node, self.data)
            j = dict(
                id=uid(),
                kind="文本对话",
                status="running",
                created=now(),
                segment=self.sid,
                scene=self.scene_id,
                scope=self.scope(),
                node=self.node,
                params=params,
                context=context,
                messages=copy.deepcopy(self.data["messages"]),
                attachments=rels,
                assets=copy.deepcopy(
                    self.project.scene_assets(self.scene_id) if self.scene_id else []
                ),
            )
            self.project.save_job(j)
            messages = copy.deepcopy(self.data["messages"])
            key = self.connection_key(params["connection_id"])
            self.model_badge.setText(self.param_form.connection_summary.text())
            self.message.clear()
            self.clear_attachments()
            self.render_chat()
            self.start_job(
                j,
                lambda cancel, progress: text_call(
                    params, messages, context, key, paths, cancel
                ),
            )
        except Exception as e:
            self.error(e)

    def retry_text(self):
        if self.busy or not self.data:
            return
        old = next(
            (
                j
                for j in self.project.jobs()
                if j.get("scope", j.get("segment")) == self.scope()
                and j.get("node") == self.node
                and j["kind"] == "文本对话"
            ),
            None,
        )
        if not old or old["status"] not in ("failed", "unknown"):
            self.info("当前情节节点没有可重试的失败请求")
            return
        if (
            old["status"] == "unknown"
            and QMessageBox.question(
                self, "可能重复计费", "远端执行状态未知，可能已经计费。仍要重新提交吗？"
            )
            != QMessageBox.Yes
        ):
            return
        try:
            p = self.param_form.value()
            paths = [self.project.path / r for r in old.get("attachments", [])]
            if not self.confirm_upload(p, paths):
                return
            j = copy.deepcopy(old)
            j.update(
                id=uid(), retry_of=old["id"], status="running", created=now(), params=p
            )
            for k in ("error", "result", "finished"):
                j.pop(k, None)
            self.project.secrets = self.known_secrets()
            self.project.save_job(j)
            self.data["status"] = "运行中"
            self.project.save_node(self.scope(), self.node, self.data)
            key = self.connection_key(p["connection_id"])
            self.start_job(
                j,
                lambda cancel, progress: text_call(
                    p, j["messages"], j["context"], key, paths, cancel
                ),
            )
        except Exception as e:
            self.error(e)

    def start_job(self, j, fn):
        self.busy = True
        self.set_busy()
        self.update_cards()
        self.status.setText("任务执行中 · 不会自动重试或切换模型")
        self.current_job = j
        self.worker = Worker(fn)
        self.worker.progress.connect(self.job_progress)
        self.worker.done.connect(self.job_done)
        self.worker.failed.connect(self.job_failed)
        self.worker.finished.connect(self.thread_finished)
        self.worker.start()

    def set_busy(self):
        self.send.setEnabled(bool(self.data) and not self.busy)
        self.stop.setEnabled(self.busy)
        self.confirm_btn.setEnabled(bool(self.data) and not self.busy)
        self.generate_btn.setEnabled(not self.busy)
        self.param_host.setEnabled(not self.busy)
        self.image_connections.setEnabled(not self.busy)
        self.final.setReadOnly(self.busy)
        self.retry_btn.setEnabled(not self.busy)

    def job_progress(self, data):
        self.current_job.update(data)
        self.project.save_job(self.current_job)

    def job_done(self, result):
        j = self.current_job
        j.update(status="succeeded", finished=now())
        if j["kind"] == "文本对话":
            j["result"] = result
            self.data["messages"].append(
                dict(role="assistant", content=result, time=now())
            )
            self.data["status"] = "待确认"
            self.project.save_node(j["scope"], j["node"], self.data)
            self.render_chat()
        else:
            j["results"] = [
                Path(p).relative_to(self.project.path).as_posix() for p in result
            ]
            for p in result:
                self.image_list.addItem(Path(p).name, p)
            self.image_list.setCurrentIndex(self.image_list.count() - 1)
        self.project.save_job(j)
        self.status.setText("结果已保存，等待审核；结构化结果可采用后预览入库")
        self.update_cards()
        self.refresh_jobs()

    def job_failed(self, error, unknown):
        j = self.current_job
        j.update(status="unknown" if unknown else "failed", error=error, finished=now())
        self.project.save_job(j)
        if j["kind"] == "文本对话":
            self.data["status"] = "状态未知" if unknown else "失败"
            self.project.save_node(j["scope"], j["node"], self.data)
        self.status.setText(error)
        self.update_cards()
        self.refresh_jobs()
        self.error(error)

    def thread_finished(self):
        self.busy = False
        self.set_busy()
        self.worker.deleteLater()
        self.worker = None

    def cancel_task(self):
        if self.worker and self.busy:
            self.worker.cancel.set()
            self.current_job["cancel_requested_at"] = now()
            self.project.save_job(self.current_job)
            self.status.setText(
                "已请求停止等待 · 已提交的文本请求须等待本次响应或超时；远端仍可能计费"
            )

    def export_text(self):
        if not self.data:
            return
        scope, ok = QInputDialog.getItem(
            self,
            "导出文本",
            "导出范围",
            [
                "完整对话",
                "仅模型输出",
                "最近一次模型输出",
                "选中的对话文本",
                "当前最终方案",
            ],
            0,
            False,
        )
        if not ok:
            return
        path, fmt = QFileDialog.getSaveFileName(
            self,
            "导出文本",
            str(self.project.path / "07_导出" / f"{NODES[self.node]}.md"),
            "Markdown (*.md);;纯文本 (*.txt)",
        )
        if not path:
            return
        try:
            p = Path(path)
            if p.suffix.lower() not in (".md", ".txt"):
                p = p.with_suffix(".txt" if "txt" in fmt else ".md")
            if (
                str(p) != path
                and p.exists()
                and QMessageBox.question(self, "覆盖文件", "文件已存在，是否覆盖？")
                != QMessageBox.Yes
            ):
                return
            if scope == "当前最终方案":
                text = self.final.toPlainText()
            elif scope == "选中的对话文本":
                text = (
                    self.conversation.textCursor()
                    .selectedText()
                    .replace("\u2029", "\n")
                )
            elif scope == "最近一次模型输出":
                text = next(
                    (
                        m["content"]
                        for m in reversed(self.data["messages"])
                        if m["role"] == "assistant"
                    ),
                    "",
                )
            else:
                text = Project.transcript(
                    self.data, p.suffix[1:], scope == "仅模型输出"
                )
            if not text.strip():
                raise ValueError("所选范围没有可导出文本")
            p.write_text(redact(text, self.known_secrets()), encoding="utf-8")
            self.status.setText("已导出：" + str(p))
        except Exception as e:
            self.error(e)

    def refresh_assets(self):
        if not hasattr(self, "asset_grid"):
            return
        self.clear_grid(self.asset_grid)
        if not self.project:
            return
        kind = self.asset_categories.tabText(self.asset_categories.currentIndex())
        rows = [a for a in self.project.assets() if kind == "全部" or a["kind"] == kind]
        for i, a in enumerate(rows):
            self.asset_grid.addWidget(self.asset_card(a), i // 3, i % 3)
        if not rows:
            self.asset_grid.addWidget(
                label("此分类尚无资产，可手工创建或导入解析候选。"), 0, 0
            )

    def add_asset(self):
        if self.busy or not self.require_project():
            return
        self.edit_asset(None)

    def edit_asset(self, a=None):
        if self.busy or not self.project:
            return
        if (
            a
            and a["review"] == "已锁定"
            and QMessageBox.question(
                self,
                "修改锁定资产",
                "修改将建立新版本，历史任务快照保持原样。是否继续？",
            )
            != QMessageBox.Yes
        ):
            return
        d = AssetDialog(self, a)
        if d.exec():
            try:
                self.project.secrets = self.known_secrets()
                self.project.save_asset(d.value())
                self.refresh_assets()
                self.render_modules()
                self.refresh_image_assets()
                self.update_cards()
            except Exception as e:
                self.error(e)

    def import_workflow(self):
        if not self.project or self.busy:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "ComfyUI API 工作流", "", "JSON (*.json)"
        )
        if path:
            try:
                data = json.loads(Path(path).read_text("utf-8"))
                self.workflow.setPlainText(
                    json.dumps(data, ensure_ascii=False, indent=2)
                )
                dest = (
                    self.project.path
                    / "01_原始资料/过程文档"
                    / (Path(path).stem + "_" + uid() + ".json")
                )
                shutil.copy2(path, dest)
            except Exception:
                self.error("工作流不是有效 JSON")

    def load_confirmed_prompt(self):
        if not self.project or not self.scene_id:
            return
        d = self.project.load_node(self.scene_id, 3)
        if d["status"] != "已确认":
            self.info("当前情节的提示词尚未确认或需要复核，也可手工填写。")
            return
        self.comfy_prompt.setPlainText(d["final"])

    def generate_image(self):
        if self.busy or not self.require_project():
            return
        if not self.scene_id:
            self.info("请先选择情节")
            return
        try:
            c = next(
                (
                    x
                    for x in self.store.connections(self.account)
                    if x["id"] == self.image_connections.currentData()
                ),
                None,
            )
            if not c or c["kind"] not in ("comfy", "image_api"):
                raise ValueError("请选择独立图片连接；不会自动切换")
            prompt = self.comfy_prompt.toPlainText().strip()
            if not prompt:
                raise ValueError("请填写提示词")
            rows = self.project.scene_assets(self.scene_id)
            issues = [
                r["kind"] + " " + r["name"] + "：" + r["problem"]
                for r in rows
                if r["problem"]
            ]
            if not rows:
                issues.append("尚未建立此情节的资产关联")
            if (
                issues
                and QMessageBox.question(
                    self,
                    "资产检查",
                    "\n".join(issues) + "\n\n是否接受这些缺失并继续生成？",
                )
                != QMessageBox.Yes
            ):
                return
            scene = self.project.scene(self.scene_id)
            text = self.project.segment_text(self.sid)
            import hashlib

            if (
                scene["source_hash"] != hashlib.sha256(text.encode()).hexdigest()
                and QMessageBox.question(
                    self,
                    "原文已变化",
                    "当前情节基于旧原文。建议重新核对范围。仍使用当前情节继续吗？",
                )
                != QMessageBox.Yes
            ):
                return
            j = dict(
                id=uid(),
                kind="ComfyUI 图片" if c["kind"] == "comfy" else "兼容 API 图片",
                created=now(),
                status="running",
                segment=self.sid,
                scene=self.scene_id,
                scene_snapshot=scene,
                connection=copy.deepcopy(c),
                endpoint=c["endpoint"],
                prompt=prompt,
                assets=copy.deepcopy(rows),
                accepted_missing=issues,
            )
            key = self.connection_key(c["id"])
            dest = self.project.path / "05_生成任务" / j["id"] / "候选图片"
            if c["kind"] == "comfy":
                flow = json.loads(self.workflow.toPlainText())
                mapping = json.loads(self.mapping.toPlainText())
                values = dict(prompt=prompt, seed=self.seed.value())
                refs = []
                for i, r in enumerate(rows):
                    a = r.get("asset")
                    field = "reference_" + str(i + 1)
                    if (
                        a
                        and a.get("image")
                        and (self.project.path / a["image"]).exists()
                        and field in mapping
                    ):
                        refs.append((field, self.project.path / a["image"]))
                unmapped = [
                    r["name"]
                    for i, r in enumerate(rows)
                    if r.get("asset")
                    and r["asset"].get("image")
                    and "reference_" + str(i + 1) not in mapping
                ]
                if (
                    unmapped
                    and QMessageBox.question(
                        self,
                        "参考图未映射",
                        "这些参考图不会上传："
                        + ", ".join(unmapped)
                        + "。继续仅使用文字和已映射参考图吗？",
                    )
                    != QMessageBox.Yes
                ):
                    return
                if not self.confirm_upload(
                    dict(provider="openai", endpoint=c["endpoint"], model="ComfyUI"),
                    [p for _, p in refs],
                ):
                    return
                # Validate all node mappings before any upload or generation request.
                bind_workflow(
                    flow,
                    mapping,
                    dict(values, **{field: "pending_upload.png" for field, _ in refs}),
                )
                j.update(
                    workflow=flow,
                    mapping=mapping,
                    reference_files=[
                        p.relative_to(self.project.path).as_posix() for _, p in refs
                    ],
                    values=values,
                    workflow_sha256=hashlib.sha256(
                        json.dumps(flow, sort_keys=True).encode()
                    ).hexdigest(),
                )

                def run(cancel, progress):
                    from .providers import upload_comfy

                    actual = dict(values)
                    for field, path in refs:
                        if cancel.is_set():
                            raise UnknownOutcome(
                                "已取消上传后的提交；没有自动创建生成任务"
                            )
                        actual[field] = upload_comfy(c["endpoint"], path, key)
                    bound = bind_workflow(flow, mapping, actual)
                    progress({"submitted_workflow": bound})
                    return comfy_call(c["endpoint"], bound, dest, cancel, progress, key)
            else:
                if (
                    any(r.get("asset") and r["asset"].get("image") for r in rows)
                    and QMessageBox.question(
                        self,
                        "图像接口能力",
                        "当前兼容接口仅支持文生图，不会发送资产参考图。是否继续？",
                    )
                    != QMessageBox.Yes
                ):
                    return
                size = self.image_size.currentText()
                j["size"] = size

                def run(cancel, progress):
                    return image_call(c, prompt, size, dest, key, cancel)

            self.project.secrets = self.known_secrets()
            self.project.save_job(j)
            self.start_job(j, run)
        except json.JSONDecodeError:
            self.error("工作流或映射不是有效JSON")
        except Exception as e:
            self.error(e)

    def show_image(self, index):
        path = self.image_list.itemData(index)
        if path:
            pix = QPixmap(path)
            if pix.isNull():
                self.image.setText("图片无法读取")
            else:
                self.image.setPixmap(
                    pix.scaled(
                        max(180, self.image.width() - 20),
                        max(180, self.image.height() - 20),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )

    def choose_result(self):
        path = self.image_list.currentData()
        if not path or not self.project:
            return
        try:
            src = Path(path)
            dest = (
                self.project.path
                / "06_最终成果"
                / (src.stem + "_" + uid() + src.suffix)
            )
            shutil.copy2(src, dest)
            self.status.setText("已保存最终成果：" + dest.name)
        except Exception as e:
            self.error(e)

    def open_image_folder(self):
        p = self.image_list.currentData()
        if p:
            reveal(Path(p).parent)

    def refresh_jobs(self):
        self.job_tree.clear()
        if not self.project:
            return
        for j in self.project.jobs():
            item = QTreeWidgetItem(
                [
                    j["created"],
                    j["kind"],
                    j["status"],
                    j.get("remote_id", j.get("params", {}).get("model", "演示")),
                ]
            )
            item.setData(0, Qt.UserRole, j)
            self.job_tree.addTopLevelItem(item)

    def open_job(self):
        i = self.job_tree.currentItem()
        if i and self.project:
            reveal(self.project.path / "05_生成任务" / i.data(0, Qt.UserRole)["id"])

    def query_remote(self):
        i = self.job_tree.currentItem()
        if not i:
            return
        j = i.data(0, Qt.UserRole)
        if j.get("remote_id"):
            QDesktopServices.openUrl(QUrl(j["endpoint"] + "/history/" + j["remote_id"]))
        else:
            self.info("该任务没有可查询的远端 ID；请查看供应商后台记录。")

    def refresh_files(self):
        self.file_tree.clear()
        if not self.project:
            return

        def walk(parent, path, depth=0):
            if depth > 8:
                return
            for p in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name)):
                if p.is_symlink():
                    continue
                item = QTreeWidgetItem(
                    [p.name, "" if p.is_dir() else f"{p.stat().st_size / 1024:.1f} KB"]
                )
                item.setData(0, Qt.UserRole, str(p))
                parent.addChild(item) if isinstance(
                    parent, QTreeWidgetItem
                ) else parent.addTopLevelItem(item)
                if p.is_dir():
                    walk(item, p, depth + 1)

        walk(self.file_tree, self.project.path)

    def open_selected_file(self):
        i = self.file_tree.currentItem()
        if i:
            reveal(i.data(0, Qt.UserRole))

    def archive_attachment(self):
        if not self.require_project():
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "保存项目附件（不发送给模型）", "", "所有文件 (*)"
        )
        try:
            for p in paths:
                self.project.add_attachment(p)
            self.refresh_files()
            self.status.setText("附件已保存到项目目录，未发送给模型")
        except Exception as e:
            self.error(e)

    def restore_backup(self):
        if not self.guard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "恢复项目备份", "", "ZIP (*.zip)")
        if not path:
            return
        dest = self.store.account_dir(self.account) / "项目" / ("恢复项目_" + uid())
        try:
            with zipfile.ZipFile(path) as z:
                total = sum(i.file_size for i in z.infolist())
                if total > 4 * 1024**3:
                    raise ValueError("测试版仅支持恢复 4 GB 以内的项目备份")
                for i in z.infolist():
                    target = (dest / i.filename).resolve()
                    if (
                        dest.resolve() not in target.parents
                        or (i.external_attr >> 16) & 0o170000 == 0o120000
                    ):
                        raise ValueError("备份包含不安全的路径或符号链接")
                if (
                    "08_项目数据/project.json" not in z.namelist()
                    or "08_项目数据/index.sqlite" not in z.namelist()
                ):
                    raise ValueError("不是本软件的项目备份")
                z.extractall(dest)
            meta_path = dest / "08_项目数据/project.json"
            meta = json.loads(meta_path.read_text("utf-8"))
            meta["restored_from"] = meta["id"]
            meta["id"] = uid()
            write_json(meta_path, meta)
            p = Project(dest)
            p.close()
            self.reload_projects(dest)
            self.status.setText("备份已恢复为独立项目，原项目保留")
        except Exception as e:
            if dest.exists():
                shutil.rmtree(dest)
            self.error(e)

    def backup(self):
        if not self.guard() or not self.require_project():
            return
        p, _ = QFileDialog.getSaveFileName(
            self,
            "项目备份",
            str(self.store.root / (self.project.meta["name"] + "_备份.zip")),
            "ZIP (*.zip)",
        )
        if not p:
            return
        try:
            dest = Path(p).resolve()
            if self.project.path == dest or self.project.path in dest.parents:
                raise ValueError("请将备份保存到当前项目目录之外")
            self.save_draft(silent=True)
            self.project.db.commit()
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
                for file in self.project.path.rglob("*"):
                    if file.is_file() and not file.is_symlink():
                        z.write(file, file.relative_to(self.project.path))
            self.status.setText("项目备份完成（不包含账户凭据）")
        except Exception as e:
            self.error(e)

    def system_theme_changed(self, *_):
        if self.settings["theme"] == "system":
            self.apply_theme()

    def apply_theme(self):
        theme = self.settings["theme"]
        dark = theme == "dark" or (
            theme == "system"
            and QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        )
        bg = "#121d21" if dark else "#f4f7f5"
        panel = "#1a292e" if dark else "#ffffff"
        text = "#e1eae5" if dark else "#223d36"
        muted = "#9aafa5" if dark else "#71877e"
        border = "#33453f" if dark else "#dfe8e1"
        accent = "#80d6bb" if dark else "#147d64"
        inputbg = "#152326" if dark else "#fbfcfa"
        self.setStyleSheet(f"""
        QWidget {{font-family: "Microsoft YaHei UI", "Noto Sans CJK SC", "Arial";font-size:{self.settings["font_size"]}px;color:{text};}}
        QMainWindow, Backdrop {{background:{bg};}}
        QFrame#topbar,QFrame#sidebar {{background:{panel};border:0;}}
        QFrame#topbar {{border-bottom:1px solid {border};}}
        QFrame#sidebar {{border-right:1px solid {border};}}
        QFrame#panel {{background:{panel};border:1px solid {border};border-radius:14px;}}
        QLabel#brand {{font-size:20px;font-weight:700;letter-spacing:2px;}}
        QLabel#hero {{font-size:27px;font-weight:700;}}
        QLabel#section {{font-size:17px;font-weight:700;}}
        QLabel#muted {{color:{muted};font-size:12px;}}
        QLabel#eyebrow {{color:{muted};font-size:12px;margin-bottom:20px;}}
        QPushButton {{background:{panel};border:1px solid {border};min-height:18px;padding:9px 13px;border-radius:8px;}}
        QPushButton:hover {{border-color:{accent};color:{accent};}}
        QPushButton:disabled {{color:{muted};}}
        QPushButton[primary="true"] {{background:#177e66;color:white;border-color:#177e66;font-weight:600;}}
        QPushButton[nav="true"] {{background:transparent;border:0;text-align:left;padding:13px 10px;margin-bottom:4px;}}
        QPushButton[active="true"] {{background:{"#294b40" if dark else "#e4f1e9"};color:{accent};font-weight:700;}}
        QPushButton[card="true"] {{text-align:left;background:{panel};border-radius:12px;padding:15px;}}
        QPushButton[selected="true"] {{background:{"#24473e" if dark else "#edf7f0"};border:2px solid {accent};}}
        QComboBox,QLineEdit,QSpinBox,QDoubleSpinBox {{background:{inputbg};border:1px solid {border};border-radius:7px;padding:7px;selection-background-color:#177e66;}}
        QPlainTextEdit,QTextEdit,QTreeWidget,QListWidget {{background:{inputbg};border:1px solid {border};border-radius:8px;padding:10px;selection-background-color:#177e66;}}
        QTabWidget::pane {{border:0;}} QTabBar::tab {{padding:10px 13px;color:{muted};border-bottom:2px solid transparent;}}
        QTabBar::tab:selected {{color:{accent};border-bottom-color:{accent};}}
        QScrollArea {{background:transparent;}} QScrollArea>QWidget>QWidget {{background:transparent;}}
        QHeaderView::section {{background:{panel};padding:10px;border:0;border-bottom:1px solid {border};}}
        QDialog {{background:{bg};}} QMessageBox {{background:{bg};}}
        QSplitter::handle {{background:transparent;width:12px;}}
        QLabel#imagePreview {{background:{panel};border:1px dashed {border};border-radius:14px;color:{muted};}}
        QToolTip {{background:{panel};color:{text};border:1px solid {border};}}
        """)
        self.bg.pix = QPixmap(self.settings["background"])
        self.bg.opacity = self.settings["background_opacity"] / 100.0
        self.bg.update()

    def closeEvent(self, event):
        if self.busy:
            self.info(
                "任务仍在执行。请先停止等待，并等待本次网络请求结束后退出，避免丢失远端状态。"
            )
            event.ignore()
            return
        self.save_draft(silent=True)
        if self.project:
            self.project.close()
        event.accept()

    def toggle_sidebar(self):
        self.side.setVisible(self.side.isHidden())
        self.settings["sidebar_visible"] = not self.side.isHidden()
        self.store.save_settings(self.account, self.settings)

    def scope(self):
        return self.sid if self.node in (0, 7) else (self.scene_id or self.sid)

    def connection_key(self, cid):
        from .connections import credential_id

        slot = credential_id(self.account["id"], cid)
        if slot in self.session_keys:
            return self.session_keys[slot]
        key = get_key(slot)
        legacy = next(
            (
                c.get("legacy", False)
                for c in self.store.connections(self.account)
                if c["id"] == cid
            ),
            False,
        )
        if not key and legacy:
            return self.session_keys.get(self.account["id"]) or get_key(
                self.account["id"]
            )
        return key

    def set_connection_key(self, cid, value, persist=False):
        from .connections import credential_id

        slot = credential_id(self.account["id"], cid)
        if persist and (value or get_key(slot)):
            set_key(slot, value)
        self.session_keys[slot] = value
        if self.project:
            self.project.secrets = self.known_secrets()

    def known_secrets(self):
        values = [
            self.session_keys.get(self.account["id"]) or get_key(self.account["id"])
        ]
        values.extend(
            self.connection_key(c["id"]) for c in self.store.connections(self.account)
        )
        values.extend(
            value
            for slot, value in self.session_keys.items()
            if slot.startswith(self.account["id"] + ":connection:")
        )
        return list(dict.fromkeys(v for v in values if v))

    def reload_scenes(self, select=None):
        self.scene_combo.blockSignals(True)
        self.scene_combo.clear()
        if self.project and self.sid:
            self.project.ensure_scene(self.sid)
            for s in self.project.scenes(self.sid):
                self.scene_combo.addItem(s["title"], s["id"])
        if select:
            self.scene_combo.setCurrentIndex(self.scene_combo.findData(select))
        self.scene_id = self.scene_combo.currentData()
        self.scene_combo.blockSignals(False)

    def switch_scene(self, index):
        if not self.guard():
            self.scene_combo.blockSignals(True)
            self.scene_combo.setCurrentIndex(self.scene_combo.findData(self.scene_id))
            self.scene_combo.blockSignals(False)
            return
        self.save_draft(silent=True)
        self.scene_id = self.scene_combo.itemData(index)
        self.clear_attachments()
        self.comfy_prompt.clear()
        self.show_node()
        self.refresh_image_assets()

    def call_attachments(self):
        rels = list(
            dict.fromkeys(
                [p for m in self.data["messages"] for p in m.get("attachments", [])]
                + self.pending_attachments
            )
        )
        if self.include_refs.isChecked() and self.scene_id:
            rels.extend(
                r["asset"]["image"]
                for r in self.project.scene_assets(self.scene_id)
                if r["asset"] and r["asset"].get("image")
            )
        rels = list(dict.fromkeys(rels))
        for rel in rels:
            p = (self.project.path / rel).resolve()
            if self.project.path not in p.parents or not p.is_file():
                raise ValueError("附件引用缺失或超出项目目录：" + Path(rel).name)
        return rels

    def confirm_upload(self, params, paths):
        if (
            not paths
            or params["provider"] == "demo"
            or not self.settings["confirm_attachments"]
        ):
            return True
        total = sum(p.stat().st_size for p in paths)
        images = sum(
            (p.stat().st_size + 2) // 3 * 4
            for p in paths
            if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
        )
        details = "\n".join(
            f"{p.name} — {p.stat().st_size / 1024:.1f} KB" for p in paths
        )
        return (
            QMessageBox.question(
                self,
                "附件发送确认",
                f"目标：{params['endpoint']}\n模型：{params['model']}\n{details}\n文件总大小 {total / 1024:.1f} KB；图片编码约 {images / 1024:.1f} KB。\n文档将提取为文本发送；历史附件也包含在内。费用未知。\n是否发送？",
            )
            == QMessageBox.Yes
        )

    def preview_input(self):
        if not self.data:
            return
        try:
            p = self.param_form.value()
            a = self.call_attachments()
            content = self.message.toPlainText()
            text = (
                "【系统提示词】\n"
                + p["system"]
                + "\n\n【上下文】\n"
                + self.context()
                + "\n\n【历史对话】\n"
                + Project.transcript(self.data)
                + "\n\n【当前输入】\n"
                + content
                + "\n\n【附件】\n"
                + "\n".join(a)
            )
            d = QDialog(self)
            d.setWindowTitle("实际输入预览 · 不发送")
            d.resize(900, 700)
            l = QVBoxLayout(d)
            edit = QPlainTextEdit(redact(text, self.known_secrets()))
            edit.setReadOnly(True)
            l.addWidget(edit)
            l.addWidget(
                label(f"文本约 {len(text):,} 字符；不等同精确 token 或费用。", "muted")
            )
            l.addWidget(button("关闭", d.accept))
            d.exec()
        except Exception as e:
            self.error(e)

    def drop_chat_files(self, paths):
        if self.busy or not self.data:
            return
        try:
            for p in paths:
                if Path(p).suffix.lower() not in (
                    ".txt",
                    ".md",
                    ".docx",
                    ".epub",
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".webp",
                ):
                    raise ValueError("支持 TXT/MD/DOCX/EPUB 和图片")
                if Path(p).stat().st_size > 20 * 1024 * 1024:
                    raise ValueError("单附件上限为20MB")
                self.pending_attachments.append(self.project.add_attachment(p))
            self.update_attachment_label()
        except Exception as e:
            self.error(e)

    def update_attachment_label(self):
        self.attachment_label.setText(
            " · ".join(Path(p).name for p in self.pending_attachments) or "未附加文件"
        )

    def drop_final_files(self, paths):
        try:
            for p in paths:
                if Path(p).suffix.lower() in (".txt", ".md"):
                    self.final.insertPlainText(read_document(p))
                else:
                    self.drop_chat_files([p])
        except Exception as e:
            self.error(e)

    def clear_grid(self, grid):
        while grid.count():
            item = grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def render_modules(self):
        if not hasattr(self, "module_grid"):
            return
        self.clear_grid(self.module_grid)
        self.depth.setVisible(self.node == 0)
        for i in range(1, self.module_tools.count()):
            item = self.module_tools.itemAt(i)
            if item.widget():
                item.widget().setVisible(self.node == 0)
        self.module_title.setText("情节模块" if self.node == 0 else "情节关联资产")
        if not self.project or not self.sid:
            self.module_grid.addWidget(label("创建项目并导入片段，即可开始。"), 0, 0)
            return
        if self.node == 0:
            for i, s in enumerate(self.project.scenes(self.sid)):
                card = QFrame()
                card.setObjectName("panel")
                l = QVBoxLayout(card)
                l.setSizeConstraint(QLayout.SetMinimumSize)
                l.addWidget(label(s["title"], "section"))
                l.addWidget(
                    label(
                        f"段落 {s['start_paragraph']}—{s['end_paragraph']} · v{s['revision']}",
                        "muted",
                    )
                )
                l.addWidget(label(s["summary"][:180]))
                l.addWidget(label(s["source_text"][:160] + "…", "muted"))
                row = QHBoxLayout()
                row.addWidget(
                    button(
                        "进入情节", lambda checked=False, x=s["id"]: self.open_scene(x)
                    )
                )
                row.addWidget(
                    button("编辑", lambda checked=False, x=s: self.edit_scene(x))
                )
                l.addLayout(row)
                self.module_grid.addWidget(card, i, 0)
            self.module_grid.addWidget(
                button("查看归档的拆分版本", self.show_archived_scenes),
                len(self.project.scenes(self.sid)),
                0,
            )
        else:
            rows = self.project.scene_assets(self.scene_id) if self.scene_id else []
            for i, r in enumerate(rows):
                self.module_grid.addWidget(self.asset_card(r.get("asset"), r), i, 0)
            actions = QWidget()
            al = QHBoxLayout(actions)
            al.addWidget(button("关联 / 补齐资产", self.link_asset))
            al.addWidget(
                button(
                    "编辑情节需求",
                    lambda: (
                        self.edit_scene(self.project.scene(self.scene_id))
                        if self.scene_id
                        else None
                    ),
                )
            )
            self.module_grid.addWidget(actions, len(rows), 0)
            if not rows:
                self.module_grid.addWidget(
                    label(
                        "尚未列出资产需求。可以解析资产，或编辑情节手工添加。", "muted"
                    ),
                    len(rows) + 1,
                    0,
                )

    def asset_card(self, a, requirement=None):
        card = QFrame()
        card.setObjectName("panel")
        l = QVBoxLayout(card)
        l.setSizeConstraint(QLayout.SetMinimumSize)
        title = a["name"] if a else requirement["name"]
        kind = a["kind"] if a else requirement["kind"]
        l.addWidget(label(title + "  /  " + kind, "section"))
        if a and a.get("image"):
            pix = QPixmap(str(self.project.path / a["image"]))
            thumb = QLabel()
            thumb.setAlignment(Qt.AlignCenter)
            if not pix.isNull():
                thumb.setPixmap(
                    pix.scaled(260, 130, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                l.addWidget(thumb)
        l.addWidget(
            label(
                (a["description"][:180] if a else "需要补建档案，或关联已有资产"),
                "muted",
            )
        )
        if requirement and requirement.get("problem"):
            l.addWidget(label("⚑ " + requirement["problem"]))
        if a:
            l.addWidget(label(a["source"] + " · " + a["review"], "muted"))
            l.addWidget(
                button("编辑资产", lambda checked=False, x=a: self.edit_asset(x))
            )
        else:
            l.addWidget(
                button(
                    "补建 / 关联",
                    lambda checked=False, r=requirement: self.link_asset(r),
                )
            )
        return card

    def open_scene(self, scene_id):
        self.scene_combo.setCurrentIndex(self.scene_combo.findData(scene_id))
        self.select_node(1)

    def add_scene(self):
        if not self.guard() or not self.require_project() or not self.sid:
            return
        self.edit_scene(None)

    def edit_scene(self, scene=None):
        if self.busy or not self.project or not self.sid:
            return
        d = SceneDialog(self, scene)
        if d.exec():
            try:
                self.save_draft(silent=True)
                new = self.project.save_scene(d.value())
                self.data = None
                self.reload_scenes(new["id"])
                self.show_node()
                self.refresh_image_assets()
            except Exception as e:
                self.error(e)

    def show_archived_scenes(self):
        if not self.project or not self.sid:
            return
        scenes = self.project.scenes(self.sid, True)
        if not scenes:
            self.info("没有归档版本")
            return
        d = QDialog(self)
        d.setWindowTitle("归档情节 · 只读保留")
        d.resize(750, 600)
        l = QVBoxLayout(d)
        edit = QPlainTextEdit(json.dumps(scenes, ensure_ascii=False, indent=2))
        edit.setReadOnly(True)
        l.addWidget(edit)
        l.addWidget(button("关闭", d.accept))
        d.exec()

    def request_split(self):
        if not self.data or self.busy:
            return
        self.message.setPlainText(
            "请按"
            + self.depth.currentText()
            + "拆分当前片段，输出 scenes JSON。保留原文并完整覆盖段落，先给候选等待审核。"
        )
        self.tabs.setCurrentIndex(0)
        self.send_message()

    def append_text_files(self, paths, target):
        try:
            for path in paths:
                if Path(path).suffix.lower() not in (".txt", ".md"):
                    raise ValueError("此处仅支持TXT/MD")
                target.insertPlainText(read_document(path))
        except Exception as e:
            self.error(e)

    def preview_structured(self):
        if not self.project or not self.sid or not self.data or self.busy:
            return
        try:
            fmt = self.param_form.output.currentData()
            if fmt not in ("scenes", "assets"):
                raise ValueError(
                    "当前模板为自由文本。请选择结构化模板，或手工创建情节/资产。"
                )
            obj = parse_object(self.final.toPlainText())
            count = len(self.project.paragraphs(self.sid))
            rows = (
                validate_scenes(obj, count)
                if fmt == "scenes"
                else validate_assets(obj, count)
            )
            if fmt == "assets":
                paragraphs = self.project.paragraphs(self.sid)
                for a in rows:
                    evidence = list(a.get("evidence", []))
                    for attr in a.get("attributes", []):
                        evidence.extend(attr.get("evidence", []))
                    for e in evidence:
                        if e["quote"] not in paragraphs[e["paragraph"] - 1]["text"]:
                            raise ValueError("资产证据摘录不在对应原文段落中")
            d = QDialog(self)
            d.setWindowTitle("候选预览 · 确认后才写入")
            d.resize(850, 650)
            l = QVBoxLayout(d)
            l.addWidget(
                label(
                    "重新拆分会归档旧情节及其编辑记录；资产候选会创建待审核卡片，不自动覆盖已有档案。"
                )
            )
            text = QPlainTextEdit(json.dumps(rows, ensure_ascii=False, indent=2))
            text.setReadOnly(True)
            l.addWidget(text)
            row = QHBoxLayout()
            row.addWidget(button("取消", d.reject))
            row.addWidget(button("确认导入这些候选", d.accept, True))
            l.addLayout(row)
            if not d.exec():
                return
            self.apply_structured(fmt, rows)
        except Exception as e:
            self.error(e)

    def apply_structured(self, fmt, rows):
        self.save_draft(silent=True)
        if fmt == "scenes":
            self.project.apply_scene_candidates(self.sid, rows)
            self.data = None
            self.reload_scenes()
            self.show_node()
        elif fmt == "assets":
            if not self.scene_id:
                raise ValueError("请先选择情节")
            requirements = self.project.requirements(self.scene_id)
            for row in rows:
                # Existing matches are review proposals, never silent overwrites.
                a = {
                    k: copy.deepcopy(v)
                    for k, v in row.items()
                    if k
                    in (
                        "name",
                        "kind",
                        "source",
                        "description",
                        "evidence",
                        "states",
                        "suggestions",
                        "conflicts",
                        "missing",
                        "existing_id",
                        "attributes",
                    )
                }
                a.setdefault("source", "AI 建议")
                a.update(id=uid(), review="待审核")
                a["description"] = row.get("description", "")
                a = self.project.save_asset(a)
                target = next(
                    (
                        r
                        for r in requirements
                        if r["name"] == a["name"]
                        and r["kind"] == a["kind"]
                        and not r.get("asset_id")
                    ),
                    None,
                )
                if target:
                    target["asset_id"] = a["id"]
                else:
                    requirements.append(
                        dict(name=a["name"], kind=a["kind"], asset_id=a["id"])
                    )
            self.project.set_requirements(self.scene_id, requirements)
            self.refresh_assets()
            self.render_modules()
            self.refresh_image_assets()
        self.status.setText("候选已按用户确认导入；资产仍待审核，旧内容未覆盖")

    def link_asset(self, requirement=None):
        if self.busy or not self.scene_id:
            return
        rows = self.project.requirements(self.scene_id)
        if not requirement:
            if not rows:
                self.info("先编辑情节，添加画面需要的资产名称和类型。")
                return
            names = [r["kind"] + " / " + r["name"] for r in rows]
            name, ok = QInputDialog.getItem(
                self, "选择资产需求", "需求", names, 0, False
            )
            if not ok:
                return
            requirement = rows[names.index(name)]
        choices = [a for a in self.project.assets() if a["kind"] == requirement["kind"]]
        names = ["＋ 新建该资产"] + [a["name"] + " · " + a["id"] for a in choices]
        chosen, ok = QInputDialog.getItem(
            self, "补建或关联", "选择档案", names, 0, False
        )
        if not ok:
            return
        if chosen == names[0]:
            d = AssetDialog(
                self, dict(name=requirement["name"], kind=requirement["kind"])
            )
            if not d.exec():
                return
            try:
                a = self.project.save_asset(d.value())
            except Exception as e:
                self.error(e)
                return
        else:
            a = choices[names.index(chosen) - 1]
        for r in rows:
            if r["name"] == requirement["name"] and r["kind"] == requirement["kind"]:
                r["asset_id"] = a["id"]
                break
        self.project.set_requirements(self.scene_id, rows)
        self.render_modules()
        self.refresh_assets()
        self.refresh_image_assets()
        self.update_cards()

    def reload_image_connections(self):
        if not hasattr(self, "image_connections"):
            return
        selected = (
            self.project.config.get("image_connection", "image-default")
            if self.project
            else "image-default"
        )
        self.image_connections.blockSignals(True)
        self.image_connections.clear()
        for c in self.store.connections(self.account):
            if c["kind"] in ("comfy", "image_api"):
                self.image_connections.addItem(c["name"], c["id"])
        self.image_connections.setCurrentIndex(
            self.image_connections.findData(selected)
        )
        self.image_connections.blockSignals(False)
        self.image_connection_changed()

    def image_connection_changed(self, *_):
        c = next(
            (
                x
                for x in self.store.connections(self.account)
                if x["id"] == self.image_connections.currentData()
            ),
            None,
        )
        comfy = bool(c and c["kind"] == "comfy")
        self.workflow.setVisible(comfy)
        self.mapping.setVisible(comfy)
        self.seed.setVisible(comfy)
        self.image_size.setVisible(not comfy)
        if self.project and c:
            self.project.config["image_connection"] = c["id"]
            self.project.save_config()

    def edit_image_connection(self):
        if not self.guard():
            return
        c = next(
            (
                x
                for x in self.store.connections(self.account)
                if x["id"] == self.image_connections.currentData()
            ),
            None,
        )
        if not c:
            return
        d = ConnectionDialog(self, c)
        if d.exec():
            self.reload_image_connections()

    def new_image_connection(self):
        if not self.guard():
            return
        d = ConnectionDialog(self, kind="image_api")
        if d.exec():
            if self.project:
                self.project.config["image_connection"] = d.profile["id"]
                self.project.save_config()
            self.reload_image_connections()

    def refresh_image_assets(self):
        if not hasattr(self, "image_asset_grid"):
            return
        self.clear_grid(self.image_asset_grid)
        scene = (
            self.project.scene(self.scene_id)
            if self.project and self.scene_id
            else None
        )
        self.image_scope_label.setText(
            "当前情节：" + scene["title"] if scene else "请先在情节工作区选择原文与情节"
        )
        rows = self.project.scene_assets(self.scene_id) if scene else []
        for i, r in enumerate(rows):
            self.image_asset_grid.addWidget(self.asset_card(r["asset"], r), i, 0)
        if not rows:
            self.image_asset_grid.addWidget(
                label("当前情节未列出资产需求；生成前会提示。", "muted"), 0, 0
            )

    def drop_image_prompt(self, paths):
        try:
            for p in paths:
                if Path(p).suffix.lower() not in (".txt", ".md"):
                    raise ValueError("此处仅接收TXT/MD提示词；参考图请添加到资产卡")
                self.comfy_prompt.insertPlainText(read_document(p))
        except Exception as e:
            self.error(e)

    def drop_workflow(self, paths):
        try:
            for p in paths:
                data = json.loads(Path(p).read_text("utf-8"))
                self.workflow.setPlainText(
                    json.dumps(data, ensure_ascii=False, indent=2)
                )
                self.project.add_attachment(p)
        except Exception as e:
            self.error(e)

    def result_as_asset_image(self):
        path = self.image_list.currentData()
        if not path or not self.project or self.busy:
            return
        assets = self.project.assets()
        if not assets:
            self.info("请先建立资产档案")
            return
        names = [a["name"] + " · " + a["id"] for a in assets]
        name, ok = QInputDialog.getItem(
            self, "选择资产", "将当前图片设为主参考图", names, 0, False
        )
        if ok:
            a = assets[names.index(name)]
            a["image"] = self.project.save_asset_image(a, path)
            self.project.save_asset(a)
            self.refresh_assets()
            self.render_modules()
            self.refresh_image_assets()


def seed_demo(store):
    a = store.accounts[0]
    if store.projects(a):
        return
    p = store.create_project(a, "青灯夜渡 · 演示项目")
    s = p.add_segment(
        "第一章 · 雨夜渡口",
        "暮色沉入江面，细雨打湿了渡口的青石。\n\n沈青提着一盏旧铜灯，站在柳树下。她穿着灰蓝色布衣，衣角沾着泥水。\n\n“船还来吗？”她问。\n\n摆渡人将竹篙靠在船边，望向雾里的对岸。\n\n——以上为软件内置虚构示例，用于体验工作流程。",
    )
    p.add_segment(
        "第二章 · 对岸来信",
        "渡船靠岸时，沈青仍提着那盏旧铜灯。摆渡人递给她一封封着红蜡的信。\n\n——演示片段：与第一章共享人物与道具档案。",
    )
    p.save_asset(
        dict(
            name="沈青",
            kind="人物",
            source="原文明确",
            review="已确认",
            description="第一章：灰蓝色布衣，衣角沾泥。手提旧铜灯。\n证据：“沈青提着一盏旧铜灯……她穿着灰蓝色布衣”。\n面容、年龄：原文未描述，待确认。",
        )
    )
    p.save_asset(
        dict(
            name="旧铜灯",
            kind="道具",
            source="原文明确",
            review="已确认",
            description="第一章、第二章由沈青持有。材质为铜；具体造型待确认。",
        )
    )
    p.ensure_scene(s)
    scene = p.scenes(s)[0]
    by_name = {x["name"]: x for x in p.assets()}
    p.set_requirements(
        scene["id"],
        [
            dict(name="沈青", kind="人物", asset_id=by_name["沈青"]["id"]),
            dict(name="渡口", kind="场景"),
            dict(name="旧铜灯", kind="道具", asset_id=by_name["旧铜灯"]["id"]),
        ],
    )
    d = p.load_node(s, 0)
    d["final"] = (
        "保留渡口、细雨、灰蓝色布衣和旧铜灯。人物面容与年龄尚未明确，后续作为建议交由用户确认。"
    )
    p.confirm(s, 0, d)
    p.close()


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
    app.setStyle("Fusion")
    q = QSettings()
    root = args.data_root or (None if args.choose_root else q.value("data_root", ""))
    if not root:
        QMessageBox.information(
            None,
            "选择数据目录",
            "请选择软件数据根目录。建议选择 D 盘等容量充足的位置；账户、项目和资源将集中保存在这里。",
        )
        root = QFileDialog.getExistingDirectory(None, "选择数据根目录")
        if not root:
            return
        q.setValue("data_root", root)
    if args.demo:
        seed_demo(Store(root))
    w = Window(root)
    w.show()
    if args.screenshot:
        QTimer.singleShot(1000, lambda: (w.grab().save(args.screenshot), app.quit()))
    sys.exit(app.exec())
