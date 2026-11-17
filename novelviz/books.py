"""Account-scoped whole-book recycling. Files outside projects are never touched."""

import json
import shutil
from .storage import now, uid, write_json


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
