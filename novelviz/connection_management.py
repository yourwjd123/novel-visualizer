"""Account connection cards, explicit node ownership and reference-safe deletion."""

from .storage import NODES, write_json, redact, uid
from .connections import credential_id, clean_profile
from . import credentials

TEXT_NODES = [0, 1, 2, 3, 5, 6, 7]
IMAGE_TASKS = ["illustration", "人物", "场景", "道具"]


class ConnectionManagementMixin:
    def connection_cards(self):
        self.require_account()
        catalog = [
            dict(id="default_text", name="默认语言模型", kind="language"),
            dict(id="default_image", name="默认生图连接", kind="image"),
        ]
        catalog += [
            dict(id=f"text:{n}", name=NODES[n], kind="language") for n in TEXT_NODES
        ]
        catalog += [
            dict(
                id="image:" + n,
                name="场景插图生成" if n == "illustration" else n + "参考图生成",
                kind="image",
            )
            for n in IMAGE_TASKS
        ]
        settings = self.store.settings(self.account)
        defaults = self.store.node_defaults(self.account)
        image = self.store.image_defaults(self.account)
        bindings = {
            "default_text": settings.get("language_connection_id", ""),
            "default_image": image.get("connection_id", "image-default"),
        }
        for n in TEXT_NODES:
            node = defaults.get(str(n), {})
            bindings[f"text:{n}"] = (
                node.get("connection_id", "")
                if node.get("connection_override", bool(node.get("connection_id")))
                else ""
            )
        for task in IMAGE_TASKS:
            d = image.get("tasks", {}).get(task, {})
            bindings["image:" + task] = (
                d.get("connection_id", "")
                if d.get("connection_override", bool(d.get("connection_id")))
                else ""
            )

        def key_storage(c):
            stored = credentials.get_key(credential_id(self.account["id"], c["id"]))
            session = self.keys.get(self.account["id"] + ":" + c["id"])
            if stored and (session is None or session == stored):
                return "system"
            if session:
                return "session"
            return "none"

        rows = [
            dict(
                c,
                key_set=bool(self.key(c["id"])),
                key_storage=key_storage(c),
                bindings=[key for key, value in bindings.items() if value == c["id"]],
            )
            for c in self.store.connections(self.account)
        ]
        return dict(cards=rows, catalog=catalog, bindings=bindings)

    def save_connection_card(self, profile, bindings, key=None, remember=False):
        self.require_account()
        self.guard()
        profile = clean_profile(profile)
        previous = next(
            (
                p
                for p in self.store.connections(self.account)
                if p["id"] == profile["id"]
            ),
            None,
        )
        if previous and (previous["kind"] in ("demo", "openai")) != (
            profile["kind"] in ("demo", "openai")
        ):
            raise ValueError("不能将已有语言连接改为图片连接，请新建独立连接")
        catalog = self.connection_cards()["catalog"]
        kind = "language" if profile["kind"] in ("demo", "openai") else "image"
        allowed = {c["id"] for c in catalog if c["kind"] == kind}
        if not isinstance(bindings, list) or any(k not in allowed for k in bindings):
            raise ValueError("默认节点与连接类型不匹配")
        current = self.connection_cards()["bindings"]
        self.save_connection(profile, key, remember)
        settings = self.store.settings(self.account)
        nodes = self.store.node_defaults(self.account)
        image = self.store.image_defaults(self.account)
        for slot, owner in current.items():
            if slot not in bindings and owner != profile["id"]:
                continue
            cid = profile["id"] if slot in bindings else ""
            if slot == "default_text":
                settings["language_connection_id"] = cid
            elif slot == "default_image":
                image["connection_id"] = cid
            elif slot.startswith("text:"):
                n = slot.split(":")[1]
                d = nodes.setdefault(n, {})
                d.update(
                    connection_id=cid,
                    connection_override=bool(cid)
                    or not bool(settings.get("language_connection_id")),
                )
            else:
                task = slot.split(":")[1]
                d = image.setdefault("tasks", {}).setdefault(task, {})
                if d.get("connection_id") != cid:
                    d.pop("preset_id", None)
                d.update(
                    connection_id=cid,
                    connection_override=bool(cid)
                    or not bool(image.get("connection_id")),
                )
        if (
            current.get("default_text") == profile["id"]
            and "default_text" not in bindings
        ):
            for n in TEXT_NODES:
                d = nodes.setdefault(str(n), {})
                if (
                    not d.get("connection_override", bool(d.get("connection_id")))
                    and f"text:{n}" not in bindings
                ):
                    d.update(connection_id="", connection_override=True)
        if "default_text" in bindings:
            for d in nodes.values():
                if not d.get("connection_id"):
                    d["connection_override"] = False
        if "default_image" in bindings:
            for d in image.get("tasks", {}).values():
                if not d.get("connection_id"):
                    d["connection_override"] = False
        self.store.save_settings(self.account, redact(settings, self.secrets()))
        for n, d in nodes.items():
            self.store.save_node_default(self.account, int(n), d, self.secrets())
        self.store.save_image_defaults(self.account, image, self.secrets())

    def delete_connection_card(self, identity, replacement=""):
        self.require_account()
        self.guard()
        profiles = self.store.connections(self.account)
        old = next((c for c in profiles if c["id"] == identity), None)
        if not old:
            raise ValueError("连接不存在")
        alternative = (
            next((c for c in profiles if c["id"] == replacement), None)
            if replacement
            else None
        )
        if replacement and (
            not alternative
            or replacement == identity
            or (old["kind"] in ("demo", "openai"))
            != (alternative["kind"] in ("demo", "openai"))
        ):
            raise ValueError("替代连接不存在或类别不匹配")
        secrets = self.secrets()
        slot = credential_id(self.account["id"], identity)
        if credentials.get_key(slot):
            credentials.set_key(slot, "")
        self.keys.pop(self.account["id"] + ":" + identity, None)
        settings = self.store.settings(self.account)
        nodes = self.store.node_defaults(self.account)
        image = self.store.image_defaults(self.account)
        removed_default = settings.get("language_connection_id") == identity
        if removed_default:
            settings["language_connection_id"] = replacement

        def detach_legacy(config, name):
            if config.get("workflow"):
                import json

                try:
                    mapping = json.loads(config.get("mapping", "{}"))
                    count = sum(k.startswith("reference_") for k in mapping)
                except (ValueError, TypeError):
                    count = 0
                image.setdefault("presets", []).append(
                    dict(
                        id=uid(),
                        name=name + "（原连接已删除）",
                        connection_id="",
                        workflow=config["workflow"],
                        mapping=config.get("mapping", "{}"),
                        reference_count=count,
                        default=False,
                        inactive_reason="原连接已删除",
                    )
                )
                config.pop("workflow", None)
                config.pop("mapping", None)

        if image.get("connection_id") == identity:
            detach_legacy(image, "旧版默认工作流")
            image["connection_id"] = replacement
        for n in TEXT_NODES:
            d = nodes.setdefault(str(n), {})
            if (
                (
                    removed_default
                    and not d.get("connection_override", bool(d.get("connection_id")))
                )
                or d.get("connection_id") == identity
                or (
                    identity == "node-" + str(n)
                    and not d.get("connection_id")
                    and not settings.get("language_connection_id")
                )
            ):
                d.update(connection_id=replacement, connection_override=True)
        for task, d in image.get("tasks", {}).items():
            if d.get("connection_id") == identity:
                detach_legacy(d, "旧版" + task + "工作流")
                d.update(connection_id=replacement, connection_override=True)
                d.pop("preset_id", None)
        # Presets remain as inactive records; deletion never repoints a workflow to a new server.
        for preset in image.get("presets", []):
            if preset.get("connection_id") == identity:
                preset.update(connection_id="", inactive_reason="原连接已删除")
        for path in self.store.projects(self.account):
            config_file = path.parent / "workspace.json"
            if config_file.exists():
                import json

                config = json.loads(config_file.read_text("utf-8"))
                for k, cid in config.get("connections", {}).items():
                    if cid == identity:
                        config["connections"][k] = replacement
                if config.get("image_connection") == identity:
                    config["image_connection"] = replacement
                write_json(config_file, config)
                if self.project and self.project.path == path.parent.parent:
                    self.project.config = config
        self.store.save_settings(self.account, settings)
        for n, d in nodes.items():
            self.store.save_node_default(self.account, int(n), d, self.secrets())
        self.store.save_image_defaults(self.account, image, secrets)
        write_json(
            self.store.account_dir(self.account) / "账户设置/connections.json",
            [p for p in profiles if p["id"] != identity],
        )
