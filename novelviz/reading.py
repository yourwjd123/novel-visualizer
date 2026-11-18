"""Bookshelf, stable reader anchors and read-only chapter image browsing."""

from __future__ import annotations
import copy
import hashlib
import json
import shutil
from pathlib import Path
from .storage import now, uid, write_json, redact

READER_DEFAULTS = dict(
    mode="scroll",
    font_size=20,
    line_height=1.95,
    width=820,
    font="serif",
    paper="warm",
    images_collapsed=False,
)


class ReadingMixin:
    def bookshelf(self):
        self.require_account()
        books = []
        for meta_file in self.store.projects(self.account):
            root = meta_file.parent.parent.resolve()
            if self.store.account_dir(self.account).resolve() not in root.parents:
                continue
            meta = json.loads(meta_file.read_text("utf-8"))
            config_file = root / "08_项目数据/workspace.json"
            config = (
                json.loads(config_file.read_text("utf-8"))
                if config_file.exists()
                else {}
            )
            cover = config.get("book_cover", "")
            image = ""
            if cover:
                path = (root / cover).resolve()
                if root in path.parents and not path.is_symlink():
                    image = self.reader_thumbnail(path)
            books.append(
                dict(id=meta["id"], name=meta["name"], path=str(root), cover=image)
            )
        return books

    @staticmethod
    def reader_thumbnail(path):
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from PySide6.QtGui import QImageReader
        import base64

        if (
            path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp")
            or not path.is_file()
        ):
            return ""
        reader = QImageReader(str(path))
        size = reader.size()
        if not size.isValid() or size.width() * size.height() > 100_000_000:
            return ""
        reader.setAutoTransform(True)
        reader.setScaledSize(size.scaled(480, 640, Qt.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            return ""
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.WriteOnly)
        image.save(buf, "JPEG", 82)
        return "data:image/jpeg;base64," + base64.b64encode(bytes(data)).decode()

    def set_book_cover(self, path=None):
        self.require_project()
        self.guard()
        if path:
            path = Path(path)
            if not self.reader_thumbnail(path):
                raise ValueError("封面图片无法读取或尺寸过大")
            dest = (
                self.project.path
                / "01_原始资料/封面"
                / ("封面_" + uid() + path.suffix.lower())
            )
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
            self.project.config["book_cover"] = dest.relative_to(
                self.project.path
            ).as_posix()
        else:
            self.project.config.pop("book_cover", None)
        self.project.save_config()

    def reader_preferences(self, data=None):
        self.require_project()
        settings = dict(
            READER_DEFAULTS,
            **self.project.config.get("reader", {}).get("preferences", {}),
        )
        settings.pop("include_candidates", None)
        if data is not None:
            for key in READER_DEFAULTS:
                if key in data:
                    settings[key] = data[key]
            if (
                settings["mode"] not in ("scroll", "pages")
                or settings["font"] not in ("serif", "sans")
                or settings["paper"] not in ("warm", "white", "mint")
            ):
                raise ValueError("阅读设置无效")
            for key, low, high in [
                ("font_size", 14, 36),
                ("line_height", 1.4, 2.6),
                ("width", 420, 1100),
            ]:
                if (
                    type(settings[key]) not in (int, float)
                    or not low <= settings[key] <= high
                ):
                    raise ValueError("阅读参数超出范围")
            for key in ("images_collapsed",):
                if type(settings[key]) is not bool:
                    raise ValueError("阅读开关无效")
            self.project.config.setdefault("reader", {})["preferences"] = settings
            self.save_reader_data()
        return settings

    def save_reader_data(self):
        self.project.save_config()
        write_json(
            self.project.path / "08_项目数据/阅读记录.json",
            redact(self.project.config.get("reader", {}), self.secrets()),
        )

    def reader_anchor(self, chapter, paragraph=1, offset=0, **_):
        chapters = {c["id"] for c in self.project.segments()}
        if chapter not in chapters:
            raise ValueError("阅读章节不存在或已归档")
        paragraphs = self.project.paragraphs(chapter)
        if type(paragraph) is not int or not 1 <= paragraph <= len(paragraphs):
            raise ValueError("阅读位置超出章节")
        expected = _.get("source_hash")
        if (
            expected
            and expected
            != hashlib.sha256(self.project.segment_text(chapter).encode()).hexdigest()
        ):
            raise ValueError("原文已变化，请重新打开章节后保存位置")
        text = paragraphs[paragraph - 1]["text"]
        if type(offset) is not int or not 0 <= offset <= len(text):
            raise ValueError("阅读偏移无效")
        return dict(
            chapter=chapter,
            paragraph=paragraph,
            offset=offset,
            quote=text[offset : offset + 48] or text[-48:],
            quote_offset=offset if offset < len(text) else max(0, len(text) - 48),
            source_hash=hashlib.sha256(
                self.project.segment_text(chapter).encode()
            ).hexdigest(),
        )

    def resolve_reader_anchor(self, anchor):
        if not anchor:
            return None
        anchor = copy.deepcopy(anchor)
        if anchor.get("chapter") not in {c["id"] for c in self.project.segments()}:
            return dict(anchor, stale=True, chapter_missing=True)
        paragraphs = self.project.paragraphs(anchor["chapter"])
        source_hash = hashlib.sha256(
            self.project.segment_text(anchor["chapter"]).encode()
        ).hexdigest()
        if source_hash == anchor.get("source_hash"):
            return dict(anchor, stale=False)
        quote = anchor.get("quote", "")
        matches = []
        if quote:
            for p in paragraphs:
                start = 0
                while (index := p["text"].find(quote, start)) >= 0:
                    matches.append((p["number"], index))
                    start = index + 1
        if len(matches) == 1:
            paragraph, quote_offset = matches[0]
            offset = (
                quote_offset
                + anchor.get("offset", 0)
                - anchor.get("quote_offset", anchor.get("offset", 0))
            )
            return dict(
                anchor,
                paragraph=paragraph,
                offset=offset,
                source_hash=source_hash,
                quote_offset=quote_offset,
                stale=False,
                relocated=True,
            )
        return dict(anchor, stale=True)

    def reader_chapter(self, chapter=None):
        self.require_project()
        chapters = self.project.segments()
        saved = self.resolve_reader_anchor(
            self.project.config.get("reader", {}).get("position")
        )
        chapter = (
            chapter
            or (
                saved.get("chapter")
                if saved and not saved.get("chapter_missing")
                else None
            )
            or (chapters[0]["id"] if chapters else None)
        )
        if chapter and chapter not in {c["id"] for c in chapters}:
            raise ValueError("章节不属于当前小说")
        bookmarks = [
            dict(b, anchor=self.resolve_reader_anchor(b["anchor"]))
            for b in self.project.config.get("reader", {}).get("bookmarks", [])
        ]
        return redact(
            dict(
                chapter=chapter,
                source_hash=hashlib.sha256(
                    self.project.segment_text(chapter).encode()
                ).hexdigest()
                if chapter
                else "",
                chapters=chapters,
                paragraphs=self.project.paragraphs(chapter) if chapter else [],
                position=saved,
                bookmarks=bookmarks,
                preferences=self.reader_preferences(),
                progress=self.project.progress(),
                cover=self.image(self.project.config.get("book_cover")),
            ),
            self.secrets(),
        )

    def save_reading_position(self, data):
        self.require_project()
        anchor = self.reader_anchor(**data)
        self.project.config.setdefault("reader", {})["position"] = dict(
            anchor, updated=now()
        )
        self.save_reader_data()
        return anchor

    def reader_bookmark(self, data):
        self.require_project()
        bookmarks = self.project.config.setdefault("reader", {}).setdefault(
            "bookmarks", []
        )
        if data.get("action") == "delete":
            bookmarks[:] = [b for b in bookmarks if b["id"] != data["id"]]
        else:
            anchor = self.reader_anchor(**data["anchor"])
            label = (
                str(data.get("label", "")).strip()[:100]
                or anchor["quote"][:24]
                or "书签"
            )
            bookmarks.append(dict(id=uid(), label=label, anchor=anchor, created=now()))
        self.save_reader_data()

    def reader_media(self, chapter, start, end):
        self.require_project()
        if chapter not in {c["id"] for c in self.project.segments()}:
            raise ValueError("章节不存在")
        paragraphs = self.project.paragraphs(chapter)
        if (
            type(start) is not int
            or type(end) is not int
            or not 1 <= start <= end <= len(paragraphs)
        ):
            raise ValueError("阅读范围无效")
        scenes = [
            s
            for s in self.project.scenes(chapter)
            if s["start_paragraph"] <= end and s["end_paragraph"] >= start
        ]
        linked = {
            r.get("asset_id")
            for s in scenes
            for r in self.project.requirements(s["id"])
        }
        text = "\n".join(p["text"] for p in paragraphs[start - 1 : end])
        assets = []
        for a in self.project.assets():
            appearances = a.get("appearances", []) + a.get("evidence", [])
            relevant = (
                a["id"] in linked
                or any(
                    e.get("segment") == chapter
                    and type(e.get("paragraph")) is int
                    and start <= e["paragraph"] <= end
                    for e in appearances
                )
                or any(t and t in text for t in [a["name"]] + a.get("aliases", []))
            )
            if not relevant:
                continue
            images = [
                dict(
                    title="主卡",
                    path=a.get("image", ""),
                    state=a.get("review", "待确认"),
                )
            ] + [
                dict(
                    title=v["title"],
                    path=v.get("image", ""),
                    chapter=v.get("chapter"),
                    state="副卡",
                )
                for v in a.get("variants", [])
                if v.get("image")
            ]
            for im in images:
                im["thumbnail"] = self.image(im["path"])
            images = [im for im in images if im["thumbnail"]]
            if images:
                assets.append(
                    dict(id=a["id"], name=a["name"], kind=a["kind"], images=images)
                )
        results = self.project.final_results()
        pictures = []
        for scene in scenes:
            images = [
                dict(title=r["title"], path=r["file"], state="成果", result_id=r["id"])
                for r in results
                if r["scene"] == scene["id"]
            ]
            for im in images:
                im["thumbnail"] = self.image(im["path"])
            images = [im for im in images if im["thumbnail"]]
            if images:
                pictures.append(
                    dict(id=scene["id"], name=scene["title"], images=images)
                )
        return redact(dict(assets=assets, scenes=pictures), self.secrets())
