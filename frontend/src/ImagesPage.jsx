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

import { RenderEditor } from "./RenderWorkspace";
export default function ImagesPage() {
  const { s, run, navigate, setAssetEdit, setLarge, dirty } = useWorkspace();
  const scene = s.scenes.find((v) => v.id === s.scene);
  if (!scene)
    return (
      <>
        <PageHeading title="场景插图" />
        <Empty
          title="请先确认情节"
          text="从原文与情节选择一个情节。"
          action={<button onClick={() => navigate("source")}>前往情节</button>}
        />
      </>
    );
  const pictures = s.jobs
    .filter((j) => j.scene === s.scene && !j.asset)
    .flatMap((j) => (j.pictures || []).map((p) => ({ ...p, job: j })));
  return (
    <>
      <PageHeading title="场景插图" subtitle={scene.title} />
      <label>
        当前情节
        <select
          className="scene-selector"
          value={s.scene}
          onChange={(e) => {
            if (
              !dirty.current ||
              window.confirm("放弃未保存方案并切换情节？")
            ) {
              dirty.current = false;
              run("select", { scene: e.target.value });
            }
          }}
        >
          {s.scenes.map((v) => (
            <option key={v.id} value={v.id}>
              {v.title}
            </option>
          ))}
        </select>
      </label>
      <RenderEditor key={s.scene} />
      <h2>情节关联与实际出镜</h2>
      <div className="shot-ref-grid">
        {s.requirements.map((r, i) => (
          <section className="reference-card" key={r.slot || i}>
            <button
              className="quiet"
              onClick={() => {
                const asset = s.assets.find((a) => a.id === r.asset_id);
                if (asset) setAssetEdit(asset);
              }}
            >
              {r.asset?.thumbnail && <img src={r.asset.thumbnail} alt="" />}
              {r.name}
            </button>
            <small>
              {r.problem || "档案可用"} ·{" "}
              {r.asset?.selected_variant?.title || "主卡"}
            </small>
            {r.asset_id && (
              <>
                <label>
                  <input
                    type="checkbox"
                    checked={!(s.cast_omissions || []).includes(r.asset_id)}
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
                  {(
                    s.assets.find((a) => a.id === r.asset_id)?.variants || []
                  ).map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.title}
                    </option>
                  ))}
                </select>
              </>
            )}
          </section>
        ))}
      </div>
      <h2>插图候选</h2>
      <div className="result-grid">
        {pictures.map((p) => (
          <ImageCard
            key={p.path}
            image={p.thumbnail}
            title={scene.title}
            onOpen={() => setLarge({ path: p.path, title: scene.title })}
          >
            <button onClick={() => run("choose_result", { path: p.path })}>
              选为成果
            </button>
          </ImageCard>
        ))}
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
