from __future__ import annotations
import argparse
import copy
import html
import json
import os
import shutil
import sys
import threading
import zipfile
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QThread, Signal, QUrl, QTimer
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
 QComboBox,QFileDialog,QMessageBox,QInputDialog,QDialog,QFormLayout,QLineEdit,QTextEdit,QPlainTextEdit,
 QSpinBox,QDoubleSpinBox,QCheckBox,QTabWidget,QDialogButtonBox,QScrollArea,QSplitter,QListWidget,
 QStackedWidget,QFrame,QTreeWidget,QTreeWidgetItem,QHeaderView,QAbstractItemView)
from .storage import Store,Project,DEFAULTS,NODES,read_document,uid,now,write_json
from .providers import text_call,bind_workflow,comfy_call,UnknownOutcome,endpoint
from .credentials import get_key,set_key

def button(text,fn,primary=False):
    b=QPushButton(text); b.setCursor(Qt.PointingHandCursor); b.clicked.connect(fn)
    if primary: b.setProperty('primary',True)
    return b

def label(text,kind=''):
    x=QLabel(text); x.setWordWrap(True)
    if kind: x.setObjectName(kind)
    return x

def scroll(widget):
    s=QScrollArea(); s.setWidgetResizable(True); s.setFrameShape(QFrame.NoFrame); s.setWidget(widget); return s

def reveal(path): QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))

class Worker(QThread):
    done=Signal(object); failed=Signal(str,bool); progress=Signal(object)
    def __init__(self,fn): super().__init__(); self.fn=fn; self.cancel=threading.Event()
    def run(self):
        try: self.done.emit(self.fn(self.cancel,self.progress.emit))
        except Exception as e:
            # Show controlled provider errors; avoid arbitrary raw response contents.
            from .providers import ProviderError
            self.failed.emit(str(e) if isinstance(e,ProviderError) else f'本地执行失败（{type(e).__name__}），输入已保留。',isinstance(e,UnknownOutcome))

class Backdrop(QWidget):
    def __init__(self): super().__init__(); self.pix=QPixmap(); self.opacity=.18
    def paintEvent(self,e):
        super().paintEvent(e)
        if not self.pix.isNull():
            p=QPainter(self); p.setOpacity(self.opacity)
            pix=self.pix.scaled(self.size(),Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation)
            p.drawPixmap((self.width()-pix.width())//2,(self.height()-pix.height())//2,pix)

class ParamForm(QWidget):
    def __init__(self,settings):
        super().__init__(); f=QFormLayout(self)
        self.provider=QComboBox(); self.provider.addItems(['演示模式（不调用模型）','OpenAI 兼容接口（云端 / 本地）'])
        self.provider.setCurrentIndex(0 if settings['provider']=='demo' else 1)
        self.url=QLineEdit(settings['endpoint']); self.model=QLineEdit(settings['model']); self.model.setPlaceholderText('例如：实际服务提供的模型标识')
        self.system=QPlainTextEdit(settings['system']); self.system.setMaximumHeight(125)
        self.tokens=QSpinBox(); self.tokens.setRange(1,131072); self.tokens.setValue(settings['max_tokens'])
        self.temp=QDoubleSpinBox(); self.temp.setRange(0,2); self.temp.setSingleStep(.1); self.temp.setValue(settings['temperature'])
        self.vision=QCheckBox('已验证此模型支持图片输入'); self.vision.setChecked(settings['vision'])
        for title,w in [('接入方式',self.provider),('服务地址 /v1',self.url),('模型标识',self.model),('背景提示词',self.system),('最大输出 token',self.tokens),('温度',self.temp),('图片输入',self.vision)]: f.addRow(title,w)
        f.addRow(label('参数仅用于支持这些字段的兼容接口；请按服务商实际能力设置。','muted'))
    def value(self):
        s=dict(provider='demo' if self.provider.currentIndex()==0 else 'openai',endpoint=self.url.text().strip(),model=self.model.text().strip(),system=self.system.toPlainText(),max_tokens=self.tokens.value(),temperature=self.temp.value(),vision=self.vision.isChecked())
        if s['provider']=='openai': endpoint(s['endpoint'])
        return s

class SettingsDialog(QDialog):
    def __init__(self,win):
        super().__init__(win); self.win=win; self.s=copy.deepcopy(win.settings)
        self.setWindowTitle('账户设置 · '+win.account['name']); self.resize(760,710)
        layout=QVBoxLayout(self); tabs=QTabWidget(); layout.addWidget(tabs)
        self.params=ParamForm(self.s); tabs.addTab(scroll(self.params),'模型默认值')
        general=QWidget(); f=QFormLayout(general)
        self.theme=QComboBox(); self.theme.addItems(['明亮','暗色','跟随系统']); self.theme.setCurrentIndex(['light','dark','system'].index(self.s['theme']))
        self.font=QSpinBox(); self.font.setRange(11,24); self.font.setValue(self.s['font_size'])
        self.bg=QLineEdit(self.s['background']); bgrow=QWidget(); h=QHBoxLayout(bgrow); h.setContentsMargins(0,0,0,0); h.addWidget(self.bg); h.addWidget(button('选图片',self.choose_bg))
        self.opacity=QSpinBox(); self.opacity.setRange(0,60); self.opacity.setSuffix(' %'); self.opacity.setValue(self.s['background_opacity'])
        self.attach=QCheckBox('发送附件前确认文件、目标服务和预计上传大小'); self.attach.setChecked(self.s['confirm_attachments'])
        self.comfy=QLineEdit(self.s['comfy_url'])
        for t,w in [('明暗主题',self.theme),('界面字号',self.font),('背景图片',bgrow),('背景可见度',self.opacity),('附件提示',self.attach),('ComfyUI 地址',self.comfy)]: f.addRow(t,w)
        f.addRow(button('一键恢复默认外观',self.reset_appearance))
        f.addRow('当前数据根目录',label(str(win.store.root),'muted'))
        f.addRow(button('打开账户文件夹',lambda:reveal(win.store.account_dir(win.account))))
        f.addRow(label('数据根目录可在启动时重新选择（命令行 --choose-root）。已有项目不会自动移动。','muted'))
        tabs.addTab(scroll(general),'外观与文件')
        sec=QWidget(); f=QFormLayout(sec)
        self.key=QLineEdit(); self.key.setEchoMode(QLineEdit.Password); self.key.setPlaceholderText('留空保留现有密钥；只在本机使用')
        self.persist=QCheckBox('存入系统安全凭据库'); self.clear_key=QCheckBox('删除当前账户已有密钥')
        f.addRow('API 密钥',self.key); f.addRow(self.persist); f.addRow(self.clear_key)
        f.addRow(label('默认仅本次会话有效。凭据不会进入项目、日志或设置导出。设置导出排除服务地址与背景图片文件，并移除已知凭据。','muted'))
        f.addRow(button('导出账户设置（无凭据）',self.export_settings)); f.addRow(button('导入账户设置',self.import_settings))
        tabs.addTab(sec,'凭据与迁移')
        bb=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); bb.button(QDialogButtonBox.Save).setText('保存'); bb.button(QDialogButtonBox.Cancel).setText('取消'); bb.accepted.connect(self.save); bb.rejected.connect(self.reject); layout.addWidget(bb)
    def choose_bg(self):
        p,_=QFileDialog.getOpenFileName(self,'背景图片','','图片 (*.png *.jpg *.jpeg *.webp)')
        if p: self.bg.setText(p)
    def reset_appearance(self):
        self.theme.setCurrentIndex(0); self.font.setValue(14); self.bg.clear(); self.opacity.setValue(18)
    def export_settings(self):
        p,_=QFileDialog.getSaveFileName(self,'导出已保存的账户设置','账户设置.json','JSON (*.json)')
        if p:
            self.win.store.export_settings(self.win.account,p,[self.win.session_keys.get(self.win.account['id']) or get_key(self.win.account['id'])]); QMessageBox.information(self,'已导出','已排除凭据、地址及背景文件。未保存的修改未导出。')
    def import_settings(self):
        p,_=QFileDialog.getOpenFileName(self,'导入设置','','JSON (*.json)')
        if p:
            try:
                self.win.store.import_settings(self.win.account,p); self.win.settings=self.win.store.settings(self.win.account); self.win.apply_theme(); self.accept()
            except Exception: QMessageBox.warning(self,'导入失败','文件格式不正确，未导入设置。')
    def save(self):
        try:
            self.s.update(self.params.value()); endpoint(self.comfy.text().strip())
            self.s.update(theme=['light','dark','system'][self.theme.currentIndex()],font_size=self.font.value(),background=self.bg.text(),background_opacity=self.opacity.value(),confirm_attachments=self.attach.isChecked(),comfy_url=self.comfy.text().strip())
            if self.s['background']:
                src=Path(self.s['background'])
                if QPixmap(str(src)).isNull(): raise ValueError('无法读取背景图片')
                dest=self.win.store.account_dir(self.win.account)/'界面资源'/('背景'+src.suffix.lower())
                if src.resolve()!=dest.resolve(): shutil.copy2(src,dest)
                self.s['background']=str(dest)
            aid=self.win.account['id']
            if self.clear_key.isChecked(): set_key(aid,''); self.win.session_keys.pop(aid,None)
            if self.key.text():
                if self.persist.isChecked(): set_key(aid,self.key.text())
                self.win.session_keys[aid]=self.key.text()
            self.win.store.save_settings(self.win.account,self.s); self.win.settings=self.s; self.win.apply_theme(); self.accept()
        except Exception as e: QMessageBox.warning(self,'无法保存',str(e))

