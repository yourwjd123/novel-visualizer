"""Preset import, inferred mapping and explicit submission in the native Qt UI."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from desktop_e2e import CDP

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_workflows import graph


def main():
    out = Path(
        os.environ.get("NOVELVIZ_WORKFLOW_OUTPUT", str(ROOT / "build/workflow-e2e"))
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").unlink(missing_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="novelviz-workflow-") as data:
        env = dict(
            os.environ,
            QT_QPA_PLATFORM="offscreen",
            QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu --disable-dev-shm-usage",
            QTWEBENGINE_REMOTE_DEBUGGING=str(port),
            NOVELVIZ_WORKFLOW_E2E="1",
            PYTHONPATH=str(ROOT),
        )
        with (out / "native.log").open("w") as log:
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / "tests/native_host.py"), data],
                env=env,
                cwd=ROOT,
                stdout=log,
                stderr=log,
            )
            try:
                c = CDP(port)
                c.wait("document.querySelector('.bookshelf')")
                c.click("账户 / 登录")
                c.wait("document.querySelector('.account-list button')")
                c.evaluate("document.querySelector('.account-list button').click()")
                c.wait("document.querySelector('.book-cover')")
                c.evaluate("document.querySelector('.book-cover').click()")
                c.wait("document.querySelector('.reader-stage')")
                c.click("进入制作")
                c.wait("document.querySelector('.assets-workspace')")
                c.click("设置", ".system-sidebar button")
                c.click("生图模型配置", ".settings-tabs button")
                c.wait("document.querySelector('.workflow-presets')")
                c.evaluate(
                    "[...document.querySelectorAll('.provider-card')].find(e=>e.innerText.includes('测试云端')).querySelectorAll('button')[2].click()"
                )
                c.wait("document.querySelector('[aria-label=\"工作流预设编辑\"]')")
                text = json.dumps(json.dumps(graph(4)), ensure_ascii=False)
                c.evaluate(
                    "(()=>{const input=document.querySelector('[aria-label=\\\"工作流预设编辑\\\"] input[type=file]');const dt=new DataTransfer();dt.items.add(new File(["
                    + text
                    + "],'workflow.json',{type:'application/json'}));input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));})()".replace(
                        '\\"', '"'
                    )
                )
                c.wait(
                    "document.querySelector('[aria-label=\"预设节点映射\"]').value.includes('reference_4')"
                )
                c.fill('[aria-label="工作流预设编辑"] input', "四图测试预设")
                c.screenshot(out / "workflow-mapping.png")
                c.click("校验并保存预设")
                c.wait("!document.querySelector('[aria-label=\"工作流预设编辑\"]')")
                c.wait(
                    "document.querySelector('.preset-row')?.innerText.includes('四图测试')"
                )
                c.screenshot(out / "workflow-presets.png")
                c.click("场景插图", ".workspace-tabs button")
                c.wait("document.querySelector('.render-editor textarea')")
                c.fill(".render-editor textarea", "沈青提灯站在雨夜渡口，摆渡人在旁。")
                c.click("开始生图…")
                c.wait(
                    "document.querySelector('[aria-label=\"本次生图接口\"]')?.value.includes('e2e-comfy')"
                )
                assert not (Path(data) / "mock-comfy.json").exists()
                assert not c.evaluate(
                    "!!document.querySelector('[aria-label=\"本次生图\"] img')"
                )
                c.screenshot(out / "generation-dialog.png")
                c.click("确认生成", '[aria-label="本次生图"] button')
                c.wait("document.querySelector('.render-candidate-strip button')", 20)
                bound = json.loads((Path(data) / "mock-comfy.json").read_text())
                assert "沈青" in bound["1"]["inputs"]["value"]
                assert all(
                    not bound[str(10 + i)]["inputs"]["image"].startswith("old-")
                    for i in range(1, 5)
                )
                assert len(list(Path(data).rglob("fixture-generated.*"))) == 1
                c.evaluate(
                    "document.querySelector('[aria-label=\"收起 AI 助手\"]').click()"
                )
                c.screenshot(out / "scene-workspace.png")
                assert not c.errors, c.errors
                (out / "result.json").write_text(
                    json.dumps(
                        dict(
                            passed=True,
                            actual_qwebchannel=True,
                            checks=[
                                "workflow file import and local auto mapping",
                                "shared connection preset list",
                                "exact-count selected before submit",
                                "no upload before explicit confirmation",
                                "four actual reference bindings and candidate output",
                            ],
                        ),
                        indent=2,
                    )
                )
                print(
                    "Workflow native end-to-end passed; mock provider only, no GPU calls."
                )
            except Exception:
                try:
                    c.screenshot(out / "failure.png")
                except Exception:
                    pass
                raise
            finally:
                proc.terminate()
                proc.wait(timeout=15)


if __name__ == "__main__":
    main()
