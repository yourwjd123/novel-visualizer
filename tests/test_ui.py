import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from novelviz.storage import Store
from novelviz.ui import Window as DesktopWindow
from novelviz.ui import seed_demo


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_desktop_roundtrip_and_account_switch(app, tmp_path):
    seed_demo(Store(tmp_path))
    w = Window(tmp_path)
    w.show()
    app.processEvents()
    assert w.sid and len(w.project.segments()) == 2
    w.select_node(1)
    w.final.setPlainText("手工定稿，无需模型")
    w.confirm_final()
    assert w.data["status"] == "已确认"
    w.message.setPlainText("请修改为两项建议")
    w.send_message()
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: loop.quit() if not w.busy else None)
    timer.start()
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    timer.stop()
    assert not w.busy and len(w.data["messages"]) == 2
    assert "演示输出" in w.data["messages"][-1]["content"]
    assert w.project.jobs()[0]["status"] == "succeeded"
    w.use_last()
    w.confirm_final()
    assert w.data["revision"] == 2
    original = w.sid
    w.segments_combo.setCurrentIndex(1)
    assert w.sid != original and len(w.project.assets()) == 2
    w.store.create_account("空账户")
    w.reload_accounts()
    w.account_combo.setCurrentIndex(1)
    assert w.project is None and w.excerpt.toPlainText() == ""
    w.close()


def wait_job(w):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: loop.quit() if not w.busy else None)
    timer.start()
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    timer.stop()
    assert not w.busy


def test_unsent_draft_survives_switch_and_invalid_configuration(app, tmp_path):
    seed_demo(Store(tmp_path))
    w = Window(tmp_path)
    w.select_node(1)
    w.message.setPlainText("尚未发送的补充要求")
    w.final.setPlainText("人工草稿")
    w.param_form.connection.setCurrentIndex(-1)
    w.select_node(2)
    w.select_node(1)
    assert w.message.toPlainText() == "尚未发送的补充要求"
    assert w.final.toPlainText() == "人工草稿"
    w.close()


def test_attachment_confirmation_and_pure_text_default(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from novelviz import ui

    seed_demo(Store(tmp_path))
    w = Window(tmp_path)
    w.select_node(1)
    f = tmp_path / "附件.txt"
    f.write_text("附件正文", encoding="utf-8")
    w.pending_attachments = [w.project.add_attachment(f)]
    set_real_connection(w)
    w.message.setPlainText("检查附件")
    questions = []

    def reject(*args):
        questions.append(args)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "question", reject)
    w.send_message()
    assert (
        len(questions) == 1
        and not w.project.jobs()
        and w.message.toPlainText() == "检查附件"
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    requests = []

    def fake(params, messages, context, key, paths, cancel):
        requests.append(paths)
        return "已检查"

    monkeypatch.setattr(ui, "text_call", fake)
    w.send_message()
    wait_job(w)
    assert len(requests) == 1 and len(requests[0]) == 1
    # Follow-up text still includes prior attachments, requiring confirmation.
    monkeypatch.setattr(QMessageBox, "question", reject)
    w.message.setPlainText("继续讨论")
    w.send_message()
    assert len(questions) == 2 and len(requests) == 1
    # New node with pure text requires no confirmation.
    w.select_node(2)
    set_real_connection(w)
    w.message.setPlainText("纯文本")
    w.send_message()
    wait_job(w)
    assert len(questions) == 2 and len(requests) == 2
    w.close()


def test_export_and_backup_restore(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QInputDialog

    seed_demo(Store(tmp_path))
    w = Window(tmp_path)
    w.select_node(1)
    w.session_keys[w.account["id"]] = "known-secret-token"
    w.final.setPlainText("定稿 known-secret-token")
    w.confirm_final()
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a: ("当前最终方案", True))
    dest = tmp_path / "方案.txt"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a: (str(dest), "纯文本 (*.txt)")
    )
    w.export_text()
    assert dest.read_text("utf-8") == "定稿 [凭据已移除]"
    zip_path = tmp_path / "backup.zip"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a: (str(zip_path), "ZIP (*.zip)")
    )
    before = w.project.meta["id"]
    w.backup()
    assert zip_path.exists()
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a: (str(zip_path), "ZIP (*.zip)")
    )
    w.restore_backup()
    assert w.project.meta["id"] != before and w.project.meta["restored_from"] == before
    assert len(w.store.projects(w.account)) == 2
    w.close()


def test_appearance_modes_and_image(app, tmp_path):
    from PySide6.QtGui import QColor, QImage

    seed_demo(Store(tmp_path))
    w = Window(tmp_path)
    image = QImage(20, 20, QImage.Format_RGB32)
    image.fill(QColor("#307c75"))
    path = tmp_path / "背景.png"
    image.save(str(path))
    for theme in ("dark", "system", "light"):
        w.settings.update(theme=theme, background=str(path), background_opacity=20)
        w.apply_theme()
        assert not w.bg.pix.isNull()
    w.settings["background"] = ""
    w.apply_theme()
    assert w.bg.pix.isNull()
    w.close()


def set_real_connection(w):
    cid = "test-node-" + str(w.node)
    w.store.save_connection(
        w.account,
        dict(
            id=cid,
            name=cid,
            kind="openai",
            endpoint="http://127.0.0.1:11434/v1",
            model="mock",
            vision=False,
        ),
    )
    w.param_form.reload_connections(cid)


def Window(root):
    window = DesktopWindow(root)
    window.activate_account(window.store.accounts[0]["id"])
    return window
