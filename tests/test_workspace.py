"""Production workspace regressions: no simulated renderer or external credentials."""

import base64
import json
import os
import threading
from pathlib import Path
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
    w.store.save_settings(
        account, {**w.store.settings(account), "asset_association_mode": "local"}
    )
    p = w.store.create_project(account, "测试小说")
    path = str(p.path)
    p.close()
    w.open_project(path)
    w.import_text("第一段", "甲走进渡口。\n\n乙交给她一封信。\n\n甲转身登船。")
    w.finish_assets([])
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
            work.account,
            dict(connection_id="test-image", size="1024x1024", preface="图片首位规则"),
        )
        bridge = Bridge(work.store.root)
        bridge.workspace = work
        bridge.confirm = lambda *args: True
        bridge.dispatch("generate", dict(prompt="交信动作"))
        wait(bridge)
        assert len(requests) == 1
        assert requests[0][1] == "Bearer image-only-key"
        assert requests[0][2]["prompt"].startswith("图片首位规则")
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


def test_reference_generation_inherits_default_image_connection(work, monkeypatch):
    asset = work.save_asset(dict(name="人物甲", kind="人物", description="用户设定"))
    profile = dict(
        id="shared-image",
        name="默认图片",
        kind="image_api",
        endpoint="http://127.0.0.1:9999/v1",
        model="image",
    )
    work.save_connection(profile)
    work.store.save_image_defaults(work.account, dict(connection_id="shared-image"))
    bridge = Bridge(work.store.root)
    bridge.workspace = work
    captured = []
    monkeypatch.setattr(bridge, "start", lambda job, run, text: captured.append(job))
    bridge.dispatch("generate", dict(asset=asset["id"], prompt="参考图"))
    assert captured[0]["connection"]["id"] == "shared-image"


def test_card_status_delete_undo_preserves_ids_and_associations(work):
    candidates = rows()
    work.save_split(candidates)
    first, second = [r["id"] for r in candidates]
    work.review_scenes(candidates, [first], "已确认")
    assert len(work.project.scenes(work.segment)) == 1
    assert work.scene == first
    work.project.set_requirements(first, [dict(name="甲", kind="人物")])
    requirement = work.project.requirements(first)
    candidates[0]["required_assets"] = requirement
    work.review_scenes(candidates, [first], "候选")
    assert work.project.requirements(first) == requirement
    work.review_scenes(candidates[1:], [], "候选")
    archived_revision = work.project.scene(first)["revision"]
    assert work.project.scene(first)["archived"]
    work.review_scenes(candidates, [first, second], "已确认")
    assert work.project.scene(first)["revision"] > archived_revision
    assert {r["id"] for r in work.project.scenes(work.segment)} == {first, second}
    assert work.project.requirements(first) == requirement
    assert work.segment not in work.project.config["split_drafts"]


def test_partial_confirmation_allows_unassigned_source(work):
    candidates = rows()[1:]
    work.save_split(candidates)
    work.review_scenes(candidates, [candidates[0]["id"]], "已确认")
    assert work.project.scene(work.scene)["start_paragraph"] == 2
    assert len(work.project.paragraphs(work.segment)) == 3
    bad = [dict(candidates[0]), dict(candidates[0], id="duplicate-range")]
    with pytest.raises(ValueError, match="重叠"):
        work.review_scenes(bad, [], "候选")


def test_language_defaults_and_explicit_override(work):
    settings = work.store.settings(work.account)
    settings.update(language_connection_id="node-0", language_max_tokens=10000)
    work.store.save_settings(work.account, settings)
    work.store.save_node_default(
        work.account, 1, dict(connection_override=False, parameter_override=False)
    )
    assert work.parameters(1)["connection_id"] == "node-0"
    assert work.parameters(1)["max_tokens"] == 10000
    work.store.save_node_default(
        work.account,
        1,
        dict(connection_id="node-1", connection_override=True, max_tokens=2345),
    )
    assert work.parameters(1)["connection_id"] == "node-1"
    assert work.parameters(1)["max_tokens"] == 2345
    work.store.save_node_default(
        work.account, 1, dict(connection_id="missing", connection_override=True)
    )
    with pytest.raises(ValueError, match="连接"):
        work.parameters(1)


def test_single_task_keeps_full_local_history_but_sends_only_current_turn(work):
    record = work.project.load_node(work.segment, 0)
    for i in range(8):
        record["messages"].extend(
            [
                dict(role="user", content=f"修订要求{i}"),
                dict(role="assistant", content="旧草稿" * 1000),
            ]
        )
    work.project.save_node(work.segment, 0, record)
    job, _, _, _ = work.prepare_text(0, "本轮要求")
    assert len(job["messages"]) < 17
    assert job["messages"] == [
        dict(
            role="user",
            content="本轮要求",
            time=job["messages"][0]["time"],
            attachments=[],
        )
    ]
    assert len(work.project.load_node(work.segment, 0)["messages"]) == 17
    assert job["request_summary"]["estimated_input_tokens"] > 0


def test_current_scene_context_does_not_repeat_source_or_downstream_outputs(work):
    work.confirm_split(rows())
    for n in (2, 3):
        d = work.project.load_node(work.scene, n)
        d.update(status="已确认", final=f"下游方案{n}")
        work.project.save_node(work.scene, n, d)
    context = work.context(1)
    assert context.count("甲走进渡口。") == 1
    assert "下游方案" not in context
    assert "乙交给她一封信。" not in context


def test_actual_usage_and_truncation_are_preserved(monkeypatch):
    from novelviz.providers import text_call

    monkeypatch.setattr(
        "novelviz.providers.request_json",
        lambda *args, **kwargs: dict(
            choices=[dict(message=dict(content="截断文本"), finish_reason="length")],
            usage=dict(prompt_tokens=120, completion_tokens=30),
        ),
    )
    meta = {}
    answer = text_call(
        dict(
            provider="openai",
            system="任务",
            endpoint="http://localhost:9999/v1",
            model="test",
            max_tokens=30,
            temperature=0.5,
        ),
        [dict(role="user", content="拆分")],
        "",
        metadata=meta,
    )
    assert answer == "截断文本"
    assert meta["usage"]["prompt_tokens"] == 120
    assert meta["finish_reason"] == "length"
    assert "截断" in meta["output_warning"]


def test_default_language_reference_remaps_on_settings_import(work, tmp_path):
    settings = work.store.settings(work.account)
    settings.update(language_connection_id="node-0", language_temperature=0)
    work.store.save_settings(work.account, settings)
    assert work.store.settings(work.account)["language_temperature"] == 0
    target = tmp_path / "settings.json"
    work.store.export_settings(work.account, target)
    work.store.import_settings(work.account, target)
    imported = work.store.settings(work.account)["language_connection_id"]
    assert imported.startswith("import-")
    assert imported in {c["id"] for c in work.store.connections(work.account)}


def candidate_output():
    return json.dumps(
        dict(
            assets=[
                dict(
                    name="甲",
                    kind="人物",
                    description="外貌未知",
                    source="原文明确",
                    evidence=[dict(paragraph=1, quote="甲走进渡口")],
                    attributes=[
                        dict(
                            name="行动",
                            value="走进渡口",
                            source="原文明确",
                            evidence_refs=[0],
                        )
                    ],
                    priority="核心",
                    priority_reason="当前章节主要行动者",
                    first_paragraph=1,
                )
            ]
        ),
        ensure_ascii=False,
    )


