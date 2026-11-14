"""Actual compiled renderer + QWebChannel + Python persistence, via raw CDP.

Qt intentionally lacks Browser context management, so this driver does not
pretend a normal Playwright browser is equivalent to the native application.
"""

import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed

ROOT = Path(__file__).resolve().parents[1]


class CDP:
    def __init__(self, port):
        self.errors = []
        self.id = 0
        end = time.monotonic() + 35
        while time.monotonic() < end:
            try:
                pages = json.load(
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/json/list", timeout=2
                    )
                )
                page = next(p for p in pages if p["type"] == "page")
                self.ws = connect(
                    page["webSocketDebuggerUrl"], max_size=40 * 1024 * 1024
                )
                self.call("Runtime.enable")
                return
            except (OSError, StopIteration):
                time.sleep(0.2)
        raise RuntimeError("Native debug page did not become available")

    def call(self, method, params=None):
        self.id += 1
        index = self.id
        self.ws.send(json.dumps(dict(id=index, method=method, params=params or {})))
        while True:
            value = json.loads(self.ws.recv(timeout=30))
            if value.get("method") == "Runtime.exceptionThrown":
                self.errors.append(value["params"])
            if value.get("id") == index:
                if "error" in value:
                    raise RuntimeError(value["error"])
                return value.get("result", {})

    def evaluate(self, expression):
        result = self.call(
            "Runtime.evaluate",
            dict(expression=expression, awaitPromise=True, returnByValue=True),
        )
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"])
        return result.get("result", {}).get("value")

    def wait(self, expression, timeout=12):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            value = self.evaluate("!!(" + expression + ")")
            if value:
                return value
            time.sleep(0.08)
        raise AssertionError(
            expression + "\n" + str(self.evaluate("document.body.innerText"))[-2500:]
        )

    def click(self, text, selector="button"):
        value = json.dumps(text, ensure_ascii=False)
        self.evaluate(
            f"(()=>{{const b=[...document.querySelectorAll({json.dumps(selector)})].find(b=>b.getClientRects().length&&b.textContent.trim()==={value});if(!b)throw Error('Button missing: '+{value});b.click();}})()"
        )

    def fill(self, selector, value):
        self.evaluate(
            "(()=>{const el=document.querySelector("
            + json.dumps(selector)
            + ");if(!el)throw Error('Input missing');const proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:el.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(el,"
            + json.dumps(value, ensure_ascii=False)
            + ");el.dispatchEvent(new Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}));})()"
        )

    def screenshot(self, path):
        time.sleep(0.2)
        result = self.call("Page.captureScreenshot", dict(format="png"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(result["data"]))


def main():
    output = Path(os.environ.get("NOVELVIZ_E2E_OUTPUT", str(ROOT / "build/e2e")))
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="novelviz-e2e-") as data:
        env = dict(
            os.environ,
            QT_QPA_PLATFORM="offscreen",
            QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu --disable-dev-shm-usage",
            QTWEBENGINE_REMOTE_DEBUGGING=str(port),
            PYTHONPATH=str(ROOT),
        )
        with (output / "native.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "tests/native_host.py"), data],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                c = CDP(port)
                c.wait("document.querySelector('.empty-workspace')")
                assert "访客" in c.evaluate(
                    "document.querySelector('.topbar').innerText"
                )
                c.click("明 / 暗", ".topbar button")
                assert (
                    c.evaluate("document.querySelector('.app').dataset.theme") == "dark"
                )
                c.click("明 / 暗", ".topbar button")
                c.click("账户 / 登录")
                c.wait("document.querySelector('.account-list button')")
                c.evaluate("document.querySelector('.account-list button').click()")
                c.wait("document.querySelectorAll('.paragraph').length===8")
                c.screenshot(output / "source.png")
                c.click("视觉资产库", ".workspace-tabs button")
                c.wait("document.querySelectorAll('.image-card').length===6")
                c.wait(
                    "[...document.querySelectorAll('.image-hit img')].every(i=>i.complete&&i.naturalWidth>0)"
                )
                c.screenshot(output / "assets.png")
                c.evaluate("document.querySelector('.image-hit').click()")
                c.wait("document.querySelector('.asset-editor')")
                c.fill(".asset-editor textarea", "灰蓝布衣，保留原文与演示补充的区别。")
                c.click("保存资产修改", ".asset-editor button")
                c.wait("!document.querySelector('.asset-editor')")
                c.click("参考图画廊")
                c.wait("document.querySelectorAll('.image-card').length===4")
                c.evaluate("document.querySelector('.image-check').click()")
                c.click("移入回收站", ".selection-bar button")
                c.wait("document.querySelectorAll('.image-card').length===3")
                c.click("回收站")
                c.wait("document.querySelectorAll('.image-card').length===1")
                c.click("恢复", ".image-card button")
                c.wait("document.querySelectorAll('.image-card').length===0")
                c.click("场景插图", ".workspace-tabs button")
                c.wait("document.querySelector('.shot-toolbar select')")
                value = c.evaluate(
                    "[...document.querySelector('.shot-toolbar select').options].find(o=>o.text==='渡口来信').value"
                )
                c.fill(".shot-toolbar select", value)
                c.wait("document.querySelector('.hero-image img')?.naturalWidth>0")
                c.screenshot(output / "images.png")
                c.click("选为成果")
                c.wait(
                    "document.querySelector('.under-image').innerText.includes('已选为成果')"
                )
                c.click("讨论方案")
                c.wait("document.querySelector('.assistant:not([hidden])')")
                c.fill(
                    "textarea[aria-label='本轮对话输入']", "保持交信动作与原文一致。"
                )
                c.click("发送", ".assistant-compose button")
                c.wait("document.querySelector('.message.assistant')", 20)
                c.screenshot(output / "assistant.png")
                c.click("采用到待确认方案 →", ".message.assistant button")
                c.wait("document.querySelector('.assistant-body textarea')")
                c.click("确认最终方案", ".assistant-body button")
                c.evaluate(
                    "document.querySelector('[aria-label=\"收起 AI 助手\"]').click()"
                )
                c.click("原文与情节", ".workspace-tabs button")
                c.click("导入下一片段")
                c.wait("document.querySelector('.modal textarea')")
                c.fill(".modal form input", "端到端测试片段")
                c.fill(".modal form textarea", "甲来到桥边。\n\n乙递给甲一封信。")
                c.click("保留为原文片段", ".modal button")
                c.wait("document.querySelectorAll('.paragraph').length===2")
                c.wait("document.querySelectorAll('.scene-card').length===0")
                c.click("分析并生成候选", ".source-toolbar button")
                c.wait("document.querySelectorAll('.scene-card').length===2", 20)
                c.wait(
                    "[...document.querySelectorAll('.page-heading button')].some(b=>b.textContent==='确认拆分'&&!b.disabled)"
                )
                c.click("确认拆分", ".page-heading button")
                c.wait(
                    "document.querySelector('.status-line').innerText.includes('拆分已确认')"
                )
                c.click("设置", ".system-sidebar button")
                c.wait("document.querySelector('.settings-sheet textarea')")
                assert "语言模型配置" in c.evaluate(
                    "document.querySelector('.settings-tabs').innerText"
                )
                c.fill(".settings-sheet input[type=number]", "1234")
                c.click("保存此节点配置")
                c.screenshot(output / "settings.png")
                c.click("成果集", ".workspace-tabs button")
                c.wait(
                    "document.querySelectorAll('.result-grid .image-card').length===1"
                )
                for width, scale in [
                    (1920, 1),
                    (1440, 1),
                    (1024, 1.25),
                    (760, 1.5),
                    (640, 2),
                    (390, 2),
                ]:
                    c.call(
                        "Emulation.setDeviceMetricsOverride",
                        dict(
                            width=width,
                            height=900,
                            deviceScaleFactor=scale,
                            mobile=False,
                        ),
                    )
                    for tab in ["原文与情节", "视觉资产库", "场景插图", "成果集"]:
                        c.click(tab, ".workspace-tabs button")
                        assert c.evaluate(
                            "document.documentElement.scrollWidth<=innerWidth+1"
                        ), (width, tab)
                assert not c.errors, c.errors
                (output / "result.json").write_text(
                    json.dumps(
                        dict(
                            passed=True,
                            actual_qwebchannel=True,
                            actual_storage=True,
                            widths=[1920, 1440, 1024, 760, 640, 390],
                            checks=[
                                "guest entry",
                                "local account login",
                                "source evidence",
                                "asset edit",
                                "gallery trash/restore",
                                "scene association",
                                "choose result",
                                "multi-round demo provider",
                                "import without AI",
                                "review candidates before confirm",
                                "node settings",
                                "responsive layout",
                            ],
                        ),
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "utf-8",
                )
                try:
                    c.evaluate("window.__novelvizRequestClose()")
                except ConnectionClosed:
                    pass  # Native close tears down CDP before replying.
                c.ws.close()
                process.wait(timeout=15)
                assert process.returncode == 0
                print(
                    "Native desktop end-to-end passed: real Qt WebEngine, QWebChannel and local project files."
                )
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
