"""Reader and bookshelf exercised through actual compiled Qt/QWebChannel UI."""

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
    out = Path(os.environ.get("NOVELVIZ_READER_OUTPUT", str(ROOT / "build/reader-e2e")))
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").unlink(missing_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="novelviz-reader-") as data:
        env = dict(
            os.environ,
            QT_QPA_PLATFORM="offscreen",
            QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu --disable-dev-shm-usage",
            QTWEBENGINE_REMOTE_DEBUGGING=str(port),
            NOVELVIZ_READER_E2E="1",
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
                assert not c.evaluate("!!document.querySelector('.workspace-tabs')")
                c.click("账户 / 登录")
                c.wait("document.querySelector('.account-list button')")
                c.evaluate("document.querySelector('.account-list button').click()")
                c.wait("document.querySelector('.book-cover')")
                assert (
                    c.evaluate("document.querySelector('.book-cover').innerText.trim()")
                    == "青灯夜渡 · 离线演示"
                )
                c.screenshot(out / "bookshelf.png")
                c.evaluate("document.querySelector('.book-cover').click()")
                c.wait("document.querySelector('.reader-stage')")
                c.evaluate("document.querySelector('[aria-label=\"目录\"]').click()")
                c.wait("document.querySelector('[aria-label=\"章节目录\"]')")
                c.click("2 · 阅读测试章", ".reader-directory-item")
                c.wait(
                    "document.querySelector('.reader-flow h2').textContent==='阅读测试章'"
                )
                c.wait("document.querySelectorAll('.reader-thumb').length>0")
                before = c.evaluate(
                    "(()=>{const e=document.querySelector('.reader-stage'),p=document.querySelector('.reader-flow p');return {width:e.clientWidth,left:p.getBoundingClientRect().left,top:p.getBoundingClientRect().top,text:p.textContent}})()"
                )
                c.evaluate(
                    "document.querySelector('[aria-label=\"预览资产 沈青\"]').click()"
                )
                c.wait("document.querySelector('.reader-preview-image img')")
                assert "主卡" in c.evaluate(
                    "document.querySelector('.reader-image-preview header').innerText"
                )
                c.evaluate(
                    "document.querySelector('[aria-label=\"下一张资产或场景图\"]').click()"
                )
                c.wait(
                    "document.querySelector('.reader-image-preview header').innerText.includes('受伤副卡')"
                )
                c.evaluate(
                    "document.querySelector('[aria-label=\"下一张资产或场景图\"]').click()"
                )
                c.wait(
                    "document.querySelector('.reader-image-preview header').innerText.includes('伤愈副卡')"
                )
                after = c.evaluate(
                    "(()=>{const e=document.querySelector('.reader-stage'),p=document.querySelector('.reader-flow p');return {width:e.clientWidth,left:p.getBoundingClientRect().left,top:p.getBoundingClientRect().top,text:p.textContent}})()"
                )
                assert before == after, (before, after)
                c.screenshot(out / "reading-overlay.png")
                c.evaluate(
                    "document.querySelector('[aria-label=\"关闭图片预览\"]').click()"
                )
                c.evaluate(
                    "document.querySelector('[aria-label=\"收起图像栏\"]').click()"
                )
                c.wait(
                    "document.querySelector('.reader-image-rail').classList.contains('collapsed')"
                )
                assert (
                    c.evaluate(
                        "document.querySelector('[aria-label=\"展开图像栏\"]').innerText"
                    )
                    == ""
                )
                assert (
                    c.evaluate("document.querySelector('.reader-stage').clientWidth")
                    == before["width"]
                )
                c.evaluate(
                    "document.querySelector('[aria-label=\"阅读设置\"]').click()"
                )
                c.wait("document.querySelector('[aria-label=\"阅读方式\"]')")
                c.fill('[aria-label="阅读方式"]', "pages")
                c.wait(
                    "document.querySelector('.reader-stage').classList.contains('page-mode')"
                )
                c.evaluate(
                    "document.querySelector('[aria-label=\"关闭阅读工具\"]').click()"
                )
                c.wait(
                    "document.querySelector('.reader-footer small').textContent.includes('页')"
                )
                geometry = c.evaluate(
                    "(()=>{const e=document.querySelector('.reader-stage');return {width:e.clientWidth,height:e.clientHeight,scroll:e.scrollWidth}})()"
                )
                assert (
                    geometry["height"] > 100
                    and geometry["scroll"] > geometry["width"] * 2
                ), geometry
                c.wait(
                    "document.querySelector('[aria-label=\"下一页\"]')?.disabled===false"
                )
                c.evaluate("document.querySelector('[aria-label=\"下一页\"]').click()")
                c.wait("document.querySelector('.reader-stage').scrollLeft>0")
                c.evaluate(
                    "document.querySelector('[aria-label=\"添加当前位置书签\"]').click()"
                )
                c.wait(
                    "document.querySelector('.toast')?.textContent.includes('书签已保存')"
                )
                c.evaluate("document.querySelector('[aria-label=\"书签\"]').click()")
                c.wait("document.querySelector('.reader-bookmark')")
                c.screenshot(out / "reading-pages-bookmark.png")
                c.evaluate(
                    "document.querySelector('[aria-label=\"关闭阅读工具\"]').click()"
                )
                c.evaluate(
                    "document.querySelector('[aria-label=\"阅读设置\"]').click()"
                )
                thumb = c.evaluate("document.querySelector('.reader-thumb img').src")
                payload = json.dumps(thumb.split(",")[1])
                c.evaluate(
                    "(()=>{const file=new File([Uint8Array.from(atob("
                    + payload
                    + "),c=>c.charCodeAt(0))],'封面.jpg',{type:'image/jpeg'});const dt=new DataTransfer();dt.items.add(file);const input=document.querySelector('.reader-popover input[type=file]');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));})()"
                )
                c.wait("document.querySelector('.toast')?.textContent.includes('保存')")
                c.evaluate(
                    "document.querySelector('[aria-label=\"返回书架\"]').click()"
                )
                c.wait("document.querySelector('.book-cover img')")
                c.screenshot(out / "bookshelf-custom-cover.png")
                records = list(Path(data).rglob("阅读记录.json"))
                assert len(records) == 1
                reading = json.loads(records[0].read_text())
                assert (
                    reading["bookmarks"]
                    and reading["preferences"]["mode"] == "pages"
                    and reading["preferences"]["images_collapsed"]
                )
                assert reading["position"]["paragraph"] >= 1
                (out / "saved-position.json").write_text(
                    json.dumps(reading, ensure_ascii=False, indent=2)
                )
                c.evaluate("document.querySelector('.book-cover').click()")
                c.wait("document.querySelector('.reader-stage.page-mode')")
                c.wait(
                    "document.querySelector('.reader-flow h2').textContent==='阅读测试章'"
                )
                c.wait("document.querySelector('.reader-stage').scrollLeft>0")
                for width in (1440, 1024, 760, 390):
                    c.call(
                        "Emulation.setDeviceMetricsOverride",
                        dict(
                            width=width, height=950, deviceScaleFactor=1.5, mobile=False
                        ),
                    )
                    c.wait("document.querySelector('.reader-stage').clientWidth>100")
                    assert c.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth+1"
                    ), width
                    assert c.evaluate(
                        "document.querySelector('[aria-label=\"展开图像栏\"]').getBoundingClientRect().right<=innerWidth"
                    ), width
                assert not c.errors, c.errors
                (out / "result.json").write_text(
                    json.dumps(
                        dict(
                            passed=True,
                            actual_qwebchannel=True,
                            checks=[
                                "bookshelf startup and title-only covers",
                                "all variants browsable without state adoption",
                                "overlay and rail do not reflow prose",
                                "pagination and bookmark persistence",
                                "cover upload and reader resume",
                                "multiple viewport widths",
                            ],
                        ),
                        indent=2,
                    )
                )
                print("Reader native end-to-end passed.")
            except Exception:
                try:
                    c.screenshot(out / "failure.png")
                    (out / "failure.txt").write_text(
                        str(c.evaluate("document.body.innerText"))
                    )
                except Exception:
                    pass
                raise
            finally:
                proc.terminate()
                proc.wait(timeout=15)


if __name__ == "__main__":
    main()