def test_chapter_assets_before_plot_candidates_mapping_and_archive(work):
    job, _, _, _ = work.prepare_text(1, "构建章节资产", paragraph_range=[1, 2])
    assert job["scope"] == work.segment
    assert "甲走进渡口" in job["context"] and "甲转身登船" in job["context"]
    work.process_task_output(job, candidate_output())
    candidate = work.project.config["asset_candidates"][work.segment][0]
    assert candidate["priority"] == "核心"
    assert candidate["attributes"][0]["evidence"][0]["quote"] == "甲走进渡口"
    assert not work.project.assets()
    work.candidate_action(candidate["id"], "approve")
    asset = work.project.assets()[0]
    assert asset["chapter_levels"][work.segment]["priority"] == "核心"
    scenes = work.confirm_split(rows())
    assert work.project.requirements(scenes[0]["id"])[0]["asset_id"] == asset["id"]
    assert work.project.requirements(scenes[1]["id"])[0]["asset_id"] == asset["id"]
    work.archive_asset(asset["id"])
    assert not work.project.assets()
    assert work.project.scene_assets(scenes[0]["id"])[0]["problem"] == "缺少档案"
    work.archive_asset(asset["id"], True)
    assert work.project.assets()[0]["id"] == asset["id"]


def test_consultation_exact_prefix_summary_only_and_explicit_reference(work):
    settings = work.store.settings(work.account)
    settings["language_preface"] = "用户首位规则"
    settings["compact_requests"] = False
    work.store.save_settings(work.account, settings)
    work.project.config["rules"] = "旧项目规则绝不能发送"
    work.project.save_config()
    work.save_summary("本章梗概哨兵")
    job, _, paths, _ = work.prepare_text(7, "第一次咨询", mode="consult")
    work.finish_text(job, "第一次回答")
    second, _, _, _ = work.prepare_text(7, "第二次咨询", mode="consult")
    assert second["params"]["system"] == "用户首位规则"
    assert second["context"] == "【本章内容梗概】\n本章梗概哨兵"
    assert (
        len(second["messages"]) == 1
        and second["messages"][0]["content"] == "第二次咨询"
    )
    assert "甲走进渡口" not in second["context"]
    assert not paths and not second["attachments"]
    with pytest.raises(ValueError, match="历史引用"):
        work.prepare_text(7, "追问", mode="consult", reference="明确引用的回答")


def test_completion_has_only_declared_context_and_never_applies_automatically(work):
    work.save_summary("梗概背景")
    settings = work.store.settings(work.account)
    settings.update(
        language_preface="用户前置", completion_guidance="只改描述；输出 changes JSON"
    )
    work.store.save_settings(work.account, settings)
    asset = work.save_asset(
        dict(name="甲", kind="人物", description="原描述", source="原文明确")
    )
    target = dict(
        asset, type="asset", segment=work.segment, project=work.project.meta["id"]
    )
    job, _, _, _ = work.prepare_text(
        5, "补全伤势", mode="complete", target=target, fields=["description"]
    )
    assert job["params"]["system"] == "用户前置"
    assert (
        "梗概背景" in job["context"]
        and "原描述" in job["context"]
        and "只改描述" in job["context"]
    )
    assert "甲走进渡口" not in job["context"]
    work.process_task_output(
        job,
        json.dumps(
            dict(
                changes=[
                    dict(field="description", value="建议的伤势", reason="世界知识推测")
                ]
            ),
            ensure_ascii=False,
        ),
    )
    assert work.project.assets()[0]["description"] == "原描述"
    assert job["changes"][0]["source"] == "AI建议"
    with pytest.raises(ValueError, match="未允许"):
        work.process_task_output(
            job,
            json.dumps(
                dict(changes=[dict(field="name", value="更名")]), ensure_ascii=False
            ),
        )


def test_single_requests_ignore_history_even_when_old_compact_setting_off(work):
    settings = work.store.settings(work.account)
    settings.update(compact_requests=False, language_preface="首位规则")
    work.store.save_settings(work.account, settings)
    previous = work.project.load_node(work.segment, 0)
    previous.update(
        messages=[
            dict(role="user", content="旧指令"),
            dict(role="assistant", content="旧输出"),
        ],
        final="旧最终方案",
    )
    work.project.save_node(work.segment, 0, previous)
    job, _, _, _ = work.prepare_text(0, "本轮解析")
    assert len(job["messages"]) == 1
    assert "旧指令" not in json.dumps(job["messages"], ensure_ascii=False)
    assert "旧最终方案" not in job["context"]
    assert job["params"]["system"].startswith("首位规则")
    assert len(work.project.load_node(work.segment, 0)["messages"]) == 3


def test_candidate_approval_existing_asset_does_not_overwrite_confirmed_content(work):
    asset = work.save_asset(
        dict(name="甲", kind="人物", description="用户确认的外貌", review="已锁定")
    )
    job, _, _, _ = work.prepare_text(1, "构建")
    work.process_task_output(job, candidate_output())
    candidate = work.project.config["asset_candidates"][work.segment][0]
    work.candidate_action(candidate["id"], "approve")
    assert len(work.project.assets()) == 1
    saved = work.project.assets()[0]
    assert (
        saved["id"] == asset["id"]
        and saved["description"] == "用户确认的外貌"
        and saved["review"] == "已锁定"
    )
    assert saved["appearances"][0]["segment"] == work.segment


def test_invalid_truncated_and_ambiguous_outputs_do_not_create_cards(work):
    from novelviz.prompts import parse_object

    job, _, _, _ = work.prepare_text(1, "构建")
    job["finish_reason"] = "length"
    with pytest.raises(ValueError, match="长度限制"):
        work.process_task_output(job, candidate_output())
    assert not work.project.config.get("asset_candidates")
    assert (
        parse_object("这是说明\n" + candidate_output(), expected="assets")["assets"][0][
            "name"
        ]
        == "甲"
    )
    with pytest.raises(ValueError, match="多份"):
        parse_object(candidate_output() + "\n" + candidate_output(), expected="assets")
    with pytest.raises(ValueError, match="JSON"):
        parse_object(candidate_output()[:-8], expected="assets")


def test_summary_is_stale_after_external_change_and_manual_summary_is_preserved(work):
    work.save_summary("人工梗概")
    work.save_summary("模型新梗概", manual=False)
    assert work.chapter_summary()["text"] == "人工梗概"
    assert work.chapter_summary()["suggested_text"] == "模型新梗概"
    segment = work.project.segments()[0]
    (work.project.path / segment["file"]).write_text("完全不同的原文", encoding="utf-8")
    with pytest.raises(ValueError, match="梗概"):
        work.prepare_text(7, "问题", mode="consult")


def test_prefix_inheritance_and_empty_override(work):
    settings = work.store.settings(work.account)
    settings["language_preface"] = "默认规则"
    work.store.save_settings(work.account, settings)
    assert work.parameters(0)["system"].startswith("默认规则")
    work.store.save_node_default(
        work.account, 0, dict(preface_override=True, preface="")
    )
    assert not work.parameters(0)["system"].startswith("默认规则")
    work.store.save_node_default(
        work.account, 0, dict(preface_override=True, preface="节点规则")
    )
    assert work.parameters(0)["system"].startswith("节点规则")


def test_bridge_single_task_generates_visible_candidates_without_plot(work):
    bridge = Bridge(work.store.root)
    bridge.workspace = work
    bridge.dispatch(
        "send", dict(node=1, message="构建章节资产", paragraph_range=[1, 2])
    )
    wait(bridge)
    state = work.snapshot()
    assert not state["scenes"] and len(state["asset_advice"]["items"]) == 1
    chosen = [state["asset_advice"]["items"][0]["id"]]
    bridge.dispatch(
        "send", dict(node=1, asset_phase="build", selected=chosen, message="建卡")
    )
    wait(bridge)
    assert len(work.snapshot()["assets"]) == 1


