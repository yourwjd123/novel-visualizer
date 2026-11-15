import React, { useState, useEffect, useRef } from "react";
import {
  Expand,
  Plus,
  Check,
  Search,
  Download,
  X,
  ZoomIn,
  ZoomOut,
  RotateCcw,
} from "lucide-react";
import { useWorkspace } from "./context";
import { PageHeading, Empty } from "./App";
import ImageCard from "./components/ImageCard";
import { api } from "./api";

export default function ImagesPage() {
  const {
    s,
    run,
    notify,
    setAssetEdit,
    setModal,
    setLarge,
    openAI,
    openCompletion,
    navigate,
  } = useWorkspace();
  const [prompt, setPrompt] = useState(s.prompt || ""),
    [selected, setSelected] = useState(""),
    [editing, setEditing] = useState(false),
    [annotations, setAnnotations] = useState([]);
  const currentPrompt = useRef(prompt);
  currentPrompt.current = prompt;
  useEffect(() => {
    setPrompt(s.prompt || "");
    setSelected("");
  }, [s.scene]);
  useEffect(() => {
    if (!editing) setPrompt(s.prompt || "");
  }, [s.prompt]);
  const pictures = s.jobs
    .filter((j) => j.scene === s.scene && !j.asset)
    .flatMap((j) => (j.pictures || []).map((p) => ({ ...p, job: j })));
  const picture = pictures.find((p) => p.path === selected) || pictures[0];
  const scene = s.scenes.find((r) => r.id === s.scene);
  const chosen = s.results.some(
    (r) => r.scene === s.scene && r.job === picture?.job.id,
  );
  async function savePrompt() {
    const ok = await run("save_prompt", { text: prompt, annotations });
    if (ok) {
      setEditing(false);
      notify("本情节提示词已保存");
    }
    return ok;
  }
  if (!s.scene)
    return (
      <>
        <PageHeading
          title="场景插图"
          subtitle="把已确认情节和所需资产组合为画面。"
        />
        <Empty
          title="请先确认情节"
          text="原文拆分经用户确认后，选择一个情节开始制作插图。"
          action={
            <button className="primary" onClick={() => navigate("source")}>
              前往原文与情节
            </button>
          }
        />
      </>
    );
  return (
    <>
      <PageHeading
        title="场景插图"
        subtitle={
          scene?.title +
          " / 原文段落 " +
          scene?.start_paragraph +
          "—" +
          scene?.end_paragraph
        }
        actions={
          <>
            <button
              disabled={s.busy}
              onClick={() =>
                run("send", {
                  node: 2,
                  message: "根据当前情节与资产生成一个场景插图方案。",
                })
              }
            >
              生成插图方案
            </button>
            <button
              className="primary"
              disabled={s.busy}
              onClick={async () => {
                if (!prompt.trim()) {
                  setEditing(true);
                  notify("请填写本情节提示词，也可与 AI 讨论后手工确认。");
                  return;
                }
                await savePrompt();
                run("generate", { prompt });
              }}
            >
              生成新候选
            </button>
          </>
        }
      />
      <div className="shot-toolbar">
        <label className="inline-label">
          当前情节
          <select
            value={s.scene}
            disabled={s.busy}
            onChange={async (e) => {
              if (editing && !window.confirm("放弃未保存提示词并切换情节？"))
                return;
              await run("select", { scene: e.target.value });
            }}
          >
            {s.scenes.map((r) => (
              <option key={r.id} value={r.id}>
                {r.title}
              </option>
            ))}
          </select>
        </label>
        <button onClick={() => setEditing(!editing)}>
          {editing ? "收起提示词" : "查看 / 编辑提示词"}
        </button>
        <button
          className="quiet"
          disabled={s.busy}
          onClick={() =>
            run("send", {
              node: 3,
              message: "依据当前情节、资产和已确认方案生成可编辑的生图提示词。",
            })
          }
        >
          生成提示词
        </button>
      </div>
      {Object.entries(s.task_outputs || {})
        .filter(([node]) => ["2", "3", "4", "6"].includes(node))
        .map(([node, value]) => (
          <details
            className="task-result"
            key={node}
            open={value.status !== "已确认"}
          >
            <summary>
              {s.nodes[Number(node)]} · {value.status}
            </summary>
            <pre>{value.text}</pre>
            {node === "3" ? (
              <button
                onClick={() => {
                  if (
                    prompt.trim() &&
                    !window.confirm(
                      "将生成的提示词载入编辑器？尚未保存的内容将被替换。",
                    )
                  )
                    return;
                  setPrompt(value.text);
                  setEditing(true);
                }}
              >
                载入提示词编辑器
              </button>
            ) : (
              <button
                disabled={s.busy}
                onClick={() =>
                  run("apply_output", { node: Number(node), text: value.text })
                }
              >
                确认此结果
              </button>
            )}
          </details>
        ))}
      {annotations.length > 0 && (
        <p className="notice">提示词包含采纳的 AI 补全建议，保存前请核对。</p>
      )}
      {editing && (
        <section className="prompt-editor">
          <label>
            本情节最终提示词
            <textarea
              rows={5}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={async (e) => {
                e.preventDefault();
                for (const f of e.dataTransfer.files) {
                  if (/\.(txt|md)$/i.test(f.name)) {
                    const text = await f.text();
                    setPrompt((v) => v + "\n" + text);
                  } else
                    notify(
                      "提示词文本区支持 TXT / MD；图片请添加为资产参考图。",
                    );
                }
              }}
            />
          </label>
          <div className="actions">
            <button
              disabled={s.busy}
              onClick={() =>
                openCompletion(
                  { type: "prompt", id: s.scene, text: prompt },
                  ["text"],
                  (changes, original) => {
                    if (currentPrompt.current !== original.text) {
                      notify("提示词已变化，请重新补全，避免覆盖新编辑。");
                      return false;
                    }
                    const c = changes.find((c) => c.field === "text");
                    if (c) {
                      setPrompt(c.value);
                      setAnnotations((v) => [
                        ...v,
                        {
                          source: "AI建议",
                          reason: c.reason,
                          time: new Date().toISOString(),
                        },
                      ]);
                      setEditing(true);
                    }
                  },
                )
              }
            >
              AI补全
            </button>
            <button className="primary" onClick={savePrompt}>
              保存提示词
            </button>
            <button
              onClick={() => {
                setPrompt(s.prompt || "");
                setEditing(false);
              }}
            >
              取消
            </button>
          </div>
          <p className="muted small">
            生成时附带图片节点约束、关联资产设定与本情节状态，真实任务保留最终输入快照。
          </p>
        </section>
      )}
      <div className="shot-layout">
        <section className="shot-main">
          {picture ? (
            <div className="hero-image">
              <img src={picture.thumbnail} alt={scene?.title + "候选插图"} />
              <span className="picture-badge">
                {chosen ? "已选为成果" : "候选 · 待人工审核"}
              </span>
              <button
                className="image-expand icon"
                aria-label="查看原图"
                onClick={() =>
                  setLarge({ path: picture.path, title: scene?.title })
                }
              >
                <Expand size={17} />
              </button>
            </div>
          ) : (
            <Empty
              title="尚无本情节的候选插图"
              text="先确认资产和提示词，再使用独立图片连接生成。也可先讨论构图与画面方案。"
              action={
                <button
                  onClick={() =>
                    run("send", {
                      node: 2,
                      message: "生成当前情节的单个插图方案。",
                    })
                  }
                >
                  生成插图方案
                </button>
              }
            />
          )}
          {picture && (
            <>
              <div className="under-image">
                <span className="muted small">
                  {picture.job.created} ·{" "}
                  {picture.job.model || picture.job.kind}
                </span>
                <div className="actions">
                  <button
                    onClick={() =>
                      run("send", {
                        node: 6,
                        attachments: [picture.path],
                        message: "审核本张图片，给出有依据的单轮检查结果。",
                      })
                    }
                  >
                    审核本张图片
                  </button>
                  <button
                    className="primary"
                    onClick={async () => {
                      if (await run("choose_result", { path: picture.path })) {
                        notify("已选为本情节成果，旧图片文件仍保留");
                      }
                    }}
                  >
                    <Check size={14} />
                    {chosen ? "已选为成果" : "选为成果"}
                  </button>
                </div>
              </div>
              <div className="candidate-strip">
                {pictures.map((p, i) => (
                  <button
                    key={p.path}
                    className={p.path === picture.path ? "selected" : ""}
                    onClick={() => setSelected(p.path)}
                  >
                    <img src={p.thumbnail} alt={"候选 " + (i + 1)} />
                    <span>候选 {i + 1}</span>
                  </button>
                ))}
              </div>
              <label className="inline-label separated">
                将当前候选用作资产参考
                <select
                  defaultValue=""
                  onChange={(e) => {
                    if (e.target.value)
                      run("candidate_to_reference", {
                        path: picture.path,
                        asset: e.target.value,
                      });
                    e.target.value = "";
                  }}
                >
                  <option value="">选择资产…</option>
                  {s.assets.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
        </section>
        <aside className="shot-assets">
          <div className="section-heading">
            <h2>本画面引用的资产</h2>
            <button
              className="quiet small"
              onClick={() => setModal({ type: "links" })}
            >
              调整关联
            </button>
          </div>
          <div className="shot-ref-grid">
            {s.requirements.map((r, i) => {
              const a = s.assets.find((a) => a.id === r.asset_id);
              return (
                <div className="reference-card" key={r.slot || i}>
                  <button
                    className="reference-open quiet"
                    onClick={() =>
                      a
                        ? setAssetEdit(a)
                        : setAssetEdit({
                            name: r.name,
                            kind: r.kind,
                            description: "",
                            source: "用户自定",
                            review: "待确认",
                          })
                    }
                  >
                    {r.asset?.thumbnail ? (
                      <img src={r.asset.thumbnail} alt="" />
                    ) : (
                      <span className="reference-glyph">
                        {r.name.slice(0, 1)}
                      </span>
                    )}
                    <span>
                      <strong>{r.name}</strong>
                      <small>{r.problem || "已确认参考"}</small>
                    </span>
                    <span>›</span>
                  </button>
                  {a && (
                    <label>
                      此情节采用
                      <select
                        value={s.scene_variant_choices?.[a.id] || "auto"}
                        onChange={(e) =>
                          run("select_variant", {
                            id: a.id,
                            variant: e.target.value,
                            scene: s.scene,
                          })
                        }
                      >
                        <option value="auto">继承本章选择</option>
                        <option value="base">主卡</option>
                        {(a.variants || []).map((v) => (
                          <option key={v.id} value={v.id}>
                            {v.title}
                          </option>
                        ))}
                      </select>
                      <small>
                        {r.asset?.image
                          ? "参考图片＋文字（需接口支持及映射）"
                          : "仅文字设定"}
                      </small>
                    </label>
                  )}
                  {a && (
                    <button
                      className="quiet small state-link"
                      onClick={() => setModal({ type: "override", asset: a })}
                    >
                      {s.overrides?.[a.id]
                        ? "本情节状态：" + s.overrides[a.id].slice(0, 32)
                        : "设置本情节服装 / 状态"}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
          {(!s.requirements.length ||
            s.requirements.some((r) => r.problem)) && (
            <p className="notice warning">
              △ 存在缺失或待确认资产，可补充，也可在生成时确认后继续。
            </p>
          )}
          <div className="separated">
            <h3>视觉方案</h3>
            <p className="muted small prose">
              {prompt
                ? prompt.slice(0, 300)
                : "尚未填写提示词。可生成单轮方案、手工编辑，或通过 AI 补全提供建议。"}
            </p>
            <button className="quiet small" onClick={() => setEditing(true)}>
              编辑方案与提示词
            </button>
          </div>
          <div className="separated">
            <h3>原文依据</h3>
            <p className="muted small prose">{scene?.source_text}</p>
            <button className="quiet small" onClick={() => navigate("source")}>
              核对原文 ↗
            </button>
          </div>
        </aside>
      </div>
    </>
  );
}

export function ResultsPage() {
  const { s, run, notify, setLarge, navigate, setModal } = useWorkspace();
  const [selected, setSelected] = useState(new Set());
  return (
    <>
      <PageHeading
        title="成果集"
        subtitle="已选定插图按情节回链；原文、引用资产及生成快照保留在项目中。"
        actions={
          <button
            className="primary"
            onClick={async () => {
              const r = await run(
                "export_results",
                selected.size ? { selected: [...selected] } : {},
              );
              if (r) notify("成果已导出：" + r.path);
            }}
          >
            <Download size={14} />
            导出{selected.size ? "选中" : "全部"}成果
          </button>
        }
      />
      <div className="result-grid">
        {s.results.map((r) => (
          <ImageCard
            key={r.id}
            image={r.thumbnail}
            title={r.title}
            subtitle={r.selected}
            badge="已选定"
            selected={selected.has(r.id)}
            onSelect={() =>
              setSelected((prev) => {
                const next = new Set(prev);
                next.has(r.id) ? next.delete(r.id) : next.add(r.id);
                return next;
              })
            }
            onOpen={() => setLarge({ path: r.file, title: r.title })}
          >
            <footer>
              <button
                className="quiet"
                onClick={async () => {
                  if (await run("select", { scene: r.scene }))
                    navigate("images");
                }}
              >
                返回情节
              </button>
              <button
                className="quiet"
                onClick={() => run("reveal", { path: r.file })}
              >
                打开原文件
              </button>
            </footer>
          </ImageCard>
        ))}
      </div>
      {!s.results.length && (
        <Empty
          title="还没有选定插图"
          text="在“场景插图”中审核候选，并选为该情节的正式成果。"
          action={
            <button onClick={() => navigate("images")}>前往场景插图</button>
          }
        />
      )}
    </>
  );
}

export function ImageViewer({ image, onClose }) {
  const { notify } = useWorkspace();
  const [src, setSrc] = useState(image.thumbnail || ""),
    [scale, setScale] = useState(1),
    [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef(null);
  useEffect(() => {
    let active = true;
    api("image", { path: image.path })
      .then((value) => {
        if (active) setSrc(value);
      })
      .catch((e) => notify(e.message));
    const key = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", key);
    return () => {
      active = false;
      window.removeEventListener("keydown", key);
    };
  }, [image.path]);
  return (
    <div
      className="image-viewer"
      role="dialog"
      aria-modal="true"
      aria-label="图片大图查看"
    >
      <header>
        <h2>{image.title}</h2>
        <div className="actions">
          <button
            className="icon"
            aria-label="缩小"
            onClick={() => setScale(Math.max(0.25, scale / 1.2))}
          >
            <ZoomOut size={17} />
          </button>
          <span>{Math.round(scale * 100)}%</span>
          <button
            className="icon"
            aria-label="放大"
            onClick={() => setScale(Math.min(6, scale * 1.2))}
          >
            <ZoomIn size={17} />
          </button>
          <button
            onClick={() => {
              setScale(1);
              setOffset({ x: 0, y: 0 });
            }}
          >
            <RotateCcw size={14} />
            复位
          </button>
          <button className="icon" aria-label="关闭大图" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
      </header>
      <div
        className="image-canvas"
        onWheel={(e) =>
          setScale((v) =>
            Math.min(6, Math.max(0.25, v * Math.exp(-e.deltaY * 0.001))),
          )
        }
        onPointerDown={(e) => {
          drag.current = { x: e.clientX - offset.x, y: e.clientY - offset.y };
          e.currentTarget.setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (drag.current)
            setOffset({
              x: e.clientX - drag.current.x,
              y: e.clientY - drag.current.y,
            });
        }}
        onPointerUp={() => (drag.current = null)}
      >
        {src ? (
          <img
            draggable="false"
            src={src}
            alt={image.title}
            style={{
              transform: `translate(${offset.x}px,${offset.y}px) scale(${scale})`,
            }}
          />
        ) : (
          <p>正在读取原图…</p>
        )}
      </div>
    </div>
  );
}
