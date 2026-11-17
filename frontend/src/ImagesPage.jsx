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
    }
  }
  return (
    <>
      <PageHeading
        title="成果集"
        subtitle="已选定插图按情节回链；原文、引用资产及生成快照保留在项目中。"
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
              <button onClick={() => setEditing(r)}>编辑</button>
              <button className="danger" onClick={() => remove([r.id])}>
                删除
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
          </ImageCard>
        ))}
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
