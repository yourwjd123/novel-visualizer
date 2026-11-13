"""Readable project files plus a transactional SQLite project index. No credentials."""
from __future__ import annotations
import copy
import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

NODES = ['原文整理', '资产解析', '插图方案', '提示词定稿', '插图生成']
DIRS = ['01_原始资料/小说原文', '01_原始资料/过程文档', '01_原始资料/其他附件',
        '02_文本与解析/分段正文', '02_文本与解析/已确认方案', '03_对话记录',
        '04_视觉资产/人物', '04_视觉资产/场景', '04_视觉资产/道具',
        '05_生成任务', '06_最终成果', '07_导出', '08_项目数据']
DEFAULTS = dict(theme='light', background='', background_opacity=18, font_size=14,
                confirm_attachments=True, provider='demo', endpoint='http://localhost:11434/v1',
                model='', system='你是小说插图制作助手。区分原文事实与推测，引用原文证据；不得将推测表述为事实。',
                max_tokens=2048, temperature=0.7, vision=False, comfy_url='http://127.0.0.1:8188')
SETTING_KEYS = set(DEFAULTS)

def uid(): return uuid.uuid4().hex[:12]
def now(): return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
def safe_name(name):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:70]
    if not s: raise ValueError('名称不能为空')
    if s.upper().split('.')[0] in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}: s = '_' + s
    return s

def redact(data,secrets=()):
    if isinstance(data,str):
        for secret in secrets:
            if secret:data=data.replace(secret,'[凭据已移除]')
        return data
    if isinstance(data,list):return [redact(x,secrets) for x in data]
    if isinstance(data,dict):return {k:redact(v,secrets) for k,v in data.items()}
    return data

def write_json(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'); tmp.replace(path)

def clean_settings(data):
    """Allowlist only; imported arbitrary nesting and secret fields never survive."""
    if not isinstance(data, dict): raise ValueError('设置必须是 JSON 对象')
    out = copy.deepcopy(DEFAULTS)
    for k in SETTING_KEYS:
        if k in data and type(data[k]) is type(DEFAULTS[k]): out[k] = data[k]
    if out['theme'] not in ('light','dark','system'): out['theme']='light'
    if out['provider'] not in ('demo','openai'): out['provider']='demo'
    out['max_tokens']=max(1,min(131072,out['max_tokens']))
    out['temperature']=max(0.,min(2.,out['temperature']))
    out['font_size']=max(11,min(24,out['font_size']))
    out['background_opacity']=max(0,min(60,out['background_opacity']))
    return out

def read_document(path):
    p = Path(path); ext=p.suffix.lower()
    if ext in ('.txt','.md'):
        raw=p.read_bytes()
        for enc in ('utf-8-sig','gb18030'):
            try: return raw.decode(enc)
            except UnicodeDecodeError: pass
        raise ValueError('无法识别文本编码，请另存为 UTF-8')
    if ext == '.docx':
        from docx import Document
        return '\n\n'.join(x.text for x in Document(str(p)).paragraphs if x.text.strip())
    if ext == '.epub':
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup
        book=epub.read_epub(str(p), options={'ignore_ncx':True})
        docs={i.get_id():i for i in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)}
        ordered=[docs[i] for i,_ in book.spine if i in docs]
        return '\n\n'.join(BeautifulSoup(i.get_content(),'html.parser').get_text('\n',strip=True) for i in ordered)
    raise ValueError('正文仅支持 TXT、MD、DOCX、EPUB；其他文件可作为附件保存')

