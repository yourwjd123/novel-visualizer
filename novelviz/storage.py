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

NODES = [
    "原文整理",
    "资产解析",
    "插图方案",
    "提示词定稿",
    "插图生成",
    "资产设定图",
    "图片审核",
    "全过程规划",
]
DIRS = [
    "01_原始资料/小说原文",
    "01_原始资料/过程文档",
    "01_原始资料/其他附件",
    "02_文本与解析/分段正文",
    "02_文本与解析/已确认方案",
    "03_对话记录",
    "04_视觉资产/人物",
    "04_视觉资产/场景",
    "04_视觉资产/道具",
    "05_生成任务",
    "06_最终成果",
    "07_导出",
    "08_项目数据",
]
DEFAULTS = dict(
    theme="light",
    background="",
    background_opacity=18,
    font_size=14,
    sidebar_visible=True,
    project_rules="",
    confirm_attachments=True,
    provider="demo",
    endpoint="http://localhost:11434/v1",
    model="",
    system="你是小说插图制作助手。区分原文事实与推测，引用原文证据；不得将推测表述为事实。",
    max_tokens=2048,
    temperature=0.7,
    vision=False,
    comfy_url="http://127.0.0.1:8188",
)
SETTING_KEYS = set(DEFAULTS)


def uid():
    return uuid.uuid4().hex[:12]


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def safe_name(name):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:70]
    if not s:
        raise ValueError("名称不能为空")
    if s.upper().split(".")[0] in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        s = "_" + s
    return s


def redact(data, secrets=()):
    if isinstance(data, str):
        for secret in secrets:
            if secret:
                data = data.replace(secret, "[凭据已移除]")
        return data
    if isinstance(data, list):
        return [redact(x, secrets) for x in data]
    if isinstance(data, dict):
        return {k: redact(v, secrets) for k, v in data.items()}
    return data


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def clean_settings(data):
    """Allowlist only; imported arbitrary nesting and secret fields never survive."""
    if not isinstance(data, dict):
        raise ValueError("设置必须是 JSON 对象")
    out = copy.deepcopy(DEFAULTS)
    for k in SETTING_KEYS:
        if k in data and type(data[k]) is type(DEFAULTS[k]):
            out[k] = data[k]
    if out["theme"] not in ("light", "dark", "system"):
        out["theme"] = "light"
    if out["provider"] not in ("demo", "openai"):
        out["provider"] = "demo"
    out["max_tokens"] = max(1, min(131072, out["max_tokens"]))
    out["temperature"] = max(0.0, min(2.0, out["temperature"]))
    out["font_size"] = max(11, min(24, out["font_size"]))
    out["background_opacity"] = max(0, min(60, out["background_opacity"]))
    return out


