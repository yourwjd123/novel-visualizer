import React, { useState, useEffect, useRef } from "react";
import { Plus, LocateFixed, Undo2, ChevronRight } from "lucide-react";
import { useWorkspace, copy, freshId } from "./context";
import { PageHeading, Empty, DropZone } from "./App";
import { api } from "./api";

export default function SourcePage() {
  const {
    s,
    run,
    setModal,
    openAI,
    navigate,
    notify,
    uploadFiles,
    setAssetEdit,
    dirty,
  } = useWorkspace();
  const [rows, setRows] = useState([]),
    [selected, setSelected] = useState(0),
    [edit, setEdit] = useState(null),
    [editData, setEditData] = useState(null),
    [split, setSplit] = useState(null),
    [boundary, setBoundary] = useState(1),
    [history, setHistory] = useState([]),
    [showSource, setShowSource] = useState(true),
    [depth, setDepth] = useState(s.depth || "中 · 连续情节"),
    [summaryText, setSummaryText] = useState(s.chapter_summary?.text || "");
  useEffect(
    () => setSummaryText(s.chapter_summary?.text || ""),
    [s.segment, s.chapter_summary?.text],
  );
  const sourceRef = useRef(null);
  const draft = s.drafts?.[s.segment];
  const signature = JSON.stringify([draft?.rows, s.scenes]);
  useEffect(() => {
    setRows(
      copy(draft?.rows || s.scenes || []).map((r) => ({
        ...r,
        required_assets:
          r.required_assets ||
          s.scenes.find((v) => v.id === r.id)?.required_assets ||
          [],
        id: r.id || freshId(),
        review: r.review || (draft ? "候选" : "已确认"),
      })),
    );
    setSelected(0);
    setEdit(null);
    setEditData(null);
    setHistory([]);
    dirty.current = false;
  }, [s.segment]);
  useEffect(() => {
    if (edit === null)
      setRows(
        copy(draft?.rows || s.scenes || []).map((r) => ({
          ...r,
          required_assets:
            r.required_assets ||
            s.scenes.find((v) => v.id === r.id)?.required_assets ||
            [],
          id: r.id || freshId(),
          review: r.review || (draft ? "候选" : "已确认"),
        })),
      );
  }, [signature]);
  function validate(list) {
    let previous = 0;
    for (const r of list) {
      if (!r.title?.trim()) return "每个情节需要标题";
      if (
        r.start_paragraph <= previous ||
        r.end_paragraph < r.start_paragraph ||
        r.end_paragraph > s.paragraphs.length ||
        r.start_paragraph < 1
      )
        return "段落存在重叠或越界，请调整后再确认";
      previous = r.end_paragraph;
    }
    return "";
  }
  const error = rows.length ? validate(rows) : "";
  async function save(next, keepUndo = true) {
    next = next.map((r) => ({
      ...r,
      id: r.id || freshId(),
      review: r.review || "候选",
    }));
    if (!(await run("review_scenes", { rows: next, ids: [], status: "候选" })))
      return false;
    if (keepUndo) setHistory((h) => [...h, copy(rows)]);
    setRows(next);
    setSplit(null);
    dirty.current = false;
    return true;
  }
  function startEdit(i) {
    if (
      edit !== null &&
      dirty.current &&
      !window.confirm("放弃当前未保存编辑并编辑另一张卡片？")
    )
      return;
    setEdit(i);
    setEditData(copy(rows[i]));
    setSelected(i);
    dirty.current = true;
  }
  async function analyze() {
    if (!s.asset_ready) {
      notify("请先完成本章资产整理");
      return;
    }
    if (!s.segment) {
      navigate("assets");
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
  async function review(ids, status) {
    if (await run("review_scenes", { rows, ids, status }))
      setRows(
        rows.map((r) => (ids.includes(r.id) ? { ...r, review: status } : r)),
      );
  }
  function locate(i) {
    setSelected(i);
    setShowSource(true);
    if (s.scenes.some((r) => r.id === rows[i].id))
      run("select", { scene: rows[i].id });
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        const el = document.getElementById(
            "paragraph-" + rows[i].start_paragraph,
          ),
          pane = sourceRef.current;
        if (el && pane)
          pane.scrollTo({
            top:
              pane.scrollTop +
              el.getBoundingClientRect().top -
              pane.getBoundingClientRect().top -
              12,
            behavior: "smooth",
          });
      }),
    );
  }
  async function extract() {
    navigate("assets");
  }
  const current = rows[selected];
  const covered = new Set(
    rows.flatMap((r) =>
      Array.from(
        { length: Math.max(0, r.end_paragraph - r.start_paragraph + 1) },
        (_, i) => r.start_paragraph + i,
      ),
    ),
  );
  const missing = s.paragraphs.filter((p) => !covered.has(p.number));
  const imported = !rows.length;
  const confirmed = rows.length > 0 && rows.every((r) => r.review === "已确认");
  if (!s.segment)
    return (
      <>
        <PageHeading title="原文与情节" subtitle="对照原文，拆分和编辑情节。" />
        <Empty
          title="尚未导入章节"
          text="请先在视觉资产库导入原文并完成资产整理。"
          action={
            <button onClick={() => navigate("assets")}>前往视觉资产库</button>
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
            <button
              disabled={
                s.busy || !s.asset_ready || !!error || imported || edit !== null
              }
              onClick={() =>
                review(
                  rows.map((r) => r.id),
                  confirmed ? "候选" : "已确认",
                )
              }
            >
              {confirmed ? "全部转为候选" : "确认全部情节"}
            </button>
            <button className="primary" disabled={!s.segment} onClick={extract}>
              前往本章资产库 →
            </button>
          </>
        }
      />
      {(s.archived_chapters || []).length > 0 && (
        <details>
          <summary>已删除章节</summary>
          {s.archived_chapters.map((ch) => (
            <p key={ch.id}>
              {ch.name}
              <button
                onClick={() =>
                  run("chapter_action", { id: ch.id, restore: true })
                }
              >
                恢复章节
              </button>
            </p>
          ))}
        </details>
      )}
      {!s.asset_ready && (
        <div className="notice warning">
          先完成本章资产整理，再开始情节解析。
          <button onClick={() => navigate("assets")}>前往资产整理</button>
        </div>
      )}
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
        <button disabled={s.busy || !s.asset_ready} onClick={analyze}>
          {imported ? "分析并生成候选" : "重新生成候选"}
        </button>
        <button
          className="quiet"
          disabled={s.busy || !s.asset_ready}
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
      <details className="chapter-summary">
        <summary>
          本章内容梗概 · 咨询与补全的背景依据
          {s.chapter_summary?.stale ? "（原文已变化，请更新）" : ""}
        </summary>
        <p className="muted small">
          解析时生成，也可手工填写；咨询和补全不会改用章节全文。手工梗概不会被重新解析自动覆盖。
        </p>
        <textarea
          aria-label="本章梗概"
          rows={4}
          value={summaryText}
          onChange={(e) => setSummaryText(e.target.value)}
        />
        <button onClick={() => run("save_summary", { text: summaryText })}>
          保存本章梗概
        </button>
        {s.chapter_summary?.suggested_text && (
          <button
            onClick={() => setSummaryText(s.chapter_summary.suggested_text)}
          >
            载入重新解析建议梗概
          </button>
        )}
      </details>
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
      {missing.length > 0 && rows.length > 0 && (
        <div className="notice warning">
          未分配原文：{missing.map((p) => p.number).join("、")}{" "}
          段。不会删除原文或阻止已确认情节制作。
          <button
            onClick={() =>
              save(
                [
                  ...rows,
                  ...missing.map((p) => ({
                    id: freshId(),
                    title: "待整理原文 · 段落 " + p.number,
                    start_paragraph: p.number,
                    end_paragraph: p.number,
                    review: "候选",
                    required_assets: [],
                  })),
                ].sort((a, b) => a.start_paragraph - b.start_paragraph),
              )
            }
          >
            为未分配原文补建卡片
          </button>
        </div>
      )}
      <div className={"source-layout " + (!showSource ? "source-hidden" : "")}>
        {showSource && (
          <section className="source-paper">
            <header>
              <h2>原文对照</h2>
              <small>只读 · 原文件已保留</small>
            </header>
            <div className="chapter-stack" aria-label="章节卡片">
              {s.segments.map((ch, i) => (
                <div
                  key={ch.id}
                  className={
                    "chapter-tab " + (ch.id === s.segment ? "active" : "")
                  }
                >
                  <button
                    title={ch.name}
                    onClick={() => {
                      if (
                        dirty.current &&
                        !window.confirm("放弃未保存编辑并切章？")
                      )
                        return;
                      run("select", { segment: ch.id });
                    }}
                  >
                    {i + 1} · {ch.name}
                  </button>
                  <button
                    aria-label={"删除章节 " + ch.name}
                    disabled={s.busy}
                    onClick={() => {
                      if (
                        window.confirm(
                          "归档此章节卡？原文、资产和历史保留，可恢复。",
                        )
                      )
                        run("chapter_action", { id: ch.id });
                    }}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
            <div className="paragraph-list" ref={sourceRef}>
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
              查看解析任务
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
                <button
                  className="primary"
                  disabled={s.busy || !s.asset_ready}
                  onClick={analyze}
                >
                  分析此片段
                </button>
              }
            />
          ) : (
            <div className="scene-grid">
              {rows.map((row, i) => (
                <article
                  className={"scene-card " + (selected === i ? "selected" : "")}
                  key={row.id || i}
                  tabIndex={0}
                  aria-label={"情节：" + row.title}
                  aria-selected={selected === i}
                  onClick={(e) => {
                    if (
                      !e.target.closest("button,input,textarea,select,label")
                    ) {
                      setSelected(i);
                      if (s.scenes.some((r) => r.id === row.id))
                        run("select", { scene: row.id });
                    }
                  }}
                  onKeyDown={(e) => {
                    if (
                      e.target === e.currentTarget &&
                      (e.key === "Enter" || e.key === " ")
                    ) {
                      e.preventDefault();
                      setSelected(i);
                    }
                  }}
                >
                  <div className="card-meta">
                    <span>
                      情节 {String(i + 1).padStart(2, "0")} · 段落{" "}
                      {row.start_paragraph}—{row.end_paragraph}
                    </span>
                    <button
                      className="badge"
                      disabled={s.busy || edit !== null || !!error}
                      title="点击切换候选／确认状态"
                      onClick={() =>
                        review(
                          [row.id],
                          row.review === "已确认" ? "候选" : "已确认",
                        )
                      }
                    >
                      {row.review === "已确认" ? "已确认" : "候选"}
                    </button>
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
                          onClick={async () => {
                            const next = copy(rows);
                            next[i] = { ...editData, review: "候选" };
                            if (await save(next)) setEdit(null);
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
                      {row.match_ambiguities?.length > 0 && (
                        <p className="notice warning">
                          同名或别名冲突，需人工关联：
                          {row.match_ambiguities.join("、")}
                        </p>
                      )}
                      {row.association_note && (
                        <p className="notice warning">{row.association_note}</p>
                      )}
                      <div className="plot-assets">
                        <small>关联资产（关联不等于实际出镜）</small>
                        {(row.required_assets || []).map((a, n) => {
                          const asset = s.assets.find(
                            (v) => v.id === a.asset_id,
                          );
                          const selection =
                            s.scene_variant_choices_all?.[row.id]?.[
                              asset?.id
                            ] || "auto";
                          const effective =
                            selection === "auto"
                              ? asset?.effective
                              : selection === "base"
                                ? asset
                                : asset?.variants?.find(
                                    (v) => v.id === selection,
                                  );
                          return (
                            <div className="plot-asset-row" key={n}>
                              {effective?.thumbnail && (
                                <img src={effective.thumbnail} alt="" />
                              )}
                              <button
                                onClick={() =>
                                  asset
                                    ? setAssetEdit(asset)
                                    : notify("资产缺失，请补建")
                                }
                              >
                                {a.name}
                              </button>
                              {asset && (
                                <select
                                  aria-label={"情节副卡 " + a.name}
                                  value={
                                    s.scene_variant_choices_all?.[row.id]?.[
                                      asset.id
                                    ] || "auto"
                                  }
                                  onChange={(e) =>
                                    run("select_variant", {
                                      id: asset.id,
                                      variant: e.target.value,
                                      scene: row.id,
                                    })
                                  }
                                >
                                  <option value="auto">跟随本章</option>
                                  <option value="base">主卡</option>
                                  {(asset.variants || []).map((v) => (
                                    <option key={v.id} value={v.id}>
                                      {v.title}
                                    </option>
                                  ))}
                                </select>
                              )}
                              <button
                                disabled={
                                  !s.scenes.some((v) => v.id === row.id)
                                }
                                onClick={() =>
                                  run("scene_assets_edit", {
                                    scene: row.id,
                                    id: a.asset_id,
                                    slot: a.slot,
                                    action: "remove",
                                  })
                                }
                              >
                                移除关联
                              </button>
                            </div>
                          );
                        })}
                        {s.scenes.some((v) => v.id === row.id) ? (
                          <div className="actions">
                            <select
                              aria-label="新增资产关联"
                              value=""
                              onChange={(e) =>
                                e.target.value &&
                                run("scene_assets_edit", {
                                  scene: row.id,
                                  id: e.target.value,
                                  action: "add",
                                })
                              }
                            >
                              <option value="">关联已有资产…</option>
                              {s.assets
                                .filter(
                                  (a) =>
                                    !(row.required_assets || []).some(
                                      (r) => r.asset_id === a.id,
                                    ),
                                )
                                .map((a) => (
                                  <option key={a.id} value={a.id}>
                                    {a.name}
                                  </option>
                                ))}
                            </select>
                            <button
                              onClick={() =>
                                setAssetEdit({
                                  name: "",
                                  kind: "人物",
                                  description: "",
                                  source: "用户自定",
                                  review: "待确认",
                                  _linkScene: row.id,
                                })
                              }
                            >
                              新建并关联
                            </button>
                          </div>
                        ) : (
                          <p className="small muted">确认情节后可管理关联。</p>
                        )}
                      </div>
                    </>
                  )}
                  <div className="card-actions">
                    <button
                      className="quiet locate"
                      onClick={() => {
                        locate(i);
                      }}
                    >
                      <LocateFixed size={12} />
                      定位原文
                    </button>
                    <button
                      disabled={s.busy}
                      onClick={async () => {
                        if (
                          !window.confirm(
                            "删除此情节卡？原文、历史资产及图片保留，可撤销。",
                          )
                        )
                          return;
                        if (!(await save(rows.filter((_, j) => j !== i))))
                          return;
                        setSelected(
                          Math.max(0, Math.min(selected, rows.length - 2)),
                        );
                      }}
                    >
                      删除
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
                          review: "候选",
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
                              review: "候选",
                              title: row.title + " · 前段",
                              end_paragraph: boundary,
                            },
                            {
                              ...copy(row),
                              id: freshId(),
                              review: "候选",
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
                  {row.review === "已确认" && (
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
                  : `原文 ${covered.size} / ${s.paragraphs.length} 段已分配 · ${missing.length} 段未参与制作`}
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
