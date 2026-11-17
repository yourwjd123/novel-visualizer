"""Only launched by desktop_e2e.py; accepts dialogs on behalf of that test."""

import sys
import json
import os
from PySide6.QtWidgets import QApplication
from novelviz.desktop import Desktop, LocalPage
from novelviz.demo import seed_visual_demo
from novelviz.storage import Store

# Regression fixture: large valid model output, without using a paid service.
if os.environ.get("NOVELVIZ_E2E_LONG_RESPONSE") == "1":
    import novelviz.desktop as desktop

    original_text_call = desktop.text_call

    def long_response(params, *args, **kwargs):
        answer = original_text_call(params, *args, **kwargs)
        if params.get("template", {}).get("id") == "consult":
            return answer + "演示长回复，用于测试浮窗交互。" * 3000
        if (
            params.get("provider") == "demo"
            and params.get("template", {}).get("format") == "assets"
        ):
            data = json.loads(answer)
            data["note"] = "演示长回复，用于测试浮窗交互。" * 3000
            return json.dumps(data, ensure_ascii=False)
        return answer

    desktop.text_call = long_response

LocalPage.javaScriptConfirm = lambda self, origin, message: True
app = QApplication([])
app.setApplicationName("NovelVisualizerE2E")
app.setOrganizationName("NovelStudioTests")
store = Store(sys.argv[1])
seed_visual_demo(store)
if os.environ.get("NOVELVIZ_READER_E2E") == "1":
    from novelviz.storage import Project

    project = Project(store.projects(store.accounts[0])[0].parent.parent)
    chapter = project.add_segment(
        "阅读测试章",
        "\n\n".join(
            "沈青来到雨夜渡口，手提旧铜灯。"
            + ("晚风拂过水面，远处的灯火照见归途。" * 12)
            + str(i)
            for i in range(60)
        ),
    )
    later = project.add_segment("后续章节", "沈青伤愈，继续启程。")
    asset = next(a for a in project.assets() if a["name"] == "沈青")
    asset["variants"] = [
        dict(
            id="reader-hurt",
            title="受伤副卡",
            chapter=chapter,
            confirmed=True,
            revision=1,
            image=asset["image"],
            data=dict(description="受伤"),
        ),
        dict(
            id="reader-healed",
            title="伤愈副卡",
            chapter=later,
            confirmed=True,
            revision=1,
            image=asset["image"],
            data=dict(description="伤愈"),
        ),
    ]
    project.save_asset(asset)
    project.close()
if os.environ.get("NOVELVIZ_WORKFLOW_E2E") == "1":
    from pathlib import Path
    import shutil
    import novelviz.desktop as desktop

    account = store.accounts[0]
    store.save_connection(
        account,
        dict(
            id="e2e-comfy",
            name="测试云端 ComfyUI",
            kind="comfy",
            endpoint="http://127.0.0.1:1",
        ),
    )
    store.save_image_defaults(account, dict(connection_id="e2e-comfy"))

    def fake_upload(endpoint, path, key):
        return path.name

    def fake_comfy(endpoint, flow, dest, cancel, progress, key):
        dest.mkdir(parents=True, exist_ok=True)
        source = next(
            p
            for p in Path(sys.argv[1]).rglob("*")
            if p.suffix.lower() in (".png", ".jpg", ".jpeg")
            and "05_生成任务" not in str(p)
        )
        target = dest / ("fixture-generated" + source.suffix)
        shutil.copyfile(source, target)
        (Path(sys.argv[1]) / "mock-comfy.json").write_text(
            json.dumps(flow), encoding="utf-8"
        )
        return [str(target)]

    desktop.Bridge.confirm = lambda self, title, message: True
    desktop.upload_comfy = fake_upload
    desktop.comfy_call = fake_comfy
window = Desktop(sys.argv[1])
window.resize(1440, 1000)
window.show()
sys.exit(app.exec())