def read_document(path):
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".txt", ".md"):
        raw = p.read_bytes()
        for enc in ("utf-8-sig", "gb18030"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                pass
        raise ValueError("无法识别文本编码，请另存为 UTF-8")
    if ext == ".docx":
        from docx import Document

        return "\n\n".join(
            x.text for x in Document(str(p)).paragraphs if x.text.strip()
        )
    if ext == ".epub":
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup

        book = epub.read_epub(str(p), options={"ignore_ncx": True})
        docs = {i.get_id(): i for i in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)}
        ordered = [docs[i] for i, _ in book.spine if i in docs]
        return "\n\n".join(
            BeautifulSoup(i.get_content(), "html.parser").get_text("\n", strip=True)
            for i in ordered
        )
    raise ValueError("正文仅支持 TXT、MD、DOCX、EPUB；其他文件可作为附件保存")


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index = self.root / "accounts.json"
        self.accounts = (
            json.loads(self.index.read_text("utf-8")) if self.index.exists() else []
        )
        if not self.accounts:
            self.create_account("默认账户")

    def save(self):
        write_json(self.index, self.accounts)

    def account_dir(self, a):
        return self.root / a["folder"]

    def create_account(self, name):
        a = dict(id=uid(), name=name.strip(), folder=safe_name(name) + "_" + uid())
        p = self.account_dir(a)
        p.mkdir(parents=True)
        for d in ("账户设置", "界面资源", "通用导出", "项目"):
            (p / d).mkdir()
        write_json(p / "账户设置/settings.json", DEFAULTS)
        self.accounts.append(a)
        self.save()
        return a

    def rename_account(self, a, name):
        safe_name(name)
        a["name"] = name.strip()
        self.save()

    def delete_account(self, a):
        self.accounts.remove(a)
        self.save()
        # Keep user projects. Move account out of active list without destructive deletion.
        archive = self.root / "已归档账户"
        archive.mkdir(exist_ok=True)
        shutil.move(
            str(self.account_dir(a)), str(archive / (a["folder"] + "_" + uid()))
        )

    def settings(self, a):
        return clean_settings(
            json.loads(
                (self.account_dir(a) / "账户设置/settings.json").read_text("utf-8")
            )
        )

    def save_settings(self, a, s):
        write_json(self.account_dir(a) / "账户设置/settings.json", clean_settings(s))

    def export_settings(self, a, path, secrets=()):
        data = self.settings(a)
        data["background"] = ""
        # Connection URLs may contain embedded authentication. Never share them.
        data["endpoint"] = DEFAULTS["endpoint"]
        data["comfy_url"] = DEFAULTS["comfy_url"]
        data = redact(data, secrets)
        profiles = []
        for c in self.connections(a):
            c = copy.deepcopy(c)
            c["endpoint"] = (
                ""
                if c["kind"] == "demo"
                else (
                    "http://localhost:8188"
                    if c["kind"] == "comfy"
                    else "http://localhost:11434/v1"
                )
            )
            c["legacy"] = False
            profiles.append(c)
        write_json(
            path,
            redact(
                dict(
                    format="novelviz-settings-v2",
                    settings=data,
                    connections=profiles,
                    templates=self.templates(a),
                ),
                secrets,
            ),
        )

    def import_settings(self, a, path):
        data = json.loads(Path(path).read_text("utf-8"))
        if data.get("format") not in ("novelviz-settings-v1", "novelviz-settings-v2"):
            raise ValueError("不是本软件的设置导出文件")
        s = clean_settings(data["settings"])
        s["background"] = ""
        s["endpoint"] = DEFAULTS["endpoint"]
        s["comfy_url"] = DEFAULTS["comfy_url"]
        profiles = []
        templates = []
        if data.get("format") == "novelviz-settings-v2":
            from .connections import clean_profile

            for c in data.get("connections", []):
                c = copy.deepcopy(c)
                c["id"] = "import-" + uid()
                c["legacy"] = False
                profiles.append(clean_profile(c))
            from .prompts import DEFAULT_IDS

            for t in data.get("templates", []):
                if (
                    not isinstance(t, dict)
                    or type(t.get("node")) is not int
                    or not 0 <= t["node"] < len(DEFAULT_IDS)
                    or t.get("format") not in ("text", "scenes", "assets")
                    or (t.get("format") == "scenes" and t["node"] != 0)
                    or (t.get("format") == "assets" and t["node"] != 1)
                    or not all(
                        isinstance(t.get(k), str) and t[k].strip()
                        for k in ("name", "body", "version")
                    )
                ):
                    raise ValueError("模板格式错误")
                t = copy.deepcopy(t)
                t["id"] = "import-" + uid()
                templates.append(t)
        self.save_settings(a, s)
        for c in profiles:
            self.save_connection(a, c)
        for t in templates:
            self.save_template(a, t)

    def connections(self, a):
        from .connections import defaults, clean_profile

        path = self.account_dir(a) / "账户设置/connections.json"
        if not path.exists():
            write_json(path, defaults(self.settings(a)))
        return [clean_profile(x) for x in json.loads(path.read_text("utf-8"))]

    def save_connection(self, a, profile):
        from .connections import clean_profile

        profile = clean_profile(profile)
        rows = self.connections(a)
        rows = [x for x in rows if x["id"] != profile["id"]] + [profile]
        write_json(self.account_dir(a) / "账户设置/connections.json", rows)
        return profile

    def templates(self, a, node=None):
        from .prompts import builtins

        path = self.account_dir(a) / "账户设置/templates.json"
        custom = json.loads(path.read_text("utf-8")) if path.exists() else []
        merged = {t["id"]: t for t in builtins()}
        for t in custom:
            merged[t["id"]] = t
        return [t for t in merged.values() if node is None or t["node"] == node]

    def save_template(self, a, t):
        from .prompts import DEFAULT_IDS

        if (
            not isinstance(t, dict)
            or type(t.get("node")) is not int
            or not 0 <= t["node"] < len(DEFAULT_IDS)
        ):
            raise ValueError("模板节点无效")
        if not t.get("name", "").strip() or not t.get("body", "").strip():
            raise ValueError("模板名称和正文不能为空")
        if (
            t.get("format") not in ("text", "scenes", "assets")
            or (t["format"] == "scenes" and t["node"] != 0)
            or (t["format"] == "assets" and t["node"] != 1)
        ):
            raise ValueError("模板输出格式与节点不匹配")
        clean = {
            k: copy.deepcopy(t[k])
            for k in ("id", "name", "node", "format", "body", "version")
        }
        if not isinstance(clean["id"], str) or not clean["id"]:
            raise ValueError("模板ID无效")
        path = self.account_dir(a) / "账户设置/templates.json"
        rows = json.loads(path.read_text("utf-8")) if path.exists() else []
        rows = [x for x in rows if x["id"] != clean["id"]] + [clean]
        write_json(path, rows)
        return clean

    def reset_template(self, a, tid):
        path = self.account_dir(a) / "账户设置/templates.json"
        if path.exists():
            write_json(
                path, [x for x in json.loads(path.read_text("utf-8")) if x["id"] != tid]
            )

    def projects(self, a):
        return sorted((self.account_dir(a) / "项目").glob("*/08_项目数据/project.json"))

    def create_project(self, a, name):
        return Project.create(
            self.account_dir(a) / "项目" / (safe_name(name) + "_" + uid()), name
        )


