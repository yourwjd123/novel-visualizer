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

from PySide6.QtCore import QPoint, QSettings, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .credentials import get_key, set_key
from .providers import UnknownOutcome, bind_workflow, comfy_call, image_call, text_call
from .storage import (
    DEFAULTS,
    NODES,
    Project,
    Store,
    now,
    read_document,
    redact,
    uid,
    write_json,
)


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


from .components import AssetDialog, ConnectionDialog, DropEdit, NodeForm, SceneDialog
from .connections import KINDS
from .panels import AccountDialog, FloatingAssistant, SettingsPanel
from .prompts import parse_object, validate_assets, validate_scenes


class Window(QMainWindow):
    def __init__(self, root):
        super().__init__()
        self.store = Store(root, create_default=False)
        self.account = None
        self.settings = copy.deepcopy(DEFAULTS)
        self.project = None
        self.sid = None
        self.scene_id = None
        self.node = 0
        self.data = None
        self.worker = None
        self.busy = False
        self.session_keys = {}
        self.pending_attachments = []
        self.node_buttons = []
        self.settings_page = None
        self.image_defaults_cache = {}
        self._navigating = False
        self._closing = False
        self._card_columns = None
        self._runtime_loading = False
        self.setWindowTitle("墨境 · 小说智能可视化 | 0.3.0")
        self.resize(1440, 940)
        self.setMinimumSize(1000, 680)
        self.runtime_config = QWidget(self)
        self.runtime_config.hide()
        self.account_combo = QComboBox(self.runtime_config)
        self.account_combo.currentIndexChanged.connect(self.switch_account)
        self.bg = Backdrop()
        self.setCentralWidget(self.bg)
        outer = QVBoxLayout(self.bg)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        top = QFrame()
        top.setObjectName("topbar")
        top.setFixedHeight(36)
        t = QHBoxLayout(top)
        t.setContentsMargins(12, 1, 12, 1)
        t.addStretch()
        self.user_label = label("访客 · 未登录", "muted")
        t.addWidget(self.user_label)
        self.theme_button = button("明 / 暗", self.toggle_theme)
        self.theme_button.setStyleSheet("padding:2px 9px;min-height:20px;")
        t.addWidget(self.theme_button)
        outer.addWidget(top)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)
        self.side = QFrame()
        self.side.setObjectName("sidebar")
        self.side.setFixedWidth(174)
        sl = QVBoxLayout(self.side)
        sl.setContentsMargins(10, 12, 10, 12)
        self.brand = label("墨境", "brand")
        sl.addWidget(self.brand)
        self.system_buttons = []
        for symbol, title, fn in [
            ("☰", "收起侧栏", self.toggle_sidebar),
            ("▣", "项目与进度", self.project_dialog),
            ("○", "用户 / 登录", self.choose_account),
            ("⚙", "设置", self.open_settings),
            ("◷", "任务与历史", lambda: self.navigate(4)),
            ("▱", "项目文件", lambda: self.navigate(5)),
        ]:
            b = button(symbol + "  " + title, fn)
            b.setProperty("nav", True)
            b.setToolTip(title)
            sl.addWidget(b)
            self.system_buttons.append((b, symbol, title))
        self.projects_combo = QComboBox()
        self.projects_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.projects_combo.setMinimumContentsLength(8)
        self.projects_combo.addItem("选择账户后打开项目", None)
        self.projects_combo.currentIndexChanged.connect(self.switch_project)
        sl.addWidget(self.projects_combo)
        self.progress_label = label("选择本地账户后查看制作进度", "muted")
        sl.addWidget(self.progress_label)
        sl.addStretch()
        self.account_manage_button = button("账户管理", self.manage_accounts)
        sl.addWidget(self.account_manage_button)
        body.addWidget(self.side)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(18, 10, 18, 8)
        cl.setSpacing(10)
        body.addWidget(center, 1)
        self.work_tabs = QTabBar()
        self.work_tabs.setExpanding(False)
        self.work_tabs.setUsesScrollButtons(True)
        self.tab_pages = [0, 2, 3, 6, 1, 4, 5, 7]
        for name in [
            "原文与情节",
            "视觉资产库",
            "场景插图",
            "成果集",
            "原文阅读",
            "任务与历史",
            "项目文件",
            "设置",
        ]:
            self.work_tabs.addTab(name)
        for i in range(4, 8):
            self.work_tabs.setTabVisible(i, False)
        self.work_tabs.currentChanged.connect(
            lambda i: self.navigate(self.tab_pages[i]) if not self._navigating else None
        )
        cl.addWidget(self.work_tabs)
        self.stage_tabs = self.work_tabs
        self.stage_order = [0, 1, 5, 2, 3, 4, 6, 7]
        self.location_label = label(
            "访客工作区 · 开始操作时选择或创建本地账户", "muted"
        )
        cl.addWidget(self.location_label)
        self.pages = QStackedWidget()
        cl.addWidget(self.pages, 1)
        self.build_workbench()
        self.build_reader()
        self.build_assets()
        self.build_images()
        self.build_jobs()
        self.build_files()
        self.build_results()
        self.pages.addWidget(QWidget())
        self.status = label("就绪 · 未登录，不读取个人项目或密钥", "muted")
        cl.addWidget(self.status)
        self.build_assistant()
        self.param_host = self.runtime_config
        self.param_layout = QVBoxLayout(self.runtime_config)
        self.param_form = None
        self.ai_launcher = button("✦ AI 助手", self.show_assistant, True)
        self.ai_launcher.setParent(self.bg)
        self.ai_launcher.setFixedSize(140, 44)
        self.ai_launcher.setStyleSheet("border-radius:20px;")
        self.ai_launcher.raise_()
        self.show_node()
        self.apply_theme()
        self.navigate(0)
        QApplication.styleHints().colorSchemeChanged.connect(self.system_theme_changed)
        QTimer.singleShot(0, self.place_launcher)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "ai_launcher"):
            self.place_launcher()
        if hasattr(self, "module_grid"):
            QTimer.singleShot(0, self.reflow_cards)

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
        if not self.ensure_account():
            return False
        if not self.project:
            self.info("请从左侧“项目与进度”新建或打开小说项目。")
            return False
        return True

    def build_workbench(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(0, 0, 0, 54)
        l.setSpacing(12)
        row = QHBoxLayout()
        row.addWidget(label("原文与情节", "hero"), 1)
        row.addWidget(button("导入原文", self.import_segment))
        row.addWidget(button("智能拆分", self.request_split, True))
        l.addLayout(row)
        row = QHBoxLayout()
        self.segments_combo = QComboBox()
        self.segments_combo.setMinimumContentsLength(12)
        self.segments_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.segments_combo.currentIndexChanged.connect(self.switch_segment)
        row.addWidget(self.segments_combo, 2)
        self.scene_combo = QComboBox()
        self.scene_combo.setMinimumContentsLength(10)
        self.scene_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.scene_combo.currentIndexChanged.connect(self.switch_scene)
        row.addWidget(self.scene_combo, 2)
        self.depth = QComboBox()
        self.depth.addItems(["粗 · 主要事件", "中 · 连续场景", "细 · 插图瞬间"])
        self.depth.setCurrentIndex(1)
        row.addWidget(self.depth)
        l.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(button("＋ 粘贴片段", self.paste_segment))
        row.addWidget(button("＋ 手工情节", self.add_scene))
        row.addWidget(button("查看原文", lambda: self.navigate(1)))
        row.addWidget(button("查看归档版本", self.show_archived_scenes))
        row.addStretch()
        l.addLayout(row)
        self.scope_note = label("", "muted")
        l.addWidget(self.scope_note)
        self.module_title = label("情节模块", "section")
        l.addWidget(self.module_title)
        self.module_cards = QWidget()
        self.module_grid = QGridLayout(self.module_cards)
        self.module_grid.setContentsMargins(0, 0, 0, 0)
        self.module_grid.setSpacing(14)
        self.module_grid.setAlignment(Qt.AlignTop)
        self.module_grid.setSizeConstraint(QLayout.SetMinimumSize)
        l.addWidget(scroll(self.module_cards), 1)
        self.excerpt = QPlainTextEdit(self.runtime_config)
        self.excerpt.setReadOnly(True)
        self.context_count = label("", "muted")
        l.addWidget(self.context_count)
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
        l.setContentsMargins(0, 0, 0, 54)
        row = QHBoxLayout()
        row.addWidget(label("视觉资产库", "hero"), 1)
        row.addWidget(button("解析当前情节资产", lambda: self.discuss_node(1)))
        row.addWidget(button("＋ 新建资产", self.add_asset, True))
        l.addLayout(row)
        self.asset_categories = QTabBar()
        self.asset_categories.setExpanding(False)
        for kind in ("全部", "人物", "场景", "道具"):
            self.asset_categories.addTab(kind)
        self.asset_categories.currentChanged.connect(lambda _: self.refresh_assets())
        l.addWidget(self.asset_categories)
        self.asset_cards = QWidget()
        self.asset_grid = QGridLayout(self.asset_cards)
        self.asset_grid.setContentsMargins(0, 0, 0, 0)
        self.asset_grid.setSpacing(14)
        self.asset_grid.setAlignment(Qt.AlignTop)
        self.asset_grid.setSizeConstraint(QLayout.SetMinimumSize)
        l.addWidget(scroll(self.asset_cards), 1)
        self.pages.addWidget(page)

    def build_images(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(0, 0, 0, 54)
        row = QHBoxLayout()
        row.addWidget(label("场景插图", "hero"), 1)
        row.addWidget(button("讨论场景方案", lambda: self.discuss_node(2)))
        self.generate_btn = button("检查并生成", self.generate_image, True)
        row.addWidget(self.generate_btn)
        l.addLayout(row)
        self.image_scope_label = label("请先选择情节", "muted")
        l.addWidget(self.image_scope_label)
        row = QHBoxLayout()
        self.image_scene_picker = QComboBox()
        self.image_scene_picker.currentIndexChanged.connect(self.pick_image_scene)
        row.addWidget(self.image_scene_picker, 1)
        row.addWidget(button("载入确认提示词", self.load_confirmed_prompt))
        row.addWidget(button("查看 / 编辑最终提示词", self.edit_generation_prompt))
        l.addLayout(row)
        self.image = label(
            "尚无候选插图\n\n选择情节，讨论方案并确认提示词后生成。", "imagePreview"
        )
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumHeight(230)
        self.image.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        l.addWidget(self.image, 3)
        row = QHBoxLayout()
        self.image_list = QComboBox()
        self.image_list.currentIndexChanged.connect(self.show_image)
        row.addWidget(self.image_list, 1)
        row.addWidget(button("审核当前图片", lambda: self.discuss_node(6)))
        row.addWidget(button("选为正式插图", self.choose_result))
        row.addWidget(button("用作资产参考图", self.result_as_asset_image))
        l.addLayout(row)
        self.image_model_label = label("图片模型配置在设置中维护", "muted")
        l.addWidget(self.image_model_label)
        row = QHBoxLayout()
        row.addWidget(label("本场景引用的资产", "section"), 1)
        row.addWidget(button("调整关联", self.link_asset))
        l.addLayout(row)
        self.image_assets = QWidget()
        self.image_asset_grid = QGridLayout(self.image_assets)
        self.image_asset_grid.setContentsMargins(0, 0, 0, 0)
        self.image_asset_grid.setAlignment(Qt.AlignTop)
        self.image_asset_grid.setSizeConstraint(QLayout.SetMinimumSize)
        asset_scroll = scroll(self.image_assets)
        asset_scroll.setMinimumHeight(150)
        l.addWidget(asset_scroll, 2)
        self.comfy_prompt = DropEdit(self.runtime_config)
        self.comfy_prompt.filesDropped.connect(self.drop_image_prompt)
        self.image_connections = QComboBox(self.runtime_config)
        self.image_connections.currentIndexChanged.connect(
            self.image_connection_changed
        )
        self.workflow = DropEdit(self.runtime_config)
        self.workflow.filesDropped.connect(self.drop_workflow)
        self.mapping = DropEdit('{\n  "prompt": ["6", "text"]\n}')
        self.mapping.setParent(self.runtime_config)
        self.mapping.setMaximumHeight(130)
        self.workflow.setMinimumHeight(180)
        self.seed = QSpinBox(self.runtime_config)
        self.seed.setRange(0, 2147483647)
        self.seed.setValue(42)
        self.image_size = QComboBox(self.runtime_config)
        self.image_size.addItems(["1024x1024", "1536x1024", "1024x1536"])
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
        if self._navigating:
            return
        if i not in range(8):
            return
        if i in (4, 5, 7) and not self.ensure_account():
            self.sync_tabs()
            return
        current = self.pages.currentIndex()
        if (
            current == 7
            and i != 7
            and self.settings_page
            and not self.settings_page.settle()
        ):
            self.sync_tabs()
            return
        if i == 7:
            if self.busy:
                self.info("任务执行中，稍后再修改设置。")
                self.sync_tabs()
                return
            self.ensure_settings_panel()
        self._navigating = True
        self.pages.setCurrentIndex(i)
        idx = self.tab_pages.index(i)
        self.work_tabs.setTabVisible(idx, True)
        self.work_tabs.setCurrentIndex(idx)
        self._navigating = False
        if i == 0:
            self.render_modules()
        elif i == 2:
            self.refresh_assets()
        elif i == 3:
            self.refresh_image_assets()
            self.refresh_candidates()
        elif i == 4:
            self.refresh_jobs()
        elif i == 5:
            self.refresh_files()
        elif i == 6:
            self.refresh_results()
        self.update_location()
        self.place_launcher()

    def reload_accounts(self):
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        if self.account:
            for a in self.store.accounts:
                self.account_combo.addItem(a["name"], a["id"])
            self.account_combo.setCurrentIndex(
                self.account_combo.findData(self.account["id"])
            )
        self.account_combo.blockSignals(False)

    def switch_account(self, index):
        if index < 0:
            return
        if not self.guard():
            self.reload_accounts()
            return
        aid = self.account_combo.itemData(index)
        if aid:
            self.activate_account(aid)

    def manage_accounts(self):
        if not self.ensure_account() or not self.guard():
            return
        action, ok = QInputDialog.getItem(
            self,
            "账户管理",
            "操作",
            [
                "选择 / 创建账户",
                "修改当前名称",
                "退出到访客",
                "删除当前账户（资料归档）",
            ],
            0,
            False,
        )
        if not ok:
            return
        if action == "选择 / 创建账户":
            self.choose_account()
        elif action == "退出到访客":
            self.logout()
        elif action == "修改当前名称":
            name, ok = QInputDialog.getText(
                self, "账户名称", "名称", text=self.account["name"]
            )
            if ok:
                try:
                    self.store.rename_account(self.account, name)
                    self.user_label.setText(name)
                    self.reload_accounts()
                except Exception as e:
                    self.error(e)
        elif (
            QMessageBox.question(
                self, "删除账户", "归档资料并清除各配置凭据，是否继续？"
            )
            == QMessageBox.Yes
        ):
            from .connections import credential_id

            try:
                for c in self.store.connections(self.account):
                    slot = credential_id(self.account["id"], c["id"])
                    if get_key(slot):
                        set_key(slot, "")
                    self.session_keys.pop(slot, None)
                if get_key(self.account["id"]):
                    set_key(self.account["id"], "")
                self.session_keys.pop(self.account["id"], None)
                old = self.account
                self.logout()
                self.store.delete_account(old)
            except Exception as e:
                self.error(e)

    def open_settings(self):
        if not self.guard() or not self.ensure_account():
            return
        self.save_draft(silent=True)
        self.navigate(7)

    def reload_projects(self, select=None):
        self.projects_combo.blockSignals(True)
        self.projects_combo.clear()
        if self.account:
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
        if (
            self.settings_page
            and self.pages.currentIndex() == 7
            and not self.settings_page.settle()
        ):
            self.projects_combo.blockSignals(True)
            if self.project:
                self.projects_combo.setCurrentIndex(
                    self.projects_combo.findData(str(self.project.path))
                )
            self.projects_combo.blockSignals(False)
            return
        self.save_draft(silent=True)
        self.reset_settings_panel()
        if self.project:
            self.project.close()
        self.project = None
        self.sid = None
        self.scene_id = None
        self.data = None
        self.clear_attachments()
        self.image_list.clear()
        self.image.setText("尚无候选插图")
        self.comfy_prompt.clear()
        if self.account and i >= 0 and self.projects_combo.itemData(i):
            try:
                self.project = Project(self.projects_combo.itemData(i))
                self.project.secrets = self.known_secrets()
            except Exception as e:
                self.error(e)
        self.reload_segments()
        self.reload_image_connections()
        self.load_image_runtime()
        self.refresh_assets()
        self.refresh_jobs()
        self.refresh_files()
        self.refresh_results()
        self.refresh_progress()
        self.update_location()
        self.refresh_candidates()

    def new_project(self):
        if not self.guard() or not self.ensure_account():
            return
        name, ok = QInputDialog.getText(self, "新建小说项目", "项目名称")
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
        if not self.busy:
            self.save_image_prompt()
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
        self.refresh_candidates()
        self.load_image_prompt()
        self.refresh_progress()
        self.update_location()

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

    def select_node(self, n, go_page=True):
        if n is None or not self.guard():
            return
        self.save_draft(silent=True)
        self.node = n
        self.clear_attachments()
        self.task_combo.blockSignals(True)
        self.task_combo.setCurrentIndex(self.task_combo.findData(n))
        self.task_combo.blockSignals(False)
        self.show_node()
        if go_page:
            self.navigate(3 if n == 4 else 2 if n == 1 else 0)

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
        if self.param_form:
            self.param_form.hide()
            self.param_form.deleteLater()
        self.param_form = (
            NodeForm(self, self.node, self.node_parameters(self.node, self.data))
            if self.account
            else None
        )
        if self.param_form:
            self.param_form.setParent(self.runtime_config)
            self.param_form.hide()
        self.model_badge.setText(
            self.param_form.connection_summary.text()
            if self.param_form
            else "选择本地账户后加载语言模型配置"
        )
        self.render_chat()
        self.update_cards()
        self.render_modules()
        self.set_busy()
        self.structured_btn.setVisible(self.node in (0, 1))
        self.update_location()

    def final_changed(self):
        if self.data:
            self.data["final"] = self.final.toPlainText()
            if self.data["status"] == "已确认":
                self.data["status"] = "待确认"
            self.update_cards()

    def update_cards(self):
        if self.data and self.data["status"] == "需复核":
            self.node_title.setText(NODES[self.node] + " · 上游变更，需复核")

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
        self.generate_btn.setEnabled(bool(self.project) and not self.busy)
        self.task_combo.setEnabled(not self.busy)
        self.final.setReadOnly(self.busy)
        self.retry_btn.setEnabled(bool(self.data) and not self.busy)
        self.image_connections.setEnabled(not self.busy)
        if self.settings_page:
            self.settings_page.setEnabled(not self.busy)

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
        self.refresh_progress()
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
            self.asset_grid.addWidget(
                label("选择账户和小说项目后管理共享资产。", "muted"), 0, 0
            )
            return
        kind = self.asset_categories.tabText(self.asset_categories.currentIndex())
        rows = [a for a in self.project.assets() if kind == "全部" or a["kind"] == kind]
        cols = 3 if self.pages.width() > 1000 else 2 if self.pages.width() > 620 else 1
        for i, a in enumerate(rows):
            self.asset_grid.addWidget(self.asset_card(a), i // cols, i % cols)
        if not rows:
            self.asset_grid.addWidget(
                label(
                    "此分类暂无资产。可手工创建，或解析当前情节后审核入库。", "muted"
                ),
                0,
                0,
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
                raise ValueError("请先编辑或载入本场景的最终提示词")
            rules = self.image_defaults_cache.get("generation_rules", "").strip()
            if rules:
                prompt += "\n\n" + rules
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
        if not path or not self.project or not self.scene_id:
            return
        try:
            source = Path(path)
            dest = (
                self.project.path
                / "06_最终成果"
                / (source.stem + "_" + uid() + source.suffix)
            )
            shutil.copy2(source, dest)
            job = next(
                (
                    j["id"]
                    for j in self.project.jobs()
                    if any(
                        str(self.project.path / p) == str(source)
                        for p in j.get("results", [])
                    )
                ),
                "",
            )
            self.project.register_result(self.scene_id, dest, job)
            self.refresh_results()
            self.refresh_progress()
            self.status.setText("已选为正式插图：" + dest.name)
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
        if not self.guard() or not self.ensure_account():
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
        QFrame#topbar QPushButton {{padding:2px 9px;min-height:20px;}}
        QLabel#assetThumb {{background:{inputbg};border:1px dashed {border};border-radius:8px;color:{muted};}}
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
        if hasattr(self, "assistant"):
            self.assistant.setStyleSheet(self.styleSheet())

    def closeEvent(self, event):
        if self.busy:
            self.info(
                "任务仍在运行，输入已保存。请先停止等待，等待本次请求返回或超时。"
            )
            event.ignore()
            return
        if self.settings_page and not self.settings_page.settle():
            event.ignore()
            return
        self.save_draft(silent=True)
        self.save_image_prompt()
        self.assistant.hide()
        self._closing = True
        if self.project:
            self.project.close()
        event.accept()

    def toggle_sidebar(self):
        self.settings["sidebar_visible"] = not self.settings["sidebar_visible"]
        self.apply_sidebar()
        if self.account:
            self.store.save_settings(self.account, self.settings)

    def scope(self):
        return self.sid if self.node in (0, 7) else (self.scene_id or self.sid)

    def connection_key(self, cid):
        if not self.account:
            return ""
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
        if not self.account:
            return []
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
        if not self.busy:
            self.save_image_prompt()
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
        self.refresh_candidates()
        self.load_image_prompt()
        self.refresh_progress()
        self.update_location()

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
        if not self.project or not self.sid:
            self.module_grid.addWidget(
                label(
                    "直接进入工作区。\n\n从系统侧栏选择本地账户，再新建小说项目或导入原文。",
                    "section",
                ),
                0,
                0,
            )
            return
        scenes = self.project.scenes(self.sid)
        cols = 2 if self.pages.width() > 850 else 1
        for i, s in enumerate(scenes):
            card = QFrame()
            card.setObjectName("panel")
            l = QVBoxLayout(card)
            l.setContentsMargins(18, 16, 18, 16)
            l.setSizeConstraint(QLayout.SetMinimumSize)
            l.addWidget(label(f"{i + 1:02d}  {s['title']}", "section"))
            l.addWidget(
                label(
                    f"原文段落 {s['start_paragraph']}—{s['end_paragraph']} · v{s['revision']}",
                    "muted",
                )
            )
            l.addWidget(label(s.get("summary", "")[:140] or "尚未填写摘要"))
            quote = label(
                s["source_text"][:90] + ("…" if len(s["source_text"]) > 90 else ""),
                "muted",
            )
            l.addWidget(quote)
            row = QHBoxLayout()
            row.addWidget(button("编辑", lambda checked=False, x=s: self.edit_scene(x)))
            row.addWidget(
                button("拆分", lambda checked=False, x=s: self.split_scene(x))
            )
            row.addWidget(
                button("合并", lambda checked=False, x=s: self.merge_scene(x))
            )
            l.addLayout(row)
            row = QHBoxLayout()
            row.addWidget(
                button(
                    "解析资产", lambda checked=False, x=s["id"]: self.discuss_node(1, x)
                )
            )
            row.addWidget(
                button(
                    "制作此场景",
                    lambda checked=False, x=s["id"]: self.open_scene(x),
                    True,
                )
            )
            l.addLayout(row)
            self.module_grid.addWidget(card, i // cols, i % cols)
        self.scope_note.setText(
            f"当前片段：{self.segments_combo.currentText()} · {len(scenes)} 个情节模块"
        )

    def asset_card(self, a, requirement=None, compact=False):
        card = QFrame()
        card.setObjectName("panel")
        l = QVBoxLayout(card)
        l.setContentsMargins(14, 14, 14, 14)
        l.setSizeConstraint(QLayout.SetMinimumSize)
        if not compact:
            thumbnail = QLabel()
            thumbnail.setAlignment(Qt.AlignCenter)
            thumbnail.setObjectName("assetThumb")
            thumbnail.setFixedHeight(145)
            thumbnail.setMinimumWidth(120)
            thumbnail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            pix = (
                QPixmap(str(self.project.path / a["image"]))
                if a and a.get("image")
                else QPixmap()
            )
            if pix.isNull():
                thumbnail.setText("待添加参考图" if a else "缺少资产档案")
            else:
                thumbnail.setPixmap(
                    pix.scaled(245, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
            l.addWidget(thumbnail)
        title = a["name"] if a else requirement["name"]
        kind = a["kind"] if a else requirement["kind"]
        l.addWidget(label(title + " / " + kind, "section"))
        if a:
            l.addWidget(label(a["source"] + " · " + a["review"], "muted"))
            l.addWidget(
                label(
                    a["description"][:65] if not compact else "引用当前档案版本",
                    "muted",
                )
            )
        if requirement and requirement.get("problem"):
            l.addWidget(label("⚑ " + requirement["problem"]))
        if a:
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
        self.navigate(3)
        self.load_image_prompt()

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
        if not self.require_project() or self.busy or not self.sid:
            return
        self.select_node(0, go_page=False)
        self.show_assistant()
        self.message.setPlainText(
            "请按"
            + self.depth.currentText()
            + "拆分当前片段，完整覆盖原文，输出待审核 scenes JSON。"
        )
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

    def reload_image_connections(self, selected=None):
        selected = selected or (
            self.image_parameters().get("connection_id", "image-default")
            if self.account
            else ""
        )
        self.image_connections.blockSignals(True)
        self.image_connections.clear()
        if self.account:
            for c in self.store.connections(self.account):
                if c["kind"] in ("comfy", "image_api"):
                    self.image_connections.addItem(c["name"], c["id"])
        self.image_connections.setCurrentIndex(
            self.image_connections.findData(selected)
        )
        self.image_connections.blockSignals(False)
        self.refresh_model_summary()

    def image_connection_changed(self, *_):
        self.refresh_model_summary()

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
        self.clear_grid(self.image_asset_grid)
        scene = (
            self.project.scene(self.scene_id)
            if self.project and self.scene_id
            else None
        )
        self.image_scope_label.setText(
            "当前场景：" + scene["title"] if scene else "请先在“原文与情节”选择情节"
        )
        self.image_scene_picker.blockSignals(True)
        self.image_scene_picker.clear()
        if self.project and self.sid:
            for s in self.project.scenes(self.sid):
                self.image_scene_picker.addItem(s["title"], s["id"])
            self.image_scene_picker.setCurrentIndex(
                self.image_scene_picker.findData(self.scene_id)
            )
        self.image_scene_picker.blockSignals(False)
        rows = self.project.scene_assets(self.scene_id) if scene else []
        cols = 3 if self.pages.width() > 850 else 2
        for i, r in enumerate(rows):
            self.image_asset_grid.addWidget(
                self.asset_card(r["asset"], r, compact=True), i // cols, i % cols
            )
        if not rows:
            self.image_asset_grid.addWidget(
                label("尚未建立资产关联；生成前会提示缺失项。", "muted"), 0, 0
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

    def place_launcher(self):
        self.ai_launcher.move(
            max(5, self.bg.width() - 157), max(36, self.bg.height() - 65)
        )
        self.ai_launcher.raise_()

    def reflow_cards(self):
        if not hasattr(self, "pages"):
            return
        columns = (
            2 if self.pages.width() > 850 else 1,
            3 if self.pages.width() > 1000 else 2 if self.pages.width() > 620 else 1,
        )
        if columns != self._card_columns:
            self._card_columns = columns
            self.render_modules()
            self.refresh_assets()

    def assistant_offset(self):
        return QPoint(-self.assistant.width() - 22, 125)

    def build_assistant(self):
        self.assistant = FloatingAssistant(self)
        l = QVBoxLayout(self.assistant)
        l.setContentsMargins(14, 12, 14, 12)
        self.assistant_context = label("尚未选择对象", "section")
        l.addWidget(self.assistant_context)
        row = QHBoxLayout()
        self.task_combo = QComboBox()
        for n in (0, 1, 5, 2, 3, 4, 6, 7):
            self.task_combo.addItem(NODES[n], n)
        self.task_combo.currentIndexChanged.connect(
            lambda _: self.select_node(self.task_combo.currentData(), go_page=False)
        )
        row.addWidget(self.task_combo, 1)
        row.addWidget(button("收起", self.assistant.hide))
        l.addLayout(row)
        self.node_title = label("", "muted")
        l.addWidget(self.node_title)
        self.tabs = QTabWidget()
        l.addWidget(self.tabs, 1)
        chat = QWidget()
        c = QVBoxLayout(chat)
        c.setContentsMargins(0, 8, 0, 0)
        self.conversation = QTextEdit()
        self.conversation.setReadOnly(True)
        c.addWidget(self.conversation, 1)
        self.message = DropEdit()
        self.message.setMinimumHeight(70)
        self.message.setMaximumHeight(115)
        self.message.setPlaceholderText("补充要求，可拖入文档或参考图作为附件。")
        self.message.filesDropped.connect(self.drop_chat_files)
        c.addWidget(self.message)
        self.attachment_label = label("未附加文件", "muted")
        c.addWidget(self.attachment_label)
        row = QHBoxLayout()
        row.addWidget(button("＋ 附件", self.add_attachments))
        row.addWidget(button("清除", self.clear_attachments))
        row.addStretch()
        self.retry_btn = button("重试失败", self.retry_text)
        row.addWidget(self.retry_btn)
        self.send = button("发送", self.send_message, True)
        row.addWidget(self.send)
        c.addLayout(row)
        self.tabs.addTab(chat, "多轮讨论")
        final_page = QWidget()
        f = QVBoxLayout(final_page)
        self.final = DropEdit()
        self.final.setPlaceholderText(
            "可直接手工输入最终方案；确认采用后才供后续阶段使用。"
        )
        self.final.textChanged.connect(self.final_changed)
        self.final.filesDropped.connect(self.drop_final_files)
        f.addWidget(self.final, 1)
        row = QHBoxLayout()
        row.addWidget(button("采用最近输出", self.use_last))
        row.addWidget(button("保存草稿", self.save_draft))
        self.confirm_btn = button("确认采用", self.confirm_final, True)
        row.addWidget(self.confirm_btn)
        f.addLayout(row)
        self.structured_btn = button(
            "校验并预览入库候选", self.preview_structured, True
        )
        f.addWidget(self.structured_btn)
        self.tabs.addTab(final_page, "方案与入库")
        context = QWidget()
        co = QVBoxLayout(context)
        self.include_text = QCheckBox("附带当前原文 / 情节范围")
        self.include_text.setChecked(True)
        self.include_assets = QCheckBox("附带本情节关联资产")
        self.include_assets.setChecked(True)
        self.include_refs = QCheckBox("附带关联参考图（需视觉模型）")
        co.addWidget(self.include_text)
        co.addWidget(self.include_assets)
        co.addWidget(self.include_refs)
        co.addWidget(button("预览实际输入", self.preview_input))
        co.addWidget(button("导出 TXT / MD", self.export_text))
        co.addStretch()
        self.tabs.addTab(context, "输入与导出")
        self.model_badge = label("语言模型配置在设置中维护", "muted")
        l.addWidget(self.model_badge)
        self.stop = button("停止等待（远端仍可能计费）", self.cancel_task)
        l.addWidget(self.stop)

    def build_results(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(0, 0, 0, 54)
        row = QHBoxLayout()
        row.addWidget(label("成果集", "hero"), 1)
        row.addWidget(button("打开成果目录", self.open_results_folder))
        row.addWidget(button("备份整个项目", self.backup))
        l.addLayout(row)
        l.addWidget(label("选定插图按原文情节回链；点击缩略图查看原文件。", "muted"))
        self.result_cards = QWidget()
        self.result_grid = QGridLayout(self.result_cards)
        self.result_grid.setAlignment(Qt.AlignTop)
        self.result_grid.setSizeConstraint(QLayout.SetMinimumSize)
        l.addWidget(scroll(self.result_cards), 1)
        self.pages.addWidget(page)

    def sync_tabs(self):
        self._navigating = True
        self.work_tabs.setCurrentIndex(self.tab_pages.index(self.pages.currentIndex()))
        self._navigating = False

    def toggle_theme(self):
        dark = (
            self.settings["theme"] == "dark"
            or self.settings["theme"] == "system"
            and QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        )
        self.settings["theme"] = "light" if dark else "dark"
        if self.account:
            self.store.save_settings(self.account, self.settings)
        self.apply_theme()

    def apply_sidebar(self):
        expanded = self.settings["sidebar_visible"]
        self.side.setFixedWidth(174 if expanded else 48)
        self.side.show()
        self.brand.setVisible(expanded)
        self.projects_combo.setVisible(expanded)
        self.progress_label.setVisible(expanded)
        self.account_manage_button.setVisible(expanded)
        for b, symbol, title in self.system_buttons:
            b.setText(symbol + "  " + title if expanded else symbol)
        self.reflow_cards()

    def ensure_account(self):
        if self.account:
            return True
        return self.choose_account()

    def choose_account(self):
        if not self.guard():
            return False
        if (
            self.settings_page
            and self.pages.currentIndex() == 7
            and not self.settings_page.settle()
        ):
            return False
        d = AccountDialog(self)
        if not d.exec():
            return False
        self.activate_account(d.account_id, d.selected_store)
        return True

    def activate_account(self, account_id, store=None):
        if self.busy:
            return False
        candidate = store or self.store
        account = next((a for a in candidate.accounts if a["id"] == account_id), None)
        if not account:
            raise ValueError("账户不存在")
        self.save_draft(silent=True)
        self.assistant.hide()
        self.reset_settings_panel()
        if self.project:
            self.project.close()
        self.project = None
        self.sid = None
        self.scene_id = None
        self.data = None
        self.store = candidate
        self.account = account
        self.settings = self.store.settings(account)
        self.image_defaults_cache = self.store.image_defaults(account)
        self.user_label.setText(account["name"])
        QSettings().setValue("data_root", str(candidate.root))
        self.reload_accounts()
        self.reload_projects()
        self.apply_theme()
        self.apply_sidebar()
        self.navigate(0)
        self.status.setText("已登录 · " + account["name"])
        return True

    def logout(self):
        if not self.guard():
            return
        if self.settings_page and not self.settings_page.settle():
            return
        self.save_draft(silent=True)
        self.assistant.hide()
        self.reset_settings_panel()
        if self.project:
            self.project.close()
        self.project = None
        self.sid = None
        self.scene_id = None
        self.data = None
        self.account = None
        self.session_keys.clear()
        self.settings = copy.deepcopy(DEFAULTS)
        self.user_label.setText("访客 · 未登录")
        self.reload_accounts()
        self.reload_projects()
        self.apply_theme()
        self.apply_sidebar()
        self.navigate(0)

    def project_dialog(self):
        if not self.guard() or not self.ensure_account():
            return
        d = QDialog(self)
        d.setWindowTitle("项目与制作进度")
        d.resize(640, 480)
        l = QVBoxLayout(d)
        projects = QListWidget()
        l.addWidget(projects, 1)
        for index in range(self.projects_combo.count()):
            path = self.projects_combo.itemData(index)
            if not path:
                continue
            p = Project(path)
            progress = p.progress()
            p.close()
            item = QListWidgetItem(
                f"{self.projects_combo.itemText(index)}\n情节 {progress['scenes']} · 已确认资产 {progress['confirmed_assets']}/{progress['assets']} · 已选插图 {progress['results']}"
            )
            item.setData(Qt.UserRole, index)
            projects.addItem(item)
        row = QHBoxLayout()
        row.addWidget(button("新建项目", lambda: (d.reject(), self.new_project())))
        row.addWidget(
            button("导入项目备份", lambda: (d.reject(), self.restore_backup()))
        )
        row.addWidget(button("备份当前项目", lambda: (d.reject(), self.backup())))
        row.addWidget(button("打开所选项目", d.accept, True))
        l.addLayout(row)
        if d.exec() and projects.currentItem():
            self.projects_combo.setCurrentIndex(
                projects.currentItem().data(Qt.UserRole)
            )

    def refresh_progress(self):
        if self.project:
            p = self.project.progress()
            self.progress_label.setText(
                f"原文片段 {p['segments']}\n情节模块 {p['scenes']}\n已确认资产 {p['confirmed_assets']}/{p['assets']}\n已选定插图 {p['results']}"
            )
        else:
            self.progress_label.setText(
                "未打开项目" if self.account else "访客浏览\n操作前选择本地账户"
            )

    def update_location(self):
        if not self.account:
            self.location_label.setText(
                "访客工作区 · 从左侧选择或创建本地账户后继续操作"
            )
        elif not self.project:
            self.location_label.setText(
                self.account["name"] + " · 请从“项目与进度”新建或打开小说"
            )
        else:
            self.location_label.setText(
                self.project.meta["name"]
                + " / "
                + (self.scene_combo.currentText() or "未选择情节")
            )
        if hasattr(self, "assistant_context"):
            self.assistant_context.setText(
                (self.project.meta["name"] + " / " if self.project else "")
                + (
                    self.segments_combo.currentText()
                    if self.node in (0, 7)
                    else self.scene_combo.currentText() or "尚未选择情节"
                )
            )

    def show_assistant(self):
        if not self.ensure_account():
            return
        if not self.project:
            self.info("请先新建或打开小说项目。")
            return
        if not self.assistant.isVisible():
            self.assistant.restore_position()
        self.assistant.show()
        self.assistant.raise_()
        self.assistant.activateWindow()

    def persist_assistant_geometry(self):
        if self.account and hasattr(self, "assistant"):
            self.settings["assistant_geometry"] = bytes(
                self.assistant.saveGeometry().toBase64()
            ).decode()
            self.store.save_settings(self.account, self.settings)

    def discuss_node(self, node, scene_id=None):
        if not self.require_project():
            return
        if scene_id:
            self.scene_combo.setCurrentIndex(self.scene_combo.findData(scene_id))
        self.select_node(node, go_page=False)
        self.show_assistant()

    def node_parameters(self, node, data=None):
        if not self.account:
            return {}
        p = copy.deepcopy((data or {}).get("params", {}))
        if not data and self.project and self.sid:
            scope = self.sid if node in (0, 7) else self.scene_id or self.sid
            p = copy.deepcopy(self.project.load_node(scope, node).get("params", {}))
        defaults = self.store.node_defaults(self.account).get(str(node))
        if defaults is not None:
            p.update(copy.deepcopy(defaults))
        else:
            binding = (
                self.project.config.get("connections", {}).get(str(node))
                if self.project
                else None
            )
            if binding is not None:
                p["connection_id"] = binding
            else:
                p.setdefault("connection_id", f"node-{node}")
            if (
                p.get("provider") == "openai"
                and not (data or {}).get("params", {}).get("connection_id")
                and self.project
                and binding is None
            ):
                cid = "migrated-" + self.project.meta["id"] + "-" + str(node)
                if not any(
                    c["id"] == cid for c in self.store.connections(self.account)
                ):
                    self.store.save_connection(
                        self.account,
                        dict(
                            id=cid,
                            name="迁移的语言模型配置 · " + NODES[node],
                            kind="openai",
                            endpoint=p["endpoint"],
                            model=p.get("model", ""),
                            vision=p.get("vision", False),
                            legacy=True,
                        ),
                    )
                p["connection_id"] = cid
        return p

    def refresh_runtime_parameters(self):
        if self.account and not self.busy:
            self.save_draft(silent=True)
            self.show_node()
            self.refresh_model_summary()

    def ensure_settings_panel(self):
        if self.settings_page:
            return
        placeholder = self.pages.widget(7)
        self.pages.removeWidget(placeholder)
        placeholder.deleteLater()
        self.settings_page = SettingsPanel(self)
        self.pages.insertWidget(7, self.settings_page)

    def reset_settings_panel(self):
        if not self.settings_page:
            return
        for w in (
            self.image_connections,
            self.workflow,
            self.mapping,
            self.seed,
            self.image_size,
        ):
            w.setParent(self.runtime_config)
            w.hide()
        old = self.settings_page
        self.pages.removeWidget(old)
        old.hide()
        old.deleteLater()
        self.pages.insertWidget(7, QWidget())
        self.settings_page = None

    def preview_config_form(self, form):
        try:
            p = form.value()
            d = QDialog(self)
            d.setWindowTitle(NODES[form.node] + " · 提示词预览")
            d.resize(800, 600)
            l = QVBoxLayout(d)
            edit = QPlainTextEdit(redact(p["system"], self.known_secrets()))
            edit.setReadOnly(True)
            l.addWidget(edit)
            l.addWidget(button("关闭", d.accept))
            d.exec()
        except Exception as e:
            self.error(e)

    def image_parameters(self):
        if not self.account:
            return {}
        data = self.store.image_defaults(self.account)
        if data:
            return data
        latest = (
            next((j for j in self.project.jobs() if j["kind"] == "ComfyUI 图片"), None)
            if self.project
            else None
        )
        return dict(
            connection_id=self.project.config.get("image_connection", "image-default")
            if self.project
            else "image-default",
            workflow=json.dumps(
                latest.get("workflow", {}), ensure_ascii=False, indent=2
            )
            if latest
            else "",
            mapping=json.dumps(
                latest.get("mapping", {"prompt": ["6", "text"]}),
                ensure_ascii=False,
                indent=2,
            )
            if latest
            else '{\n  "prompt": ["6", "text"]\n}',
            seed=latest.get("values", {}).get("seed", 42) if latest else 42,
            size="1024x1024",
            generation_rules="",
        )

    def load_image_runtime(self):
        data = self.image_parameters()
        self.image_defaults_cache = copy.deepcopy(data)
        self._runtime_loading = True
        self.image_connections.setCurrentIndex(
            self.image_connections.findData(data.get("connection_id", "image-default"))
        )
        self.workflow.setPlainText(data.get("workflow", ""))
        self.mapping.setPlainText(
            data.get("mapping", '{\n  "prompt": ["6", "text"]\n}')
        )
        self.seed.setValue(data.get("seed", 42))
        self.image_size.setCurrentText(data.get("size", "1024x1024"))
        self._runtime_loading = False
        self.refresh_model_summary()

    def refresh_model_summary(self):
        profile = (
            next(
                (
                    c
                    for c in self.store.connections(self.account)
                    if c["id"] == self.image_connections.currentData()
                ),
                None,
            )
            if self.account
            else None
        )
        self.image_model_label.setText(
            "图片模型配置："
            + (
                profile["name"] + " · " + KINDS[profile["kind"]]
                if profile
                else "尚未配置；请在系统设置中选择"
            )
        )

    def pick_image_scene(self, index):
        sid = self.image_scene_picker.itemData(index)
        if sid and sid != self.scene_id:
            self.scene_combo.setCurrentIndex(self.scene_combo.findData(sid))

    def refresh_candidates(self):
        previous = self.image_list.currentData()
        self.image_list.blockSignals(True)
        self.image_list.clear()
        if self.project and self.scene_id:
            for j in reversed(self.project.jobs()):
                if j.get("scene") == self.scene_id:
                    for p in j.get("results", []):
                        path = self.project.path / p
                        if path.exists():
                            self.image_list.addItem(
                                f"{path.name} · {j['created']}", str(path)
                            )
        index = self.image_list.findData(previous)
        self.image_list.setCurrentIndex(
            index if index >= 0 else self.image_list.count() - 1
        )
        self.image_list.blockSignals(False)
        if self.image_list.count():
            self.show_image(self.image_list.currentIndex())
        else:
            self.image.setText(
                "尚无本场景的候选插图\n\n先讨论方案、确认提示词，再生成。"
            )

    def edit_generation_prompt(self):
        if not self.require_project():
            return
        d = QDialog(self)
        d.setWindowTitle("本场景最终提示词（模型配置在设置中）")
        d.resize(760, 500)
        l = QVBoxLayout(d)
        edit = DropEdit(self.comfy_prompt.toPlainText())
        edit.filesDropped.connect(lambda paths: self.append_text_files(paths, edit))
        l.addWidget(edit)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        l.addWidget(bb)
        if d.exec():
            self.comfy_prompt.setPlainText(edit.toPlainText())
            self.save_image_prompt()

    def save_image_prompt(self):
        if self.project and self.scene_id:
            self.project.config.setdefault("image_prompt_drafts", {})[self.scene_id] = (
                self.comfy_prompt.toPlainText()
            )
            self.project.save_config()

    def load_image_prompt(self):
        text = (
            self.project.config.get("image_prompt_drafts", {}).get(self.scene_id, "")
            if self.project and self.scene_id
            else ""
        )
        if not text and self.project and self.scene_id:
            d = self.project.load_node(self.scene_id, 3)
            if d["status"] == "已确认":
                text = d["final"]
        self.comfy_prompt.setPlainText(text)

    def split_scene(self, scene):
        if not self.guard():
            return
        a, b = scene["start_paragraph"], scene["end_paragraph"]
        if a == b:
            self.info("当前情节只有一个原文段落；请先调整原文段落或手工修改范围。")
            return
        boundary, ok = QInputDialog.getInt(
            self, "拆分情节", "上半部分结束于段落", a, a, b - 1
        )
        if not ok:
            return
        req = self.project.requirements(scene["id"])
        rows = [
            dict(
                title=scene["title"] + " · 上",
                summary=scene.get("summary", ""),
                start_paragraph=a,
                end_paragraph=boundary,
                required_assets=req,
            ),
            dict(
                title=scene["title"] + " · 下",
                summary="",
                start_paragraph=boundary + 1,
                end_paragraph=b,
                required_assets=req,
            ),
        ]
        self.save_draft(silent=True)
        new = self.project.replace_scene_partition([scene["id"]], rows)
        self.data = None
        self.reload_scenes(new[0]["id"])
        self.show_node()
        self.refresh_image_assets()
        self.refresh_progress()

    def merge_scene(self, scene):
        if not self.guard():
            return
        others = [
            s
            for s in self.project.scenes(self.sid)
            if s["id"] != scene["id"]
            and (
                s["end_paragraph"] + 1 == scene["start_paragraph"]
                or scene["end_paragraph"] + 1 == s["start_paragraph"]
            )
        ]
        if not others:
            self.info("没有可以合并的相邻情节。")
            return
        name, ok = QInputDialog.getItem(
            self,
            "合并相邻情节",
            "选择另一个情节",
            [s["title"] + " · " + s["id"] for s in others],
            0,
            False,
        )
        if not ok:
            return
        other = next(s for s in others if name.endswith(s["id"]))
        requirements = []
        seen = set()
        for sid in (scene["id"], other["id"]):
            for r in self.project.requirements(sid):
                key = (r["kind"], r["name"], r.get("asset_id"))
                if key not in seen:
                    seen.add(key)
                    requirements.append({k: v for k, v in r.items() if k != "slot"})
        rows = [
            dict(
                title=scene["title"] + " / " + other["title"],
                summary="\n".join(
                    s.get("summary", "")
                    for s in sorted([scene, other], key=lambda s: s["start_paragraph"])
                ),
                start_paragraph=min(scene["start_paragraph"], other["start_paragraph"]),
                end_paragraph=max(scene["end_paragraph"], other["end_paragraph"]),
                required_assets=requirements,
            )
        ]
        self.save_draft(silent=True)
        new = self.project.replace_scene_partition([scene["id"], other["id"]], rows)
        self.data = None
        self.reload_scenes(new[0]["id"])
        self.show_node()
        self.refresh_image_assets()
        self.refresh_progress()

    def refresh_results(self):
        if not hasattr(self, "result_grid"):
            return
        self.clear_grid(self.result_grid)
        if not self.project:
            return
        rows = self.project.final_results()
        cols = 3 if self.pages.width() > 1000 else 2
        for i, r in enumerate(rows):
            card = QFrame()
            card.setObjectName("panel")
            l = QVBoxLayout(card)
            l.setSizeConstraint(QLayout.SetMinimumSize)
            pix = QPixmap(str(self.project.path / r["file"]))
            thumb = QLabel()
            thumb.setAlignment(Qt.AlignCenter)
            thumb.setFixedHeight(150)
            thumb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            if not pix.isNull():
                thumb.setPixmap(
                    pix.scaled(250, 145, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
            else:
                thumb.setText("成果图片缺失")
            l.addWidget(thumb)
            l.addWidget(label(r["title"], "section"))
            l.addWidget(label("选定时间 " + r["selected"], "muted"))
            l.addWidget(
                button(
                    "查看原图",
                    lambda checked=False, path=self.project.path / r["file"]: reveal(
                        path
                    ),
                )
            )
            self.result_grid.addWidget(card, i // cols, i % cols)
        if not rows:
            self.result_grid.addWidget(
                label("尚未选定正式插图。候选图确认后会显示在这里。", "muted"), 0, 0
            )

    def open_results_folder(self):
        if self.require_project():
            reveal(self.project.path / "06_最终成果")

    def reveal_path(self, path):
        reveal(path)


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
        if args.choose_root:
            root = QFileDialog.getExistingDirectory(None, "选择数据根目录")
            if not root:
                return
        else:
            root = str(Path.cwd() / "user-data")
    if args.demo:
        seed_demo(Store(root))
    w = Window(root)
    w.show()
    if args.screenshot:
        QTimer.singleShot(1000, lambda: (w.grab().save(args.screenshot), app.quit()))
    sys.exit(app.exec())