class Store:
    def __init__(self, root):
        self.root=Path(root).resolve(); self.root.mkdir(parents=True,exist_ok=True)
        self.index=self.root/'accounts.json'
        self.accounts=json.loads(self.index.read_text('utf-8')) if self.index.exists() else []
        if not self.accounts: self.create_account('默认账户')
    def save(self): write_json(self.index,self.accounts)
    def account_dir(self,a): return self.root/a['folder']
    def create_account(self,name):
        a=dict(id=uid(),name=name.strip(),folder=safe_name(name)+'_'+uid())
        p=self.account_dir(a); p.mkdir(parents=True)
        for d in ('账户设置','界面资源','通用导出','项目'): (p/d).mkdir()
        write_json(p/'账户设置/settings.json',DEFAULTS)
        self.accounts.append(a); self.save(); return a
    def rename_account(self,a,name):
        safe_name(name); a['name']=name.strip(); self.save()
    def delete_account(self,a):
        self.accounts.remove(a); self.save()
        # Keep user projects. Move account out of active list without destructive deletion.
        archive=self.root/'已归档账户'; archive.mkdir(exist_ok=True)
        shutil.move(str(self.account_dir(a)),str(archive/(a['folder']+'_'+uid())))
    def settings(self,a):
        return clean_settings(json.loads((self.account_dir(a)/'账户设置/settings.json').read_text('utf-8')))
    def save_settings(self,a,s): write_json(self.account_dir(a)/'账户设置/settings.json',clean_settings(s))
    def export_settings(self,a,path,secrets=()):
        data=self.settings(a); data['background']=''
        # Connection URLs may contain embedded authentication. Never share them.
        data['endpoint']=DEFAULTS['endpoint']; data['comfy_url']=DEFAULTS['comfy_url']
        data=redact(data,secrets)
        write_json(path,dict(format='novelviz-settings-v1',settings=data))
    def import_settings(self,a,path):
        data=json.loads(Path(path).read_text('utf-8'))
        if data.get('format')!='novelviz-settings-v1': raise ValueError('不是本软件的设置导出文件')
        s=clean_settings(data['settings']); s['background']=''
        s['endpoint']=DEFAULTS['endpoint']; s['comfy_url']=DEFAULTS['comfy_url']
        self.save_settings(a,s)
    def projects(self,a):
        return sorted((self.account_dir(a)/'项目').glob('*/08_项目数据/project.json'))
    def create_project(self,a,name):
        return Project.create(self.account_dir(a)/'项目'/(safe_name(name)+'_'+uid()),name)

