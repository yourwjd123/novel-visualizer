import React, { useState, useEffect } from "react";
import { Plus, LocateFixed, Undo2, ChevronRight } from "lucide-react";
import { useWorkspace, copy } from "./context";
import { PageHeading, Empty, DropZone } from "./App";
import { api } from "./api";

export default function SourcePage() {
  const { s, run, setModal, openAI, navigate, notify, uploadFiles, dirty } =
    useWorkspace();
  const [rows, setRows] = useState([]),
    [selected, setSelected] = useState(0),
    [edit, setEdit] = useState(null),
    [editData, setEditData] = useState(null),
    [split, setSplit] = useState(null),
    [boundary, setBoundary] = useState(1),
    [history, setHistory] = useState([]),
    [showSource, setShowSource] = useState(true),
    [depth, setDepth] = useState(s.depth || "中 · 连续情节");
  const draft = s.drafts?.[s.segment];
  const signature = JSON.stringify(draft?.rows || s.scenes);
  useEffect(() => {
    setRows(copy(draft?.rows || s.scenes || []));
    setSelected(0);
    setEdit(null);
    setEditData(null);
    setHistory([]);
    dirty.current = false;
  }, [s.segment]);
  useEffect(() => {
    if (edit === null) setRows(copy(draft?.rows || s.scenes || []));
  }, [signature]);
  function validate(list) {
    let next = 1;
    for (const r of list) {
      if (!r.title?.trim()) return "每个情节需要标题";
      if (
        r.start_paragraph !== next ||
        r.end_paragraph < r.start_paragraph ||
        r.end_paragraph > s.paragraphs.length
      )
        return "段落存在遗漏、重叠或越界，请调整后再确认";
      next = r.end_paragraph + 1;
    }
    return next === s.paragraphs.length + 1 ? "" : "情节尚未覆盖全部原文";
  }
  const error = rows.length ? validate(rows) : "";
  async function save(next, keepUndo = true) {
    if (keepUndo) setHistory((h) => [...h, copy(rows)]);
    setRows(next);
    await run("save_split", { rows: next });
    setSplit(null);
    dirty.current = false;
  }
  function startEdit(i) {
    setEdit(i);
    setEditData(copy(rows[i]));
    setSelected(i);
    dirty.current = true;
  }
  async function analyze() {
    if (!s.segment) {
      setModal({ type: "import" });
      return;
    }
    if (
      (draft || s.scenes.length) &&
      !window.confirm(
        "生成新候选会保留已确认版本，但当前未确认候选将被替换。继续吗？",
      )
    )
      return;
    await run("set_depth", { depth });
    const result = await run("send", {
      node: 0,
      split: true,
      message:
        "请按指定深度拆分当前原文，完整覆盖段落，不改写小说。仅输出约定的情节 JSON。",
    });
    if (result && !result.cancelled)
      notify("分析已开始，输出会作为待确认候选，不自动生成资产或图片。");
  }
  const current = rows[selected];
  const imported = !rows.length;
  const confirmed = !!s.scenes.length && !draft;
  if (!s.segment)
    return (
      <>
        <PageHeading
          title="原文与情节"
          subtitle="导入已有文本，保留原文件，再整理需要可视化的情节。"
          actions={
            <button
              className="primary"
              onClick={() => setModal({ type: "import" })}
            >
              导入原文
            </button>
          }
        />
        <DropZone
          onFiles={(files) => uploadFiles(files, "text")}
          accept=".txt,.md,.docx,.epub"
          label="拖入第一段原文，或点击选择文件"
        />
        <Empty
          title="先导入原文片段"
          text="支持分多次上传。导入本身不调用模型；也可以完全手工拆分。"
          action={
            <button onClick={() => setModal({ type: "import" })}>
              粘贴原文
            </button>
          }
        />
      </>
    );
  return (
    <>
      <PageHeading
        title="原文与情节"
        subtitle="保留原文，整理需要可视化的情节与关键瞬间。"
        actions={
          <>
            <button onClick={() => setModal({ type: "import" })}>
              <Plus size={15} />
              导入下一片段
            </button>
            <button
              className="primary"
              disabled={s.busy || !!error || imported || edit !== null}
              onClick={async () => {
                if (confirmed) {
                  await run("select", {
                    scene: rows[selected]?.id || rows[0].id,
                  });
                  openAI(1);
                  return;
                }
                if (await run("confirm_split", { rows })) {
                  notify("拆分已确认，可选择情节解析资产。");
                }
              }}
            >
              {confirmed ? "解析本情节资产 →" : "确认拆分"}
            </button>
          </>
        }
      />
      <div className="source-toolbar">
        <label className="inline-label">
          当前片段
          <select
            value={s.segment}
            disabled={s.busy}
            onChange={async (e) => {
              if (dirty.current && !window.confirm("放弃当前编辑？")) return;
              await run("select", { segment: e.target.value });
            }}
          >
            {s.segments.map((seg) => (
              <option key={seg.id} value={seg.id}>
                {seg.name}
              </option>
            ))}
          </select>
        </label>
        <label className="inline-label">
          拆分深度
          <select value={depth} onChange={(e) => setDepth(e.target.value)}>
            <option>粗 · 主要事件</option>
            <option>中 · 连续情节</option>
            <option>细 · 关键画面</option>
          </select>
        </label>
        <span className="spacer" />
        <button disabled={s.busy} onClick={analyze}>
          {imported ? "分析并生成候选" : "重新生成候选"}
        </button>
        <button
          className="quiet"
          disabled={s.busy}
          onClick={() => {
            const next = [
              {
                title: "手工情节",
                summary: "",
                visual_moment: "",
                start_paragraph: 1,
                end_paragraph: s.paragraphs.length,
                required_assets: [],
              },
            ];
            save(next).then(() => {
              setEdit(0);
              setEditData(next[0]);
              dirty.current = true;
            });
          }}
        >
          手工拆分
        </button>
      </div>
      <div className="status-line">
        <span>
          {s.busy
            ? "任务执行中；可在 AI 助手或历史查看"
            : confirmed
              ? "拆分已确认"
              : imported
                ? "原文已导入 · 尚未调用模型"
                : "拆分候选待确认"}{" "}
          · {s.paragraphs.length} 个原文段落
          {rows.length ? " · " + rows.length + " 个情节" : ""}
        </span>
        <div className="actions">
          <button
            className="quiet small"
            disabled={!history.length}
            onClick={() => {
              const next = history.at(-1);
              setHistory(history.slice(0, -1));
              save(next, false);
              setEdit(null);
            }}
          >
            {" "}
            <Undo2 size={13} />
            撤销调整
          </button>
          <button
            className="quiet small"
            onClick={() => setShowSource(!showSource)}
          >
            {showSource ? "收起原文" : "展开原文"}
          </button>
        </div>
      </div>
      {s.jobs.find((j) => j.node === 0 && j.segment === s.segment)
        ?.validation_error && (
        <div className="notice warning">
          模型输出未通过校验：
          {
            s.jobs.find((j) => j.node === 0 && j.segment === s.segment)
              .validation_error
          }
          <button onClick={() => openAI(0)}>打开输出并手工修正</button>
        </div>
      )}
      <div className={"source-layout " + (!showSource ? "source-hidden" : "")}>
        {showSource && (
          <section className="source-paper">
            <header>
              <h2>原文对照</h2>
              <small>只读 · 原文件已保留</small>
            </header>
            <div className="paragraph-list">
              {s.paragraphs.map((p) => (
                <div
                  className={
                    "paragraph " +
                    (current &&
                    p.number >= current.start_paragraph &&
                    p.number <= current.end_paragraph
                      ? "highlight"
                      : "")
                  }
                  id={"paragraph-" + p.number}
                  key={p.number}
                >
                  <span>{String(p.number).padStart(2, "0")}</span>
                  <p>{p.text}</p>
                </div>
              ))}
            </div>
            <footer>
              {current
                ? "当前对应：" +
                  current.title +
                  " · 段落 " +
                  current.start_paragraph +
                  "—" +
                  current.end_paragraph
                : "分析或手工划分后，点击卡片定位原文。"}
            </footer>
          </section>
        )}
        <section className="split-area">
          <div className="section-heading">
            <h2>情节卡 · {confirmed ? "已确认" : "待确认"}</h2>
            <button className="quiet small" onClick={() => openAI(0)}>
              讨论拆分
            </button>
          </div>
          {error && (
            <div role="alert" className="notice warning">
              {error}
            </div>
          )}
          {imported ? (
            <Empty
              title="先把原文整理成情节卡"
              text="选择拆分深度后发起分析；模型输出先经过检查，也可手工整理。"
              action={
                <button className="primary" disabled={s.busy} onClick={analyze}>
                  分析此片段
                </button>
              }
            />
          ) : (
            <div className="scene-grid">
              {rows.map((row, i) => (
                <article
                  className={"scene-card " + (selected === i ? "selected" : "")}
                  key={i}
                >
                  <div className="card-meta">
                    <span>
                      情节 {String(i + 1).padStart(2, "0")} · 段落{" "}
                      {row.start_paragraph}—{row.end_paragraph}
                    </span>
                    <span className="badge">
                      {confirmed ? "已确认" : "候选"}
                    </span>
                  </div>
                  {edit === i ? (
                    <div className="edit-form">
                      <label>
                        标题
                        <input
                          value={editData.title}
                          onChange={(e) =>
                            setEditData({ ...editData, title: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        摘要
                        <textarea
                          rows={3}
                          value={editData.summary || ""}
                          onChange={(e) =>
                            setEditData({
                              ...editData,
                              summary: e.target.value,
                            })
                          }
                        />
                      </label>
                      <label>
                        可视化瞬间
                        <textarea
                          rows={2}
                          value={editData.visual_moment || ""}
                          onChange={(e) =>
                            setEditData({
                              ...editData,
                              visual_moment: e.target.value,
                            })
                          }
                        />
                      </label>
                      <div className="range-inputs">
                        <label>
                          开始段
                          <input
                            type="number"
                            min={1}
                            max={s.paragraphs.length}
                            value={editData.start_paragraph}
                            onChange={(e) =>
                              setEditData({
                                ...editData,
                                start_paragraph: Number(e.target.value),
                              })
                            }
                          />
                        </label>
                        <label>
                          结束段
                          <input
                            type="number"
                            min={1}
                            max={s.paragraphs.length}
                            value={editData.end_paragraph}
                            onChange={(e) =>
                              setEditData({
                                ...editData,
                                end_paragraph: Number(e.target.value),
                              })
                            }
                          />
                        </label>
                      </div>
                      <div className="actions">
                        <button
                          className="primary"
                          onClick={() => {
                            const next = copy(rows);
                            next[i] = editData;
                            save(next);
                            setEdit(null);
                          }}
                        >
                          保存调整
                        </button>
                        <button
                          onClick={() => {
                            setEdit(null);
                            dirty.current = false;
                          }}
                        >
                          取消
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <h3>{row.title}</h3>
                      <p className="card-summary">
                        {row.summary || "摘要待填写"}
                      </p>
                      <div className="visual-moment">
                        <small>建议可视化瞬间</small>
                        <p>{row.visual_moment || "待用户确定"}</p>
                      </div>
                      <div className="tags">
                        {(row.required_assets || []).map((a, n) => (
                          <span key={n}>{a.name}</span>
                        ))}
                      </div>
                    </>
                  )}
                  <div className="card-actions">
                    <button
                      className="quiet locate"
                      onClick={() => {
                        setSelected(i);
                        if (row.id) run("select", { scene: row.id });
                      }}
                    >
                      <LocateFixed size={12} />
                      定位原文
                    </button>
                    <button disabled={s.busy} onClick={() => startEdit(i)}>
                      编辑
                    </button>
                    <button
                      disabled={
                        s.busy || row.start_paragraph === row.end_paragraph
                      }
                      onClick={() => {
                        setSplit(split === i ? null : i);
                        setBoundary(row.start_paragraph);
                      }}
                    >
                      拆分
                    </button>
                    <button
                      disabled={s.busy || i === rows.length - 1}
                      onClick={() => {
                        const next = copy(rows),
                          a = next[i],
                          b = next[i + 1];
                        next.splice(i, 2, {
                          ...a,
                          title: a.title + "与" + b.title,
                          summary: (a.summary || "") + (b.summary || ""),
                          end_paragraph: b.end_paragraph,
                          required_assets: [
                            ...(a.required_assets || []),
                            ...(b.required_assets || []),
                          ],
                        });
                        save(next);
                      }}
                    >
                      合并下条
                    </button>
                  </div>
                  {split === i && (
                    <div className="split-boundary">
                      <label>
                        在此段后拆开
                        <select
                          value={boundary}
                          onChange={(e) => setBoundary(Number(e.target.value))}
                        >
                          {Array.from(
                            { length: row.end_paragraph - row.start_paragraph },
                            (_, j) => (
                              <option key={j} value={row.start_paragraph + j}>
                                段落 {row.start_paragraph + j}
                              </option>
                            ),
                          )}
                        </select>
                      </label>
                      <button
                        className="primary small"
                        onClick={() => {
                          const next = copy(rows);
                          next.splice(
                            i,
                            1,
                            {
                              ...copy(row),
                              title: row.title + " · 前段",
                              end_paragraph: boundary,
                            },
                            {
                              ...copy(row),
                              title: row.title + " · 后段",
                              start_paragraph: boundary + 1,
                            },
                          );
                          save(next);
                          notify("已拆分，请分别核对摘要和可视化瞬间。");
                        }}
                      >
                        确定
                      </button>
                    </div>
                  )}
                  {confirmed && (
                    <button
                      className="card-next quiet"
                      onClick={async () => {
                        if (await run("select", { scene: row.id }))
                          navigate("images");
                      }}
                    >
                      制作此情节插图 <ChevronRight size={13} />
                    </button>
                  )}
                </article>
              ))}
            </div>
          )}
          {!imported && (
            <div className="split-footer">
              <span className="muted small">
                {error
                  ? "覆盖检查未通过"
                  : `原文 ${s.paragraphs.length} / ${s.paragraphs.length} 段已覆盖 · 无遗漏、无重叠`}
              </span>
              <span className="small muted">
                候选中的资产名称不会自动变成正式档案。
              </span>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