class AssetDialog(QDialog):
    def __init__(self,parent,data=None):
        super().__init__(parent); self.setWindowTitle('共享资产档案'); self.resize(580,540); self.data=copy.deepcopy(data or {})
        l=QVBoxLayout(self); f=QFormLayout(); l.addLayout(f)
        self.name=QLineEdit(self.data.get('name','')); self.kind=QComboBox(); self.kind.addItems(['人物','场景','道具']); self.kind.setCurrentText(self.data.get('kind','人物'))
        self.source=QComboBox(); self.source.addItems(['原文明确','AI 建议','用户自定']); self.source.setCurrentText(self.data.get('source','用户自定'))
        self.review=QComboBox(); self.review.addItems(['待审核','已确认','已锁定']); self.review.setCurrentText(self.data.get('review','待审核'))
        self.description=QPlainTextEdit(self.data.get('description','')); self.description.setPlaceholderText('外貌、服装版本、生效章节、原文证据……\n基础版用文本记录状态与证据。')
        for t,w in [('名称',self.name),('类型',self.kind),('来源',self.source),('审核状态',self.review),('档案与证据',self.description)]: f.addRow(t,w)
        bb=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); bb.button(QDialogButtonBox.Save).setText('保存'); bb.button(QDialogButtonBox.Cancel).setText('取消'); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); l.addWidget(bb)
    def value(self):
        self.data.update(name=self.name.text().strip(),kind=self.kind.currentText(),source=self.source.currentText(),review=self.review.currentText(),description=self.description.toPlainText()); return self.data

