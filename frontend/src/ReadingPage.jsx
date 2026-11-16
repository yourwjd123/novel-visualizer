import React, {
  useState,
  useEffect,
  useRef,
  useLayoutEffect,
  useCallback,
} from "react";
import {
  Library,
  BookOpen,
  List,
  Bookmark,
  Settings2,
  PanelRightClose,
  PanelRightOpen,
  ChevronLeft,
  ChevronRight,
  X,
  Images,
  UserRound,
  ImageOff,
  ImagePlus,
  RotateCcw,
  ArrowRight,
  Plus,
  Trash2,
  Maximize2,
} from "lucide-react";
import { api } from "./api";
import { useWorkspace } from "./context";
import { Empty, PageHeading } from "./App";

export function Bookshelf() {
  const { s, run, notify, setModal, navigate } = useWorkspace();
  const [books, setBooks] = useState([]),
    [loading, setLoading] = useState(false);
  useEffect(() => {
    let alive = true;
    if (!s.account) {
      setBooks([]);
      return;
    }
    setLoading(true);
    api("bookshelf")
      .then((v) => {
        if (alive) setBooks(v);
      })
      .catch((e) => notify(e.message))
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [s.account?.id, JSON.stringify(s.projects)]);
  async function open(book) {
    if (await run("project_open", { path: book.path })) {
      await navigate("reader");
    }
  }
  return (
    <div className="bookshelf">
      <PageHeading
        title="书架"
        actions={
          <button
            onClick={() =>
              setModal({ type: s.account ? "projects" : "accounts" })
            }
          >
            <Plus size={15} />
            添加或导入小说
          </button>
        }
      />
      {!s.account ? (
        <Empty
          title="你的书架"
          text="选择账户后查看各本小说，继续阅读或进入制作。"
          action={
            <button
              className="primary"
              onClick={() => setModal({ type: "accounts" })}
            >
              选择或创建账户
            </button>
          }
        />
      ) : loading ? (
        <p role="status">正在整理书架…</p>
      ) : books.length ? (
        <div className="bookshelf-grid">
          {books.map((book, index) => (
            <button
              className={"book-cover cover-" + (index % 6)}
              key={book.id}
              aria-label={"阅读 " + book.name}
              onClick={() => open(book)}
            >
              {book.cover && <img src={book.cover} alt="" />}
              <span>{book.name}</span>
            </button>
          ))}
        </div>
      ) : (
        <Empty
          title="书架还没有小说"
          text="新建小说项目后，在视觉资产库分章导入原文。"
          action={
            <button
              className="primary"
              onClick={() => setModal({ type: "projects" })}
            >
              新建小说项目
            </button>
          }
        />
      )}
    </div>
  );
}

export default function ReadingPage() {
  const {
    s,
    run,
    navigate,
    notify,
    uploadFiles,
    setLarge,
    registerReaderFlush,
  } = useWorkspace();
  const [data, setData] = useState(null),
    [chapter, setChapter] = useState(null),
    [panel, setPanel] = useState(null),
    [media, setMedia] = useState({ assets: [], scenes: [] }),
    [range, setRange] = useState([1, 1]),
    [preview, setPreview] = useState(null),
    [largeImage, setLargeImage] = useState(""),
    [pagination, setPagination] = useState({ page: 0, total: 1 }),
    [ready, setReady] = useState(false);
  const stage = useRef(null),
    flow = useRef(null),
    coverInput = useRef(null),
    anchor = useRef(null),
    pending = useRef(null),
    timer = useRef(null),
    sequence = useRef(0),
    initialized = useRef(false),
    saveQueue = useRef(Promise.resolve()),
    previewSeq = useRef(0),
    mediaSeq = useRef(0);
  const prefs = data?.preferences;
  const pageMode = prefs?.mode === "pages";
  const project = s.project.id;
  const flush = useCallback(async () => {
    clearTimeout(timer.current);
    if (pending.current) {
      const payload = pending.current;
      pending.current = null;
      saveQueue.current = saveQueue.current
        .catch(() => {})
        .then(() => api("reader_position", { ...payload, _project: project }));
    }
    await saveQueue.current;
  }, [project]);
  useEffect(() => {
    registerReaderFlush(flush);
    return () => {
      registerReaderFlush(null);
      clearTimeout(timer.current);
    };
  }, [flush]);
  async function load(id) {
    const n = ++sequence.current;
    try {
      const result = await api("reader_chapter", {
        chapter: id,
        _project: project,
      });
      if (n !== sequence.current) return;
      setData(result);
      setChapter(result.chapter);
      return result;
    } catch (e) {
      notify(e.message);
    }
  }
  useEffect(() => {
    load();
    return () => {
      sequence.current++;
    };
  }, [project]);
  function queuePosition(value) {
    anchor.current = value;
    pending.current = value;
    clearTimeout(timer.current);
    timer.current = setTimeout(
      () => flush().catch((e) => notify(e.message)),
      500,
    );
  }
  function scan() {
    if (
      !stage.current ||
      !flow.current ||
      !initialized.current ||
      !data?.paragraphs.length
    )
      return;
    const viewport = stage.current.getBoundingClientRect();
    const list = [...flow.current.querySelectorAll("[data-paragraph]")];
    const visible = list.filter((p) =>
      [...p.getClientRects()].some(
        (r) =>
          r.bottom > viewport.top + 2 &&
          r.top < viewport.bottom - 2 &&
          r.right > viewport.left + 2 &&
          r.left < viewport.right - 2,
      ),
    );
    if (!visible.length) return;
    const first = visible[0];
    let offset = 0;
    const textNode = first.firstChild;
    if (textNode) {
      let low = 0,
        high = textNode.textContent.length;
      while (low < high) {
        const mid = Math.floor((low + high) / 2);
        const range = document.createRange();
        range.setStart(textNode, mid);
        range.setEnd(textNode, Math.min(mid + 1, textNode.textContent.length));
        const rect = range.getBoundingClientRect();
        const earlier = pageMode
          ? rect.right <= viewport.left + 2 ||
            (rect.left < viewport.right && rect.bottom <= viewport.top + 2)
          : rect.bottom <= viewport.top + 2;
        if (earlier) low = mid + 1;
        else high = mid;
      }
      let index = low;
      const code = textNode.textContent.charCodeAt(index);
      if (code >= 0xdc00 && code <= 0xdfff) index = Math.max(0, index - 1);
      offset = Array.from(textNode.textContent.slice(0, index)).length;
    }
    const start = Number(first.dataset.paragraph),
      end = Number(visible.at(-1).dataset.paragraph);
    setRange((old) =>
      old[0] === start && old[1] === end ? old : [start, end],
    );
    queuePosition({
      chapter: data.chapter,
      paragraph: start,
      offset,
      source_hash: data.source_hash,
    });
    if (pageMode)
      setPagination({
        page: Math.round(stage.current.scrollLeft / stage.current.clientWidth),
        total: Math.max(
          1,
          Math.ceil(stage.current.scrollWidth / stage.current.clientWidth),
        ),
      });
  }
  function locate(value) {
    if (!stage.current || !flow.current) return;
    const node = flow.current.querySelector(
      `[data-paragraph="${value?.paragraph || 1}"]`,
    );
    if (!node) return;
    const r = document.createRange();
    const text = node.firstChild;
    if (text) {
      const off = Array.from(text.textContent)
        .slice(0, value?.offset || 0)
        .join("").length;
      r.setStart(text, off);
      r.setEnd(text, Math.min(off + 1, text.textContent.length));
    } else r.selectNodeContents(node);
    const rect = r.getBoundingClientRect(),
      bounds = stage.current.getBoundingClientRect();
    if (pageMode) {
      const index = Math.max(
        0,
        Math.floor(
          (rect.left - bounds.left + stage.current.scrollLeft) /
            stage.current.clientWidth,
        ),
      );
      stage.current.scrollLeft = index * stage.current.clientWidth;
    } else
      stage.current.scrollTop = Math.max(
        0,
        rect.top - bounds.top + stage.current.scrollTop - 20,
      );
  }
  const scanRef = useRef(scan);
  scanRef.current = scan;
  useLayoutEffect(() => {
    if (!data?.chapter) return;
    initialized.current = false;
    setReady(false);
    const saved =
      anchor.current?.chapter === data.chapter
        ? anchor.current
        : data.position?.chapter === data.chapter
          ? data.position
          : null;
    anchor.current = saved;
    const id = requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        if (!stage.current) return;
        stage.current.style.setProperty(
          "--page-width",
          stage.current.clientWidth + "px",
        );
        if (saved && !saved.stale) locate(saved);
        else {
          stage.current.scrollTop = 0;
          stage.current.scrollLeft = 0;
          if (saved?.stale)
            notify("原文已变化，旧位置无法唯一定位，已打开章节供你核对。");
        }
        initialized.current = true;
        setReady(true);
        scanRef.current();
      }),
    );
    return () => cancelAnimationFrame(id);
  }, [
    data?.chapter,
    prefs?.mode,
    prefs?.font_size,
    prefs?.line_height,
    prefs?.width,
    prefs?.font,
  ]);
  useEffect(() => {
    if (!stage.current || !data?.chapter) return;
    let frame;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (!stage.current) return;
        initialized.current = false;
        stage.current.style.setProperty(
          "--page-width",
          stage.current.clientWidth + "px",
        );
        locate(anchor.current);
        initialized.current = true;
        scanRef.current();
      });
    });
    observer.observe(stage.current);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [data?.chapter, pageMode]);
  useEffect(() => {
    if (!chapter || !ready) return;
    const n = ++mediaSeq.current;
    const timeout = setTimeout(
      () =>
        api("reader_media", {
          chapter,
          start: range[0],
          end: range[1],
          _project: project,
        })
          .then((value) => {
            if (n === mediaSeq.current) setMedia(value);
          })
          .catch((e) => notify(e.message)),
      160,
    );
    return () => {
      clearTimeout(timeout);
      mediaSeq.current++;
    };
  }, [
    chapter,
    range[0],
    range[1],
    ready,
    JSON.stringify(s.results),
    JSON.stringify(s.assets.map((a) => [a.id, a.revision])),
  ]);
  useEffect(() => {
    const n = ++previewSeq.current;
    setLargeImage("");
    const im = preview?.images[preview.index];
    if (im?.path)
      api("image", { path: im.path, _project: project })
        .then((src) => {
          if (n === previewSeq.current) setLargeImage(src);
        })
        .catch((e) => notify(e.message));
    return () => {
      previewSeq.current++;
    };
  }, [preview?.id, preview?.index, project]);
  async function changeChapter(id, position = null) {
    if (id === chapter && position) {
      if (position.stale) {
        notify("此书签的原文已变化，无法唯一定位。");
        return;
      }
      locate(position);
      scanRef.current();
      setPanel(null);
      return;
    }
    await flush().catch((e) => notify(e.message));
    initialized.current = false;
    setReady(false);
    setPreview(null);
    setMedia({ assets: [], scenes: [] });
    setRange([1, 1]);
    anchor.current = position;
    await load(id);
    setPanel(null);
  }
  async function preference(patch) {
    const result = await run("reader_preferences", patch, false);
    if (result) setData((d) => ({ ...d, preferences: result }));
  }
  function turn(direction) {
    if (!stage.current || !ready) return;
    const width = stage.current.clientWidth;
    const current = Math.round(stage.current.scrollLeft / width);
    const total = Math.max(1, Math.ceil(stage.current.scrollWidth / width));
    const next = current + direction;
    if (next < 0 || next >= total) {
      const index = data.chapters.findIndex((c) => c.id === chapter);
      const ch = data.chapters[index + direction];
      if (ch) changeChapter(ch.id);
      return;
    }
    stage.current.scrollLeft = next * width;
    scanRef.current();
  }
  useEffect(() => {
    function key(e) {
      if (
        e.target.closest("input,textarea,select") ||
        e.ctrlKey ||
        e.metaKey ||
        e.altKey
      )
        return;
      if (e.key === "Escape") {
        setPreview(null);
        setPanel(null);
      } else if (
        pageMode &&
        !preview &&
        !panel &&
        ["ArrowLeft", "ArrowRight"].includes(e.key)
      ) {
        e.preventDefault();
        turn(e.key === "ArrowRight" ? 1 : -1);
      }
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [pageMode, preview, panel, data, chapter]);
  async function bookmark() {
    if (!ready) return;
    const current = anchor.current || {
      chapter,
      paragraph: 1,
      offset: 0,
      source_hash: data.source_hash,
    };
    if (await run("reader_bookmark", { anchor: current }, false)) {
      notify("书签已保存");
      const updated = await api("reader_chapter", {
        chapter,
        _project: project,
      });
      setData((d) => ({ ...d, bookmarks: updated.bookmarks }));
    }
  }
  async function enterMaking() {
    await flush();
    if (chapter && !(await run("select", { segment: chapter }))) return;
    await navigate("assets");
  }
  const active = data?.chapters.find((c) => c.id === chapter);
  const position = data?.position;
  const scenes = (media.scenes || [])
    .map((group) => ({
      ...group,
      images: group.images.filter(
        (im) => prefs?.include_candidates || im.state === "成果",
      ),
    }))
    .filter((group) => group.images.length);
  const assets = media.assets || [];
  if (!data) return <p className="reader-loading">正在打开小说…</p>;
  return (
    <section
      className={"reader-shell paper-" + prefs.paper}
      style={{
        "--reader-size": prefs.font_size + "px",
        "--reader-line": prefs.line_height,
        "--reader-width": prefs.width + "px",
        "--reader-font":
          prefs.font === "serif"
            ? '"Noto Serif CJK SC", "Songti SC", serif'
            : "system-ui,sans-serif",
      }}
      aria-label="小说阅读界面"
    >
      <header className="reader-header">
        <div className="reader-book-meta">
          <button
            className="icon quiet"
            title="返回书架"
            aria-label="返回书架"
            onClick={() => navigate("bookshelf")}
          >
            <Library size={19} />
          </button>
          <div>
            <h1>{s.project.name}</h1>
            <small>
              共 {data.chapters.length} 章 ·{" "}
              {position
                ? `上次读到 ${data.chapters.find((c) => c.id === position.chapter)?.name || "已归档章节"}`
                : "尚无阅读记录"}{" "}
              · 制作进度 {data.progress.results}/{data.progress.scenes}
            </small>
          </div>
        </div>
        <div className="reader-tools">
          <button
            aria-label="目录"
            className={"icon quiet " + (panel === "contents" ? "active" : "")}
            title="目录"
            onClick={() => setPanel(panel === "contents" ? null : "contents")}
          >
            <List size={19} />
          </button>
          <button
            className="icon quiet"
            title="书签"
            aria-label="书签"
            onClick={() => setPanel(panel === "bookmarks" ? null : "bookmarks")}
          >
            <Bookmark size={19} />
          </button>
          <button
            className="icon quiet"
            title="阅读设置"
            aria-label="阅读设置"
            onClick={() => setPanel(panel === "settings" ? null : "settings")}
          >
            <Settings2 size={19} />
          </button>
          <button className="primary" onClick={enterMaking}>
            <ArrowRight size={15} />
            进入制作
          </button>
        </div>
      </header>
      <div className="reader-body">
        {panel && (
          <aside
            className="reader-popover"
            aria-label={
              panel === "contents"
                ? "章节目录"
                : panel === "bookmarks"
                  ? "阅读书签"
                  : "阅读设置面板"
            }
          >
            <div className="section-heading">
              <h2>
                {panel === "contents"
                  ? "目录"
                  : panel === "bookmarks"
                    ? "书签"
                    : "阅读设置"}
              </h2>
              <button
                className="icon quiet"
                aria-label="关闭阅读工具"
                onClick={() => setPanel(null)}
              >
                <X size={17} />
              </button>
            </div>
            {panel === "contents" ? (
              data.chapters.map((c, index) => (
                <button
                  key={c.id}
                  className={
                    "reader-directory-item " +
                    (chapter === c.id ? "active" : "")
                  }
                  onClick={() => changeChapter(c.id)}
                >
                  {index + 1} · {c.name}
                </button>
              ))
            ) : panel === "bookmarks" ? (
              <>
                <button onClick={bookmark} disabled={!chapter || !ready}>
                  <Plus size={15} />
                  添加当前位置书签
                </button>
                {data.bookmarks.map((b) => (
                  <div className="reader-bookmark" key={b.id}>
                    <button
                      disabled={b.anchor.chapter_missing}
                      onClick={() => changeChapter(b.anchor.chapter, b.anchor)}
                    >
                      {b.label}
                      <small>
                        {data.chapters.find((c) => c.id === b.anchor.chapter)
                          ?.name || "章节已归档"}
                        {b.anchor.stale ? " · 位置需复核" : ""}
                      </small>
                    </button>
                    <button
                      className="icon quiet"
                      title="删除书签"
                      aria-label={"删除书签 " + b.label}
                      onClick={async () => {
                        await run(
                          "reader_bookmark",
                          { id: b.id, action: "delete" },
                          false,
                        );
                        setData((d) => ({
                          ...d,
                          bookmarks: d.bookmarks.filter((v) => v.id !== b.id),
                        }));
                      }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </>
            ) : (
              <>
                <label>
                  阅读方式
                  <select
                    aria-label="阅读方式"
                    value={prefs.mode}
                    onChange={(e) => preference({ mode: e.target.value })}
                  >
                    <option value="scroll">滚动阅读</option>
                    <option value="pages">模拟翻页</option>
                  </select>
                </label>
                <label>
                  字体
                  <select
                    value={prefs.font}
                    onChange={(e) => preference({ font: e.target.value })}
                  >
                    <option value="serif">宋体／衬线</option>
                    <option value="sans">清晰无衬线</option>
                  </select>
                </label>
                <label>
                  字号 {prefs.font_size}
                  <input
                    aria-label="阅读字号"
                    type="range"
                    min="14"
                    max="36"
                    value={prefs.font_size}
                    onChange={(e) =>
                      preference({ font_size: Number(e.target.value) })
                    }
                  />
                </label>
                <label>
                  行距 {prefs.line_height}
                  <input
                    type="range"
                    min="1.4"
                    max="2.6"
                    step="0.05"
                    value={prefs.line_height}
                    onChange={(e) =>
                      preference({ line_height: Number(e.target.value) })
                    }
                  />
                </label>
                <label>
                  正文宽度
                  <input
                    type="range"
                    min="420"
                    max="1100"
                    step="20"
                    value={prefs.width}
                    onChange={(e) =>
                      preference({ width: Number(e.target.value) })
                    }
                  />
                </label>
                <label>
                  阅读底色
                  <select
                    value={prefs.paper}
                    onChange={(e) => preference({ paper: e.target.value })}
                  >
                    <option value="warm">暖纸</option>
                    <option value="white">清白</option>
                    <option value="mint">浅绿</option>
                  </select>
                </label>
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={prefs.include_candidates}
                    onChange={(e) =>
                      preference({ include_candidates: e.target.checked })
                    }
                  />
                  也显示场景候选图
                </label>
                <div className="actions">
                  <button
                    className="icon quiet"
                    title="自定义小说封面"
                    aria-label="自定义小说封面"
                    onClick={() => coverInput.current.click()}
                  >
                    <ImagePlus size={19} />
                  </button>
                  <button
                    className="icon quiet"
                    title="恢复默认封面"
                    aria-label="恢复默认封面"
                    onClick={async () => {
                      if (await run("book_cover_reset", {}, false))
                        load(chapter);
                    }}
                  >
                    <RotateCcw size={18} />
                  </button>
                </div>
                <input
                  ref={coverInput}
                  hidden
                  type="file"
                  accept=".png,.jpg,.jpeg,.webp"
                  onChange={async (e) => {
                    if (
                      e.target.files.length &&
                      (await uploadFiles(e.target.files, "book_cover"))
                    )
                      load(chapter);
                    e.target.value = "";
                  }}
                />
              </>
            )}
          </aside>
        )}
        <div className="reader-canvas">
          <div
            ref={stage}
            className={
              "reader-stage " + (pageMode ? "page-mode" : "scroll-mode")
            }
            onScroll={() => scanRef.current()}
            aria-label="阅读正文"
          >
            <article ref={flow} className="reader-flow">
              <h2>{active?.name || "尚未导入章节"}</h2>
              {data.paragraphs.map((p) => (
                <p key={p.number} data-paragraph={p.number}>
                  {p.text}
                </p>
              ))}
              {!chapter && (
                <div className="reader-empty">
                  <p>在视觉资产库导入原文后，即可分章阅读。</p>
                  <button onClick={enterMaking}>导入原文</button>
                </div>
              )}
            </article>
          </div>
        </div>
        <button
          className="reader-rail-toggle icon"
          aria-label={prefs.images_collapsed ? "展开图像栏" : "收起图像栏"}
          title={prefs.images_collapsed ? "展开图像栏" : "收起图像栏"}
          onClick={() =>
            preference({ images_collapsed: !prefs.images_collapsed })
          }
        >
          {prefs.images_collapsed ? (
            <PanelRightOpen size={20} />
          ) : (
            <PanelRightClose size={20} />
          )}
        </button>
        <aside
          className={
            "reader-image-rail " + (prefs.images_collapsed ? "collapsed" : "")
          }
          aria-label="当前阅读范围图像"
          aria-hidden={prefs.images_collapsed}
          inert={prefs.images_collapsed ? true : undefined}
        >
          <div className="rail-category" title="资产图">
            <UserRound size={17} />
          </div>
          {assets.map((group) => (
            <button
              className="reader-thumb"
              key={group.id}
              title={group.name + " · 资产图"}
              aria-label={"预览资产 " + group.name}
              onClick={() => setPreview({ ...group, index: 0 })}
            >
              <img
                src={group.images.find((i) => i.thumbnail)?.thumbnail}
                alt={group.name}
              />
            </button>
          ))}
          <div className="rail-category" title="场景图">
            <Images size={17} />
          </div>
          {scenes.map((group) => (
            <button
              className="reader-thumb landscape"
              key={group.id}
              title={group.name + " · 场景图"}
              aria-label={"预览场景 " + group.name}
              onClick={() => setPreview({ ...group, index: 0 })}
            >
              <img src={group.images[0].thumbnail} alt={group.name} />
            </button>
          ))}
          {!assets.length && !scenes.length && (
            <ImageOff
              className="rail-empty"
              size={22}
              aria-label="当前范围暂无图片"
            />
          )}
        </aside>
        {preview && (
          <aside
            className="reader-image-preview"
            role="dialog"
            aria-label="阅读图片预览"
          >
            <header>
              <strong>
                {preview.name} · {preview.images[preview.index].title}
              </strong>
              <button
                className="icon quiet"
                title="关闭图片预览"
                aria-label="关闭图片预览"
                onClick={() => setPreview(null)}
              >
                <X size={18} />
              </button>
            </header>
            <small>
              {preview.images[preview.index].state}
              {preview.images[preview.index].chapter
                ? " · " +
                  (data.chapters.find(
                    (c) => c.id === preview.images[preview.index].chapter,
                  )?.name || "其他章节")
                : ""}
            </small>
            <div className="reader-preview-image">
              {largeImage ? (
                <img
                  src={largeImage}
                  alt={preview.images[preview.index].title}
                />
              ) : preview.images[preview.index].path ? (
                <span>正在读取图片…</span>
              ) : (
                <span>主卡尚无图片，可翻看已有副卡。</span>
              )}
            </div>
            <footer>
              <button
                className="icon quiet"
                aria-label="上一张资产或场景图"
                disabled={preview.index === 0}
                onClick={() =>
                  setPreview((v) => ({ ...v, index: v.index - 1 }))
                }
              >
                <ChevronLeft size={20} />
              </button>
              <small>
                {preview.index + 1} / {preview.images.length}
              </small>
              <button
                className="icon quiet"
                title="放大查看"
                aria-label="放大阅读图片"
                disabled={!preview.images[preview.index].path}
                onClick={() =>
                  setLarge({
                    path: preview.images[preview.index].path,
                    title: preview.name,
                  })
                }
              >
                <Maximize2 size={18} />
              </button>
              <button
                className="icon quiet"
                aria-label="下一张资产或场景图"
                disabled={preview.index === preview.images.length - 1}
                onClick={() =>
                  setPreview((v) => ({ ...v, index: v.index + 1 }))
                }
              >
                <ChevronRight size={20} />
              </button>
            </footer>
          </aside>
        )}
      </div>
      <footer className="reader-footer">
        <button
          className="icon quiet"
          aria-label={pageMode ? "上一页" : "上一章"}
          onClick={() =>
            pageMode
              ? turn(-1)
              : changeChapter(
                  data.chapters[
                    data.chapters.findIndex((c) => c.id === chapter) - 1
                  ]?.id,
                )
          }
          disabled={
            !chapter ||
            !ready ||
            (!pageMode && data.chapters[0]?.id === chapter)
          }
        >
          <ChevronLeft size={19} />
        </button>
        <small>
          {pageMode
            ? `${pagination.page + 1} / ${pagination.total} 页`
            : `${active?.name || "未导入原文"} · 第 ${range[0]} 段`}
        </small>
        <button
          className="icon quiet"
          aria-label="添加当前位置书签"
          title="添加书签"
          onClick={bookmark}
          disabled={!chapter || !ready}
        >
          <Bookmark size={16} />
        </button>
        <button
          className="icon quiet"
          aria-label={pageMode ? "下一页" : "下一章"}
          onClick={() =>
            pageMode
              ? turn(1)
              : changeChapter(
                  data.chapters[
                    data.chapters.findIndex((c) => c.id === chapter) + 1
                  ]?.id,
                )
          }
          disabled={
            !chapter ||
            !ready ||
            (!pageMode && data.chapters.at(-1)?.id === chapter)
          }
        >
          <ChevronRight size={19} />
        </button>
      </footer>
    </section>
  );
}
