import json
import os
import zipfile

from novelviz.connections import credential_id

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from novelviz.prompts import (
    assemble,
    default_template,
    parse_object,
    validate_assets,
    validate_scenes,
)
from novelviz.storage import Project, Store, write_json
from novelviz.ui import Window as DesktopWindow
from novelviz.ui import seed_demo


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait(w):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: loop.quit() if not w.busy else None)
    timer.start()
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    timer.stop()
    assert not w.busy


def make_project(tmp):
    store = Store(tmp)
    p = store.create_project(store.accounts[0], "新书")
    sid = p.add_segment("章一", "第一段。\n\n第二段。\n\n第三段。")
    p.ensure_scene(sid)
    return store, p, sid


def test_templates_cover_every_node_and_preserve_edits(tmp_path):
    store = Store(tmp_path)
    a = store.accounts[0]
    for n in range(8):
        t = default_template(n)
        assert len(t["body"]) > 110 and "原文" in assemble(t)
    t = default_template(0)
    t.update(body=t["body"] + "\n用户补充：保留人物对话。")
    store.save_template(a, t)
    assert "用户补充" in store.templates(a, 0)[0]["body"]
    t.update(id="custom-new", name="自定义拆分")
    store.save_template(a, t)
    assert len(store.templates(a, 0)) == 3
    store.reset_template(a, "split")
    assert store.templates(a, 0)[0]["body"] == default_template(0)["body"]
    assert any(t["id"] == "custom-new" for t in store.templates(a, 0))


@pytest.mark.parametrize(
    "rows",
    [
        [dict(title="空缺", start_paragraph=2, end_paragraph=3)],
        [
            dict(title="重叠", start_paragraph=1, end_paragraph=2),
            dict(title="重复", start_paragraph=2, end_paragraph=3),
        ],
        [dict(title="超界", start_paragraph=1, end_paragraph=4)],
    ],
)
def test_split_validator_rejects_bad_coverage(rows):
    with pytest.raises(ValueError):
        validate_scenes({"scenes": rows}, 3)


def test_invalid_model_output_never_repaired_implicitly():
    with pytest.raises(ValueError, match="不会自动调用"):
        parse_object("不是JSON")
    with pytest.raises(ValueError):
        validate_assets(
            {
                "assets": [
                    dict(
                        name="某人",
                        kind="人物",
                        evidence=[dict(paragraph=99, quote="不存在")],
                    )
                ]
            },
            3,
        )


def test_scene_links_shared_across_segments_and_invalidate(tmp_path):
    store, p, sid = make_project(tmp_path)
    first = p.scenes(sid)[0]
    a = p.save_asset(
        dict(
            name="沈青",
            kind="人物",
            source="原文明确",
            review="已确认",
            description="布衣",
        )
    )
    p.set_requirements(
        first["id"],
        [
            dict(name="沈青", kind="人物", asset_id=a["id"]),
            dict(name="渡口", kind="场景"),
        ],
    )
    assert [r["problem"] for r in p.scene_assets(first["id"])] == [
        "缺少参考图",
        "缺少档案",
    ]
    second = p.add_segment("章二", "新的原文")
    p.ensure_scene(second)
    sc = p.scenes(second)[0]
    p.set_requirements(sc["id"], [dict(name="沈青", kind="人物", asset_id=a["id"])])
    d = p.load_node(first["id"], 3)
    d["final"] = "已确认提示词"
    p.confirm(first["id"], 3, d)
    a["description"] = "更新衣服"
    p.save_asset(a)
    assert p.load_node(first["id"], 3)["status"] == "需复核"
    assert p.scene_assets(sc["id"])[0]["asset"]["description"] == "更新衣服"
    assert p.scene_assets(sc["id"])[0]["asset"]["revision"] == 2
    p.close()


def test_resplit_archives_old_edits_and_records(tmp_path):
    store, p, sid = make_project(tmp_path)
    old = p.scenes(sid)[0]
    old["summary"] = "人工编辑"
    p.save_scene(old)
    d = p.load_node(old["id"], 2)
    d["final"] = "旧方案"
    p.confirm(old["id"], 2, d)
    p.apply_scene_candidates(
        sid,
        [
            dict(title="前半", summary="一二", start_paragraph=1, end_paragraph=2),
            dict(title="后半", summary="三", start_paragraph=3, end_paragraph=3),
        ],
    )
    assert len(p.scenes(sid)) == 2 and p.scenes(sid, True)[0]["summary"] == "人工编辑"
    assert p.load_node(old["id"], 2)["final"] == "旧方案"
    p.close()