class Window(QMainWindow):
    def __init__(self,root):
        super().__init__(); self.store=Store(root); self.account=self.store.accounts[0]; self.settings=self.store.settings(self.account)
        self.project=None; self.sid=None; self.node=0; self.data=None; self.busy=False; self.worker=None; self.session_keys={}; self.pending_attachments=[]; self.node_buttons=[]
        self.setWindowTitle('墨境 · 小说智能可视化  |  基础测试版 0.1'); self.resize(1440,940); self.setMinimumSize(1080,730)
        self.bg=Backdrop(); self.setCentralWidget(self.bg); outer=QVBoxLayout(self.bg); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        top=QFrame(); top.setObjectName('topbar'); h=QHBoxLayout(top); h.setContentsMargins(24,15,24,15)
        h.addWidget(label('墨境  /  NOVEL STUDIO','brand')); h.addStretch()
        self.account_combo=QComboBox(); self.account_combo.setMinimumWidth(130); self.account_combo.currentIndexChanged.connect(self.switch_account)
        h.addWidget(self.account_combo); h.addWidget(button('账户管理',self.manage_accounts)); h.addWidget(button('⚙  设置',self.open_settings)); outer.addWidget(top)
        body=QHBoxLayout(); body.setSpacing(0); outer.addLayout(body,1)
        side=QFrame(); side.setObjectName('sidebar'); side.setFixedWidth(190); sl=QVBoxLayout(side); sl.setContentsMargins(18,25,18,20)
        sl.addWidget(label('创作空间','eyebrow')); self.nav=[]
        for i,t in enumerate(['◈  片段工作台','▤  原文阅读','◇  共享资产库','▧  插图生成','◷  任务历史','▱  项目文件']):
            b=button(t,lambda checked=False,k=i:self.navigate(k)); b.setProperty('nav',True); sl.addWidget(b); self.nav.append(b)
        sl.addStretch(); sl.addWidget(label('每一步，由你确认。\n本地保存 · 模型自选','muted')); body.addWidget(side)
        center=QWidget(); cl=QVBoxLayout(center); cl.setContentsMargins(24,20,24,15); cl.setSpacing(14); body.addWidget(center,1)
        ph=QHBoxLayout(); self.projects_combo=QComboBox(); self.projects_combo.setMinimumWidth(230); self.projects_combo.currentIndexChanged.connect(self.switch_project)
        ph.addWidget(self.projects_combo,1); ph.addWidget(button('＋ 新建项目',self.new_project)); ph.addWidget(button('导入小说片段',self.import_segment,True)); ph.addWidget(button('备份项目',self.backup)); ph.addWidget(button('恢复备份',self.restore_backup)); cl.addLayout(ph)
        self.pages=QStackedWidget(); cl.addWidget(self.pages,1)
        self.build_workbench(); self.build_reader(); self.build_assets(); self.build_images(); self.build_jobs(); self.build_files()
        self.status=label('就绪 · 数据保存在你选择的目录','muted'); cl.addWidget(self.status)
        self.reload_accounts(); self.reload_projects(); self.apply_theme(); self.navigate(0)
        QApplication.styleHints().colorSchemeChanged.connect(self.system_theme_changed)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'pages'):QTimer.singleShot(0,self.fit_workbench)
    def fit_workbench(self):
        if self.pages.count():
            self.pages.widget(0).widget().setFixedHeight(max(750,self.pages.height()-2))
    def info(self,t): QMessageBox.information(self,'墨境',t)
    def error(self,e): QMessageBox.warning(self,'操作未完成',str(e))
    def guard(self):
        if self.busy: self.info('有任务正在执行。请等待完成，或停止等待后再切换账户、项目或片段。'); return False
        return True
    def require_project(self):
        if not self.project: self.info('请先新建或选择项目'); return False
        return True
    def build_workbench(self):
        page=QWidget(); l=QVBoxLayout(page); l.setContentsMargins(0,0,0,0); l.setSpacing(12)
        l.addWidget(label('把文字，变成可见的世界。','hero')); l.addWidget(label('按片段推进创作，所有片段共享当前项目的资产。每个节点都可以讨论、编辑，再确认。','muted'))
        bar=QHBoxLayout(); bar.addWidget(label('当前片段')); self.segments_combo=QComboBox(); self.segments_combo.setMinimumWidth(240); self.segments_combo.currentIndexChanged.connect(self.switch_segment); bar.addWidget(self.segments_combo,1)
        bar.addWidget(button('＋ 粘贴片段',self.paste_segment)); l.addLayout(bar)
        cards=QWidget(); ch=QHBoxLayout(cards); ch.setContentsMargins(0,0,0,0); ch.setSpacing(10)
        descriptions=['保留证据与位置','梳理人物 · 场景 · 道具','讨论动作与构图','编辑并确认提示词','交给工作流生成']
        for i,title in enumerate(NODES):
            b=button('',lambda checked=False,n=i:self.select_node(n)); b.setMinimumSize(185,112); b.setProperty('card',True); b.setToolTip(descriptions[i]); self.node_buttons.append(b); ch.addWidget(b)
        cs=scroll(cards); cs.setFixedHeight(140); cs.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded); l.addWidget(cs)
        splitter=QSplitter(Qt.Horizontal)
        left=QFrame(); left.setObjectName('panel'); ll=QVBoxLayout(left); ll.setContentsMargins(18,18,18,18)
        ll.addWidget(label('原文与项目上下文','section')); self.excerpt=QPlainTextEdit(); self.excerpt.setReadOnly(True); self.excerpt.setPlaceholderText('导入或粘贴一段小说，即可开始。'); ll.addWidget(self.excerpt,1)
        self.include_text=QCheckBox('调用时附带本片段原文'); self.include_text.setChecked(True)
        self.include_assets=QCheckBox('附带已确认资产摘要（项目共享）'); self.include_assets.setChecked(True)
        ll.addWidget(self.include_text); ll.addWidget(self.include_assets)
        self.context_count=label('','muted'); ll.addWidget(self.context_count); splitter.addWidget(left)
        right=QFrame(); right.setObjectName('panel'); rl=QVBoxLayout(right); rl.setContentsMargins(18,18,18,18)
        title=QHBoxLayout(); self.node_title=label('原文整理','section'); title.addWidget(self.node_title,1); title.addWidget(button('导出 TXT / MD',self.export_text)); rl.addLayout(title)
        self.tabs=QTabWidget(); rl.addWidget(self.tabs,1)
        chat=QWidget(); chl=QVBoxLayout(chat); chl.setContentsMargins(0,10,0,0)
        self.conversation=QTextEdit(); self.conversation.setReadOnly(True); self.conversation.setMinimumHeight(130); chl.addWidget(self.conversation,1)
        self.message=QPlainTextEdit(); self.message.setPlaceholderText('补充要求、提出修改……也可在「最终方案」中直接手工定稿。'); self.message.setMinimumHeight(78); self.message.setMaximumHeight(90); chl.addWidget(self.message)
        self.model_badge=label('演示模式 · 不调用外部模型','muted'); mr=QHBoxLayout(); mr.addWidget(self.model_badge,1); self.retry_btn=button('重试上次失败请求',self.retry_text); mr.addWidget(self.retry_btn); chl.addLayout(mr)
        self.attachment_label=label('未附加文件','muted'); chl.addWidget(self.attachment_label)
        row=QHBoxLayout(); row.addWidget(button('＋ 附件',self.add_attachments)); row.addWidget(button('清除附件',self.clear_attachments)); row.addStretch(); self.stop=button('停止等待',self.cancel_task); self.stop.setEnabled(False); row.addWidget(self.stop); self.send=button('发送',self.send_message,True); row.addWidget(self.send); chl.addLayout(row)
        self.tabs.addTab(chat,'多轮对话')
        final=QWidget(); fl=QVBoxLayout(final); self.final=QPlainTextEdit(); self.final.setPlaceholderText('直接输入最终方案，或从对话中采用模型输出。'); self.final.textChanged.connect(self.final_changed); fl.addWidget(self.final,1)
        row=QHBoxLayout(); row.addWidget(button('采用最近一次模型输出',self.use_last)); row.addWidget(button('保存草稿',self.save_draft)); self.confirm_btn=button('确认采用此版本',self.confirm_final,True); row.addWidget(self.confirm_btn); fl.addLayout(row); self.tabs.addTab(final,'最终方案')
        self.param_host=QWidget(); self.param_layout=QVBoxLayout(self.param_host); self.tabs.addTab(scroll(self.param_host),'节点参数')
        splitter.addWidget(right); splitter.setSizes([380,620]); splitter.setChildrenCollapsible(False); l.addWidget(splitter,1)
        page.setMinimumHeight(720); self.pages.addWidget(scroll(page))
    def build_reader(self):
        page=QWidget(); l=QVBoxLayout(page); l.addWidget(label('原文阅读','hero')); l.addWidget(label('外部修改正文后，点击重新读取。确认方案和历史任务仍保留原版本。','muted'))
        row=QHBoxLayout(); row.addWidget(button('重新读取文件',self.refresh_text)); row.addWidget(button('打开正文文件',self.open_segment_file)); row.addStretch(); l.addLayout(row)
        self.reader=QPlainTextEdit(); self.reader.setReadOnly(True); l.addWidget(self.reader,1); self.pages.addWidget(page)
    def build_assets(self):
        page=QWidget(); l=QVBoxLayout(page); l.addWidget(label('共享资产库','hero')); l.addWidget(label('同一项目的所有片段共享档案。基础版通过文本记录服装、生效范围与原文证据。','muted'))
        row=QHBoxLayout(); row.addWidget(button('＋ 新建资产',self.add_asset,True)); row.addWidget(button('编辑选中资产',self.edit_asset)); row.addStretch(); l.addLayout(row)
        self.asset_tree=QTreeWidget(); self.asset_tree.setHeaderLabels(['名称','类型','来源','审核','档案摘要']); self.asset_tree.header().setSectionResizeMode(4,QHeaderView.Stretch); self.asset_tree.itemDoubleClicked.connect(lambda *_:self.edit_asset()); l.addWidget(self.asset_tree,1); self.pages.addWidget(page)
    def build_images(self):
        page=QWidget(); l=QVBoxLayout(page); l.addWidget(label('让方案成为画面','hero')); l.addWidget(label('ComfyUI API 工作流 · 手动映射 · 显式提交。测试版不含云端图片适配器和参考图上传映射。','muted'))
        split=QSplitter(); left=QWidget(); ll=QVBoxLayout(left)
        self.comfy_prompt=QPlainTextEdit(); self.comfy_prompt.setPlaceholderText('填写图像提示词，或从当前片段的「提示词定稿」载入'); self.comfy_prompt.setMaximumHeight(140); ll.addWidget(self.comfy_prompt)
        ll.addWidget(button('载入已确认提示词',self.load_confirmed_prompt))
        self.workflow=QPlainTextEdit(); self.workflow.setPlaceholderText('导入 ComfyUI API 格式工作流 JSON'); ll.addWidget(button('导入 API 工作流',self.import_workflow)); ll.addWidget(self.workflow,1)
        self.mapping=QPlainTextEdit('{\n  "prompt": ["6", "text"]\n}'); self.mapping.setMaximumHeight(110); ll.addWidget(label('输入映射：字段 → [节点 ID, 输入名]','muted')); ll.addWidget(self.mapping)
        self.seed=QSpinBox(); self.seed.setRange(0,2147483647); self.seed.setValue(42); ll.addWidget(label('Seed（仅映射 seed 时生效）','muted')); ll.addWidget(self.seed)
        row=QHBoxLayout(); self.generate_btn=button('提交到 ComfyUI',self.generate_image,True); row.addWidget(self.generate_btn); row.addWidget(button('停止等待',self.cancel_task)); ll.addLayout(row)
        left.setMinimumHeight(700); split.addWidget(scroll(left)); right=QWidget(); rl=QVBoxLayout(right); self.image=label('生成的图片将在这里显示\n\n先确认方案，再提交工作流。','imagePreview'); self.image.setAlignment(Qt.AlignCenter); self.image.setMinimumWidth(310); rl.addWidget(self.image,1)
        self.image_list=QComboBox(); self.image_list.currentIndexChanged.connect(self.show_image); rl.addWidget(self.image_list)
        rl.addWidget(button('选为最终成果',self.choose_result)); rl.addWidget(button('打开图片所在目录',self.open_image_folder)); split.addWidget(right); split.setSizes([500,450]); l.addWidget(split,1); self.pages.addWidget(page)
    def build_jobs(self):
        page=QWidget(); l=QVBoxLayout(page); l.addWidget(label('任务历史','hero')); l.addWidget(label('失败不自动重试，超时不自动切换。停止等待不代表远端停止执行或停止计费。','muted'))
        self.job_tree=QTreeWidget(); self.job_tree.setHeaderLabels(['时间','任务','状态','模型 / 远端 ID']); self.job_tree.header().setSectionResizeMode(3,QHeaderView.Stretch); l.addWidget(self.job_tree,1)
        row=QHBoxLayout(); row.addWidget(button('查看任务快照',self.open_job)); row.addWidget(button('查询 ComfyUI 远端历史',self.query_remote)); row.addStretch(); l.addLayout(row); self.pages.addWidget(page)
    def build_files(self):
        page=QWidget(); l=QVBoxLayout(page); l.addWidget(label('项目文件','hero')); l.addWidget(label('文件按用途保存，可随时打开。对话 JSON、数据库与索引由软件管理；外部文本修改可在原文页重新读取。','muted'))
        row=QHBoxLayout(); row.addWidget(button('刷新目录',self.refresh_files)); row.addWidget(button('保存其他附件',self.archive_attachment)); row.addWidget(button('打开项目文件夹',lambda:self.project and reveal(self.project.path))); row.addWidget(button('打开选中文件',self.open_selected_file)); row.addStretch(); l.addLayout(row)
        self.file_tree=QTreeWidget(); self.file_tree.setHeaderLabels(['目录 / 文件','大小']); self.file_tree.header().setSectionResizeMode(0,QHeaderView.Stretch); self.file_tree.itemDoubleClicked.connect(lambda *_:self.open_selected_file()); l.addWidget(self.file_tree,1); self.pages.addWidget(page)
    def navigate(self,i):
        self.pages.setCurrentIndex(i)
        for j,b in enumerate(self.nav): b.setProperty('active',i==j); b.style().unpolish(b); b.style().polish(b)
        if i==2: self.refresh_assets()
        if i==4: self.refresh_jobs()
        if i==5: self.refresh_files()
    def reload_accounts(self):
        self.account_combo.blockSignals(True); self.account_combo.clear()
        for a in self.store.accounts: self.account_combo.addItem(a['name'],a['id'])
        self.account_combo.setCurrentIndex(next((i for i,a in enumerate(self.store.accounts) if a['id']==self.account['id']),0)); self.account_combo.blockSignals(False)
    def switch_account(self,index):
        if index<0:return
        if not self.guard(): self.reload_accounts(); return
        self.save_draft(silent=True); self.account=self.store.accounts[index]; self.settings=self.store.settings(self.account); self.reload_projects(); self.apply_theme()
    def manage_accounts(self):
        if not self.guard():return
        action,ok=QInputDialog.getItem(self,'账户管理','操作',['创建账户','修改账户名称','删除当前账户（项目归档保留）'],0,False)
        if not ok:return
        try:
            if action.startswith('删除'):
                if len(self.store.accounts)==1: self.info('请先创建另一个账户，至少保留一个账户。'); return
                if QMessageBox.question(self,'删除账户','账户将从列表删除，资料移至「已归档账户」。是否继续？')!=QMessageBox.Yes:return
                aid=self.account['id']; self.session_keys.pop(aid,None)
                # Erase stored key before removing the account; no plaintext fallback.
                if get_key(aid): set_key(aid,'')
                self.store.delete_account(self.account); self.account=self.store.accounts[0]
            else:
                name,ok=QInputDialog.getText(self,'账户名称','名称',text='' if action.startswith('创建') else self.account['name'])
                if not ok:return
                if action.startswith('创建'): self.account=self.store.create_account(name)
                else:self.store.rename_account(self.account,name)
            self.settings=self.store.settings(self.account); self.reload_accounts(); self.reload_projects(); self.apply_theme()
        except Exception as e:self.error(e)
    def open_settings(self):
        if not self.guard():return
        self.save_draft(silent=True)
        SettingsDialog(self).exec(); self.settings=self.store.settings(self.account)
        if self.project:self.project.secrets=[self.session_keys.get(self.account['id']) or get_key(self.account['id'])]
        self.apply_theme(); self.show_node()
    def reload_projects(self,select=None):
        self.projects_combo.blockSignals(True); self.projects_combo.clear()
        for p in self.store.projects(self.account):
            try: meta=json.loads(p.read_text('utf-8')); self.projects_combo.addItem(meta['name'],str(p.parent.parent))
            except Exception: pass
        if select:
            for i in range(self.projects_combo.count()):
                if self.projects_combo.itemData(i)==str(select):self.projects_combo.setCurrentIndex(i)
        self.projects_combo.blockSignals(False); self.switch_project(self.projects_combo.currentIndex())
    def switch_project(self,i):
        if not self.guard():
            self.projects_combo.blockSignals(True)
            for n in range(self.projects_combo.count()):
                if self.project and self.projects_combo.itemData(n)==str(self.project.path): self.projects_combo.setCurrentIndex(n)
            self.projects_combo.blockSignals(False);return
        self.save_draft(silent=True)
        if self.project:self.project.close()
        self.project=None; self.sid=None; self.data=None; self.clear_attachments(); self.image_list.clear(); self.image.setText('尚无图片'); self.workflow.clear(); self.comfy_prompt.clear()
        if i>=0:
            try:
                self.project=Project(self.projects_combo.itemData(i)); self.project.secrets=[self.session_keys.get(self.account['id']) or get_key(self.account['id'])]
            except Exception as e:self.error(e)
        self.reload_segments(); self.refresh_assets(); self.refresh_jobs(); self.refresh_files()
        if self.project:
            for j in reversed(self.project.jobs()):
                for rel in j.get('results',[]):
                    path=self.project.path/rel
                    if path.exists():self.image_list.addItem(path.name,str(path))
    def new_project(self):
        if not self.guard():return
        name,ok=QInputDialog.getText(self,'新建项目','项目名称')
        if ok:
            try:
                p=self.store.create_project(self.account,name); path=p.path; p.close(); self.reload_projects(path)
            except Exception as e:self.error(e)
    def reload_segments(self,select=None):
        self.segments_combo.blockSignals(True); self.segments_combo.clear()
        if self.project:
            for s in self.project.segments():self.segments_combo.addItem(s['name'],s['id'])
        if select:
            i=self.segments_combo.findData(select); self.segments_combo.setCurrentIndex(i)
        self.segments_combo.blockSignals(False); self.switch_segment(self.segments_combo.currentIndex())
    def switch_segment(self,i):
        if not self.guard():
            self.segments_combo.blockSignals(True); self.segments_combo.setCurrentIndex(self.segments_combo.findData(self.sid)); self.segments_combo.blockSignals(False);return
        self.save_draft(silent=True); self.sid=self.segments_combo.itemData(i) if i>=0 else None; self.clear_attachments(); self.refresh_text(); self.show_node()
    def paste_segment(self):
        if not self.guard() or not self.require_project():return
        d=QDialog(self); d.setWindowTitle('添加小说片段'); d.resize(650,500); l=QVBoxLayout(d); name=QLineEdit(); name.setPlaceholderText('片段名称，例如：第一章 · 夜渡'); text=QPlainTextEdit(); text.setPlaceholderText('粘贴本段原文。后续片段仍共享当前项目资产。'); l.addWidget(name); l.addWidget(text); bb=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); bb.button(QDialogButtonBox.Ok).setText('添加'); bb.button(QDialogButtonBox.Cancel).setText('取消'); l.addWidget(bb); bb.accepted.connect(d.accept); bb.rejected.connect(d.reject)
        if d.exec()==QDialog.Accepted:
            try:
                self.save_draft(silent=True); sid=self.project.add_segment(name.text() or '新片段',text.toPlainText()); self.data=None; self.reload_segments(sid)
            except Exception as e:self.error(e)
    def import_segment(self):
        if not self.guard() or not self.require_project():return
        p,_=QFileDialog.getOpenFileName(self,'导入小说片段','','小说文档 (*.txt *.md *.docx *.epub)')
        if not p:return
        try:
            text=read_document(p)
            self.save_draft(silent=True); sid=self.project.add_segment(Path(p).stem,text,p); self.data=None; self.reload_segments(sid); self.status.setText('已导入正文与原始文件副本 · 可继续导入下一片段')
        except Exception as e:self.error(e)
    def refresh_text(self):
        text=''
        if self.project and self.sid:
            try:text=self.project.segment_text(self.sid)
            except Exception as e:self.error(e)
        self.excerpt.setPlainText(text); self.reader.setPlainText(text); self.context_count.setText(f'当前正文 {len(text):,} 字符 · 仅勾选的上下文参与调用')
    def open_segment_file(self):
        if self.project and self.sid:
            s=next(x for x in self.project.segments() if x['id']==self.sid); reveal(self.project.path/s['file'])
    def select_node(self,n):
        if not self.guard():return
        self.save_draft(silent=True); self.node=n; self.clear_attachments(); self.show_node()
    def show_node(self):
        self.data=self.project.load_node(self.sid,self.node) if self.project and self.sid else None
        self.node_title.setText(f'{self.node+1:02d}  {NODES[self.node]}')
        self.final.blockSignals(True); self.final.setPlainText(self.data['final'] if self.data else ''); self.final.blockSignals(False); self.message.setPlainText(self.data.get('draft','') if self.data else '')
        self.pending_attachments=list(self.data.get('draft_attachments',[]) if self.data else [])
        self.attachment_label.setText(' · '.join(Path(p).name for p in self.pending_attachments) or '未附加文件')
        while self.param_layout.count():
            item=self.param_layout.takeAt(0)
            if item.widget():item.widget().deleteLater()
        p=copy.deepcopy(self.settings)
        if self.data:p.update(self.data.get('params',{}))
        self.model_badge.setText('演示模式 · 不发送网络请求' if p['provider']=='demo' else '当前模型：'+(p['model'] or '尚未填写')+' · '+p['endpoint'])
        self.param_form=ParamForm(p); self.param_layout.addWidget(label('本节点覆盖值 · 保存后只影响后续调用','muted')); self.param_layout.addWidget(self.param_form); self.param_layout.addWidget(button('保存节点参数',self.save_draft)); self.param_layout.addStretch()
        self.render_chat(); self.update_cards()
        self.send.setEnabled(bool(self.data) and not self.busy); self.confirm_btn.setEnabled(bool(self.data) and not self.busy)
    def final_changed(self):
        if self.data:
            self.data['final']=self.final.toPlainText()
            if self.data['status']=='已确认': self.data['status']='待确认'
            self.update_cards()
    def update_cards(self):
        for i,b in enumerate(self.node_buttons):
            d=self.data if i==self.node else self.project.load_node(self.sid,i) if self.project and self.sid else None
            status=d['status'] if d else '未开始'; marker='●' if status=='已确认' else '○'
            b.setText(f'{i+1:02d}  {NODES[i]}\n\n{marker}  {status}'); b.setProperty('selected',i==self.node); b.style().unpolish(b); b.style().polish(b)
    def render_chat(self):
        if not self.data:self.conversation.setHtml('<p style="color:#84938e">创建项目并添加片段，开始你的第一次创作。</p>');return
        pieces=[]
        for m in self.data['messages']:
            role='你' if m['role']=='user' else '模型'
            pieces.append(f'<p><b>{role}</b> <small>{html.escape(m.get("time",""))}</small></p><p>{html.escape(m["content"]).replace(chr(10),"<br>")}</p><hr>')
        self.conversation.setHtml(''.join(pieces) or '<p style="color:#84938e">可以与模型多轮讨论，也可以直接输入最终方案。<br><br>演示模式不会发送网络请求。</p>'); self.conversation.verticalScrollBar().setValue(self.conversation.verticalScrollBar().maximum())
    def save_draft(self,checked=False,silent=False):
        if not self.project or not self.sid or not self.data:return
        try:
            self.data['final']=self.final.toPlainText(); self.data['draft']=self.message.toPlainText(); self.data['draft_attachments']=list(self.pending_attachments)
            validation_error=None
            try:self.data['params']=self.param_form.value()
            except Exception as e:validation_error=e
            self.project.save_node(self.sid,self.node,self.data)
            if validation_error and not silent:self.error(str(validation_error)+' 正文草稿仍已保存。')
            if not silent:self.status.setText('已保存节点草稿及参数 · 不会发起模型调用')
        except Exception as e:
            if not silent:self.error(e)
    def use_last(self):
        if not self.data:return
        m=next((m for m in reversed(self.data['messages']) if m['role']=='assistant'),None)
        if m:self.final.setPlainText(m['content']); self.tabs.setCurrentIndex(1)
        else:self.info('当前节点还没有模型输出，可直接手工输入方案。')
    def confirm_final(self):
        if not self.data or self.busy:return
        try:
            self.save_draft(silent=True); p=self.project.confirm(self.sid,self.node,self.data); self.update_cards(); self.status.setText(f'已确认 v{self.data["revision"]} · 独立版本已保存：{p.name}')
        except Exception as e:self.error(e)
    def add_attachments(self):
        if not self.data or self.busy:return
        paths,_=QFileDialog.getOpenFileNames(self,'添加调用附件','','支持的附件 (*.txt *.md *.docx *.epub *.png *.jpg *.jpeg *.webp)')
        try:
            for p in paths:
                if Path(p).stat().st_size>20*1024*1024:raise ValueError('测试版单个附件上限为 20 MB')
                self.pending_attachments.append(self.project.add_attachment(p))
            self.attachment_label.setText(' · '.join(Path(p).name for p in self.pending_attachments) or '未附加文件')
        except Exception as e:self.error(e)
    def clear_attachments(self):
        self.pending_attachments=[]
        if hasattr(self,'attachment_label'):self.attachment_label.setText('未附加文件')
    def context(self):
        chunks=[]
        if self.include_text.isChecked():chunks.append('【当前片段原文】\n'+self.project.segment_text(self.sid))
        if self.include_assets.isChecked():
            assets=[a for a in self.project.assets() if a['review'] in ('已确认','已锁定')]
            chunks.append('【已确认共享资产；请根据生效范围使用】\n'+json.dumps(assets,ensure_ascii=False))
        # Include only explicitly confirmed earlier stages in this segment.
        for n in range(self.node):
            d=self.project.load_node(self.sid,n)
            if d['status']=='已确认':chunks.append('【已确认 '+NODES[n]+'】\n'+d['final'])
        return '\n\n'.join(chunks)
    def send_message(self):
        if not self.data or self.busy:return
        content=self.message.toPlainText().strip()
        if not content:self.info('请输入本轮要求');return
        try:
            params=self.param_form.value(); context=self.context()
            all_attachments=list(dict.fromkeys([p for m in self.data['messages'] for p in m.get('attachments',[])]+self.pending_attachments))
            paths=[self.project.path/p for p in all_attachments]
            # Historical attachments are resent so follow-up questions can refer to them.
            for p in paths:
                if not p.exists():raise ValueError('历史附件缺失，请从项目目录恢复：'+p.name)
            if paths and params['provider']!='demo' and self.settings['confirm_attachments']:
                total=sum(p.stat().st_size for p in paths); expanded=sum(int(p.stat().st_size*4/3) for p in paths if p.suffix.lower() in ('.png','.jpg','.jpeg','.webp'))
                msg='目标：'+params['endpoint']+'\n模型：'+params['model']+'\n\n'+'\n'.join(f'{p.name} — {p.stat().st_size/1024:.1f} KB' for p in paths)+f'\n\n文件合计 {total/1024:.1f} KB；图片编码约 {expanded/1024:.1f} KB。\n文档将提取为文本发送。大小不等于计费量，当前无法估算费用。\n是否提交本次请求？'
                if QMessageBox.question(self,'确认发送附件（包含历史对话附件）',msg)!=QMessageBox.Yes:return
            # Keep immutable attachment references in each explicit request snapshot.
            self.data['messages'].append(dict(role='user',content=content,time=now(),attachments=list(self.pending_attachments)))
            self.data['status']='运行中'; self.data['params']=params; self.data['draft']=''; self.data['draft_attachments']=[]
            self.project.secrets=[self.session_keys.get(self.account['id']) or get_key(self.account['id'])]
            self.project.save_node(self.sid,self.node,self.data)
            j=dict(id=uid(),kind='文本对话',status='running',created=now(),segment=self.sid,node=self.node,params=params,context=context,messages=copy.deepcopy(self.data['messages']),attachments=all_attachments,assets=copy.deepcopy(self.project.assets()))
            self.project.save_job(j); messages=copy.deepcopy(self.data['messages']); key=self.session_keys.get(self.account['id']) or get_key(self.account['id'])
            self.model_badge.setText('演示模式 · 不发送网络请求' if params['provider']=='demo' else '当前模型：'+params['model'])
            self.message.clear(); self.clear_attachments(); self.render_chat(); self.start_job(j,lambda cancel,progress:text_call(params,messages,context,key,paths,cancel))
        except Exception as e:self.error(e)
    def retry_text(self):
        if self.busy or not self.data:return
        previous=next((j for j in self.project.jobs() if j.get('segment')==self.sid and j.get('node')==self.node and j['kind']=='文本对话'),None)
        if not previous or previous['status'] not in ('failed','unknown'):
            self.info('本节点没有可重试的失败请求。');return
        if previous['status']=='unknown' and QMessageBox.question(self,'可能重复计费','上次请求执行状态未知，可能已经计费。请先检查服务端记录。仍要重新提交吗？')!=QMessageBox.Yes:return
        try:
            params=self.param_form.value(); paths=[self.project.path/p for p in previous.get('attachments',[])]
            if paths and params['provider']!='demo' and self.settings['confirm_attachments']:
                total=sum(p.stat().st_size for p in paths)
                if QMessageBox.question(self,'重试附件确认',f'目标：{params["endpoint"]}\n附件 {len(paths)} 个，文件合计 {total/1024:.1f} KB。费用未知。是否提交？')!=QMessageBox.Yes:return
            j=copy.deepcopy(previous); j.update(id=uid(),retry_of=previous['id'],status='running',created=now(),params=params)
            for k in ('error','result','finished'):j.pop(k,None)
            self.project.save_job(j); self.data['status']='运行中'; self.project.save_node(self.sid,self.node,self.data)
            key=self.session_keys.get(self.account['id']) or get_key(self.account['id'])
            self.start_job(j,lambda cancel,progress:text_call(params,j['messages'],j['context'],key,paths,cancel))
        except Exception as e:self.error(e)
    def start_job(self,j,fn):
        self.busy=True; self.set_busy(); self.update_cards(); self.status.setText('任务执行中 · 不会自动重试或切换模型')
        self.current_job=j; self.worker=Worker(fn); self.worker.progress.connect(self.job_progress); self.worker.done.connect(self.job_done); self.worker.failed.connect(self.job_failed); self.worker.finished.connect(self.thread_finished); self.worker.start()
    def set_busy(self):
        self.send.setEnabled(bool(self.data) and not self.busy); self.stop.setEnabled(self.busy); self.confirm_btn.setEnabled(bool(self.data) and not self.busy); self.generate_btn.setEnabled(not self.busy); self.final.setReadOnly(self.busy); self.retry_btn.setEnabled(not self.busy)
    def job_progress(self,data):self.current_job.update(data); self.project.save_job(self.current_job)
    def job_done(self,result):
        j=self.current_job; j.update(status='succeeded',finished=now())
        if j['kind']=='文本对话':
            j['result']=result; self.data['messages'].append(dict(role='assistant',content=result,time=now())); self.data['status']='待确认'; self.project.save_node(self.sid,self.node,self.data); self.render_chat()
        else:
            j['results']=[Path(p).relative_to(self.project.path).as_posix() for p in result]
            for p in result:self.image_list.addItem(Path(p).name,p)
            self.image_list.setCurrentIndex(self.image_list.count()-1)
        self.project.save_job(j); self.status.setText('任务完成 · 结果已保存，等待你审核确认'); self.update_cards(); self.refresh_jobs()
    def job_failed(self,error,unknown):
        j=self.current_job; j.update(status='unknown' if unknown else 'failed',error=error,finished=now()); self.project.save_job(j)
        if j['kind']=='文本对话':self.data['status']='状态未知' if unknown else '失败'; self.project.save_node(self.sid,self.node,self.data)
        self.status.setText(error); self.update_cards(); self.refresh_jobs(); self.error(error)
    def thread_finished(self):
        self.busy=False; self.set_busy(); self.worker.deleteLater(); self.worker=None
    def cancel_task(self):
        if self.worker and self.busy:
            self.worker.cancel.set(); self.current_job['cancel_requested_at']=now(); self.project.save_job(self.current_job); self.status.setText('已请求停止等待 · 已提交的文本请求须等待本次响应或超时；远端仍可能计费')
    def export_text(self):
        if not self.data:return
        scope,ok=QInputDialog.getItem(self,'导出文本','导出范围',['完整对话','仅模型输出','最近一次模型输出','选中的对话文本','当前最终方案'],0,False)
        if not ok:return
        path,fmt=QFileDialog.getSaveFileName(self,'导出文本',str(self.project.path/'07_导出'/f'{NODES[self.node]}.md'),'Markdown (*.md);;纯文本 (*.txt)')
        if not path:return
        try:
            suffix='.txt' if 'txt' in fmt else '.md'; p=Path(path)
            if p.suffix.lower() not in ('.md','.txt'):p=p.with_suffix(suffix)
            if p.exists() and str(p)!=path and QMessageBox.question(self,'覆盖文件','文件已存在，是否覆盖？')!=QMessageBox.Yes:return
            if scope=='当前最终方案':text=self.final.toPlainText()
            elif scope=='选中的对话文本':text=self.conversation.textCursor().selectedText().replace('\u2029','\n')
            elif scope=='最近一次模型输出':text=next((m['content'] for m in reversed(self.data['messages']) if m['role']=='assistant'),'')
            else:text=Project.transcript(self.data,p.suffix[1:],scope=='仅模型输出')
            if not text.strip():raise ValueError('所选范围没有可导出的文本')
            # redact the known credential if a model or user echoed it in chat
            key=self.session_keys.get(self.account['id']) or get_key(self.account['id'])
            if key:text=text.replace(key,'[凭据已移除]')
            p.write_text(text,encoding='utf-8'); self.status.setText('已导出：'+str(p))
        except Exception as e:self.error(e)
    def refresh_assets(self):
        self.asset_tree.clear()
        if not self.project:return
        for a in self.project.assets():
            item=QTreeWidgetItem([a['name'],a['kind'],a['source'],a['review'],a['description'].replace('\n',' ')[:110]]); item.setData(0,Qt.UserRole,a); self.asset_tree.addTopLevelItem(item)
    def add_asset(self):
        if not self.require_project():return
        if self.busy:self.info('请等待当前任务完成再修改资产。');return
        d=AssetDialog(self)
        if d.exec()==QDialog.Accepted:
            try:self.project.save_asset(d.value()); self.refresh_assets()
            except Exception as e:self.error(e)
    def edit_asset(self):
        if not self.project or self.busy:return
        item=self.asset_tree.currentItem()
        if not item:return
        a=item.data(0,Qt.UserRole)
        if a['review']=='已锁定' and QMessageBox.question(self,'修改锁定资产','修改将创建新档案版本，历史任务快照保持不变。是否继续？')!=QMessageBox.Yes:return
        d=AssetDialog(self,a)
        if d.exec()==QDialog.Accepted:
            try:self.project.save_asset(d.value()); self.refresh_assets()
            except Exception as e:self.error(e)
    def import_workflow(self):
        if not self.project or self.busy:return
        path,_=QFileDialog.getOpenFileName(self,'ComfyUI API 工作流','','JSON (*.json)')
        if path:
            try:
                data=json.loads(Path(path).read_text('utf-8')); self.workflow.setPlainText(json.dumps(data,ensure_ascii=False,indent=2))
                dest=self.project.path/'01_原始资料/过程文档'/(Path(path).stem+'_'+uid()+'.json'); shutil.copy2(path,dest)
            except Exception:self.error('工作流不是有效 JSON')
    def load_confirmed_prompt(self):
        if not self.project or not self.sid:return
        d=self.project.load_node(self.sid,3)
        if d['status']!='已确认':self.info('请先在「提示词定稿」节点确认方案，或直接在此输入提示词。');return
        self.comfy_prompt.setPlainText(d['final'])
    def generate_image(self):
        if self.busy or not self.require_project():return
        if not self.sid:self.info('请先导入小说片段');return
        try:
            if not self.comfy_prompt.toPlainText().strip():raise ValueError('请填写提示词')
            flow=bind_workflow(json.loads(self.workflow.toPlainText()),json.loads(self.mapping.toPlainText()),dict(prompt=self.comfy_prompt.toPlainText(),seed=self.seed.value()))
            url=endpoint(self.settings['comfy_url']); j=dict(id=uid(),kind='ComfyUI 图片',created=now(),status='running',segment=self.sid,workflow=flow,mapping=json.loads(self.mapping.toPlainText()),prompt=self.comfy_prompt.toPlainText(),endpoint=url,assets=copy.deepcopy(self.project.assets()))
            import hashlib
            j['workflow_sha256']=hashlib.sha256(json.dumps(flow,sort_keys=True).encode()).hexdigest()
            self.project.save_job(j); dest=self.project.path/'05_生成任务'/j['id']/'候选图片'; self.start_job(j,lambda cancel,progress:comfy_call(url,flow,dest,cancel,progress))
        except json.JSONDecodeError:self.error('工作流或映射不是有效 JSON')
        except Exception as e:self.error(e)
    def show_image(self,index):
        path=self.image_list.itemData(index)
        if path:
            pix=QPixmap(path)
            if pix.isNull():self.image.setText('图片无法读取')
            else:self.image.setPixmap(pix.scaled(520,560,Qt.KeepAspectRatio,Qt.SmoothTransformation))
    def choose_result(self):
        path=self.image_list.currentData()
        if not path or not self.project:return
        try:
            src=Path(path); dest=self.project.path/'06_最终成果'/(src.stem+'_'+uid()+src.suffix); shutil.copy2(src,dest); self.status.setText('已保存最终成果：'+dest.name)
        except Exception as e:self.error(e)
    def open_image_folder(self):
        p=self.image_list.currentData()
        if p:reveal(Path(p).parent)
    def refresh_jobs(self):
        self.job_tree.clear()
        if not self.project:return
        for j in self.project.jobs():
            item=QTreeWidgetItem([j['created'],j['kind'],j['status'],j.get('remote_id',j.get('params',{}).get('model','演示'))]); item.setData(0,Qt.UserRole,j); self.job_tree.addTopLevelItem(item)
    def open_job(self):
        i=self.job_tree.currentItem()
        if i and self.project:reveal(self.project.path/'05_生成任务'/i.data(0,Qt.UserRole)['id'])
    def query_remote(self):
        i=self.job_tree.currentItem()
        if not i:return
        j=i.data(0,Qt.UserRole)
        if j.get('remote_id'):QDesktopServices.openUrl(QUrl(j['endpoint']+'/history/'+j['remote_id']))
        else:self.info('该任务没有可查询的远端 ID；请查看供应商后台记录。')
    def refresh_files(self):
        self.file_tree.clear()
        if not self.project:return
        def walk(parent,path,depth=0):
            if depth>8:return
            for p in sorted(path.iterdir(),key=lambda p:(not p.is_dir(),p.name)):
                if p.is_symlink():continue
                item=QTreeWidgetItem([p.name,'' if p.is_dir() else f'{p.stat().st_size/1024:.1f} KB']); item.setData(0,Qt.UserRole,str(p)); parent.addChild(item) if isinstance(parent,QTreeWidgetItem) else parent.addTopLevelItem(item)
                if p.is_dir():walk(item,p,depth+1)
        walk(self.file_tree,self.project.path)
    def open_selected_file(self):
        i=self.file_tree.currentItem()
        if i:reveal(i.data(0,Qt.UserRole))
    def archive_attachment(self):
        if not self.require_project():return
        paths,_=QFileDialog.getOpenFileNames(self,'保存项目附件（不发送给模型）','','所有文件 (*)')
        try:
            for p in paths:self.project.add_attachment(p)
            self.refresh_files(); self.status.setText('附件已保存到项目目录，未发送给模型')
        except Exception as e:self.error(e)
    def restore_backup(self):
        if not self.guard():return
        path,_=QFileDialog.getOpenFileName(self,'恢复项目备份','','ZIP (*.zip)')
        if not path:return
        dest=self.store.account_dir(self.account)/'项目'/('恢复项目_'+uid())
        try:
            with zipfile.ZipFile(path) as z:
                total=sum(i.file_size for i in z.infolist())
                if total>4*1024**3:raise ValueError('测试版仅支持恢复 4 GB 以内的项目备份')
                for i in z.infolist():
                    target=(dest/i.filename).resolve()
                    if dest.resolve() not in target.parents or (i.external_attr>>16)&0o170000==0o120000:raise ValueError('备份包含不安全的路径或符号链接')
                if '08_项目数据/project.json' not in z.namelist() or '08_项目数据/index.sqlite' not in z.namelist():raise ValueError('不是本软件的项目备份')
                z.extractall(dest)
            meta_path=dest/'08_项目数据/project.json'; meta=json.loads(meta_path.read_text('utf-8')); meta['restored_from']=meta['id']; meta['id']=uid(); write_json(meta_path,meta)
            p=Project(dest); p.close(); self.reload_projects(dest); self.status.setText('备份已恢复为独立项目，原项目保留')
        except Exception as e:
            if dest.exists():shutil.rmtree(dest)
            self.error(e)
    def backup(self):
        if not self.guard() or not self.require_project():return
        p,_=QFileDialog.getSaveFileName(self,'项目备份',str(self.store.root/(self.project.meta['name']+'_备份.zip')),'ZIP (*.zip)')
        if not p:return
        try:
            dest=Path(p).resolve()
            if self.project.path==dest or self.project.path in dest.parents:raise ValueError('请将备份保存到当前项目目录之外')
            self.save_draft(silent=True); self.project.db.commit()
            with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
                for file in self.project.path.rglob('*'):
                    if file.is_file() and not file.is_symlink():z.write(file,file.relative_to(self.project.path))
            self.status.setText('项目备份完成（不包含账户凭据）')
        except Exception as e:self.error(e)
    def system_theme_changed(self,*_):
        if self.settings['theme']=='system':self.apply_theme()
    def apply_theme(self):
        theme=self.settings['theme']; dark=theme=='dark' or (theme=='system' and QApplication.styleHints().colorScheme()==Qt.ColorScheme.Dark)
        bg='#121d21' if dark else '#f4f7f5'; panel='#1a292e' if dark else '#ffffff'; text='#e1eae5' if dark else '#223d36'; muted='#9aafa5' if dark else '#71877e'; border='#33453f' if dark else '#dfe8e1'; accent='#80d6bb' if dark else '#147d64'; inputbg='#152326' if dark else '#fbfcfa'
        self.setStyleSheet(f'''
        QWidget {{font-family: "Microsoft YaHei UI", "Noto Sans CJK SC", "Arial";font-size:{self.settings['font_size']}px;color:{text};}}
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
        QPushButton[active="true"] {{background:{'#294b40' if dark else '#e4f1e9'};color:{accent};font-weight:700;}}
        QPushButton[card="true"] {{text-align:left;background:{panel};border-radius:12px;padding:15px;}}
        QPushButton[selected="true"] {{background:{'#24473e' if dark else '#edf7f0'};border:2px solid {accent};}}
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
        ''')
        self.bg.pix=QPixmap(self.settings['background']); self.bg.opacity=self.settings['background_opacity']/100.; self.bg.update()
    def closeEvent(self,event):
        if self.busy:self.info('任务仍在执行。请先停止等待，并等待本次网络请求结束后退出，避免丢失远端状态。'); event.ignore();return
        self.save_draft(silent=True)
        if self.project:self.project.close()
        event.accept()

