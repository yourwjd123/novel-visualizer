"""Production workspace regressions: no simulated renderer or external credentials."""

import base64
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from novelviz.desktop import Bridge
from novelviz.workspace import Workspace


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def work(app, tmp_path, monkeypatch):
    monkeypatch.setattr("novelviz.credentials.get_key", lambda _: "")
    w = Workspace(tmp_path / "data")
    account = w.store.create_account("测试账户")
    w.login(account["id"])
    p = w.store.create_project(account, "测试小说")
    path = str(p.path)
    p.close()
    w.open_project(path)
    w.import_text("第一段", "甲走进渡口。\n\n乙交给她一封信。\n\n甲转身登船。")
    yield w
    w.close()


def rows():
    return [
        dict(title="候船", summary="甲来到渡口。", start_paragraph=1, end_paragraph=1),
        dict(
            title="交信", summary="乙交信后甲登船。", start_paragraph=2, end_paragraph=3
        ),
    ]


def picture(path):
    image = QImage(64, 64, QImage.Format_RGB32)
    image.fill(QColor("#345a67"))
    image.save(str(path))
    return path


def wait(bridge):
    for _ in range(500):
        QTest.qWait(10)
        if not bridge.workspace.busy:
            QTest.qWait(20)
            return
    pytest.fail("Task did not settle")


def test_guest_has_no_personal_project_or_key_access(app, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "novelviz.credentials.get_key", lambda _: pytest.fail("Guest read a key")
    )
    w = Workspace(tmp_path)
    state = w.snapshot()
    assert not state["accounts"] and state["project"] is None
    assert not (tmp_path / "accounts.json").exists()


def test_import_is_not_an_ai_call_or_implicit_scene(work):
    assert not work.project.scenes(work.segment)
    assert not work.project.jobs()
    assert len(work.snapshot()["paragraphs"]) == 3


def test_invalid_split_is_preserved_as_draft_but_cannot_commit(work):
    bad = rows()
    bad[1]["start_paragraph"] = 1
    work.save_split(bad)
    assert work.snapshot()["drafts"][work.segment]["rows"] == bad
    with pytest.raises(ValueError, match="遗漏|重叠"):
        work.confirm_split(bad)
    assert not work.project.scenes(work.segment)


def test_source_change_rejects_old_candidate(work):
    work.save_split(rows())
    segment = work.project.segments()[0]
    source = work.project.path / segment["file"]
    source.write_text("改过的原文。", "utf-8")
    with pytest.raises(ValueError, match="原文已"):
        work.confirm_split(rows())


def test_confirm_preserves_old_scenes_and_survives_reopening(work):
    work.save_split(rows())
    old = work.confirm_split(rows())
    work.save_split([dict(title="全文", start_paragraph=1, end_paragraph=3)])
    work.confirm_split([dict(title="全文", start_paragraph=1, end_paragraph=3)])
    assert work.project.scene(old[0]["id"])["archived"]
    path = str(work.project.path)
    work.open_project(path)
    assert len(work.snapshot()["scenes"]) == 1
    assert not work.snapshot()["drafts"]


def test_assets_share_only_within_project(work):
    work.save_asset(dict(name="甲", kind="人物", description="原文未描述外貌"))
    work.import_text("第二段", "甲收起信。")
    assert work.snapshot()["assets"][0]["name"] == "甲"
    new = work.store.create_project(work.account, "独立小说")
    path = str(new.path)
    new.close()
    work.open_project(path)
    assert not work.snapshot()["assets"]


def test_asset_ingestion_checks_evidence_and_does_not_overwrite(work):
    work.confirm_split(rows())
    a = work.save_asset(
        dict(name="甲", kind="人物", description="作者保留的描述", review="已确认")
    )
    output = dict(
        assets=[
            dict(
                name="甲",
                kind="人物",
                source="原文明确",
                description="模型建议覆盖",
                evidence=[dict(paragraph=1, quote="不存在的内容")],
            )
        ]
    )
    with pytest.raises(ValueError, match="证据"):
        work.apply_output(1, json.dumps(output, ensure_ascii=False))
    output["assets"][0]["evidence"][0]["quote"] = "甲走进渡口"
    work.apply_output(1, json.dumps(output, ensure_ascii=False))
    assert work.project.assets()[0]["description"] == "作者保留的描述"
    assert work.project.requirements(work.scene)[0]["asset_id"] == a["id"]