def test_schema1_migration_backs_up_and_copies_old_node_records(tmp_path):
    store, p, sid = make_project(tmp_path)
    path = p.path
    p.db.execute("DELETE FROM scenes")
    p.db.execute("PRAGMA user_version=1")
    p.db.commit()
    old = p.load_node(sid, 1)
    old["final"] = "旧资产说明"
    p.confirm(sid, 1, old)
    p.meta["schema"] = 1
    write_json(path / "08_项目数据/project.json", p.meta)
    p.close()
    p = Project(path)
    assert p.meta["schema"] == 2
    backups = list((path / "08_项目数据/迁移备份").glob("*.zip"))
    assert len(backups) == 1
    with zipfile.ZipFile(backups[0]) as z:
        assert json.loads(z.read("project.json"))["schema"] == 1
    p.ensure_scene(sid)
    assert p.load_node(p.scenes(sid)[0]["id"], 1)["final"] == "旧资产说明"
    p.close()


def test_settings_import_cannot_adopt_existing_keys(tmp_path):
    s = Store(tmp_path)
    a = s.accounts[0]
    dest = tmp_path / "settings.json"
    profile = s.connections(a)[0]
    profile["api_key"] = "BAD"
    s.save_connection(a, profile)
    assert "api_key" not in s.connections(a)[0]
    s.export_settings(a, dest, secrets=["BAD"])
    exported = json.loads(dest.read_text("utf-8"))
    assert all(not c.get("legacy") for c in exported["connections"])
    old_ids = {c["id"] for c in s.connections(a)}
    s.import_settings(a, dest)
    imported = [c for c in s.connections(a) if c["id"] not in old_ids]
    assert imported and all(c["id"].startswith("import-") for c in imported)
    assert "BAD" not in dest.read_text("utf-8")


def test_node_connections_and_keys_are_independent(app, tmp_path, monkeypatch):
    from novelviz import ui

    seed_demo(Store(tmp_path))
    w = Window(tmp_path)
    captures = []

    def fake(params, messages, context, key, paths, cancel):
        captures.append((params["connection_id"], key, params["system"]))
        return "完成"

    monkeypatch.setattr(ui, "text_call", fake)
    w.set_connection_key("node-0", "KEY_FOR_SPLIT")
    w.set_connection_key("node-1", "KEY_FOR_ASSETS")
    for n in (0, 1):
        w.select_node(n)
        w.message.setPlainText("请执行")
        w.send_message()
        wait(w)
    assert [(c, k) for c, k, _ in captures] == [
        ("node-0", "KEY_FOR_SPLIT"),
        ("node-1", "KEY_FOR_ASSETS"),
    ]
    assert "情节拆分" in captures[0][2] and "综合资产提取" in captures[1][2]
    assert w.connection_key("image-default") == ""
    w.store.create_account("其他账户")
    w.reload_accounts()
    w.account_combo.setCurrentIndex(1)
    assert w.connection_key("node-0") == ""
    w.close()


def test_modular_scene_asset_roundtrip(app, tmp_path):
    seed_demo(Store(tmp_path))
    w = Window(tmp_path)
    w.message.setPlainText("请拆分")
    w.send_message()
    wait(w)
    w.use_last()
    rows = validate_scenes(
        parse_object(w.final.toPlainText()), len(w.project.paragraphs(w.sid))
    )
    w.apply_structured("scenes", rows)
    assert w.scene_combo.count() == len(rows)
    w.select_node(1)
    w.message.setPlainText("提取资产")
    w.send_message()
    wait(w)
    w.use_last()
    assets = validate_assets(
        parse_object(w.final.toPlainText()), len(w.project.paragraphs(w.sid))
    )
    w.apply_structured("assets", assets)
    linked = w.project.scene_assets(w.scene_id)
    assert linked[0]["asset"]["review"] == "待审核"
    assert w.module_grid.count() > 0 and w.asset_grid.count() > 0
    w.select_node(4)
    assert w.pages.currentIndex() == 3
    w.select_node(2)
    assert w.pages.currentIndex() == 0
    w.close()


def test_per_scene_dialogue_drafts_are_isolated(app, tmp_path):
    seed_demo(Store(tmp_path))
    w = Window(tmp_path)
    sid = w.sid
    count = len(w.project.paragraphs(sid))
    w.project.apply_scene_candidates(
        sid,
        [
            dict(title="一", start_paragraph=1, end_paragraph=1),
            dict(title="二", start_paragraph=2, end_paragraph=count),
        ],
    )
    w.reload_scenes()
    w.show_node()
    w.select_node(2)
    w.message.setPlainText("第一情节草稿")
    w.final.setPlainText("第一方案")
    w.save_draft(silent=True)
    first = w.scene_id
    w.scene_combo.setCurrentIndex(1)
    assert w.final.toPlainText() == "" and w.message.toPlainText() == ""
    w.scene_combo.setCurrentIndex(0)
    assert w.scene_id == first and w.message.toPlainText() == "第一情节草稿"
    w.close()