class Project:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.secrets = []
        self.meta = json.loads(
            (self.path / "08_项目数据/project.json").read_text("utf-8")
        )
        version = self.meta.get("schema")
        if version not in (1, 2):
            raise ValueError("项目格式版本不受支持，请使用匹配版本的软件")
        self.db = sqlite3.connect(self.path / "08_项目数据/index.sqlite")
        db_version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if db_version not in (0, 1, 2):
            self.db.close()
            raise ValueError("数据库版本不受支持，未执行修改")
        self.db.row_factory = sqlite3.Row
        if version == 1:
            import zipfile

            dest = self.path / "08_项目数据/迁移备份" / ("schema1_" + uid() + ".zip")
            dest.parent.mkdir(exist_ok=True)
            self.db.commit()
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(self.path / "08_项目数据/project.json", "project.json")
                z.write(self.path / "08_项目数据/index.sqlite", "index.sqlite")
        self.db.executescript("""CREATE TABLE IF NOT EXISTS segments(id TEXT PRIMARY KEY,name TEXT,file TEXT,source TEXT,created TEXT);
          CREATE TABLE IF NOT EXISTS nodes(segment TEXT,node INTEGER,data TEXT,PRIMARY KEY(segment,node));
          CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,data TEXT);
          CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,data TEXT);
          CREATE TABLE IF NOT EXISTS scenes(id TEXT PRIMARY KEY,segment TEXT,data TEXT,archived INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS scene_assets(scene TEXT,slot TEXT,data TEXT,PRIMARY KEY(scene,slot));
          PRAGMA user_version=2;""")
        self.db.commit()
        if version == 1:
            self.meta["schema"] = 2
            self.meta["migrated_from"] = 1
            write_json(self.path / "08_项目数据/project.json", self.meta)
        self.config_path = self.path / "08_项目数据/workspace.json"
        self.config = (
            json.loads(self.config_path.read_text("utf-8"))
            if self.config_path.exists()
            else {"connections": {}, "image_connection": "image-default", "rules": ""}
        )
        # A crash must never cause an automatic resubmission.
        for j in self.jobs():
            if j["status"] in ("queued", "running"):
                j.update(
                    status="unknown",
                    error="程序上次退出时任务未完成。请查询远端历史；不会自动重新提交。",
                )
                self.save_job(j)
                if "segment" in j and "node" in j:
                    d = self.load_node(j.get("scope", j["segment"]), j["node"])
                    d["status"] = "状态未知"
                    self.save_node(j.get("scope", j["segment"]), j["node"], d)

    @classmethod
    def create(cls, path, name):
        path = Path(path)
        for d in DIRS:
            (path / d).mkdir(parents=True, exist_ok=True)
        write_json(
            path / "08_项目数据/project.json",
            dict(schema=2, id=uid(), name=name, created=now()),
        )
        (path / "目录说明.md").write_text(
            "# 项目目录\n\n01 原始文件副本；02 分段正文与确认方案；03 对话；04 共享资产；05 任务快照；06 用户选定成果；07 导出；08 软件索引。\n\n可通过软件重新读取外部修改的正文。历史任务和确认方案按版本保存。请勿手工编辑 SQLite。凭据不保存在项目中。\n",
            encoding="utf-8",
        )
        return cls(path)

    def close(self):
        self.db.close()

    def save_config(self):
        write_json(self.config_path, redact(self.config, self.secrets))

    def paragraphs(self, sid):
        text = self.segment_text(sid)
        return [
            dict(number=i + 1, text=m.group(), start=m.start(), end=m.end())
            for i, m in enumerate(re.finditer(r"\S.*?(?=\n\s*\n|\Z)", text, re.S))
        ]

    def scenes(self, sid, archived=False):
        return [
            json.loads(r[0])
            for r in self.db.execute(
                "SELECT data FROM scenes WHERE segment=? AND archived=? ORDER BY rowid",
                (sid, int(archived)),
            )
        ]

    def scene(self, scene_id):
        r = self.db.execute(
            "SELECT data FROM scenes WHERE id=?", (scene_id,)
        ).fetchone()
        return json.loads(r[0]) if r else None

    def ensure_scene(self, sid):
        if self.scenes(sid):
            return
        ps = self.paragraphs(sid)
        if not ps:
            return
        name = next(r["name"] for r in self.segments() if r["id"] == sid)
        scene = self.save_scene(
            dict(
                segment=sid,
                title=name,
                summary="未拆分原文，可手工编辑或由模型生成拆分候选。",
                start_paragraph=1,
                end_paragraph=len(ps),
                origin="原始片段",
            )
        )
        for n in range(1, 5):
            old = self.load_node(sid, n)
            if old["messages"] or old["final"]:
                old["migrated_from_scope"] = sid
                self.save_node(scene["id"], n, old)

    def save_scene(self, data, invalidate=True):
        from .prompts import validate_requirements

        data = redact(copy.deepcopy(data), self.secrets)
        sid = data["segment"]
        ps = self.paragraphs(sid)
        a, b = data.get("start_paragraph"), data.get("end_paragraph")
        if type(a) is not int or type(b) is not int or not 1 <= a <= b <= len(ps):
            raise ValueError("情节段落范围无效")
        if not data.get("title", "").strip():
            raise ValueError("情节标题不能为空")
        data.setdefault("summary", "")
        data.setdefault("id", uid())
        old = self.scene(data["id"])
        data.setdefault("revision", 0)
        data["revision"] += 1
        data["updated"] = now()
        text = self.segment_text(sid)
        data["source_hash"] = hashlib.sha256(text.encode()).hexdigest()
        data["source_text"] = text[ps[a - 1]["start"] : ps[b - 1]["end"]]
        data["start_offset"] = ps[a - 1]["start"]
        data["end_offset"] = ps[b - 1]["end"]
        data.setdefault("archived", False)
        required = data.pop("required_assets", None)
        if required is not None:
            validate_requirements(required)
        self.db.execute(
            "INSERT OR REPLACE INTO scenes VALUES(?,?,?,?)",
            (
                data["id"],
                sid,
                json.dumps(data, ensure_ascii=False),
                int(data["archived"]),
            ),
        )
        self.db.commit()
        folder = self.path / "02_文本与解析/情节模块" / data["id"]
        write_json(folder / "当前情节.json", data)
        write_json(folder / f"版本_{data['revision']}.json", data)
        if required is not None:
            self.set_requirements(data["id"], required)
        if old and invalidate:
            self.invalidate(data["id"], 1, "情节内容已修改")
        return data

    def apply_scene_candidates(self, sid, rows):
        from .prompts import validate_scenes

        validate_scenes({"scenes": rows}, len(self.paragraphs(sid)))
        for old in self.scenes(sid):
            old["archived"] = True
            self.db.execute(
                "UPDATE scenes SET data=?,archived=1 WHERE id=?",
                (json.dumps(old, ensure_ascii=False), old["id"]),
            )
        self.db.commit()
        for old in self.scenes(sid, True):
            write_json(
                self.path / "02_文本与解析/情节模块" / old["id"] / "当前情节.json", old
            )
        return [
            self.save_scene(
                dict(
                    {
                        k: v
                        for k, v in r.items()
                        if k
                        in (
                            "title",
                            "summary",
                            "start_paragraph",
                            "end_paragraph",
                            "required_assets",
                            "visual_moment",
                            "rationale",
                            "questions",
                        )
                    },
                    segment=sid,
                    origin="用户审核的拆分候选",
                ),
                False,
            )
            for r in rows
        ]

    def set_requirements(self, scene_id, rows):
        from .prompts import validate_requirements

        if not self.scene(scene_id):
            raise ValueError("情节不存在")
        validate_requirements(rows)
        for r in rows:
            if r.get("asset_id"):
                a = next((a for a in self.assets() if a["id"] == r["asset_id"]), None)
                if not a or a["kind"] != r["kind"]:
                    raise ValueError("关联资产不存在或类型不匹配")
        self.db.execute("DELETE FROM scene_assets WHERE scene=?", (scene_id,))
        stored = []
        for row in rows:
            r = copy.deepcopy(row)
            r.setdefault("slot", uid())
            stored.append(r)
            self.db.execute(
                "INSERT INTO scene_assets VALUES(?,?,?)",
                (scene_id, r["slot"], json.dumps(r, ensure_ascii=False)),
            )
        self.db.commit()
        write_json(
            self.path / "02_文本与解析/情节模块" / scene_id / "资产关联.json", stored
        )
        self.invalidate(scene_id, 2, "资产关联已调整")

    def requirements(self, scene_id):
        return [
            json.loads(r[0])
            for r in self.db.execute(
                "SELECT data FROM scene_assets WHERE scene=? ORDER BY rowid",
                (scene_id,),
            )
        ]

    def scene_assets(self, scene_id):
        assets = {a["id"]: a for a in self.assets()}
        out = []
        for r in self.requirements(scene_id):
            r = copy.deepcopy(r)
            a = assets.get(r.get("asset_id"))
            r["asset"] = a
            if not a:
                r["problem"] = "缺少档案"
            elif a["review"] not in ("已确认", "已锁定"):
                r["problem"] = "设定待确认"
            elif not a.get("image"):
                r["problem"] = "缺少参考图"
            elif not (self.path / a["image"]).is_file():
                r["problem"] = "参考图文件丢失"
            else:
                r["problem"] = ""
            out.append(r)
        return out

    def invalidate(self, scope, node, reason):
        for r in list(
            self.db.execute(
                "SELECT node,data FROM nodes WHERE segment=? AND node>=?", (scope, node)
            )
        ):
            d = json.loads(r["data"])
            if d["status"] == "已确认":
                d["status"] = "需复核"
                d["stale_reason"] = reason
                self.save_node(scope, r["node"], d)

    def invalidate_dependents(self, scope, node, sid):
        dependencies = {
            0: [1, 2, 3, 4, 5, 6],
            1: [2, 3, 4, 5, 6],
            5: [2, 3, 4, 6],
            2: [3, 4, 6],
            3: [4, 6],
            4: [6],
            6: [],
            7: [],
        }
        scopes = [s["id"] for s in self.scenes(sid)] if node == 0 else [scope]
        for target in scopes:
            for n in dependencies.get(node, []):
                d = self.load_node(target, n)
                if d["status"] == "已确认":
                    d.update(status="需复核", stale_reason=NODES[node] + "已更新")
                    self.save_node(target, n, d)

    def save_asset_image(self, asset, path):
        source = Path(path)
        if source.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise ValueError("参考图仅支持 PNG/JPG/WEBP")
        dest = (
            self.path
            / "04_视觉资产"
            / asset["kind"]
            / (safe_name(asset["name"]) + "_" + asset["id"])
            / ("参考图_" + uid() + source.suffix.lower())
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        return dest.relative_to(self.path).as_posix()

    def segments(self):
        return [
            dict(r) for r in self.db.execute("SELECT * FROM segments ORDER BY rowid")
        ]

    def add_segment(self, name, text, source=None):
        if not text.strip():
            raise ValueError("正文不能为空")
        sid = uid()
        dest = Path("02_文本与解析/分段正文") / (safe_name(name) + "_" + sid + ".txt")
        src = ""
        if source:
            p = Path(source)
            raw = p.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            src = str(
                Path("01_原始资料/小说原文")
                / (safe_name(p.stem) + "_" + digest[:10] + p.suffix)
            )
            if not (self.path / src).exists():
                shutil.copy2(p, self.path / src)
        (self.path / dest).write_text(text, encoding="utf-8")
        self.db.execute(
            "INSERT INTO segments VALUES(?,?,?,?,?)",
            (sid, name, dest.as_posix(), src, now()),
        )
        self.db.commit()
        write_json(self.path / "02_文本与解析/分段正文/片段索引.json", self.segments())
        return sid

    def segment_text(self, sid):
        r = self.db.execute("SELECT file FROM segments WHERE id=?", (sid,)).fetchone()
        return (self.path / r["file"]).read_text("utf-8")

    def load_node(self, sid, node):
        r = self.db.execute(
            "SELECT data FROM nodes WHERE segment=? AND node=?", (sid, node)
        ).fetchone()
        return (
            json.loads(r["data"])
            if r
            else dict(messages=[], final="", status="未开始", revision=0, params={})
        )

    def save_node(self, sid, node, data):
        data = redact(data, self.secrets)
        self.db.execute(
            "INSERT OR REPLACE INTO nodes VALUES(?,?,?)",
            (sid, node, json.dumps(data, ensure_ascii=False)),
        )
        self.db.commit()
        folder = self.path / "03_对话记录" / sid
        folder.mkdir(exist_ok=True)
        write_json(folder / (str(node + 1) + "_" + NODES[node] + ".json"), data)
        (folder / (str(node + 1) + "_" + NODES[node] + ".md")).write_text(
            self.transcript(data, "md"), encoding="utf-8"
        )

    def confirm(self, sid, node, data):
        if not data["final"].strip():
            raise ValueError("请先填写最终方案")
        data["revision"] += 1
        data["status"] = "已确认"
        self.save_node(sid, node, data)
        base = self.path / "02_文本与解析/已确认方案" / sid
        base.mkdir(exist_ok=True)
        dest = base / f"{node + 1}_{NODES[node]}_v{data['revision']}_{uid()}.md"
        dest.write_text(redact(data["final"], self.secrets), encoding="utf-8")
        return dest

    @staticmethod
    def transcript(data, fmt="md", only_output=False):
        chunks = []
        for m in data["messages"]:
            if only_output and m["role"] != "assistant":
                continue
            label = {"user": "用户", "assistant": "模型"}.get(m["role"], m["role"])
            chunks.append(
                (
                    f"## {label} · {m.get('time', '')}\n\n"
                    if fmt == "md"
                    else f"【{label}】 {m.get('time', '')}\n"
                )
                + m["content"]
            )
        return "\n\n".join(chunks)

    def add_attachment(self, path):
        p = Path(path)
        dest = self.path / "01_原始资料/其他附件" / (p.stem + "_" + uid() + p.suffix)
        shutil.copy2(p, dest)
        return dest.relative_to(self.path).as_posix()

    def assets(self):
        return [
            json.loads(r[0])
            for r in self.db.execute("SELECT data FROM assets ORDER BY rowid")
        ]

    def save_asset(self, a):
        a = redact(a, self.secrets)
        if not a.get("name", "").strip():
            raise ValueError("资产名称不能为空")
        a.setdefault("id", uid())
        a["updated"] = now()
        a["revision"] = a.get("revision", 0) + 1
        if a.get("kind") not in ("人物", "场景", "道具"):
            raise ValueError("资产类型无效")
        if a.get("image"):
            image = (self.path / a["image"]).resolve()
            if self.path not in image.parents:
                raise ValueError("资产参考图必须位于项目目录")
        self.db.execute(
            "INSERT OR REPLACE INTO assets VALUES(?,?)",
            (a["id"], json.dumps(a, ensure_ascii=False)),
        )
        self.db.commit()
        folder = (
            self.path
            / "04_视觉资产"
            / a["kind"]
            / (safe_name(a["name"]) + "_" + a["id"])
        )
        folder.mkdir(exist_ok=True)
        write_json(folder / ("档案_" + uid() + ".json"), a)
        for row in self.db.execute("SELECT scene,data FROM scene_assets"):
            if json.loads(row["data"]).get("asset_id") == a["id"]:
                self.invalidate(row["scene"], 2, "关联资产已更新")
        (folder / "当前档案.md").write_text(
            f"# {a['name']}\n\n来源：{a['source']}\n审核：{a['review']}\n\n{a['description']}",
            encoding="utf-8",
        )
        return a

    def save_job(self, j):
        j = redact(j, self.secrets)
        self.db.execute(
            "INSERT OR REPLACE INTO jobs VALUES(?,?)",
            (j["id"], json.dumps(j, ensure_ascii=False)),
        )
        self.db.commit()
        write_json(self.path / "05_生成任务" / j["id"] / "任务记录.json", j)

    def jobs(self):
        return [
            json.loads(r[0])
            for r in self.db.execute("SELECT data FROM jobs ORDER BY rowid DESC")
        ]
