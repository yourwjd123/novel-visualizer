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
    (output / "result.json").unlink(missing_ok=True)
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
            NOVELVIZ_E2E_LONG_RESPONSE="1",
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
                c.wait("document.querySelector('.bookshelf .empty-state')")
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
                c.wait("document.querySelector('.book-cover')")
                c.evaluate("document.querySelector('.book-cover').click()")
                c.wait("document.querySelector('.reader-stage')")
                c.click("进入制作")
                c.wait("document.querySelector('.workspace-tabs')")
                c.click("原文与情节", ".workspace-tabs button")
                c.wait("document.querySelectorAll('.paragraph').length===8")
                c.evaluate(
                    "document.querySelector('.paragraph-list').style.cssText='height:100px;min-height:0;max-height:100px'"
                )
                c.evaluate(
                    "[...document.querySelectorAll('.scene-card')].at(-1).querySelector('.locate').click()"
                )
                c.wait("document.querySelector('.paragraph-list').scrollTop>0")
                c.evaluate("document.querySelector('.paragraph-list').style.cssText=''")
                c.screenshot(output / "source.png")
                c.click("视觉资产库", ".workspace-tabs button")
                c.wait("document.querySelectorAll('.image-card').length===6")
                c.wait(
                    "[...document.querySelectorAll('.image-hit img')].every(i=>i.complete&&i.naturalWidth>0)"
                )
                c.screenshot(output / "assets.png")
                c.evaluate(
                    "document.querySelector('.asset-card-shell .image-info h3').click()"
                )
                c.wait("document.querySelector('.asset-editor')")
                c.fill(".asset-editor textarea", "灰蓝布衣，保留原文与演示补充的区别。")
                c.click("保存资产修改", ".asset-editor button")
                c.wait("!document.querySelector('.asset-editor')")
                c.click("参考图画廊")
                c.wait("document.querySelectorAll('.image-card').length===4")
                c.evaluate("document.querySelector('.image-check').click()")
                c.click("移入回收站", ".selection-bar button")
                c.wait("document.querySelectorAll('.image-card').length===3")
                c.evaluate("document.querySelector('.asset-more summary').click()")
                c.click("资产回收站")
                c.wait("document.querySelectorAll('.image-card').length===1")
                c.click("恢复", ".image-card button")
                c.wait("document.querySelectorAll('.image-card').length===0")
                c.click("场景插图", ".workspace-tabs button")
                c.wait("document.querySelector('.scene-selector')")
                value = c.evaluate(
                    "[...document.querySelector('.scene-selector').options].find(o=>o.text==='渡口来信').value"
                )
                c.fill(".scene-selector", value)
                c.wait(
                    "document.querySelector('.render-main-image img')?.naturalWidth>0"
                )
                c.screenshot(output / "images.png")
                external_png = c.evaluate(
                    "document.querySelector('.render-main-image img').src"
                )
                c.click("选为成果")
                c.click("成果集", ".workspace-tabs button")
                c.wait("document.querySelector('.result-grid .image-hit img')")
                c.click("编辑", ".result-grid button")
                c.wait("document.querySelector('[aria-label=\"编辑成果\"]')")
                c.fill('[aria-label="成果标题"]', "渡口来信（修订）")
                c.fill('[aria-label="成果说明"]', "桌面编辑验证")
                c.evaluate(
                    "(()=>{const bytes=Uint8Array.from(atob("
                    + json.dumps(external_png.split(",")[1])
                    + "),c=>c.charCodeAt(0));const dt=new DataTransfer();dt.items.add(new File([bytes],'替换.jpg',{type:'image/jpeg'}));const input=document.querySelector('[aria-label=\"编辑成果\"] input[type=file]');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));})()"
                )
                c.wait(
                    "document.querySelector('.toast')?.innerText.includes('图片已替换')"
                )
                c.click("保存成果修改")
                c.wait(
                    "document.querySelector('.result-grid h3')?.textContent==='渡口来信（修订）'"
                )
                c.click("删除", ".result-grid button")
                c.wait("!document.querySelector('.result-grid .image-card')")
                c.evaluate(
                    "[...document.querySelectorAll('details summary')].find(e=>e.textContent==='已删除成果').click()"
                )
                c.click("恢复成果")
                c.wait("document.querySelector('.result-grid .image-card')")
                c.screenshot(output / "results-edit.png")
                c.click("原文与情节", ".workspace-tabs button")
                c.click("视觉资产库", ".workspace-tabs button")
                c.evaluate(
                    "document.querySelector('.page-heading .toolbar-menu summary').click()"
                )
                c.click("粘贴原文")
                c.wait("document.querySelector('.modal textarea')")
                c.fill(".modal form input", "独立章节测试")
                c.fill(
                    ".modal form textarea",
                    "甲来到桥边。原文哨兵。\n\n乙递给甲一封信。\n\n甲收起信离开。",
                )
                c.click("保留为原文片段", ".modal button")
                c.wait("document.querySelector('[aria-label=\"粘贴文本归属\"]')")
                c.click("确认章节归属")
                c.wait("document.querySelector('[aria-label=\"导入字数与用量预估\"]')")
                c.screenshot(output / "import-estimate.png")
                assert "不含输出" in c.evaluate(
                    "document.querySelector('[aria-label=\"导入字数与用量预估\"]').innerText"
                )
                c.click("关闭用量提示")
                c.click("原文与情节", ".workspace-tabs button")
                c.wait("document.querySelectorAll('.paragraph').length===3")
                assert (
                    c.evaluate("document.querySelectorAll('.scene-card').length") == 0
                )
                c.click("设置", ".system-sidebar button")
                c.wait("document.querySelector('.connection-card')")
                c.evaluate(
                    "document.querySelector('[aria-label=\"编辑连接 原文整理 · 独立连接\"]').click()"
                )
                c.wait("document.querySelector('[aria-label=\"绑定 default_text\"]')")
                c.evaluate(
                    "document.querySelector('[aria-label=\"绑定 default_text\"]').click()"
                )
                c.click("保存独立连接", '[aria-label="连接与密钥"] button')
                c.wait("!document.querySelector('[aria-label=\"连接与密钥\"]')")
                c.fill("textarea[aria-label='默认语言前置提示词']", "测试用户前置规则")
                c.click("保存默认语言配置")
                c.wait(
                    "document.querySelector('.toast')?.innerText.includes('默认语言配置已保存')"
                )
                c.click("提示词管理")
                c.wait("document.querySelector('[aria-label=\"提示词管理\"]')")
                c.fill('[aria-label="提示词管理"] select', "advice")
                c.wait(
                    "document.querySelector('[aria-label=\"提示词编辑\"]').value.includes('整章')"
                )
                c.click("关闭", '[aria-label="提示词管理"] button')
                c.click("外观", ".settings-tabs button")
                assert "当前项目补充规则" not in c.evaluate(
                    "document.querySelector('.settings-sheet').innerText"
                )
                c.click("视觉资产库", ".workspace-tabs button")
                c.evaluate(
                    "document.querySelector('.source-toolbar .toolbar-menu summary').click()"
                )
                c.click("获取本章建卡建议")
                c.wait("document.querySelector('.advice-row')", 20)
                c.evaluate(
                    "document.querySelector('[aria-label=\"收起 AI 助手\"]').click()"
                )
                c.evaluate(
                    "document.querySelector('.advice-row input[type=checkbox]').click()"
                )
                c.click("为选中项建立资产卡")
                c.wait(
                    "[...document.querySelectorAll('.asset-grid .image-card h3')].some(e=>e.innerText==='甲')",
                    20,
                )
                c.evaluate(
                    "document.querySelector('[aria-label=\"收起 AI 助手\"]').click()"
                )
                c.screenshot(output / "chapter-candidates.png")
                c.evaluate(
                    "document.querySelector('.source-toolbar .toolbar-menu').open=true"
                )
                c.click("完成本章资产整理")
                c.wait(
                    "document.querySelector('.asset-stage-status').innerText.includes('已完成')"
                )
                c.evaluate("document.querySelector('.asset-grid .image-check').click()")
                c.fill('[aria-label="批量资产状态"]', "已锁定")
                c.wait(
                    "document.querySelector('.asset-grid .asset-status').value==='已锁定' "
                )
                c.fill('[aria-label="批量资产状态"]', "已确认")
                c.wait(
                    "document.querySelector('.asset-grid .asset-status').value==='已确认' "
                )
                c.click("原文与情节", ".workspace-tabs button")
                assert (
                    c.evaluate("document.querySelectorAll('.scene-card').length") == 0
                )
                c.click("分析并生成候选", ".source-toolbar button")
                c.wait("document.querySelectorAll('.scene-card').length===3", 20)
                c.wait(
                    "document.querySelector('textarea[aria-label=\"本章梗概\"]').value.length>0"
                )
                c.click("确认全部情节", ".page-heading button")
                c.wait(
                    "document.querySelector('.scene-card .plot-assets').innerText.includes('甲')"
                )
                c.evaluate("document.querySelectorAll('.scene-card')[1].click()")
                c.wait(
                    "document.querySelectorAll('.scene-card')[1].classList.contains('selected')"
                )
                c.evaluate("document.querySelectorAll('.scene-card .badge')[1].click()")
                c.wait(
                    "document.querySelectorAll('.scene-card .badge')[1].textContent.trim()==='候选'"
                )
                c.evaluate("document.querySelectorAll('.scene-card .badge')[1].click()")
                c.wait(
                    "document.querySelectorAll('.scene-card .badge')[1].textContent.trim()==='已确认'"
                )
                c.evaluate(
                    "[...document.querySelectorAll('.scene-card')[1].querySelectorAll('button')].find(b=>b.textContent==='删除').click()"
                )
                c.wait("document.querySelectorAll('.scene-card').length===2")
                c.click("撤销调整")
                c.wait("document.querySelectorAll('.scene-card').length===3")
                c.evaluate(
                    "document.querySelector('.scene-card .plot-asset-row button').click()"
                )
                c.wait("document.querySelector('.asset-editor')")
                c.evaluate(
                    "document.querySelector('[aria-label=\"关闭资产详情\"]').click()"
                )
                c.wait("!document.querySelector('.asset-editor')")
                assert "AI补全" not in c.evaluate(
                    "document.querySelector('.scene-grid').innerText"
                )
                c.screenshot(output / "source.png")
                # Task history is separate from free consultation. Closing never waits on save.
                c.evaluate(
                    "document.querySelector('[aria-label=\"收起 AI 助手\"]').click()"
                )
                c.click("✧ AI 助手", ".ai-launch")
                c.wait(
                    "document.querySelector('.assistant-tabs .active').textContent==='自由咨询'"
                )
                c.fill("textarea[aria-label='本轮对话输入']", "依据梗概咨询状态。")
                c.click("发送", ".assistant-compose button")
                c.wait("document.querySelector('.message.message-assistant')", 20)
                c.wait("document.querySelector('.messages').innerText.length>30000")
                c.screenshot(output / "assistant.png")
                c.fill("textarea[aria-label='本轮对话输入']", "独立的第二个问题。")
                c.click("发送", ".assistant-compose button")
                c.wait(
                    "document.querySelectorAll('.message.message-assistant').length===2",
                    20,
                )
                c.wait(
                    "!document.querySelector('.assistant-compose').innerText.includes('停止等待')"
                )
                close_rect = c.evaluate(
                    "(()=>{const r=document.querySelector('[aria-label=\"收起 AI 助手\"]').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()"
                )
                for event in ("mousePressed", "mouseReleased"):
                    c.call(
                        "Input.dispatchMouseEvent",
                        dict(
                            type=event,
                            x=close_rect["x"],
                            y=close_rect["y"],
                            button="left",
                            clickCount=1,
                        ),
                    )
                c.wait("document.querySelector('.assistant').hidden")
                c.click("视觉资产库", ".workspace-tabs button")
                c.wait(
                    "[...document.querySelectorAll('.asset-grid .image-card')].some(e=>e.innerText.includes('甲'))"
                )
                assert not c.evaluate(
                    "!!document.querySelector('[aria-label=\"建卡建议选择\"]')"
                )
                c.evaluate(
                    "[...document.querySelectorAll('.asset-grid .image-card')].find(e=>e.innerText.includes('甲')).querySelector('.image-info h3').click()"
                )
                c.wait("document.querySelector('.asset-editor')")
                before = c.evaluate(
                    "document.querySelector('.asset-editor textarea').value"
                )
                c.click("AI补全", ".asset-editor button")
                c.wait(
                    "document.querySelector('.assistant-tabs .active').textContent==='AI 补全'"
                )
                c.click("生成补全建议", ".assistant-compose button")
                c.wait("document.querySelector('.completion-change')", 20)
                assert (
                    c.evaluate("document.querySelector('.asset-editor textarea').value")
                    == before
                )
                c.click("采用选中建议到编辑器")
                c.wait(
                    "document.querySelector('.asset-editor textarea').value.includes('柔和侧光')"
                )
                c.click("保存资产修改", ".asset-editor button")
                c.wait("!document.querySelector('.asset-editor')")
                c.evaluate(
                    "[...document.querySelectorAll('.asset-grid .image-card')].find(e=>e.innerText.includes('甲')).querySelector('.asset-card-menu summary').click()"
                )
                c.click("删除资产", ".asset-card-menu button")
                c.wait(
                    "!([...document.querySelectorAll('.asset-grid .image-card')].some(e=>e.innerText.includes('甲')))"
                )
                c.evaluate("document.querySelector('.asset-more').open=true")
                c.click("资产回收站")
                c.click("恢复资产")
                c.click("资产档案")
                c.wait(
                    "[...document.querySelectorAll('.asset-grid .image-card')].some(e=>e.innerText.includes('甲'))"
                )
                c.click("场景插图", ".workspace-tabs button")
                c.wait("document.querySelector('.render-editor textarea')")
                c.fill(".render-editor textarea", "甲站在渡口，中景。")
                c.click("AI扩写", ".render-editor button")
                c.wait(
                    "document.querySelector('.assistant-tabs .active')?.textContent==='AI 补全'"
                )
                assert not c.evaluate("!!document.querySelector('.completion-change')")
                c.click("生成补全建议", ".assistant-compose button")
                c.wait("document.querySelector('.completion-change')", 20)
                c.click("采用选中建议到编辑器")
                c.wait(
                    "document.querySelector('.render-editor textarea').value.includes('柔和侧光')"
                )
                c.click("保存生图方案", ".render-editor button")
                c.click("保存生图资产到本地", ".render-editor button")
                c.wait("document.querySelector('[aria-label=\"保存生图素材方式\"]')")
                c.click("另存为新版本（默认）")
                c.wait(
                    "[...document.querySelectorAll('.render-editor button')].some(b=>b.textContent==='打开素材文件夹')"
                )
                c.click("保存生图资产到本地", ".render-editor button")
                c.wait("document.querySelector('[aria-label=\"保存生图素材方式\"]')")
                c.click("覆盖所选版本")
                c.wait("!document.querySelector('[aria-label=\"保存生图素材方式\"]')")
                c.click("生成生图方案", ".render-editor button")
                c.wait("document.querySelector('.render-proposal pre')", 20)
                c.evaluate(
                    "document.querySelector('[aria-label=\"收起 AI 助手\"]').click()"
                )
                c.click("载入生成方案")
                c.wait(
                    "document.querySelector('.render-editor textarea').value.includes('主体位于画面中央')"
                )
                c.click("保存生图方案", ".render-editor button")
                c.screenshot(output / "images.png")
                c.evaluate(
                    "(()=>{const bytes=Uint8Array.from(atob("
                    + json.dumps(external_png.split(",")[1])
                    + "),c=>c.charCodeAt(0));const files=new DataTransfer();files.items.add(new File([bytes],'外部生成.png',{type:'image/png'}));document.querySelector('.drop-zone').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:files}));})()"
                )
                c.wait("document.querySelector('.render-candidate-strip button')")
                c.click("移除候选", ".render-output-pane button")
                c.wait("!document.querySelector('.render-candidate-strip button')")
                c.evaluate(
                    "[...document.querySelectorAll('details summary')].find(e=>e.textContent.startsWith('已移除候选')).click()"
                )
                c.click("恢复候选")
                c.wait("document.querySelector('.render-candidate-strip button')")
                c.click("选为成果", ".render-output-pane button")
                c.screenshot(output / "external-candidates.png")
                c.click("资产图制作", ".workspace-tabs button")
                c.wait(
                    "document.querySelector('[aria-label=\"资产图方案工作区\"] textarea')"
                )
                assetid = c.evaluate(
                    "[...document.querySelector('[aria-label=\"当前制图资产\"]').options].find(o=>o.text==='甲').value"
                )
                c.fill('[aria-label="当前制图资产"]', assetid)
                c.wait(
                    "document.querySelector('[aria-label=\"拟生图名称\"]')?.value.includes('甲')"
                )
                c.fill(
                    ".render-editor textarea", "甲的角色设定图，正面站姿，纯色背景。"
                )
                c.click("保存生图资产到本地", ".render-editor button")
                c.wait("document.querySelector('[aria-label=\"保存生图素材方式\"]')")
                c.click("另存为新版本（默认）")
                c.wait(
                    "[...document.querySelectorAll('.render-editor button')].some(b=>b.textContent==='打开素材文件夹')"
                )
                c.screenshot(output / "asset-images.png")
                c.click("设置", ".system-sidebar button")
                c.wait("document.querySelector('.connections-hub')")
                c.click("AI 选项", ".settings-tabs button")
                c.wait("document.querySelector('[aria-label=\"资产关联方式\"]')")
                assert (
                    c.evaluate(
                        "document.querySelector('[aria-label=\"资产关联方式\"]').value"
                    )
                    == "ai"
                )
                c.fill('[aria-label="资产关联方式"]', "local")
                c.wait(
                    "document.querySelector('[aria-label=\"资产关联方式\"]').value==='local'"
                )
                c.fill('[aria-label="资产关联方式"]', "ai")
                c.screenshot(output / "ai-options.png")
                c.click("自定义节点接口", ".settings-tabs button")
                c.wait("document.querySelector('.settings-sheet textarea')")
                c.fill(".settings-sheet input[type=number]", "1234")
                c.click("保存此节点配置")
                c.screenshot(output / "settings.png")
                # Inspect actual persisted requests; no renderer mock or network fixture here.
                jobs = [
                    json.loads(p.read_text("utf-8"))
                    for p in Path(data).rglob("任务记录.json")
                ]
                consultation = [j for j in jobs if j.get("mode") == "consult"]
                assert len(consultation) == 2
                for j in consultation:
                    assert (
                        len(j["messages"]) == 1
                        and j["params"]["system"] == "测试用户前置规则"
                    )
                    assert "原文哨兵" not in j["context"]
                for j in jobs:
                    if j.get("mode") == "complete":
                        assert (
                            "原文哨兵" not in j["context"]
                            and "【当前编辑对象全文】" in j["context"]
                        )
                c.click("成果集", ".workspace-tabs button")
                c.wait(
                    "document.querySelectorAll('.result-grid .image-card').length===2"
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
                    c.click("✧ AI 助手", ".ai-launch")
                    c.wait("!document.querySelector('.assistant').hidden")
                    bounds = c.evaluate(
                        "(()=>{const r=document.querySelector('[aria-label=\"收起 AI 助手\"]').getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom}})()"
                    )
                    assert (
                        bounds["x"] >= 0
                        and bounds["right"] <= width
                        and bounds["y"] >= 0
                        and bounds["bottom"] <= 900
                    ), (width, bounds)
                    c.call(
                        "Input.dispatchKeyEvent",
                        dict(
                            type="keyDown",
                            key="Escape",
                            code="Escape",
                            windowsVirtualKeyCode=27,
                        ),
                    )
                    c.wait("document.querySelector('.assistant').hidden")
                    for tab in [
                        "原文与情节",
                        "视觉资产库",
                        "资产图制作",
                        "场景插图",
                        "成果集",
                    ]:
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
                                "single-turn task and consultation contexts",
                                "chapter assets before plot, grades and mapping",
                                "asset/prompt completion diff and explicit adoption",
                                "asset archive and restore",
                                "front prefix and no project rule editor",
                                "import without AI",
                                "review candidates before confirm",
                                "default and custom interface settings",
                                "card selection, individual confirmation and delete/undo",
                                "asset extraction button starts model task",
                                "assistant escape and launcher toggle",
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
