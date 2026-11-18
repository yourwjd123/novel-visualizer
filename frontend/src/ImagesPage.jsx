import React, { useState, useEffect, useRef } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Maximize2,
  Minimize2,
  Expand,
  Plus,
  Check,
  Search,
  Download,
  X,
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { useWorkspace } from "./context";
import { PageHeading, Empty, DropZone } from "./App";
import ImageCard from "./components/ImageCard";
import { api } from "./api";

import { RenderEditor } from "./RenderWorkspace";
export default function ImagesPage() {
  const { s, run, setAssetEdit, dirty, navigate } = useWorkspace();
  const scene = s.scenes.find((v) => v.id === s.scene);
  const change = async (data) => {
    if (!dirty.current || window.confirm("放弃未保存方案并切换情节？")) {
      dirty.current = false;
      await run("select", data);
    }
  };
  return (
    <div className="scene-workspace">
      <div className="compact-page-heading">
        <h1>场景插图</h1>
        <label>
          章节
          <select
            aria-label="制图章节"
            value={s.segment || ""}
            disabled={s.busy}
            onChange={(e) => change({ segment: e.target.value })}
          >
            {s.segments.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          情节
          <select
            className="scene-selector"
            aria-label="制图情节"
            value={s.scene || ""}
            disabled={s.busy}
            onChange={(e) => change({ scene: e.target.value })}
          >
            {s.scenes.map((v) => (
              <option key={v.id} value={v.id}>
                {v.title}
              </option>
            ))}
          </select>
        </label>
      </div>
      {!scene ? (
        <Empty
          title="请先确认情节"
          text="从原文与情节选择一个已确认的情节。"
          action={<button onClick={() => navigate("source")}>前往情节</button>}
        />
      ) : (
        <>
          <details className="scene-source-summary">
            <summary>情节摘要与原文依据</summary>
            <p>{scene.summary}</p>
            <pre>
              {scene.source_text ||
                scene.source_snapshot ||
                "请在原文与情节中定位原文查看。"}
            </pre>
          </details>
          <RenderEditor
            key={s.scene}
            referencesRenderer={(state) => (
              <SceneReferences state={state} setAssetEdit={setAssetEdit} />
            )}
          />
        </>
      )}
    </div>
  );
}
function SceneReferences({ state, setAssetEdit }) {
  const { s, run } = useWorkspace();
  return (
    <section className="scene-references">
      <div className="section-heading">
        <h3>关联资产与参考图</h3>
        <span className="muted small">
          {state.references.length} 张实际参考图
        </span>
      </div>
      <div className="scene-reference-strip">
        {s.requirements.map((r, i) => {
          const main = s.assets.find((a) => a.id === r.asset_id),
            ref = state.references.find(
              (f) => f.asset_id === r.asset_id || f.name === r.name,
            ),
            included = !(s.cast_omissions || []).includes(r.asset_id);
          return (
            <section
              key={r.slot || i}
              className={"reference-card " + (!included ? "omitted" : "")}
            >
              <button
                className="reference-open quiet"
                onClick={() => main && setAssetEdit(main)}
              >
                {(ref?.thumbnail || r.asset?.thumbnail) && (
                  <img src={ref?.thumbnail || r.asset.thumbnail} alt="" />
                )}
                <span>
                  {r.name}
                  <small>
                    {r.problem ||
                      (!included
                        ? "不参与本图"
                        : ref
                          ? "参考图" + ref.number
                          : "文字参与")}{" "}
                    · {r.asset?.selected_variant?.title || "主卡"}
                  </small>
                </span>
              </button>
              {r.asset_id && (
                <>
                  <label className="check-row">
                    <input
                      type="checkbox"
                      checked={included}
                      disabled={s.busy}
                      onChange={(e) =>
                        run("scene_cast", {
                          asset: r.asset_id,
                          included: e.target.checked,
                        })
                      }
                    />
                    本图出镜
                  </label>
                  <select
                    aria-label={r.name + "的状态"}
                    disabled={s.busy}
                    value={s.scene_variant_choices?.[r.asset_id] || "auto"}
                    onChange={(e) =>
                      run("select_variant", {
                        id: r.asset_id,
                        variant: e.target.value,
                        scene: s.scene,
                      })
                    }
                  >
                    <option value="auto">继承本章</option>
                    <option value="base">主卡</option>
                    {(main?.variants || []).map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.title}
                      </option>
                    ))}
                  </select>
                </>
              )}
            </section>
          );
        })}
      </div>
      {!s.requirements.length && (
        <p className="muted">尚无关联资产，可在情节卡中建立关联。</p>
      )}
    </section>
  );
}

