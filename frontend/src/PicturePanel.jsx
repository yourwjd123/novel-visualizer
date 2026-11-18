import React, { useEffect, useState } from "react";
import { Expand } from "lucide-react";
import { useWorkspace } from "./context";
import { DropZone } from "./App";
export default function PicturePanel({ asset = null }) {
  const { s, run, setLarge, uploadFiles } = useWorkspace();
  const pictures = s.jobs
    .filter((j) =>
      asset ? j.asset === asset : j.scene === s.scene && !j.asset,
    )
    .flatMap((j) => (j.pictures || []).map((p) => ({ ...p, job: j })));
  const visible = pictures.filter((p) => !p.hidden),
    [selected, setSelected] = useState(""),
    [checked, setChecked] = useState(new Set());
  const current = visible.find((p) => p.path === selected) || visible.at(-1);
  const results = s.results.filter((r) => r.scene === s.scene);
  const result =
    current && results.find((r) => (r.source_path || r.file) === current.path);
  useEffect(() => {
    setSelected("");
    setChecked(new Set());
  }, [asset, s.scene]);
  const upload = (files) => uploadFiles(files, "scene_image");
  return (
    <aside
      className="render-output-pane"
      aria-label={asset ? "资产图候选预览" : "插图候选预览"}
      onDragOver={(e) => {
        if (!asset) e.preventDefault();
      }}
      onDrop={(e) => {
        if (!asset && !e.target.closest(".drop-zone")) {
          e.preventDefault();
          upload(Array.from(e.dataTransfer.files));
        }
      }}
    >
      <div className="section-heading">
        <h2>{asset ? "参考图候选" : "插图预览"}</h2>
        <span className="badge">{visible.length} 张</span>
      </div>
      <div className="render-main-image">
        {current ? (
          <button
            className="quiet"
            aria-label="放大当前候选"
            onClick={() =>
              setLarge({
                images: visible.map((p) => ({
                  path: p.path,
                  title: p.job.original_name || "插图候选",
                })),
                index: visible.findIndex((p) => p.path === current.path),
                title: current.job.original_name || "插图候选",
              })
            }
          >
            <img src={current.thumbnail} alt="当前图片候选" />
            <Expand size={18} />
          </button>
        ) : (
          <div className="empty-preview">
            {asset ? "生成参考图后在此查看" : "尚无插图，可生成或拖入外部图片"}
          </div>
        )}
      </div>
      <div className="render-candidate-strip">
        {visible.map((p, i) => (
          <div className="candidate-tile" key={p.path}>
            <button
              aria-label={"选择候选 " + (i + 1)}
              className={current?.path === p.path ? "selected" : ""}
              key={p.path}
              onClick={() => setSelected(p.path)}
            >
              <img src={p.thumbnail} alt="" />
              {!asset &&
                results.some((r) => (r.source_path || r.file) === p.path) && (
                  <span>已选成果</span>
                )}
              {asset && <span>候选 {i + 1}</span>}
            </button>
            {!asset && (
              <label className="candidate-check">
                <input
                  type="checkbox"
                  aria-label={"勾选候选 " + (i + 1)}
                  checked={checked.has(p.path)}
                  onChange={() =>
                    setChecked((old) => {
                      const next = new Set(old);
                      next.has(p.path) ? next.delete(p.path) : next.add(p.path);
                      return next;
                    })
                  }
                />
              </label>
            )}
          </div>
        ))}
      </div>
      {!asset && !!checked.size && (
        <div className="actions">
          <span>已勾选 {checked.size} 张</span>
          <button
            onClick={() => setChecked(new Set(visible.map((p) => p.path)))}
          >
            全选候选
          </button>
          <button
            disabled={s.busy}
            onClick={async () => {
              if (await run("choose_results", { paths: [...checked] }))
                setChecked(new Set());
            }}
          >
            批量选为成果
          </button>
          <button
            disabled={s.busy}
            onClick={async () => {
              if (
                await run("choose_results", {
                  paths: [...checked],
                  selected: false,
                })
              )
                setChecked(new Set());
            }}
          >
            批量取消选定
          </button>
          <button onClick={() => setChecked(new Set())}>取消勾选</button>
        </div>
      )}
      <div className="actions">
        {!asset && (
          <DropZone
            compact
            accept=".png,.jpg,.jpeg,.webp"
            label="导入图片"
            onFiles={upload}
          />
        )}
        {current && (
          <>
            <button
              className="primary"
              disabled={s.busy}
              onClick={() =>
                run(
                  asset ? "candidate_to_reference" : "choose_results",
                  asset
                    ? {
                        asset,
                        path: current.path,
                        variant: s.assets.find((a) => a.id === asset)?.effective
                          ?.selected_variant?.id,
                      }
                    : { paths: [current.path], selected: !result },
                )
              }
            >
              {asset ? "采用为参考图" : result ? "取消选为成果" : "选为成果"}
            </button>
            {!asset && (
              <button
                disabled={s.busy}
                onClick={() => run("scene_candidate", { path: current.path })}
              >
                移除候选
              </button>
            )}
          </>
        )}
      </div>
      {pictures.some((p) => p.hidden) && !asset && (
        <details>
          <summary>已移除候选</summary>
          {pictures
            .filter((p) => p.hidden)
            .map((p) => (
              <p key={p.path}>
                {p.job.original_name || "候选图片"}
                <button
                  onClick={() =>
                    run("scene_candidate", { path: p.path, restore: true })
                  }
                >
                  恢复候选
                </button>
              </p>
            ))}
        </details>
      )}
    </aside>
  );
}
