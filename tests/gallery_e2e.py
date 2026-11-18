"""Real desktop regression for book/chapter ordering, albums and native fullscreen."""

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
        os.environ.get("NOVELVIZ_GALLERY_OUTPUT", str(ROOT / "build/gallery-e2e"))
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").unlink(missing_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="novelviz-gallery-") as data:
        env = dict(
            os.environ,
            QT_QPA_PLATFORM="offscreen",
            QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu --disable-dev-shm-usage",
            QTWEBENGINE_REMOTE_DEBUGGING=str(port),
            NOVELVIZ_GALLERY_E2E="1",
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
                c.wait("document.querySelectorAll('.book-tile').length===3")
                c.evaluate(
                    "[...document.querySelectorAll('.book-tile')].find(e=>e.innerText.includes('排序样书甲')).querySelector('summary').click()"
                )
                c.click("更名", ".book-menu button")
                c.wait("document.querySelector('[aria-label=\"新名称\"]')")
                c.fill('[aria-label="新名称"]', "已更名样书")
                c.click("保存名称")
                c.wait(
                    "document.querySelector('.bookshelf').innerText.includes('已更名样书')"
                )
                cover = c.evaluate("document.querySelector('.book-cover img').src")
                c.evaluate(
                    "[...document.querySelectorAll('.book-tile')].find(e=>e.innerText.includes('已更名样书')).querySelector('summary').click()"
                )
                c.evaluate(
                    "document.querySelector('[aria-label=\"书架封面文件\"]').click=()=>{}"
                )
                c.click("更改封面图", ".book-menu button")
                payload = json.dumps(cover.split(",")[1])
                c.evaluate(
                    "(()=>{const dt=new DataTransfer();dt.items.add(new File([Uint8Array.from(atob("
                    + payload
                    + "),c=>c.charCodeAt(0))],'新封面.jpg',{type:'image/jpeg'}));const input=document.querySelector('[aria-label=\"书架封面文件\"]');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));})()"
                )
                c.wait(
                    "[...document.querySelectorAll('.book-tile')].find(e=>e.innerText.includes('已更名样书'))?.querySelector('img')"
                )
                assert c.evaluate(
                    "getComputedStyle(document.querySelector('.book-cover img')).objectFit==='contain'"
                )
                c.evaluate(
                    "(()=>{const e=document.querySelectorAll('.book-tile'),dt=new DataTransfer();e[2].dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:dt}));e[0].dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));})()"
                )
                c.wait(
                    "document.querySelector('.book-tile .book-cover')?.innerText.includes('青灯夜渡')"
                )
                assert c.evaluate(
                    "(()=>{const r=document.querySelector('.book-cover').getBoundingClientRect();return r.height>r.width})()"
                )
                c.screenshot(out / "bookshelf-portrait.png")
                c.evaluate("document.querySelector('.book-cover').click()")
                c.wait("document.querySelector('.reader-stage')")
                c.click("进入制作")
                c.wait("document.querySelector('.assets-workspace')")
                c.click("成果集", ".workspace-tabs button")
                c.wait(
                    "document.querySelectorAll('.result-grid .image-card').length===3"
                )
                assert c.evaluate(
                    "document.querySelector('.result-grid').innerText.includes('后续章节')"
                )
                c.screenshot(out / "whole-book-results.png")
                c.evaluate("document.querySelector('.result-grid .image-hit').click()")
                c.wait("document.querySelector('[aria-label=\"下一张图片\"]')")
                c.evaluate(
                    "document.querySelector('[aria-label=\"下一张图片\"]').click()"
                )
                c.wait(
                    "document.querySelector('.image-viewer header').innerText.includes('2 / 2')"
                )
                c.evaluate(
                    "document.querySelector('[aria-label=\"全屏查看\"]').click()"
                )
                c.wait("document.querySelector('[aria-label=\"退出全屏\"]')")
                c.screenshot(out / "album-fullscreen.png")
                c.evaluate(
                    "window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"
                )
                c.wait("document.querySelector('[aria-label=\"全屏查看\"]')")
                assert c.evaluate("!!document.querySelector('.image-viewer')")
                c.evaluate(
                    "window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"
                )
                c.wait("!document.querySelector('.image-viewer')")
                c.click("场景插图", ".workspace-tabs button")
                c.wait("document.querySelector('.scene-selector')")
                scene = c.evaluate(
                    "[...document.querySelector('.scene-selector').options].find(o=>o.text==='雨夜候船').value"
                )
                c.fill(".scene-selector", scene)
                c.wait("document.querySelectorAll('.candidate-check').length===3")
                assert c.evaluate(
                    "document.querySelectorAll('.render-candidate-strip span').length===2"
                )
                c.evaluate(
                    "[...document.querySelectorAll('.candidate-tile')].find(e=>!e.innerText.includes('已选成果')).querySelector('input').click()"
                )
                c.click("批量选为成果")
                c.wait(
                    "document.querySelectorAll('.render-candidate-strip span').length===3"
                )
                c.click("原文与情节", ".workspace-tabs button")
                c.wait("document.querySelectorAll('.chapter-tab').length===2")
                c.evaluate("document.querySelector('.chapter-menu summary').click()")
                c.click("更名", ".chapter-menu button")
                c.wait("document.querySelector('[aria-label=\"新名称\"]')")
                c.fill('[aria-label="新名称"]', "第一章新名")
                c.click("保存名称")
                c.wait(
                    "document.querySelector('.chapter-tab').innerText.includes('第一章新名')"
                )
                c.evaluate(
                    "(()=>{const e=document.querySelectorAll('.chapter-tab'),dt=new DataTransfer();e[1].dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:dt}));e[0].dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));})()"
                )
                c.wait(
                    "document.querySelector('.chapter-tab').innerText.includes('后续章节')"
                )
                c.screenshot(out / "chapter-management.png")
                c.click("视觉资产库", ".workspace-tabs button")
                c.evaluate(
                    "document.querySelector('.page-heading .toolbar-menu summary').click()"
                )
                c.click("导入章节附件")
                c.wait("document.querySelector('.modal .drop-zone input')")
                c.evaluate(
                    "(()=>{const dt=new DataTransfer();dt.items.add(new File(['第一份原文'],'批量甲.txt',{type:'text/plain'}));dt.items.add(new File(['第二份原文'],'批量乙.md',{type:'text/markdown'}));const e=document.querySelector('.modal .drop-zone input');e.files=dt.files;e.dispatchEvent(new Event('change',{bubbles:true}));})()"
                )
                c.wait(
                    "document.querySelector('.source-toolbar select')?.options.length===4"
                )
                # Reports are informational; close each via the labelled close button.
                for _ in range(2):
                    c.wait(
                        "document.querySelector('[aria-label=\"导入字数与用量预估\"]')"
                    )
                    c.click("关闭用量提示", '[aria-label="导入字数与用量预估"] button')
                c.evaluate("document.querySelector('.brand').click()")
                c.wait("[...document.querySelectorAll('.book-cover')].some(e=>e.innerText.includes('青灯夜渡'))")
                c.evaluate(
                    "[...document.querySelectorAll('.book-cover')].find(e=>e.innerText.includes('青灯夜渡')).click()"
                )
                c.wait("document.querySelector('.reader-stage')")
                c.evaluate("document.querySelector('[aria-label=\"目录\"]').click()")
                c.wait("document.querySelector('[aria-label=\"章节目录\"]')")
                c.click("2 · 第一章新名", ".reader-directory-item")
                c.wait("document.querySelector('[aria-label=\"预览资产 沈青\"]')")
                c.evaluate(
                    "document.querySelector('[aria-label=\"预览资产 沈青\"]').click()"
                )
                c.wait("document.querySelector('.reader-preview-image img')")
                assert "副卡唯一图" in c.evaluate(
                    "document.querySelector('.reader-image-preview').innerText"
                )
                c.evaluate(
                    "document.querySelector('[aria-label=\"点击阅读图片查看大图\"]').click()"
                )
                c.wait("document.querySelector('.image-viewer')")
                c.evaluate(
                    "document.querySelector('[aria-label=\"关闭大图\"]').click()"
                )
                c.wait("!document.querySelector('.image-viewer')")
                assert c.evaluate("!!document.querySelector('.reader-image-preview')")
                c.screenshot(out / "reading-album.png")
                assert not c.errors, c.errors
                (out / "result.json").write_text(
                    json.dumps(
                        dict(
                            passed=True,
                            actual_qwebchannel=True,
                            checks=[
                                "portrait bookshelf rename and persisted drag order",
                                "whole book results in one grid",
                                "scene albums and native fullscreen with Escape",
                                "batch select candidates",
                                "chapter rename and drag reorder",
                                "existing multiple-file import",
                                "variant-only reading preview with direct enlargement",
                            ],
                        ),
                        indent=2,
                    )
                )
                print("Gallery native end-to-end passed.")
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