def test_asset_images_and_missing_generation_gate(app, tmp_path, monkeypatch):
    seed_demo(Store(tmp_path))
    w = Window(tmp_path)
    a = w.project.assets()[0]
    im = QImage(24, 24, QImage.Format_RGB32)
    im.fill(QColor("#44aa88"))
    source = tmp_path / "image.png"
    im.save(str(source))
    a["image"] = w.project.save_asset_image(a, source)
    a = w.project.save_asset(a)
    w.project.set_requirements(
        w.scene_id,
        [
            dict(name=a["name"], kind=a["kind"], asset_id=a["id"]),
            dict(name="缺失道具", kind="道具"),
        ],
    )
    w.refresh_image_assets()
    assert w.image_asset_grid.count() == 2
    assert w.project.scene_assets(w.scene_id)[0]["problem"] == ""
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
    w.comfy_prompt.setPlainText("提示词")
    w.generate_image()
    assert not w.project.jobs()
    w.close()


def test_sidebar_state_is_account_scoped(app, tmp_path):
    seed_demo(Store(tmp_path))
    w = Window(tmp_path)
    w.show()
    app.processEvents()
    w.toggle_sidebar()
    assert w.side.width() <= 60
    w.close()
    w = Window(tmp_path)
    assert w.settings["sidebar_visible"] is False
    w.close()


def test_drag_targets_import_without_network(app, tmp_path):
    seed_demo(Store(tmp_path))
    w = Window(tmp_path)
    p = tmp_path / "drop.md"
    p.write_text("拖拽正文", encoding="utf-8")
    w.message.filesDropped.emit([str(p)])
    assert len(w.pending_attachments) == 1 and not w.project.jobs()
    w.final.filesDropped.emit([str(p)])
    assert "拖拽正文" in w.final.toPlainText()
    before = w.segments_combo.count()
    w.reader.filesDropped.emit([str(p)])
    assert w.segments_combo.count() == before + 1
    w.close()


def test_card_layout_keeps_buttons_visible(app, tmp_path):
    seed_demo(Store(tmp_path))
    w = Window(tmp_path)
    w.show()
    w.select_node(1)
    app.processEvents()
    app.processEvents()
    for i in range(w.module_grid.count()):
        card = w.module_grid.itemAt(i).widget()
        assert card.height() >= card.minimumSizeHint().height()
    w.close()


def test_persistent_credentials_scoped_to_account_and_connection(
    app, tmp_path, monkeypatch
):
    from novelviz import ui

    memory = {}
    monkeypatch.setattr(ui, "get_key", lambda slot: memory.get(slot, ""))
    monkeypatch.setattr(
        ui, "set_key", lambda slot, value: memory.__setitem__(slot, value)
    )
    seed_demo(Store(tmp_path))
    w = Window(tmp_path)
    w.set_connection_key("node-0", "SPLIT_SECRET", True)
    w.set_connection_key("node-1", "ASSET_SECRET", True)
    assert memory[credential_id(w.account["id"], "node-0")] == "SPLIT_SECRET"
    w.set_connection_key("node-0", "", True)
    assert (
        w.connection_key("node-0") == ""
        and w.connection_key("node-1") == "ASSET_SECRET"
    )
    w.close()


def test_image_submission_uses_its_own_key_and_snapshot(app, tmp_path, monkeypatch):
    import shutil

    from novelviz import ui

    seed_demo(Store(tmp_path))
    w = Window(tmp_path)
    w.set_connection_key("image-default", "IMAGE_KEY")
    w.set_connection_key("node-3", "TEXT_KEY")
    source = tmp_path / "result.png"
    im = QImage(30, 30, QImage.Format_RGB32)
    im.fill(QColor("green"))
    im.save(str(source))
    captures = []

    def fake(url, flow, dest, cancel, progress, key):
        captures.append(key)
        dest.mkdir(parents=True)
        out = dest / "result.png"
        shutil.copy2(source, out)
        progress({"remote_id": "mock-image"})
        return [str(out)]

    monkeypatch.setattr(ui, "comfy_call", fake)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    w.workflow.setPlainText(
        json.dumps({"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}}})
    )
    w.comfy_prompt.setPlainText("当前情节提示词")
    w.generate_image()
    wait(w)
    j = w.project.jobs()[0]
    assert captures == ["IMAGE_KEY"] and j["status"] == "succeeded"
    assert j["scene"] == w.scene_id and j["assets"] and j["accepted_missing"]
    assert "IMAGE_KEY" not in json.dumps(j) and "TEXT_KEY" not in json.dumps(j)
    assert w.image_list.count() == 1
    w.close()


def Window(root):
    window = DesktopWindow(root)
    window.activate_account(window.store.accounts[0]["id"])
    return window