def test_reference_trash_preserves_file_and_other_primary(work, tmp_path):
    a = work.save_asset(dict(name="甲", kind="人物", description="用户设定"))
    work.add_reference(a["id"], picture(tmp_path / "one.png"))
    first = work.project.assets()[0]["image"]
    work.add_reference(a["id"], picture(tmp_path / "two.png"))
    primary = work.project.assets()[0]["image"]
    work.reference_action(a["id"], first, "trash")
    assert work.file(first).exists()
    assert work.project.assets()[0]["image"] == primary
    assert len(work.project.config["image_trash"]) == 1


def test_explicit_empty_session_key_does_not_fall_back_to_old_secret(work, monkeypatch):
    monkeypatch.setattr("novelviz.credentials.get_key", lambda _: "old-secret")
    monkeypatch.setattr("novelviz.credentials.set_key", lambda *args: None)
    profile = work.store.connections(work.account)[0]
    work.save_connection(profile, key="", remember=False)
    assert work.key(profile["id"]) == ""


def test_nested_image_settings_export_redacts_keys_and_remaps_ids(work, tmp_path):
    connections = work.store.connections(work.account)
    cid = connections[-2]["id"]
    work.store.save_image_defaults(
        work.account,
        dict(
            connection_id=cid,
            tasks={
                "人物": dict(
                    connection_id=cid,
                    workflow="sensitive-demo-token",
                    api_key="should-not-persist",
                )
            },
        ),
        ("sensitive-demo-token",),
    )
    raw = json.dumps(work.store.image_defaults(work.account))
    assert "api_key" not in raw and "sensitive-demo-token" not in raw
    out = tmp_path / "settings.json"
    work.store.export_settings(work.account, out)
    account = work.store.create_account("导入账户")
    work.store.import_settings(account, out)
    restored = work.store.image_defaults(account)
    assert restored["connection_id"] != cid
    assert restored["tasks"]["人物"]["connection_id"] == restored["connection_id"]


def test_old_scope_autosave_cannot_write_to_new_scene(work):
    scenes = work.confirm_split(rows())
    bridge = Bridge(work.store.root)
    bridge.workspace.close()
    bridge.workspace = work
    old = scenes[0]["id"]
    work.set_selection(scene=scenes[1]["id"])
    bridge.dispatch(
        "save_chat", dict(node=2, scope=old, final="第一情节草稿", draft="多轮输入")
    )
    assert work.project.load_node(old, 2)["final"] == "第一情节草稿"
    assert not work.project.load_node(work.scene, 2)["final"]


def test_old_project_request_rejected_after_switch(work):
    bridge = Bridge(work.store.root)
    bridge.workspace = work
    old = work.project.meta["id"]
    p = work.store.create_project(work.account, "另一项目")
    path = str(p.path)
    p.close()
    work.open_project(path)
    result = json.loads(
        bridge.invoke(
            "import_text",
            json.dumps(dict(_project=old, name="错误归属", text="不应入库")),
        )
    )
    assert not result["ok"] and not work.project.segments()


def test_file_path_escape_is_rejected(work, tmp_path):
    with pytest.raises(ValueError, match="当前项目"):
        work.file("../../secret.png")
    outside = picture(tmp_path / "outside.png")
    link = work.project.path / "逃逸.png"
    try:
        link.symlink_to(outside)
    except OSError:
        return
    with pytest.raises(ValueError):
        work.image("逃逸.png")


def test_real_demo_task_creates_reviewable_candidates_only(work):
    bridge = Bridge(work.store.root)
    bridge.workspace = work
    result = bridge.dispatch("send", dict(node=0, split=True, message="按段落拆分"))
    assert result["job"]
    wait(bridge)
    assert len(work.snapshot()["drafts"][work.segment]["rows"]) == 3
    assert not work.project.scenes(work.segment)
    assert work.project.jobs()[0]["status"] == "success"
    assert "演示" in work.project.jobs()[0]["output"]


def test_plain_text_no_dialog_but_actual_attachment_does_confirm(work, tmp_path):
    bridge = Bridge(work.store.root)
    bridge.workspace = work
    calls = []
    bridge.confirm = lambda title, message: calls.append(message) or False
    assert bridge.attachment_confirmation(dict(provider="openai"), [])
    path = tmp_path / "说明.txt"
    path.write_text("真实附件", "utf-8")
    assert not bridge.attachment_confirmation(
        dict(provider="openai", endpoint="http://127.0.0.1"), [path]
    )
    assert len(calls) == 1 and "MB" in calls[0]