def test_consultation_wire_contains_only_prefix_summary_and_current_question(
    work, monkeypatch
):
    from novelviz.providers import text_call

    settings = work.store.settings(work.account)
    settings["language_preface"] = "用户首位规则"
    work.store.save_settings(work.account, settings)
    work.save_summary("章节摘要")
    job, _, _, _ = work.prepare_text(7, "当前问题", mode="consult")
    params = dict(
        job["params"],
        provider="openai",
        endpoint="http://127.0.0.1:9999/v1",
        model="mock",
        structured_output=True,
    )
    requests = []

    def request(url, payload, *args, **kwargs):
        requests.append(payload)
        return dict(choices=[dict(message=dict(content="回答"), finish_reason="stop")])

    monkeypatch.setattr("novelviz.providers.request_json", request)
    text_call(params, job["messages"], job["context"])
    assert requests[0]["messages"] == [
        dict(role="system", content="用户首位规则"),
        dict(role="user", content="【本章内容梗概】\n章节摘要"),
        dict(role="user", content="当前问题"),
    ]
    assert "response_format" not in requests[0]


def test_variants_inherit_forward_only_and_respect_choices(work):
    first = work.segment
    asset = work.save_asset(
        dict(name="角色", kind="人物", description="基础身份", review="已确认")
    )
    hurt = work.save_variant(asset["id"], "受伤", {"description": "伤口和绷带"})
    second = work.import_text("第二章", "角色伤愈。")
    assert (
        work.project.effective_asset(work.project.assets()[0], second)["description"]
        == "伤口和绷带"
    )
    healed = work.save_variant(asset["id"], "伤愈", {"description": "伤口愈合，无绷带"})
    third = work.import_text("第三章", "角色出发。")
    assert (
        work.project.effective_asset(work.project.assets()[0], third)["description"]
        == "伤口愈合，无绷带"
    )
    assert (
        work.project.effective_asset(work.project.assets()[0], first)["description"]
        == "伤口和绷带"
    )
    work.select_variant(asset["id"], "base")
    assert (
        work.project.effective_asset(work.project.assets()[0], third)["description"]
        == "基础身份"
    )
    work.select_variant(asset["id"], hurt["id"])
    assert work.project.effective_asset(work.project.assets()[0], third)["image"] == ""
    assert healed["id"] != hurt["id"]


def test_paste_merge_and_chapter_archive_preserve_original(work):
    original = work.segment
    old = work.project.segment_text(original)
    work.paste_chapter("追加", "追加正文", target=original)
    assert (
        len(work.project.segments()) == 1
        and work.project.segment_text(original) == old + "\n\n追加正文"
    )
    work.paste_chapter("前置", "开头正文", target=original, prepend=True)
    assert work.project.segment_text(original).startswith("开头正文\n\n")
    work.chapter_action(original)
    assert (
        not work.project.segments()
        and len(work.project.segments(include_archived=True)) == 1
    )
    work.chapter_action(original, True)
    assert work.project.segment_text(original).startswith("开头正文")


def test_attachment_upload_always_one_chapter(work):
    bridge = Bridge(work.store.root)
    bridge.workspace.close()
    bridge.workspace = work
    payload = ("一段正文。\n\n" * 300).encode()
    bridge.dispatch(
        "upload",
        dict(
            name="整本附件.txt", target="text", data=base64.b64encode(payload).decode()
        ),
    )
    assert len(work.project.segments()) == 2
    assert len(work.project.paragraphs(work.segment)) == 300


def test_asset_gate_and_local_alias_matching(work):
    work.project.config["asset_ready"] = {}
    with pytest.raises(ValueError, match="资产整理"):
        work.prepare_text(0, "拆分")
    work.finish_assets([])
    asset = work.save_asset(
        dict(
            name="人物本名",
            kind="人物",
            description="测试",
            aliases=["甲"],
            review="已确认",
        )
    )
    scenes = work.confirm_split(rows())
    assert all(
        work.project.requirements(s["id"])[0]["asset_id"] == asset["id"] for s in scenes
    )
    work.paste_chapter("追加", "新内容", work.segment)
    assert not work.assets_ready()


def test_recommendation_build_only_selected_and_evidence_normalization(work):
    work.save_advice("1. 甲｜人物｜核心｜主要人物\n2. 渡口｜场景｜重要｜地点")
    items = work.project.config["asset_advice"][work.segment]["items"]
    job, _, _, _ = work.prepare_text(1, "建卡", selected=[items[0]["id"]])
    output = json.loads(candidate_output())
    output["assets"][0]["attributes"][0].pop("evidence_refs")
    output["assets"][0]["attributes"][0]["evidence"] = {
        "paragraph": 1,
        "quote": "甲走进渡口",
    }
    work.process_task_output(job, json.dumps(output, ensure_ascii=False))
    assert len(work.project.assets()) == 1
    work.finish_assets([items[0]["id"]], confirm_pending=True)
    with pytest.raises(ValueError, match="尚未"):
        work.finish_assets([items[1]["id"]])


def test_partial_build_keeps_valid_cards_and_blocks_finish(work):
    work.save_advice("1. 甲｜人物｜核心｜主角\n2. 乙｜人物｜重要｜配角")
    items = work.project.config["asset_advice"][work.segment]["items"]
    job, _, _, _ = work.prepare_text(1, "建卡", selected=[i["id"] for i in items])
    output = json.loads(candidate_output())
    output["assets"].append(
        dict(
            name="乙",
            kind="人物",
            description="资料",
            source="原文明确",
            evidence=[dict(paragraph=99, quote="不存在")],
        )
    )
    with pytest.raises(ValueError, match="部分建卡"):
        work.process_task_output(job, json.dumps(output, ensure_ascii=False))
    assert work.project.assets()[0]["name"] == "甲"
    with pytest.raises(ValueError, match="尚未"):
        work.finish_assets([i["id"] for i in items])


def test_local_match_ambiguity_and_manual_exclusion(work):
    a = work.save_asset(dict(name="甲", kind="人物", description="甲", review="已确认"))
    b = work.save_asset(
        dict(
            name="另一人",
            aliases=["甲"],
            kind="人物",
            description="另一人",
            review="已确认",
        )
    )
    scenes = work.confirm_split(rows())
    assert not work.project.requirements(scenes[0]["id"])
    assert work.project.config["asset_match_ambiguities"][scenes[0]["id"]] == ["甲"]
    work.save_asset(dict(id=b["id"], aliases=[]))
    assert work.project.requirements(scenes[0]["id"])[0]["asset_id"] == a["id"]
    bridge = Bridge(work.store.root)
    bridge.workspace.close()
    bridge.workspace = work
    bridge.dispatch("requirements", dict(rows=[]))
    work.map_assets_to_scenes()
    assert not work.project.requirements(work.scene)


def test_plot_optional_asset_fields_do_not_block(work):
    job, _, _, _ = work.prepare_text(0, "拆分")
    text = json.dumps(
        dict(
            scenes=[
                dict(
                    title="一段",
                    start_paragraph=1,
                    end_paragraph=3,
                    required_assets=["甲"],
                )
            ]
        ),
        ensure_ascii=False,
    )
    work.process_task_output(job, text)
    assert len(work.project.config["split_drafts"][work.segment]["rows"]) == 1