export function ResultsPage() {
  const { s, run, notify, setLarge, navigate, setModal } = useWorkspace();
  const [selected, setSelected] = useState(new Set()),
    [editing, setEditing] = useState(null),
    [trash, setTrash] = useState([]);
  useEffect(() => {
    api("result_trash")
      .then(setTrash)
      .catch((e) => notify(e.message));
  }, [JSON.stringify(s.results)]);
  async function remove(ids) {
    if (
      !window.confirm(
        "从成果集中移除所选图片？原图、资产和任务历史保留，可恢复。",
      )
    )
      return;
    if (await run("results_delete", { ids })) {
      setSelected(new Set());
      notify("成果已移入已删除列表");
      return true;
    }
    return false;
  }
  const groups = [];
  for (const result of s.results) {
    let group = groups.find((g) => g.scene === result.scene);
    if (!group) {
      group = { scene: result.scene, items: [] };
      groups.push(group);
    }
    group.items.push(result);
  }
  function openGroup(group) {
    setLarge({
      title: group.items[0].scene_title || group.items[0].title,
      images: group.items.map((r) => ({ ...r, path: r.file, result: r })),
      onEdit: (item) => setEditing(item.result),
      onDelete: (item) => remove([item.result.id]),
    });
  }
  return (
    <>
      <PageHeading
        title="成果集"
        subtitle="整本小说成果同页展示，按章节与情节排序；点击卡片翻看同一情节的全部成果。"
        actions={
          <>
            <button
              disabled={!selected.size}
              onClick={() => remove([...selected])}
            >
              <Trash2 size={14} />
              批量删除
            </button>
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
          </>
        }
      />
      <div className="result-grid">
        {groups.map((group) => {
          const r = group.items[0],
            ids = group.items.map((v) => v.id);
          return (
            <ImageCard
              key={group.scene}
              image={r.thumbnail}
              title={r.title}
              subtitle={r.chapter_name}
              badge={"已选定 · " + ids.length + " 张"}
              selected={ids.every((id) => selected.has(id))}
              onSelect={() =>
                setSelected((old) => {
                  const next = new Set(old);
                  if (ids.every((id) => next.has(id)))
                    ids.forEach((id) => next.delete(id));
                  else ids.forEach((id) => next.add(id));
                  return next;
                })
              }
              onOpen={() => openGroup(group)}
            >
              <footer>
                <button onClick={() => setEditing(r)}>编辑</button>
                <button className="danger" onClick={() => remove(ids)}>
                  {ids.length > 1 ? "删除本组" : "删除"}
                </button>
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
              {ids.length > 1 && (
                <small className="muted">
                  点击图片翻页，可编辑或删除其中一张。
                </small>
              )}
            </ImageCard>
          );
        })}
      </div>
      {!!trash.length && (
        <details>
          <summary>已删除成果</summary>
          {trash.map((r) => (
            <p key={r.id}>
              {r.title}
              <button
                onClick={() =>
                  run("results_delete", { ids: [r.id], restore: true })
                }
              >
                恢复成果
              </button>
            </p>
          ))}
        </details>
      )}
      {editing && (
        <ResultEditor
          key={editing.id}
          result={editing}
          onClose={() => setEditing(null)}
        />
      )}
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

function ResultEditor({ result, onClose }) {
  const { s, run, notify, uploadFiles, dirty } = useWorkspace();
  const [form, setForm] = useState({ ...result }),
    [scenes, setScenes] = useState([]);
  const [chapter, setChapter] = useState(result.segment);
  const live = s.results.find((r) => r.id === result.id) || result;
  useEffect(() => {
    api("result_scenes")
      .then(setScenes)
      .catch((e) => notify(e.message));
  }, []);
  function set(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
    dirty.current = true;
  }
  function close() {
    if (!dirty.current || window.confirm("放弃未保存的成果编辑？")) {
      dirty.current = false;
      onClose();
    }
  }
  return (
    <div className="modal-shade">
      <section className="modal" role="dialog" aria-label="编辑成果">
        <div className="modal-heading">
          <h2>编辑成果</h2>
          <button
            className="icon quiet"
            aria-label="关闭成果编辑"
            onClick={close}
          >
            <X size={18} />
          </button>
        </div>
        <label>
          标题
          <input
            aria-label="成果标题"
            value={form.title}
            onChange={(e) => set("title", e.target.value)}
          />
        </label>
        <label>
          所属章节
          <select
            aria-label="成果所属章节"
            value={chapter}
            onChange={(e) => {
              setChapter(e.target.value);
              set("scene", "");
            }}
          >
            {s.segments.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          关联情节
          <select
            aria-label="成果关联情节"
            value={form.scene}
            onChange={(e) => set("scene", e.target.value)}
          >
            <option value="">请选择情节</option>
            {scenes
              .filter((v) => v.segment === chapter)
              .map((v) => (
                <option key={v.id} value={v.id}>
                  {v.title}
                </option>
              ))}
          </select>
        </label>
        <label>
          说明
          <textarea
            aria-label="成果说明"
            rows={3}
            value={form.description || ""}
            onChange={(e) => set("description", e.target.value)}
          />
        </label>
        {live.thumbnail && (
          <img
            className="result-edit-image"
            src={live.thumbnail}
            alt={live.title}
          />
        )}
        <DropZone
          compact
          accept=".png,.jpg,.jpeg,.webp"
          label="替换成果图片（原图保留）"
          onFiles={async (files) => {
            if (
              files[0] &&
              (await uploadFiles([files[0]], "result_image", result.id))
            )
              notify("图片已替换；标题、说明或关联修改仍需保存。");
          }}
        />
        <div className="actions">
          <button onClick={close}>取消</button>
          <button
            className="primary"
            disabled={!form.scene || !form.title.trim()}
            onClick={async () => {
              if (await run("result_edit", form)) {
                dirty.current = false;
                onClose();
              }
            }}
          >
            保存成果修改
          </button>
        </div>
      </section>
    </div>
  );
}

export function ImageViewer({ image, onClose }) {
  const { notify } = useWorkspace();
  const items = image.images?.length ? image.images : [image];
  const [index, setIndex] = useState(
      Math.max(0, Math.min(image.index || 0, items.length - 1)),
    ),
    [src, setSrc] = useState(""),
    [failed, setFailed] = useState(false),
    [scale, setScale] = useState(1),
    [offset, setOffset] = useState({ x: 0, y: 0 }),
    [fullscreen, setFullscreen] = useState(false);
  const drag = useRef(null),
    full = useRef(false);
  const item = items[index];
  async function toggleFull(enabled) {
    full.current = enabled;
    setFullscreen(enabled);
    try {
      const result = await api("viewer_fullscreen", { enabled });
      full.current = !!result.fullscreen;
      setFullscreen(!!result.fullscreen);
    } catch (e) {
      full.current = !enabled;
      setFullscreen(!enabled);
      notify(e.message);
    }
  }
  async function close() {
    if (full.current) await toggleFull(false);
    onClose();
  }
  function turn(delta) {
    const next = index + delta;
    if (next < 0 || next >= items.length) return;
    setIndex(next);
    image.onIndexChange?.(next);
  }
  useEffect(
    () => () => {
      if (full.current) {
        full.current = false;
        api("viewer_fullscreen", { enabled: false }).catch(() => {});
      }
    },
    [],
  );
  useEffect(() => {
    let alive = true;
    setSrc("");
    setFailed(false);
    setScale(1);
    setOffset({ x: 0, y: 0 });
    drag.current = null;
    api("image", { path: item.path })
      .then((v) => {
        if (alive) {
          setSrc(v);
          setFailed(!v);
        }
      })
      .catch((e) => {
        if (alive) setFailed(true);
        notify(e.message);
      });
    return () => {
      alive = false;
    };
  }, [item.path]);
  useEffect(() => {
    const key = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopImmediatePropagation();
        if (full.current) toggleFull(false);
        else close();
      } else if (
        ["ArrowLeft", "ArrowRight"].includes(e.key) &&
        !e.target.closest("input,textarea,select")
      ) {
        e.preventDefault();
        e.stopImmediatePropagation();
        turn(e.key === "ArrowRight" ? 1 : -1);
      }
    };
    window.addEventListener("keydown", key, true);
    return () => window.removeEventListener("keydown", key, true);
  }, [index, items.length]);
  return (
    <div
      className={"image-viewer" + (fullscreen ? " fullscreen" : "")}
      role="dialog"
      aria-modal="true"
      aria-label="图片大图查看"
    >
      <header>
        <h2>
          {image.title}
          {item.title && item.title !== image.title ? " · " + item.title : ""}
          {items.length > 1 && (
            <small>
              {" "}
              · {index + 1} / {items.length}
            </small>
          )}
        </h2>
        <div className="actions">
          {image.onEdit && (
            <button
              onClick={async () => {
                await close();
                image.onEdit(item);
              }}
            >
              编辑当前成果
            </button>
          )}
          {image.onDelete && (
            <button
              className="danger"
              onClick={async () => {
                if (await image.onDelete(item)) close();
              }}
            >
              删除当前成果
            </button>
          )}
          <button
            className="icon"
            aria-label="缩小"
            onClick={() => setScale((v) => Math.max(0.25, v / 1.2))}
          >
            <ZoomOut size={17} />
          </button>
          <span>{Math.round(scale * 100)}%</span>
          <button
            className="icon"
            aria-label="放大"
            onClick={() => setScale((v) => Math.min(6, v * 1.2))}
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
          <button
            className="icon"
            aria-label={fullscreen ? "退出全屏" : "全屏查看"}
            title={fullscreen ? "退出全屏（Esc）" : "全屏查看"}
            onClick={() => toggleFull(!full.current)}
          >
            {fullscreen ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
          </button>
          <button className="icon" aria-label="关闭大图" onClick={close}>
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
          if (e.target.closest("button")) return;
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
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
      >
        {items.length > 1 && (
          <button
            className="viewer-arrow previous"
            aria-label="上一张图片"
            disabled={index === 0}
            onClick={() => turn(-1)}
          >
            <ChevronLeft size={30} />
          </button>
        )}
        {src ? (
          <img
            draggable={false}
            src={src}
            alt={item.title || image.title}
            onError={() => {
              setFailed(true);
              setSrc("");
            }}
            style={{
              transform: `translate(${offset.x}px,${offset.y}px) scale(${scale})`,
            }}
          />
        ) : (
          <p>{failed ? "图片无法读取，请检查原文件。" : "正在读取原图…"}</p>
        )}
        {items.length > 1 && (
          <button
            className="viewer-arrow next"
            aria-label="下一张图片"
            disabled={index === items.length - 1}
            onClick={() => turn(1)}
          >
            <ChevronRight size={30} />
          </button>
        )}
      </div>
    </div>
  );
}