class Project:
    def __init__(self,path):
        self.path=Path(path).resolve(); self.secrets=[]
        self.meta=json.loads((self.path/'08_项目数据/project.json').read_text('utf-8'))
        if self.meta.get('schema')!=1:raise ValueError('项目格式版本不受支持，请使用匹配版本的软件')
        self.db=sqlite3.connect(self.path/'08_项目数据/index.sqlite')
        if self.db.execute('PRAGMA user_version').fetchone()[0] not in (0,1):
            self.db.close(); raise ValueError('数据库版本不受支持，未执行修改')
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
          PRAGMA user_version=1;
          CREATE TABLE IF NOT EXISTS segments(id TEXT PRIMARY KEY,name TEXT,file TEXT,source TEXT,created TEXT);
          CREATE TABLE IF NOT EXISTS nodes(segment TEXT,node INTEGER,data TEXT,PRIMARY KEY(segment,node));
          CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,data TEXT);
          CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,data TEXT);
        '''); self.db.commit()
        # A crash must never cause an automatic resubmission.
        for j in self.jobs():
            if j['status'] in ('queued','running'):
                j.update(status='unknown',error='程序上次退出时任务未完成。请查询远端历史；不会自动重新提交。')
                self.save_job(j)
                if 'segment' in j and 'node' in j:
                    d=self.load_node(j['segment'],j['node']); d['status']='状态未知'; self.save_node(j['segment'],j['node'],d)
    @classmethod
    def create(cls,path,name):
        path=Path(path)
        for d in DIRS: (path/d).mkdir(parents=True,exist_ok=True)
        write_json(path/'08_项目数据/project.json',dict(schema=1,id=uid(),name=name,created=now()))
        (path/'目录说明.md').write_text('# 项目目录\n\n01 原始文件副本；02 分段正文与确认方案；03 对话；04 共享资产；05 任务快照；06 用户选定成果；07 导出；08 软件索引。\n\n可通过软件重新读取外部修改的正文。历史任务和确认方案按版本保存。请勿手工编辑 SQLite。凭据不保存在项目中。\n',encoding='utf-8')
        return cls(path)
    def close(self): self.db.close()
    def segments(self): return [dict(r) for r in self.db.execute('SELECT * FROM segments ORDER BY rowid')]
    def add_segment(self,name,text,source=None):
        if not text.strip(): raise ValueError('正文不能为空')
        sid=uid(); dest=Path('02_文本与解析/分段正文')/(safe_name(name)+'_'+sid+'.txt')
        src=''
        if source:
            p=Path(source); raw=p.read_bytes(); digest=hashlib.sha256(raw).hexdigest()
            src=str(Path('01_原始资料/小说原文')/(safe_name(p.stem)+'_'+digest[:10]+p.suffix))
            if not (self.path/src).exists(): shutil.copy2(p,self.path/src)
        (self.path/dest).write_text(text,encoding='utf-8')
        self.db.execute('INSERT INTO segments VALUES(?,?,?,?,?)',(sid,name,dest.as_posix(),src,now())); self.db.commit()
        write_json(self.path/'02_文本与解析/分段正文/片段索引.json',self.segments()); return sid
    def segment_text(self,sid):
        r=self.db.execute('SELECT file FROM segments WHERE id=?',(sid,)).fetchone()
        return (self.path/r['file']).read_text('utf-8')
    def load_node(self,sid,node):
        r=self.db.execute('SELECT data FROM nodes WHERE segment=? AND node=?',(sid,node)).fetchone()
        return json.loads(r['data']) if r else dict(messages=[],final='',status='未开始',revision=0,params={})
    def save_node(self,sid,node,data):
        data=redact(data,self.secrets)
        self.db.execute('INSERT OR REPLACE INTO nodes VALUES(?,?,?)',(sid,node,json.dumps(data,ensure_ascii=False))); self.db.commit()
        folder=self.path/'03_对话记录'/sid; folder.mkdir(exist_ok=True)
        write_json(folder/(str(node+1)+'_'+NODES[node]+'.json'),data)
        (folder/(str(node+1)+'_'+NODES[node]+'.md')).write_text(self.transcript(data,'md'),encoding='utf-8')
    def confirm(self,sid,node,data):
        if not data['final'].strip(): raise ValueError('请先填写最终方案')
        data['revision']+=1; data['status']='已确认'; self.save_node(sid,node,data)
        base=self.path/'02_文本与解析/已确认方案'/sid; base.mkdir(exist_ok=True)
        dest=base/f'{node+1}_{NODES[node]}_v{data["revision"]}_{uid()}.md'
        dest.write_text(redact(data['final'],self.secrets),encoding='utf-8'); return dest
    @staticmethod
    def transcript(data,fmt='md',only_output=False):
        chunks=[]
        for m in data['messages']:
            if only_output and m['role']!='assistant': continue
            label={'user':'用户','assistant':'模型'}.get(m['role'],m['role'])
            chunks.append((f'## {label} · {m.get("time", "")}\n\n' if fmt=='md' else f'【{label}】 {m.get("time", "")}\n')+m['content'])
        return '\n\n'.join(chunks)
    def add_attachment(self,path):
        p=Path(path); dest=self.path/'01_原始资料/其他附件'/(p.stem+'_'+uid()+p.suffix)
        shutil.copy2(p,dest); return dest.relative_to(self.path).as_posix()
    def assets(self): return [json.loads(r[0]) for r in self.db.execute('SELECT data FROM assets ORDER BY rowid')]
    def save_asset(self,a):
        a=redact(a,self.secrets)
        if not a.get('name','').strip(): raise ValueError('资产名称不能为空')
        a.setdefault('id',uid()); a['updated']=now()
        self.db.execute('INSERT OR REPLACE INTO assets VALUES(?,?)',(a['id'],json.dumps(a,ensure_ascii=False))); self.db.commit()
        folder=self.path/'04_视觉资产'/a['kind']/(safe_name(a['name'])+'_'+a['id']); folder.mkdir(exist_ok=True)
        write_json(folder/('档案_'+uid()+'.json'),a)
        (folder/'当前档案.md').write_text(f'# {a["name"]}\n\n来源：{a["source"]}\n审核：{a["review"]}\n\n{a["description"]}',encoding='utf-8')
    def save_job(self,j):
        j=redact(j,self.secrets)
        self.db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?)',(j['id'],json.dumps(j,ensure_ascii=False))); self.db.commit()
        write_json(self.path/'05_生成任务'/j['id']/'任务记录.json',j)
    def jobs(self): return [json.loads(r[0]) for r in self.db.execute('SELECT data FROM jobs ORDER BY rowid DESC')]
