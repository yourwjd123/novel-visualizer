import React from "react";
import { MoreHorizontal, ImagePlus } from "lucide-react";
import { useWorkspace } from "./context";
import ImageCard from "./components/ImageCard";
export default function AssetLibraryCard({
  asset: a,
  priority,
  firstAppearance,
  selected,
  onSelect,
  dragging,
  onDragStart,
  onDragEnd,
  onDrop,
  onOperation,
  onRestore,
}) {
  const { s, run, setAssetEdit, setLarge, openAssetRender } = useWorkspace();
  const isTarget = dragging && dragging.id !== a.id && dragging.kind === a.kind;
  const openLarge = () => {
    const images = [
      { path: a.image, title: "主卡" },
      ...(a.variants || [])
        .filter((v) => v.image)
        .map((v) => ({ path: v.image, title: v.title })),
    ].filter((i) => i.path);
    if (images.length) setLarge({ title: a.name, images });
    else setAssetEdit(a);
  };
  return (
    <div
      onClick={(e) => {
        if (
          e.target.closest(".image-info") &&
          !e.target.closest("button,input,select,summary,details")
        )
          setAssetEdit(a);
      }}
      data-asset-id={a.id}
      className={"asset-card-shell " + (isTarget ? "drop-eligible" : "")}
      draggable={!s.busy}
      onDragStart={(e) => {
        if (e.target.closest("input,select,summary,.asset-card-menu")) {
          e.preventDefault();
          return;
        }
        e.dataTransfer.setData("application/x-novel-asset", a.id);
        e.dataTransfer.effectAllowed = "move";
        onDragStart(a);
      }}
      onDragEnd={onDragEnd}
    >
      <ImageCard
        image={a.thumbnail}
        title={a.name}
        subtitle={a.description?.slice(0, 70) || "视觉设定待填写"}
        badge={a.image ? "主参考图" : "待补参考图"}
        selected={selected}
        onSelect={onSelect}
        onOpen={openLarge}
      >
        <div className="compact-asset-meta">
          <span className="badge">
            {a.kind} · {priority}
          </span>
          <select
            className="asset-status"
            aria-label={"资产状态 " + a.name}
            value={a.review || "待确认"}
            disabled={s.busy}
            onChange={(e) =>
              run("asset_review", { ids: [a.id], status: e.target.value })
            }
          >
            <option>待确认</option>
            <option>已确认</option>
            <option>已锁定</option>
          </select>
        </div>
        <div className="asset-state-row">
          <details className="asset-state-menu">
            <summary title="选择本章使用的主卡或副卡">
              当前：{a.effective?.selected_variant?.title || "主卡"}
            </summary>
            <select
              aria-label={"副卡选择 " + a.name}
              value={s.chapter_variant_choices?.[a.id] || "auto"}
              onChange={(e) =>
                run("select_variant", { id: a.id, variant: e.target.value })
              }
            >
              <option value="auto">自动</option>
              <option value="base">主卡</option>
              {(a.variants || []).map((v) => (
                <option key={v.id} value={v.id}>
                  {v.title}
                </option>
              ))}
            </select>
            <small>
              {a.effective?.selected_variant?.chapter
                ? "来源：" +
                  (s.segments.find(
                    (c) => c.id === a.effective.selected_variant.chapter,
                  )?.name || "其他章节")
                : "主卡设定"}
            </small>
          </details>
          <button className="quiet" onClick={() => setAssetEdit(a)}>
            副卡 {(a.variants || []).length}
          </button>
        </div>
        <button
          className="asset-render-shortcut icon"
          aria-label={"制作资产图 " + a.name}
          title="制作资产图"
          onClick={() => openAssetRender(a.id)}
        >
          <ImagePlus size={17} />
        </button>
        <details className="asset-card-menu">
          <summary aria-label={"管理资产 " + a.name}>
            <MoreHorizontal size={17} />
          </summary>
          <div>
            <button onClick={() => setAssetEdit(a)}>编辑档案</button>
            <button onClick={() => openAssetRender(a.id)}>制作资产图</button>
            <button
              disabled={s.busy}
              onClick={() => onOperation({ mode: "variant", source: a.id })}
            >
              归入其他主卡
            </button>
            <button
              disabled={s.busy}
              onClick={() => onOperation({ mode: "merge", source: a.id })}
            >
              合并到其他资产
            </button>
            <button onClick={() => onOperation({ mode: "history" })}>
              操作记录 / 恢复
            </button>
            {(a.variants || [])
              .filter((v) => v.origin_asset && v.operation_id)
              .map((v) => (
                <button key={v.id} onClick={() => onRestore(v.operation_id)}>
                  恢复“{v.title}”为独立资产
                </button>
              ))}
            <small>
              关联 {new Set(a.uses).size} 个情节 · {a.id.slice(-6)} ·{" "}
              {Number.isFinite(firstAppearance)
                ? "首现段落 " + firstAppearance
                : "出现位置待核对"}
            </small>
            <button
              className="danger"
              disabled={s.busy}
              onClick={() => {
                if (window.confirm("移入资产回收站？原图、原文和历史保留。"))
                  run("archive_asset", { id: a.id });
              }}
            >
              删除资产
            </button>
          </div>
        </details>
      </ImageCard>
      {isTarget && (
        <div
          className="asset-drop-zone"
          onDragOver={(e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
          }}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onDrop(a);
          }}
        >
          归入【{a.name}】的副卡
        </div>
      )}
    </div>
  );
}