def test_asset_review_and_visual_field_separation_and_export(work, tmp_path):
    asset = work.save_asset(
        dict(
            name="甲",
            kind="人物",
            details=dict(
                face="棕色眼睛",
                body="高挑",
                background="父母是教师",
                relationships="乙是朋友",
            ),
        )
    )
    work.review_assets([asset["id"]], "已锁定")
    with pytest.raises(ValueError, match="锁定"):
        work.save_asset(dict(id=asset["id"], name="新名字"))
    work.review_assets([asset["id"]], "已确认")
    work.add_reference(asset["id"], picture(tmp_path / "reference.png"))
    work.confirm_split(rows())
    work.project.set_requirements(
        work.scene, [dict(name="甲", kind="人物", asset_id=asset["id"])]
    )
    bundle = work.render_bundle("甲站在渡口，平视中景，柔和侧光。")
    assert "棕色眼睛" not in bundle["text"] and "参考图1" in bundle["text"]
    assert "父母" not in bundle["text"] and "朋友" not in bundle["text"]
    work.keys[work.account["id"] + ":test"] = "secret-sentinel"
    exported = work.export_render_bundle("甲站在渡口，平视中景。", "渡口")
    from pathlib import Path

    folder = Path(exported["path"])
    assert (folder / "参考图1_甲.png").is_file()
    assert "父母" not in (folder / "生图方案.md").read_text()
    assert work.export_render_bundle("甲站在渡口。", "渡口")["path"] != str(folder)
    assert not work.project.jobs()


def test_render_final_plan_validation_and_retired_prompt(work):
    from novelviz.rendering import validate_plan

    for text in ("建议：增加人物", "## 关键缺项：外观", "需要确认人物"):
        with pytest.raises(ValueError):
            validate_plan(text)
    with pytest.raises(ValueError, match="停用"):
        work.prepare_text(3, "定稿")


def test_plot_asset_links_persist_exclusions_and_cast(work):
    asset = work.save_asset(dict(name="甲", kind="人物", description="黑色上衣"))
    work.confirm_split(rows())
    bridge = Bridge(work.store.root)
    bridge.workspace = work
    assert any(
        r.get("asset_id") == asset["id"] for r in work.project.requirements(work.scene)
    )
    bridge.dispatch(
        "scene_assets_edit", dict(scene=work.scene, id=asset["id"], action="remove")
    )
    work.map_assets_to_scenes()
    assert not work.project.requirements(work.scene)
    bridge.dispatch(
        "scene_assets_edit", dict(scene=work.scene, id=asset["id"], action="add")
    )
    bridge.dispatch("scene_cast", dict(asset=asset["id"], included=False))
    assert not work.render_state()["rows"]
    assert len(work.project.requirements(work.scene)) == 1
    bridge.dispatch("scene_cast", dict(asset=asset["id"], included=True))
    assert len(work.render_state()["rows"]) == 1


def test_prompt_v5_preserves_edits_and_upgrades_untouched():
    from novelviz.prompts import upgrade_template, default_template

    old = dict(
        id="scene",
        node=2,
        format="text",
        name="场景插图方案",
        version="4.0",
        body="根据当前情节、确认的资产和选定副卡，给一个单张插图方案。简述画面瞬间、实际出镜对象、动作与空间关系、构图和光线。只表现同一时刻，尊重原文，不增加角色或调换道具。仅列会影响制作的关键缺项，不输出长篇分析或默认备选。",
    )
    assert upgrade_template(old) == default_template(2)
    old["body"] += "用户私人规则"
    assert upgrade_template(old)["body"].endswith("用户私人规则")


def test_comfy_reference_numbers_match_actual_upload_and_offline_export(
    work, tmp_path, monkeypatch
):
    first = work.save_asset(
        dict(name="甲", kind="人物", details=dict(face="圆脸"), review="已确认")
    )
    second = work.save_asset(
        dict(name="乙", kind="人物", details=dict(body="高大"), review="已确认")
    )
    work.add_reference(second["id"], picture(tmp_path / "乙.png"))
    work.confirm_split(rows())
    work.project.set_requirements(
        work.scene,
        [dict(name=a["name"], kind="人物", asset_id=a["id"]) for a in (first, second)],
    )
    work.save_connection(
        dict(
            id="local-comfy",
            name="本地",
            kind="comfy",
            endpoint="http://127.0.0.1:9999",
        )
    )
    work.store.save_image_defaults(
        work.account,
        dict(
            connection_id="local-comfy",
            workflow=json.dumps(
                {
                    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
                    "7": {"class_type": "LoadImage", "inputs": {"image": ""}},
                    "8": {
                        "class_type": "TestOutput",
                        "inputs": {"text": ["6", 0], "image": ["7", 0]},
                    },
                }
            ),
            mapping=json.dumps(
                {"prompt": ["6", "text"], "reference_1": ["7", "image"]}
            ),
        ),
    )
    bridge = Bridge(work.store.root)
    bridge.workspace = work
    bridge.confirm = lambda *a: True
    captured = []
    uploaded = []
    monkeypatch.setattr(
        bridge, "start", lambda job, fn, text: captured.append((job, fn))
    )
    monkeypatch.setattr(
        "novelviz.desktop.upload_comfy",
        lambda endpoint, path, key: uploaded.append(path) or "uploaded.png",
    )
    flows = []
    monkeypatch.setattr(
        "novelviz.desktop.comfy_call",
        lambda endpoint, flow, *a: flows.append(flow) or [],
    )
    bridge.dispatch("generate", dict(plan="甲与乙（参考图1）在渡口相遇。"))
    job, fn = captured[0]
    fn(threading.Event(), lambda x: None)
    assert len(uploaded) == 1 and uploaded[0].is_file()
    assert flows[0]["7"]["inputs"]["image"] == "uploaded.png"
    assert "乙（参考图1）" in job["prompt"] and "参考图2" not in job["prompt"]
    exported = work.export_render_bundle("甲与乙（参考图1）在渡口相遇。", "相遇")
    assert (Path(exported["path"]) / "生图方案.md").read_text() == job["prompt"]
    with pytest.raises(ValueError, match="编号"):
        work.render_bundle("甲（参考图2）")


def test_asset_variant_render_plans_are_separate_and_can_adopt_reference(
    work, tmp_path
):
    asset = work.save_asset(
        dict(name="甲", kind="人物", details=dict(face="圆脸"), review="已确认")
    )
    work.save_render_plan("甲正面站立。", asset["id"])
    variant = work.save_variant(
        asset["id"], "受伤", dict(details=dict(appearance_state="左臂绷带"))
    )
    assert work.render_state(asset["id"])["text"] == ""
    work.save_render_plan("甲左臂缠绷带。", asset["id"])
    work.select_variant(asset["id"], "base")
    assert work.render_state(asset["id"])["text"] == "甲正面站立。"
    work.select_variant(asset["id"], variant["id"])
    image = picture(work.project.path / "05_生成任务/test.png")
    work.project.save_job(
        dict(
            id="render-variant",
            created="2026-11-16",
            status="success",
            node=4,
            asset=asset["id"],
            results=[str(image.relative_to(work.project.path))],
        )
    )
    bridge = Bridge(work.store.root)
    bridge.workspace = work
    bridge.dispatch(
        "candidate_to_reference",
        dict(
            asset=asset["id"],
            variant=variant["id"],
            path=str(image.relative_to(work.project.path)),
        ),
    )
    assert (
        work.render_state(asset["id"])["references"][0]["variant"]["id"]
        == variant["id"]
    )

    assert not work.project.assets()[0].get("image")


def set_association(work, mode):
    work.store.save_settings(
        work.account,
        {**work.store.settings(work.account), "asset_association_mode": mode},
    )


