"""Regression checks for guest entry, settings and the floating workspace."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from novelviz.storage import Store
from novelviz.ui import Window, seed_demo


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    store = Store(tmp_path)
    seed_demo(store)
    w = Window(tmp_path)
    w.activate_account(store.accounts[0]["id"])
    w.show()
    QTest.qWait(50)
    yield w
    w.close()


def test_guest_does_not_create_or_select_account(app, tmp_path):
    w = Window(tmp_path)
    assert not w.store.accounts
    assert w.account is None and w.project is None
    assert w.param_form is None
    assert w.work_tabs.count() == 8
    assert [w.work_tabs.tabText(i) for i in range(4)] == [
        "原文与情节",
        "视觉资产库",
        "场景插图",
        "成果集",
    ]
    w.close()


def test_guest_cancel_does_not_start_operation(app, tmp_path, monkeypatch):
    w = Window(tmp_path)
    monkeypatch.setattr(w, "choose_account", lambda: False)
    w.new_project()
    assert w.project is None and not w.store.accounts
    w.close()


def test_cards_and_assistant_do_not_reduce_work_area(window):
    w = window
    card = w.module_grid.itemAt(0).widget()
    assert card.isVisible() and card.height() > 150
    width = w.pages.width()
    w.show_assistant()
    QTest.qWait(30)
    assert w.assistant.isVisible()
    assert w.pages.width() == width
    w.message.setPlainText("保留讨论草稿")
    w.assistant.close()
    assert not w.assistant.isVisible()
    w.show_assistant()
    assert w.message.toPlainText() == "保留讨论草稿"


def test_central_settings_persist_node_defaults(window):
    w = window
    w.open_settings()
    panel = w.settings_page
    assert panel.categories.tabText(0) == "语言模型配置"
    panel.form.supplement.setPlainText("只依据原文证据")
    assert panel.save_language()
    assert w.store.node_defaults(w.account)["0"]["supplement"] == "只依据原文证据"
    assert w.node_parameters(0)["supplement"] == "只依据原文证据"
    assert "1" not in w.store.node_defaults(w.account)


def test_image_settings_survive_reopening(window):
    w = window
    for _ in range(2):
        w.open_settings()
        w.settings_page.categories.setCurrentIndex(1)
        QTest.qWait(20)
        assert w.workflow.isVisible() and w.image_connections.isVisible()
        w.navigate(0)
        w.reset_settings_panel()


def test_cancel_dirty_settings_keeps_page(window, monkeypatch):
    w = window
    w.open_settings()
    w.settings_page.form.supplement.setPlainText("未保存修改")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Cancel)
    w.navigate(0)
    assert w.pages.currentIndex() == 7
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Discard)
    w.navigate(0)
    assert w.pages.currentIndex() == 0


def test_partition_preserves_old_scene(window):
    p = window.project
    old = p.scene(window.scene_id)
    start, end = old["start_paragraph"], old["end_paragraph"]
    rows = p.replace_scene_partition(
        [old["id"]],
        [
            dict(title="前半", start_paragraph=start, end_paragraph=start),
            dict(title="后半", start_paragraph=start + 1, end_paragraph=end),
        ],
    )
    assert p.scene(old["id"])["archived"]
    assert len(rows) == 2 and len(p.scenes(window.sid)) == 2
    assert p.scene(old["id"])["source_text"] == old["source_text"]


def test_selected_results_are_scene_linked(window):
    p = window.project
    dest = p.path / "06_最终成果/test.png"
    dest.write_bytes(b"local-test")
    p.register_result(window.scene_id, dest, "job-a")
    p.register_result(window.scene_id, dest, "job-b")
    assert len(p.final_results()) == 1
    assert p.final_results()[0]["scene"] == window.scene_id
    assert p.final_results()[0]["job"] == "job-b"
    assert p.progress()["results"] == 1


def test_exported_defaults_remap_connections_and_remove_secrets(tmp_path):
    import json

    store = Store(tmp_path / "data")
    a = store.accounts[0]
    cid = store.connections(a)[0]["id"]
    store.save_node_default(
        a,
        0,
        dict(connection_id=cid, supplement="private-token", api_key="private-token"),
        ("private-token",),
    )
    store.save_image_defaults(
        a, dict(connection_id=cid, generation_rules="private-token"), ("private-token",)
    )
    dest = tmp_path / "settings.json"
    store.export_settings(a, dest, ("private-token",))
    raw = dest.read_text("utf-8")
    assert "private-token" not in raw and "api_key" not in raw
    b = store.create_account("导入账户")
    store.import_settings(b, dest)
    imported = store.node_defaults(b)["0"]["connection_id"]
    assert imported != cid
    assert imported in {c["id"] for c in store.connections(b)}
    assert store.image_defaults(b)["connection_id"] == imported
    assert json.loads(raw)["format"] == "novelviz-settings-v3"