def seed_demo(store):
    a=store.accounts[0]
    if store.projects(a):return
    p=store.create_project(a,'青灯夜渡 · 演示项目')
    s=p.add_segment('第一章 · 雨夜渡口','暮色沉入江面，细雨打湿了渡口的青石。\n\n沈青提着一盏旧铜灯，站在柳树下。她穿着灰蓝色布衣，衣角沾着泥水。\n\n“船还来吗？”她问。\n\n摆渡人将竹篙靠在船边，望向雾里的对岸。\n\n——以上为软件内置虚构示例，用于体验工作流程。')
    p.add_segment('第二章 · 对岸来信','渡船靠岸时，沈青仍提着那盏旧铜灯。摆渡人递给她一封封着红蜡的信。\n\n——演示片段：与第一章共享人物与道具档案。')
    p.save_asset(dict(name='沈青',kind='人物',source='原文明确',review='已确认',description='第一章：灰蓝色布衣，衣角沾泥。手提旧铜灯。\n证据：“沈青提着一盏旧铜灯……她穿着灰蓝色布衣”。\n面容、年龄：原文未描述，待确认。'))
    p.save_asset(dict(name='旧铜灯',kind='道具',source='原文明确',review='已确认',description='第一章、第二章由沈青持有。材质为铜；具体造型待确认。'))
    d=p.load_node(s,0); d['final']='保留渡口、细雨、灰蓝色布衣和旧铜灯。人物面容与年龄尚未明确，后续作为建议交由用户确认。'; p.confirm(s,0,d); p.close()

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--data-root'); parser.add_argument('--choose-root',action='store_true'); parser.add_argument('--demo',action='store_true'); parser.add_argument('--screenshot'); args=parser.parse_args()
    app=QApplication(sys.argv[:1]); app.setApplicationName('NovelVisualizer'); app.setOrganizationName('NovelStudio'); app.setStyle('Fusion')
    q=QSettings(); root=args.data_root or (None if args.choose_root else q.value('data_root',''))
    if not root:
        QMessageBox.information(None,'选择数据目录','请选择软件数据根目录。建议选择 D 盘等容量充足的位置；账户、项目和资源将集中保存在这里。')
        root=QFileDialog.getExistingDirectory(None,'选择数据根目录')
        if not root:return
        q.setValue('data_root',root)
    if args.demo:seed_demo(Store(root))
    w=Window(root); w.show()
    if args.screenshot:
        QTimer.singleShot(1000,lambda:(w.grab().save(args.screenshot),app.quit()))
    sys.exit(app.exec())