def test_default_ai_association_and_first_person_single_request(work):
    from novelviz.storage import DEFAULTS

    assert DEFAULTS["asset_association_mode"] == "ai"
    set_association(work, "ai")
    work.import_text("第一人称", "我推开教室的门。")
    asset = work.save_asset(
        dict(
            name="李明",
            kind="人物",
            details=dict(background="本章第一人称叙述者"),
            review="已确认",
        )
    )
    work.finish_assets([], confirm_pending=True)
    job, _, _, _ = work.prepare_text(0, "拆分")
    assert len(job["messages"]) == 1 and len(work.project.jobs()) == 1
    assert (
        job["association_mode"] == "ai"
        and job["association_index"][0]["id"] == asset["id"]
    )
    assert "asset_ids" in job["params"]["system"] and "第一人称" in job["context"]
    output = dict(
        summary="李明进入教室",
        scenes=[
            dict(
                title="入室",
                start_paragraph=1,
                end_paragraph=1,
                asset_ids=[asset["id"]],
            )
        ],
    )
    work.process_task_output(job, json.dumps(output, ensure_ascii=False))
    drafts = work.snapshot()["drafts"][work.segment]["rows"]
    assert drafts[0]["required_assets"][0]["asset_id"] == asset["id"]
    work.confirm_split(drafts)
    assert work.project.requirements(work.scene)[0]["asset_id"] == asset["id"]
    work.map_assets_to_scenes()
    assert work.project.requirements(work.scene)[0]["asset_id"] == asset["id"]


def test_ai_association_invalid_ids_no_guess_or_retry_and_manual_preserved(work):
    set_association(work, "ai")
    a = work.save_asset(dict(name="甲", kind="人物", review="已确认"))
    b = work.save_asset(dict(name="乙", kind="人物", review="已确认"))
    work.confirm_split(rows())
    scene = work.scene
    work.project.set_requirements(
        scene, [dict(name="乙", kind="人物", asset_id=b["id"])]
    )
    work.project.config.setdefault("asset_match_exclusions", {})[scene] = [a["id"]]
    work.project.save_config()
    job, _, _, _ = work.prepare_text(0, "重新解析")
    proposed = rows()
    proposed[0]["asset_ids"] = ["unknown-id"]
    work.process_task_output(job, json.dumps(dict(scenes=proposed)))
    candidates = work.project.config["split_drafts"][work.segment]["rows"]
    assert candidates[0]["association_note"] and all(
        r["asset_id"] != "unknown-id" for r in candidates[0]["required_assets"]
    )
    assert len(work.project.jobs()) == 1
    proposed[0]["asset_ids"] = [a["id"]]
    work.process_task_output(job, json.dumps(dict(scenes=proposed)))
    candidates = work.project.config["split_drafts"][work.segment]["rows"]
    assert candidates[0]["id"] == scene
    assert [r["asset_id"] for r in candidates[0]["required_assets"]] == [b["id"]]
    work.confirm_split(candidates)
    assert [r["asset_id"] for r in work.project.requirements(scene)] == [b["id"]]


def test_manual_association_does_not_scan_names(work):
    set_association(work, "manual")
    work.save_asset(dict(name="甲", kind="人物", review="已确认"))
    work.confirm_split(rows())
    work.map_assets_to_scenes()
    assert not work.project.requirements(work.scene)


def test_scene_reference_omits_visual_text_and_explicit_api_fallback(
    work, tmp_path, monkeypatch
):
    a = work.save_asset(
        dict(name="甲", kind="人物", details=dict(face="外观哨兵甲"), review="已确认")
    )
    b = work.save_asset(
        dict(
            name="乙", kind="人物", details=dict(body="无图外观哨兵乙"), review="已确认"
        )
    )
    work.add_reference(a["id"], picture(tmp_path / "a.png"))
    work.confirm_split(rows())
    work.project.set_requirements(
        work.scene,
        [dict(name=r["name"], kind="人物", asset_id=r["id"]) for r in (a, b)],
    )
    bundle = work.render_bundle("甲（参考图1）和乙在渡口交谈。")
    assert "外观哨兵甲" not in bundle["text"] and "无图外观哨兵乙" in bundle["text"]
    assert "外观哨兵甲" not in work.context(2)
    work.save_connection(
        dict(
            id="img",
            name="图片",
            kind="image_api",
            endpoint="http://localhost:9999/v1",
            model="test",
        )
    )
    work.store.save_image_defaults(work.account, dict(connection_id="img"))
    bridge = Bridge(work.store.root)
    bridge.workspace = work
    calls = []
    monkeypatch.setattr(bridge, "start", lambda job, fn, text: calls.append(job))
    bridge.confirm = lambda *a: False
    assert bridge.dispatch("generate", dict(plan="甲（参考图1）和乙交谈。"))[
        "cancelled"
    ]
    assert not calls
    bridge.confirm = lambda *a: True
    bridge.dispatch("generate", dict(plan="甲（参考图1）和乙交谈。"))
    assert calls[0]["reference_fallback"] and not calls[0]["references"]
    assert "外观哨兵甲" in calls[0]["prompt"] and "参考图" not in calls[0]["prompt"]


def test_export_flat_overwrite_preserves_extra_files_and_refuses_other_plan(
    work, tmp_path
):
    a = work.save_asset(dict(name="甲", kind="人物", review="已确认"))
    work.add_reference(a["id"], picture(tmp_path / "a.png"))
    work.confirm_split(rows())
    work.project.set_requirements(
        work.scene, [dict(name="甲", kind="人物", asset_id=a["id"])]
    )
    result = work.export_render_bundle("甲站在渡口。", "素材")
    folder = Path(result["path"])
    assert (folder / "参考图1_甲.png").is_file()
    assert not (folder / "参考图").exists()
    (folder / "用户备注.txt").write_text("保留")
    options = work.render_export_options("素材")
    assert options["versions"][0]["path"] == str(folder)
    result2 = work.export_render_bundle(
        "甲坐在渡口。", "素材", mode="overwrite", version=str(folder)
    )
    assert (
        result2["path"] == str(folder) and "坐" in (folder / "生图方案.md").read_text()
    )
    assert (folder / "用户备注.txt").read_text() == "保留"
    assert not list(folder.parent.glob(".覆盖前_*"))
    with pytest.raises(ValueError, match="另一份|素材版本"):
        work.export_render_bundle(
            "甲角色设定图。",
            "素材",
            asset=a["id"],
            mode="overwrite",
            version=str(folder),
        )


def test_external_scene_image_is_candidate_before_confirmation(work, tmp_path):
    work.confirm_split(rows())
    image = picture(tmp_path / "外部.png")
    bridge = Bridge(work.store.root)
    bridge.workspace = work
    result = bridge.dispatch(
        "upload",
        dict(
            target="scene_image",
            name="外部.png",
            data=base64.b64encode(image.read_bytes()).decode(),
        ),
    )
    image.unlink()
    assert work.file(result["path"]).is_file()
    assert work.snapshot()["jobs"][0]["source"] == "用户导入"
    assert not work.project.final_results()
    bridge.dispatch("scene_candidate", dict(path=result["path"]))
    assert work.snapshot()["jobs"][0]["pictures"][0]["hidden"]
    assert work.file(result["path"]).is_file()
    bridge.dispatch("scene_candidate", dict(path=result["path"], restore=True))
    assert not work.snapshot()["jobs"][0]["pictures"][0]["hidden"]
    bridge.dispatch("choose_result", dict(path=result["path"]))
    assert len(work.project.final_results()) == 1
    assert len(work.project.jobs()) == 1


