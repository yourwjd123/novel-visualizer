"""Actual Qt/QWebChannel UI: connection cards, reversible drag and dual reader rails."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from desktop_e2e import CDP

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = Path(
        os.environ.get("NOVELVIZ_ASSET_HUB_OUTPUT", str(ROOT / "build/asset-hub-e2e"))
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").unlink(missing_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="novelviz-asset-hub-") as data:
        env = dict(
            os.environ,
            QT_QPA_PLATFORM="offscreen",
            QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu --disable-dev-shm-usage",
            QTWEBENGINE_REMOTE_DEBUGGING=str(port),
            NOVELVIZ_ASSET_HUB_E2E="1",
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
                c.wait("document.querySelector('.asset-card-shell')")
                assert c.evaluate(
                    "[...document.querySelectorAll('.asset-card-shell h3')].some(e=>e.textContent==='受伤旅人')"
                )
                c.screenshot(out / "compact-assets.png")
                c.evaluate(
                    "(()=>{const source=[...document.querySelectorAll('.asset-card-shell')].find(e=>e.querySelector('h3').textContent==='受伤旅人');const dt=new DataTransfer();source.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:dt}));window._testDrag=dt;})()"
                )
                c.wait(
                    "[...document.querySelectorAll('.asset-drop-zone')].some(e=>e.textContent.includes('【旅人】'))"
                )
                c.evaluate(
                    "[...document.querySelectorAll('.asset-drop-zone')].find(e=>e.textContent.includes('【旅人】')).dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:window._testDrag}))"
                )
                c.wait(
                    "![...document.querySelectorAll('.asset-card-shell h3')].some(e=>e.textContent==='受伤旅人')"
                )
                c.screenshot(out / "asset-grouped.png")
                c.click("撤销 / 恢复", ".operation-notice button")
                c.wait("document.querySelector('.restore-review')")
                c.click("确认恢复为独立资产")
                c.wait(
                    "[...document.querySelectorAll('.asset-card-shell h3')].some(e=>e.textContent==='受伤旅人')"
                )
                c.screenshot(out / "asset-restore.png")
                c.evaluate(
                    "document.querySelector('[aria-label=\"关闭资产操作\"]').click()"
                )
                c.click("设置", ".system-sidebar button")
                c.wait("document.querySelector('.connections-hub')")
                c.click("新建连接", ".connections-hub button")
                c.wait("document.querySelector('[aria-label=\"连接名称\"]')")
                c.fill('[aria-label="连接名称"]', "测试语言接口")
                c.fill('[aria-label="连接模型"]', "model-1")
                c.evaluate(
                    "document.querySelector('[aria-label=\"绑定 text:1\"]').click()"
                )
                c.click("保存独立连接", '[aria-label="连接与密钥"] button')
                c.wait(
                    "document.querySelector('[aria-label=\"编辑连接 测试语言接口\"]')"
                )
                c.evaluate(
                    "document.querySelector('[aria-label=\"编辑连接 测试语言接口\"]').click()"
                )
                c.wait(
                    "document.querySelector('[aria-label=\"连接模型\"]')?.value==='model-1'"
                )
                c.fill('[aria-label="连接模型"]', "model-2")
                c.click("保存独立连接", '[aria-label="连接与密钥"] button')
                c.wait(
                    "document.querySelector('[aria-label=\"编辑连接 测试语言接口\"]')?.innerText.includes('model-2')"
                )
                c.screenshot(out / "language-connections.png")
                c.evaluate(
                    "document.querySelector('[aria-label=\"删除连接 测试语言接口\"]').click()"
                )
                c.wait("document.querySelector('[aria-label=\"删除连接\"]')")
                c.click("删除连接及凭据", '[aria-label="删除连接"] button')
                c.wait(
                    "!document.querySelector('[aria-label=\"编辑连接 测试语言接口\"]')"
                )
                c.click("生图模型配置", ".settings-tabs button")
                c.wait("document.querySelector('.connection-card')")
                c.evaluate("document.querySelector('.connection-card-open').click()")
                c.wait("document.querySelector('[aria-label=\"连接名称\"]')")
                c.fill('[aria-label="连接名称"]', "本地绘图服务")
                c.fill('[aria-label="连接地址"]', "http://localhost:8189")
                c.evaluate(
                    "document.querySelector('[aria-label=\"绑定 image:人物\"]').click()"
                )
                c.click("保存独立连接", '[aria-label="连接与密钥"] button')
                c.wait(
                    "document.querySelector('[aria-label=\"编辑连接 本地绘图服务\"]')?.innerText.includes('8189')"
                )
                c.screenshot(out / "image-connections.png")
                c.evaluate("document.querySelector('.brand').click()")
                c.wait("document.querySelector('.book-cover')")
                c.evaluate("document.querySelector('.book-cover').click()")
                c.wait("document.querySelector('.reader-scene-rail .reader-thumb img')")
                assert c.evaluate(
                    "document.querySelector('.reader-scene-rail').getBoundingClientRect().left<document.querySelector('.reader-image-rail').getBoundingClientRect().left"
                )
                assert c.evaluate(
                    "document.querySelector('.reader-scene-rail .reader-thumb').clientWidth>document.querySelector('.reader-image-rail .reader-thumb').clientWidth"
                )
                c.evaluate(
                    "document.querySelector('.reader-scene-rail .reader-thumb').click()"
                )
                c.wait(
                    "document.querySelector('.reader-image-preview.scene-preview img')"
                )
                c.screenshot(out / "reader-scene-preview.png")
                scene_width = c.evaluate(
                    "document.querySelector('.reader-image-preview').clientWidth"
                )
                c.evaluate(
                    "document.querySelector('.reader-image-rail .reader-thumb').click()"
                )
                c.wait(
                    "document.querySelector('.reader-image-preview:not(.scene-preview) img')"
                )
                assert scene_width > c.evaluate(
                    "document.querySelector('.reader-image-preview').clientWidth"
                )
                before = c.evaluate("document.querySelectorAll('.reader-thumb').length")
                c.evaluate(
                    "document.querySelector('.reader-image-rail .reader-thumb img').dispatchEvent(new Event('error'))"
                )
                c.wait(f"document.querySelectorAll('.reader-thumb').length<{before}")
                assert c.evaluate(
                    "[...document.querySelectorAll('.reader-thumb img')].every(e=>e.src&&e.naturalWidth>0)"
                )
                assert not c.errors, c.errors
                (out / "result.json").write_text(
                    json.dumps(
                        dict(
                            passed=True,
                            actual_qwebchannel=True,
                            checks=[
                                "compact asset cards",
                                "drag source into same-type master and restore",
                                "language and image card edits with atomic bindings",
                                "connection delete without fallback",
                                "two reading rails and larger scene preview",
                                "decoder failure removes stale icons",
                            ],
                        ),
                        indent=2,
                    )
                )
                print("Asset hub native end-to-end passed; no model or GPU requests.")
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
