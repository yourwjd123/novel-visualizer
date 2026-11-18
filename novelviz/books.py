"""Account-scoped whole-book recycling. Files outside projects are never touched."""

import json
import shutil
from .storage import now, uid, write_json, redact


class BooksMixin:
    def book_info(self, identity):
        self.require_account()
        for meta in self.store.projects(self.account):
            data = json.loads(meta.read_text("utf-8"))
            if data["id"] == identity:
                root = meta.parent.parent
                self._safe_book_tree(
                    root, self.store.account_dir(self.account) / "项目"
                )
                return dict(
                    id=identity,
                    name=data["name"],
                    path=str(root),
                    bytes=sum(p.stat().st_size for p in root.rglob("*") if p.is_file()),
                )
        raise ValueError("小说不存在或不属于当前账户")

    @staticmethod
    def _safe_book_tree(root, parent):
        if root.is_symlink() or root.resolve().parent != parent.resolve():
            raise ValueError("项目目录不安全，已拒绝操作")
        if any(p.is_symlink() for p in root.rglob("*")):
            raise ValueError("项目包含符号链接，请先处理后再删除")

    def book_delete(self, identity, name, permanent=False):
        self.guard()
        info = self.book_info(identity)
        if name != info["name"]:
            raise ValueError("输入书名与完整书名不一致")
        from pathlib import Path

        root = Path(info["path"])
        active = self.project and self.project.meta["id"] == identity
        if active:
            self.close()
            self.segment = self.scene = None
            self.media_cache.clear()
        if permanent:
            shutil.rmtree(root)
        else:
            bucket = self.store.account_dir(self.account) / "小说回收站" / uid()
            bucket.mkdir(parents=True)
            try:
                write_json(
                    bucket / "删除信息.json",
                    dict(
                        id=identity,
                        name=info["name"],
                        deleted=now(),
                        folder=root.name,
                        bytes=info["bytes"],
                    ),
                )
                shutil.move(str(root), str(bucket / "项目"))
            except Exception:
                if not (bucket / "项目").exists():
                    shutil.rmtree(bucket)
                raise

    def book_trash(self):
        self.require_account()
        parent = self.store.account_dir(self.account) / "小说回收站"
        rows = []
        for f in parent.glob("*/删除信息.json"):
            if f.parent.is_symlink() or f.is_symlink():
                continue
            r = json.loads(f.read_text("utf-8"))
            if (f.parent / "项目").is_dir():
                rows.append(dict(r, trash_id=f.parent.name))
        return sorted(rows, key=lambda r: r["deleted"], reverse=True)

    def book_trash_action(self, identity, name, restore=False):
        self.require_account()
        self.guard()
        row = next((r for r in self.book_trash() if r["trash_id"] == identity), None)
        if not row or row["name"] != name:
            raise ValueError("小说不存在或完整书名校验失败")
        parent = self.store.account_dir(self.account) / "小说回收站"
        bucket = parent / identity
        self._safe_book_tree(bucket, parent)
        if restore:
            from pathlib import Path

            folder = row["folder"]
            if Path(folder).name != folder:
                raise ValueError("恢复目录无效")
            dest = self.store.account_dir(self.account) / "项目" / folder
            if dest.exists() or any(b["id"] == row["id"] for b in self.bookshelf()):
                raise ValueError("存在同名目录或相同项目ID，恢复已停止")
            shutil.move(str(bucket / "项目"), str(dest))
            shutil.rmtree(bucket)
        else:
            shutil.rmtree(bucket)

    def rename_book(self, identity, name):
        self.guard()
        info = self.book_info(identity)
        name = str(name).strip()
        if not name or len(name) > 100:
            raise ValueError("书名须为1—100字")
        from pathlib import Path

        path = Path(info["path"]) / "08_项目数据/project.json"
        meta = json.loads(path.read_text("utf-8"))
        meta["name"] = name
        write_json(path, redact(meta, self.secrets()))
        if self.project and self.project.meta["id"] == identity:
            self.project.meta["name"] = name

    def order_books(self, ids):
        self.require_account()
        self.guard()
        active = [b["id"] for b in self.bookshelf()]
        if (
            not isinstance(ids, list)
            or len(ids) != len(set(ids))
            or set(ids) != set(active)
        ):
            raise ValueError("书架已变化，请刷新后重新排序")
        settings = self.store.settings(self.account)
        settings["bookshelf_order"] = ids
        self.store.save_settings(self.account, settings)

    def manage_chapter(self, identity=None, name=None, ids=None):
        self.require_project()
        self.guard()
        chapters = self.project.segments()
        if ids is not None:
            active = [c["id"] for c in chapters]
            if (
                not isinstance(ids, list)
                or len(ids) != len(set(ids))
                or set(ids) != set(active)
            ):
                raise ValueError("章节列表已变化，请刷新后排序")
            order = iter(ids)
            self.project.config["chapter_order"] = [
                next(order) if c["id"] in active else c["id"]
                for c in self.project.segments(include_archived=True)
            ]
            self.project.save_config()
        else:
            if identity not in {c["id"] for c in chapters}:
                raise ValueError("章节不存在")
            name = str(name).strip()
            if not name or len(name) > 100:
                raise ValueError("章节名须为1—100字")
            self.project.db.execute(
                "UPDATE segments SET name=? WHERE id=?", (name, identity)
            )
            self.project.db.commit()

    def update_book_cover(self, identity, path=None):
        self.require_account()
        self.guard()
        info = self.book_info(identity)
        from pathlib import Path

        root = Path(info["path"])
        config_file = root / "08_项目数据/workspace.json"
        config = (
            self.project.config
            if self.project and self.project.meta["id"] == identity
            else (
                json.loads(config_file.read_text("utf-8"))
                if config_file.exists()
                else {}
            )
        )
        if path:
            path = Path(path)
            if not self.reader_thumbnail(path):
                raise ValueError("封面图片无法读取或尺寸过大")
            dest = root / "01_原始资料/封面" / ("封面_" + uid() + path.suffix.lower())
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
            config["book_cover"] = dest.relative_to(root).as_posix()
        else:
            config.pop("book_cover", None)
        write_json(config_file, redact(config, self.secrets()))