def test_import_counts_and_estimates_for_paste_merge_and_attachment(work):
    bridge = Bridge(work.store.root)
    bridge.workspace = work
    result = bridge.dispatch("import_text", dict(name="新章", text="我走进教室。"))
    report = result["import_estimate"]
    assert report["import_characters"] == 6
    assert (
        report["chapter_characters"] == 6 and report["split"][1] > report["source"][1]
    )
    assert "不含输出" in report["method"] and not work.project.jobs()
    chapter = work.segment
    result = bridge.dispatch(
        "import_text", dict(name="合并", text="下雨了。", target=chapter)
    )
    assert result["import_estimate"]["chapter_characters"] == 10
    assert result["import_estimate"]["import_characters"] == 4
    result = bridge.dispatch(
        "upload",
        dict(
            target="text",
            name="附件.txt",
            data=base64.b64encode("一个独立附件。".encode()).decode(),
        ),
    )
    assert (
        result["import_estimate"]["chapter_characters"] == 7 and work.segment != chapter
    )


def test_asset_picture_default_rules_and_upgrade_preserve_personal_edit():
    from novelviz.prompts import default_template, upgrade_template

    template = default_template(5)
    assert (
        "背景人群" in template["body"]
        and "持握者" in template["body"]
        and "前景" in template["body"]
    )
    old = dict(template, version="5.0", body="我的自定义提示词")
    assert upgrade_template(old)["body"] == "我的自定义提示词"


def test_bookshelf_covers_account_isolation_and_reader_reuses_source(work, tmp_path):
    book = work.bookshelf()[0]
    assert set(book) == {"id", "name", "path", "cover"} and not book["cover"]
    original = work.project.segment_text(work.segment)
    result = work.reader_chapter()
    assert len(result["paragraphs"]) == 3 and result["source_hash"]
    assert work.project.segment_text(work.segment) == original
    work.set_book_cover(picture(tmp_path / "cover.png"))
    assert work.bookshelf()[0]["cover"].startswith("data:image/jpeg")
    work.set_book_cover()
    assert not work.bookshelf()[0]["cover"]
    other = work.store.create_account("其他读者")
    work.login(other["id"])
    assert not work.bookshelf()


def test_reading_position_bookmarks_relocation_and_stale_source(work):
    chapter = work.segment
    work.save_reading_position(dict(chapter=chapter, paragraph=2, offset=2))
    work.reader_bookmark(
        dict(anchor=dict(chapter=chapter, paragraph=2, offset=2), label="交信")
    )
    source = work.file(work.project.segments()[0]["file"])
    source.write_text("新加入的开头。\n\n" + source.read_text(), encoding="utf-8")
    reading = work.reader_chapter()
    assert reading["position"]["paragraph"] == 3 and reading["position"]["offset"] == 2
    assert reading["position"]["relocated"]
    assert reading["bookmarks"][0]["anchor"]["paragraph"] == 3
    old_hash = reading["source_hash"]
    source.write_text("完全不同的正文。", encoding="utf-8")
    assert work.reader_chapter()["position"]["stale"]
    with pytest.raises(ValueError, match="原文已变化"):
        work.save_reading_position(
            dict(chapter=chapter, paragraph=1, offset=0, source_hash=old_hash)
        )
    bookmark = work.reader_chapter()["bookmarks"][0]
    work.reader_bookmark(dict(action="delete", id=bookmark["id"]))
    assert not work.reader_chapter()["bookmarks"]


def test_reader_preferences_persist_and_do_not_change_production_selection(work):
    first = work.segment
    work.reader_preferences(dict(mode="pages", font_size=24, images_collapsed=True))
    assert work.reader_preferences()["images_collapsed"]
    assert (work.project.path / "08_项目数据/阅读记录.json").is_file()
    second = work.import_text("第二章", "第二章正文。")
    work.reader_chapter(first)
    assert work.segment == second
    work.chapter_action(first)
    with pytest.raises(ValueError):
        work.reader_chapter(first)
    for change in [
        dict(mode="invalid"),
        dict(font_size=100),
        dict(images_collapsed="true"),
    ]:
        with pytest.raises(ValueError):
            work.reader_preferences(change)


def test_reader_media_range_primary_and_all_variants_are_read_only(work, tmp_path):
    asset = work.save_asset(dict(name="甲", kind="人物", review="已确认"))
    work.add_reference(asset["id"], picture(tmp_path / "base.png"))
    path = work.project.assets()[0]["image"]
    hurt = work.save_variant(asset["id"], "受伤", dict(description="有伤"), image=path)
    work.import_text("第二章", "我已伤愈。")
    healed = work.save_variant(
        asset["id"], "伤愈", dict(description="伤愈"), image=path
    )
    first = work.project.segments()[0]["id"]
    work.set_selection(segment=first)
    work.confirm_split(rows())
    work.project.set_requirements(
        work.scene, [dict(name="甲", kind="人物", asset_id=asset["id"])]
    )
    choices = json.loads(
        json.dumps(work.project.config.get("chapter_variant_selections", {}))
    )
    media = work.reader_media(first, 1, 1)
    assert [im["title"] for im in media["assets"][0]["images"]] == [
        "主卡",
        "受伤",
        "伤愈",
    ]
    assert choices == work.project.config.get("chapter_variant_selections", {})
    assert hurt["id"] != healed["id"] and work.project.segment_text(first).startswith(
        "甲走进"
    )
    with pytest.raises(ValueError):
        work.reader_media(first, 0, 100)


def test_results_edit_replace_delete_restore_preserves_jobs_and_original(
    work, tmp_path
):
    work.confirm_split(rows())
    source = picture(tmp_path / "candidate.png")
    copied = work.project.path / "05_生成任务/candidate.png"
    copied.write_bytes(source.read_bytes())
    job = dict(
        id="imported-result",
        created="2026-11-16",
        scene=work.scene,
        results=[copied.relative_to(work.project.path).as_posix()],
        status="success",
    )
    work.project.save_job(job)
    work.select_result(job["results"][0])
    result = work.project.final_results()[0]
    original = work.file(result["file"])
    updated = work.result_edit(
        dict(id=result["id"], title="新标题", description="已编辑")
    )
    assert updated["title"] == "新标题"
    work.result_edit(dict(id=result["id"]), picture(tmp_path / "replacement.png"))
    assert original.is_file() and copied.is_file()
    work.results_delete([result["id"]])
    assert not work.project.final_results()
    assert work.result_trash()[0]["title"] == "新标题"
    assert work.project.jobs()[0]["id"] == job["id"] and work.project.scene(work.scene)
    work.results_delete([result["id"]], restore=True)
    assert work.project.final_results()[0]["description"] == "已编辑"
    assert not work.result_trash()
    with pytest.raises(ValueError):
        work.result_edit(dict(id=result["id"], scene="other-project-scene"))
    with pytest.raises(ValueError):
        work.results_delete(["missing"])


def test_whole_book_recycle_restore_and_permanent_scope(work, tmp_path):
    identity = work.project.meta["id"]
    name = work.project.meta["name"]
    root = work.project.path
    marker = root / "06_最终成果" / "保留.txt"
    marker.write_text("original")
    outside = work.store.account_dir(work.account) / "不要删除.txt"
    outside.write_text("keep")
    work.busy = True
    with pytest.raises(ValueError, match="任务仍在运行"):
        work.book_delete(identity, name)
    work.busy = False
    with pytest.raises(ValueError, match="书名"):
        work.book_delete(identity, "wrong")
    work.book_delete(identity, name)
    assert not root.exists() and work.project is None and not work.bookshelf()
    trash = work.book_trash()
    assert len(trash) == 1
    work.book_trash_action(trash[0]["trash_id"], name, restore=True)
    assert marker.read_text() == "original" and work.bookshelf()[0]["id"] == identity
    work.open_project(str(root))
    work.book_delete(identity, name, permanent=True)
    assert not root.exists() and outside.read_text() == "keep" and not work.book_trash()