def test_actual_image_provider_receives_snapshot_and_separate_key(work):
    work.confirm_split(rows())
    a = work.save_asset(
        dict(name="甲", kind="人物", description="灰蓝布衣", review="已确认")
    )
    work.project.set_requirements(
        work.scene, [dict(name="甲", kind="人物", asset_id=a["id"])]
    )
    work.project.config["scene_overrides"] = {work.scene: {a["id"]: "袖口湿透"}}
    work.project.save_config()
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(QColor("#345a67"))
    raw = QByteArray()
    buf = QBuffer(raw)
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers.get("Authorization"), body))
            result = json.dumps(
                dict(data=[dict(b64_json=base64.b64encode(bytes(raw)).decode())])
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(result)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        work.save_connection(
            dict(
                id="test-image",
                name="本机测试图像接口",
                kind="image_api",
                endpoint=f"http://127.0.0.1:{server.server_port}/v1",
                model="test-image-model",
            ),
            "image-only-key",
        )
        work.store.save_image_defaults(
            work.account, dict(connection_id="test-image", size="1024x1024")
        )
        bridge = Bridge(work.store.root)
        bridge.workspace = work
        bridge.confirm = lambda *args: True
        bridge.dispatch("generate", dict(prompt="交信动作"))
        wait(bridge)
        assert len(requests) == 1
        assert requests[0][1] == "Bearer image-only-key"
        assert (
            "灰蓝布衣" in requests[0][2]["prompt"]
            and "袖口湿透" in requests[0][2]["prompt"]
        )
        job = work.project.jobs()[0]
        assert job["status"] == "success" and work.file(job["results"][0]).exists()
        assert "image-only-key" not in json.dumps(work.snapshot())
        work.select_result(job["results"][0])
        assert work.project.final_results()[0]["scene"] == work.scene
    finally:
        server.shutdown()
        server.server_close()


def test_rejected_missing_assets_creates_no_image_task(work):
    work.confirm_split(rows())
    work.save_connection(
        dict(
            id="test-image",
            name="本地图片",
            kind="image_api",
            endpoint="http://127.0.0.1:1/v1",
            model="never-called",
        )
    )
    work.store.save_image_defaults(work.account, dict(connection_id="test-image"))
    bridge = Bridge(work.store.root)
    bridge.workspace = work
    bridge.confirm = lambda *args: False
    assert bridge.dispatch("generate", dict(prompt="不会实际提交"))["cancelled"]
    assert not work.project.jobs()


def test_stop_detaches_local_wait_without_resending_or_adopting_late_output(work):
    bridge = Bridge(work.store.root)
    bridge.workspace = work
    release = threading.Event()
    started = threading.Event()
    count = []
    job, _, _, _ = work.prepare_text(0, "测试停止等待")

    def slow(cancel, progress):
        count.append(1)
        started.set()
        release.wait(3)
        return "迟到的响应，不应被自动采纳"

    bridge.start(job, slow, text=True)
    assert started.wait(2)
    bridge.dispatch("stop", {})
    wait(bridge)
    assert work.project.jobs()[0]["status"] == "unknown"
    release.set()
    QTest.qWait(150)
    assert len(count) == 1
    assert not any(
        m["role"] == "assistant"
        for m in work.project.load_node(work.segment, 0)["messages"]
    )


def test_node_parameters_are_validated_before_persistence(work):
    for params in (
        dict(max_tokens=-1),
        dict(max_tokens=200000),
        dict(temperature=float("nan")),
    ):
        with pytest.raises(ValueError):
            work.store.save_node_default(work.account, 0, params)
    assert not work.store.node_defaults(work.account)


def test_running_task_cannot_switch_its_source_context(work):
    other = work.import_text("第二段", "新的原文")
    first = work.project.segments()[0]["id"]
    work.busy = True
    with pytest.raises(ValueError, match="任务"):
        work.set_selection(segment=first)
    assert work.segment == other
    work.busy = False


def test_reference_generation_does_not_borrow_illustration_connection(work):
    asset = work.save_asset(dict(name="人物甲", kind="人物", description="用户设定"))
    work.store.save_image_defaults(work.account, dict(connection_id="image-default"))
    bridge = Bridge(work.store.root)
    bridge.workspace = work
    with pytest.raises(ValueError, match="不会借用"):
        bridge.dispatch("generate", dict(asset=asset["id"], prompt="参考图"))
    assert not work.project.jobs()