def test_book_trash_is_account_isolated_and_purge_needs_name(work):
    identity = work.project.meta["id"]
    name = work.project.meta["name"]
    account = work.account
    work.book_delete(identity, name)
    record = work.book_trash()[0]
    other = work.store.create_account("other")
    work.login(other["id"])
    assert work.book_trash() == []
    with pytest.raises(ValueError):
        work.book_trash_action(record["trash_id"], name)
    work.login(account["id"])
    with pytest.raises(ValueError):
        work.book_trash_action(record["trash_id"], "wrong")
    work.book_trash_action(record["trash_id"], name)
    assert not work.book_trash()


def test_presets_select_exact_count_without_switching_connections(work):
    from test_workflows import graph

    work.save_connection(
        dict(id="comfy-a", name="云端", kind="comfy", endpoint="http://localhost:8188")
    )
    work.save_connection(
        dict(id="comfy-b", name="本地", kind="comfy", endpoint="http://localhost:8189")
    )
    from novelviz.workflows import inspect_flow

    for cid, count in [("comfy-a", 1), ("comfy-a", 2), ("comfy-b", 3)]:
        f = graph(count)
        work.save_workflow_preset(
            dict(
                id=cid + str(count),
                name=f"{count}图",
                connection_id=cid,
                workflow=f,
                mapping=inspect_flow(f)["mapping"],
                reference_count=count,
                default=True,
            )
        )
    config = work.store.image_defaults(work.account)
    config["connection_id"] = "comfy-a"
    work.store.save_image_defaults(work.account, config)
    chosen, c = work.resolve_generation("illustration", 2)
    assert chosen["preset_id"] == "comfy-a2" and c["id"] == "comfy-a"
    with pytest.raises(ValueError):
        work.resolve_generation("illustration", 3)
    chosen, c = work.resolve_generation(
        "illustration", 3, dict(connection_id="comfy-b", preset_id="comfy-b3")
    )
    assert c["id"] == "comfy-b"
    assert work.store.image_defaults(work.account)["connection_id"] == "comfy-a"
    with pytest.raises(ValueError):
        work.resolve_generation(
            "illustration", 1, dict(connection_id="comfy-a", preset_id="comfy-a2")
        )


def test_ai_workflow_mapping_uses_default_only_and_no_user_material(work, monkeypatch):
    from test_workflows import graph
    from novelviz.workflows import inspect_flow

    b = Bridge(work.store.root)
    b.workspace = work
    f = graph()
    f["2"]["inputs"]["ui_cache"] = {"urls": ["nested-old-filename.png"]}
    monkeypatch.setattr(
        "novelviz.desktop.text_call",
        lambda *a, **k: pytest.fail("default local must not call AI"),
    )
    r = b.dispatch("workflow_inspect", dict(workflow=f))
    assert r["done"] and r["mapping"] == inspect_flow(f)["mapping"]
    work.save_connection(
        dict(
            id="map-model",
            name="映射模型",
            kind="openai",
            endpoint="http://localhost:9999/v1",
            model="mapper",
        )
    )
    settings = work.store.settings(work.account)
    work.store.save_settings(
        work.account,
        dict(
            settings,
            workflow_ai_assist=True,
            language_connection_id="map-model",
            language_preface="用户前置规则",
        ),
    )
    seen = []

    def call(params, messages, context, *args, **kwargs):
        seen.append((params, messages, context))
        return json.dumps(dict(mapping=inspect_flow(f)["mapping"], warnings=[]))

    monkeypatch.setattr("novelviz.desktop.text_call", call)
    b.dispatch("workflow_inspect", dict(workflow=f))
    wait(b)
    result = b.dispatch("workflow_inspect_status", {})
    assert result["done"] and result["mapping"] == inspect_flow(f)["mapping"]
    assert seen[0][0]["model"] == "mapper" and seen[0][0]["system"].startswith(
        "用户前置规则"
    )
    request = json.dumps(seen[0][1], ensure_ascii=False)
    assert (
        "old prompt" not in request
        and "old-1.png" not in request
        and "甲走进渡口" not in request
    )
    assert "nested-old-filename" not in request
    assert seen[0][2] == "" and len(seen[0][1]) == 1


def test_generation_options_counts_only_actual_files_and_never_switches_service(
    work, tmp_path
):
    from test_workflows import graph
    from novelviz.workflows import inspect_flow

    a = work.save_asset(dict(name="甲", kind="人物", review="已确认"))
    b = work.save_asset(dict(name="乙", kind="人物", review="已确认"))
    work.add_reference(b["id"], picture(tmp_path / "ref.png"))
    work.confirm_split(rows())
    work.project.set_requirements(
        work.scene,
        [dict(name=x["name"], kind="人物", asset_id=x["id"]) for x in (a, b)],
    )
    for cid, count in [("default-cloud", 2), ("other-local", 1)]:
        work.save_connection(
            dict(id=cid, name=cid, kind="comfy", endpoint="http://localhost:8188")
        )
        f = graph(count)
        work.save_workflow_preset(
            dict(
                id=cid,
                name=cid,
                connection_id=cid,
                reference_count=count,
                workflow=f,
                mapping=inspect_flow(f)["mapping"],
            )
        )
    config = work.store.image_defaults(work.account)
    work.store.save_image_defaults(
        work.account, dict(config, connection_id="default-cloud")
    )
    options = work.generation_options(plan="甲与乙相遇。")
    assert options["reference_count"] == 1 and options["selected"] == ""
    assert any(
        r["connection_id"] == "other-local" and r["available"]
        for r in options["options"]
    )
    assert not any(
        r["connection_id"] == "default-cloud" and r["available"]
        for r in options["options"]
    )
    assert not work.project.jobs()


def test_workflow_presets_export_import_remaps_connections_without_keys(work, tmp_path):
    from test_workflows import graph
    from novelviz.workflows import inspect_flow

    work.save_connection(
        dict(id="cloud", name="cloud", kind="comfy", endpoint="http://localhost:8799")
    )
    f = graph(1)
    work.save_workflow_preset(
        dict(
            id="one",
            name="单图",
            connection_id="cloud",
            reference_count=1,
            workflow=f,
            mapping=inspect_flow(f)["mapping"],
        )
    )
    dest = tmp_path / "settings.json"
    work.store.export_settings(work.account, dest)
    other = work.store.create_account("imported")
    work.store.import_settings(other, dest)
    imported = work.store.image_defaults(other)["presets"][0]
    assert imported["connection_id"] != "cloud"
    assert any(
        c["id"] == imported["connection_id"] for c in work.store.connections(other)
    )
    assert imported["mapping"] == json.dumps(
        inspect_flow(f)["mapping"], ensure_ascii=False
    )
    assert all(
        c["endpoint"] == "http://localhost:8188"
        for c in work.store.connections(other)
        if c["id"] == imported["connection_id"]
    )


def test_per_node_preset_precedes_group_default(work):
    from test_workflows import graph
    from novelviz.workflows import inspect_flow

    work.confirm_split(rows())
    work.save_connection(
        dict(id="choose", name="choose", kind="comfy", endpoint="http://localhost:8188")
    )
    f = graph(0)
    for identity in ("group-default", "node-choice"):
        work.save_workflow_preset(
            dict(
                id=identity,
                name=identity,
                connection_id="choose",
                reference_count=0,
                workflow=f,
                mapping=inspect_flow(f)["mapping"],
                default=identity == "group-default",
            )
        )
    config = work.store.image_defaults(work.account)
    work.store.save_image_defaults(
        work.account,
        dict(
            config,
            connection_id="choose",
            tasks=dict(
                illustration=dict(
                    connection_override=True,
                    connection_id="choose",
                    preset_id="node-choice",
                )
            ),
        ),
    )
    assert (
        work.generation_options(plan="雨夜渡口。")["selected"] == "choose:node-choice"
    )


def test_multiple_results_sorted_chapter_scene_and_idempotent(work, tmp_path):
    work.confirm_split(rows())
    first = work.segment
    scenes = work.project.scenes(first)
    for i, scene in enumerate(reversed(scenes)):
        work.set_selection(scene=scene["id"])
        work.import_scene_image(picture(tmp_path / f"one{i}.png"))
        work.choose_results([work.project.jobs()[0]["results"][0]])
    work.set_selection(scene=scenes[0]["id"])
    work.import_scene_image(picture(tmp_path / "extra.png"))
    source = work.project.jobs()[0]["results"][0]
    work.choose_results([source, source])
    records = work.project.final_results()
    assert len(records) == 3 and [r["scene"] for r in records] == [
        scenes[0]["id"],
        scenes[0]["id"],
        scenes[1]["id"],
    ]
    count = len(list((work.project.path / "06_最终成果").glob("*.png")))
    work.choose_results([source])
    assert len(work.project.final_results()) == 3
    assert len(list((work.project.path / "06_最终成果").glob("*.png"))) == count
    work.choose_results([source], False)
    assert len(work.project.final_results()) == 2 and work.file(source).is_file()
    work.choose_results([source])
    assert len(work.project.final_results()) == 3
    assert len(list((work.project.path / "06_最终成果").glob("*.png"))) == count
    assert (
        work.project.progress()["illustrated_scenes"] == 2
        and work.project.progress()["results"] == 3
    )
    second = work.import_text("第二章", "甲站在桥上。")
    work.finish_assets([])
    work.confirm_split(
        [dict(title="桥上", summary="", start_paragraph=1, end_paragraph=1)]
    )
    work.import_scene_image(picture(tmp_path / "chapter2.png"))
    work.choose_results([work.project.jobs()[0]["results"][0]])
    work.manage_chapter(ids=[second, first])
    assert work.project.final_results()[0]["segment"] == second
    assert len(work.snapshot()["results"]) == 4  # no current-chapter filter


def test_result_groups_edit_restore_and_reader_only_selected(work, tmp_path):
    work.confirm_split(rows())
    candidates = []
    for i in range(3):
        work.import_scene_image(picture(tmp_path / f"candidate{i}.png"))
        candidates.append(work.project.jobs()[0]["results"][0])
    assert not work.reader_media(work.segment, 1, 3)["scenes"]
    work.choose_results(candidates[:2])
    media = work.reader_media(work.segment, 1, 3)
    assert len(media["scenes"]) == 1 and len(media["scenes"][0]["images"]) == 2
    assert {im["state"] for im in media["scenes"][0]["images"]} == {"成果"}
    ids = [r["id"] for r in work.project.final_results()]
    work.result_edit(dict(id=ids[1], title="另一张"))
    work.results_delete([ids[0]])
    work.results_delete([ids[0]], True)
    assert len(work.project.final_results()) == 2
    assert all(work.file(p).is_file() for p in candidates)
    work.reader_preferences(dict(include_candidates=True))
    assert len(work.reader_media(work.segment, 1, 3)["scenes"][0]["images"]) == 2


def test_reader_asset_with_only_variant_image_has_no_empty_frame(work, tmp_path):
    a = work.save_asset(dict(name="甲", kind="人物", review="已确认"))
    work.save_variant(a["id"], "受伤", dict(description="左臂绷带"))
    asset = (
        work.project.asset(a["id"])
        if hasattr(work.project, "asset")
        else next(x for x in work.project.assets() if x["id"] == a["id"])
    )
    relative = work.project.save_asset_image(asset, picture(tmp_path / "variant.png"))
    asset["variants"][0]["image"] = relative
    work.project.save_asset(asset)
    images = work.reader_media(work.segment, 1, 1)["assets"][0]["images"]
    assert len(images) == 1 and images[0]["title"] == "受伤" and images[0]["thumbnail"]
    work.file(relative).unlink()
    assert work.reader_media(work.segment, 1, 1)["assets"] == []


def test_book_chapter_names_orders_and_cover_without_switch(work, tmp_path):
    first = work.project.meta["id"]
    original = work.project.path
    chapter = work.segment
    other = work.store.create_project(work.account, "另一本")
    identity = other.meta["id"]
    otherpath = other.path
    other.close()
    work.rename_book(identity, "新书名")
    assert work.project.meta["id"] == first and otherpath.exists()
    work.update_book_cover(identity, picture(tmp_path / "cover.png"))
    assert next(b for b in work.bookshelf() if b["id"] == identity)["cover"]
    work.order_books([identity, first])
    assert [b["id"] for b in work.bookshelf()] == [identity, first]
    work.manage_chapter(identity=chapter, name="章节新名")
    second = work.import_text("另一章", "甲离开。")
    work.manage_chapter(ids=[second, chapter])
    assert [c["id"] for c in work.project.segments()] == [second, chapter]
    assert (
        work.project.segments()[1]["name"] == "章节新名"
        and work.project.path == original
    )
    with pytest.raises(ValueError):
        work.manage_chapter(ids=[chapter, chapter])
    with pytest.raises(ValueError):
        work.order_books([first])
    work.close()
    work.open_project(str(original))
    assert [c["id"] for c in work.project.segments()] == [second, chapter]


def test_chapter_reorder_changes_only_automatic_variant_inheritance(work):
    first = work.segment
    second = work.import_text("第二章", "甲来到桥上。")
    a = work.save_asset(dict(name="甲", kind="人物", review="已确认"))
    work.set_selection(segment=first)
    v = work.save_variant(a["id"], "受伤", dict(description="左臂绷带"))
    asset = next(x for x in work.project.assets() if x["id"] == a["id"])
    assert (
        work.project.effective_asset(asset, second)["selected_variant"]["id"] == v["id"]
    )
    work.manage_chapter(ids=[second, first])
    assert (
        work.project.effective_asset(asset, second)["selected_variant"]["id"] == "base"
    )
    work.select_variant(a["id"], v["id"])
    chosen = work.project.config.get("chapter_variant_selections", {})
    work.manage_chapter(ids=[first, second])
    assert chosen == work.project.config.get("chapter_variant_selections", {})


def test_shelf_cover_upload_without_open_project_is_scoped(work, tmp_path):
    identity = work.project.meta["id"]
    work.close()
    b = Bridge(work.store.root)
    b.workspace = work
    data = base64.b64encode(picture(tmp_path / "cover.png").read_bytes()).decode()
    b.dispatch(
        "upload", dict(target="book_cover", asset=identity, name="cover.png", data=data)
    )
    assert work.project is None and work.bookshelf()[0]["cover"]
    with pytest.raises(ValueError):
        b.dispatch(
            "upload",
            dict(
                target="book_cover",
                asset="other-account-book",
                name="cover.png",
                data=data,
            ),
        )


def test_old_single_result_keeps_identity_and_recovers_candidate_source(work, tmp_path):
    work.confirm_split(rows())
    work.import_scene_image(picture(tmp_path / "old.png"))
    path = work.project.jobs()[0]["results"][0]
    work.choose_results([path])
    record = work.project.final_results()[0]
    old = dict(record)
    old.pop("source_path")
    from novelviz.storage import write_json

    write_json(work.project.path / "06_最终成果/成果索引.json", [old])
    root = work.project.path
    work.close()
    work.open_project(str(root))
    current = work.project.final_results()[0]
    assert (
        current["id"] == record["id"]
        and current["file"] == record["file"]
        and current["source_path"] == path
    )
    work.choose_results([path])
    assert len(work.project.final_results()) == 1
