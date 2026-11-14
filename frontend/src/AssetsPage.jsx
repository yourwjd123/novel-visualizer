import React, { useState, useEffect } from "react";
import {
  Plus,
  Search,
  X,
  Check,
  ImagePlus,
  Trash2,
  RotateCcw,
} from "lucide-react";
import { useWorkspace, copy } from "./context";
import { PageHeading, Empty, DropZone } from "./App";
import ImageCard from "./components/ImageCard";
import { api } from "./api";

export default function AssetsPage() {
  const { s, run, notify, setAssetEdit, setLarge, openAI, withProject } =
    useWorkspace();
  const [filter, setFilter] = useState("全部"),
    [search, setSearch] = useState(""),
    [view, setView] = useState("records"),
    [gallery, setGallery] = useState([]),
    [trash, setTrash] = useState([]),
    [selected, setSelected] = useState(new Set());
  const stamp = s.assets.map((a) => a.id + ":" + a.revision).join("|");
  useEffect(() => {
    if (view === "gallery")
      api("gallery")
        .then(setGallery)
        .catch((e) => notify(e.message));
    if (view === "trash")
      api("trash")
        .then(setTrash)
        .catch((e) => notify(e.message));
  }, [stamp, view]);
  const rows = s.assets.filter(
    (a) =>
      (filter === "全部" || a.kind === filter) &&
      (a.name + " " + (a.aliases || []).join(" ")).includes(search),
  );
  const pictures = gallery.filter(
    (r) => (filter === "全部" || r.kind === filter) && r.name.includes(search),
  );
  return (
    <>
      <PageHeading
        title="视觉资产库"
        subtitle="人物、场景与道具，在本小说的各个片段中复用。"
        actions={
          <>
            <button disabled={!s.scene} onClick={() => openAI(1)}>
              解析当前情节资产
            </button>
            <button
              className="primary"
              onClick={() =>
                setAssetEdit({
                  name: "",
                  kind: "人物",
                  description: "",
                  source: "用户自定",
                  review: "待确认",
                })
              }
            >
              <Plus size={15} />
              新建资产
            </button>
          </>
        }
      />
      <div className="view-switch" role="group" aria-label="资产视图">
        {[
          ["records", "资产档案"],
          ["gallery", "参考图画廊"],
          ["trash", "回收站"],
        ].map(([id, label]) => (
          <button
            className={view === id ? "active" : ""}
            key={id}
            onClick={() => {
              setView(id);
              setSelected(new Set());
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="gallery-toolbar">
        {["全部", "人物", "场景", "道具"].map((kind) => (
          <button
            className={"filter-chip " + (filter === kind ? "active" : "")}
            key={kind}
            onClick={() => setFilter(kind)}
          >
            {kind}
            {kind === "全部" ? " · " + s.assets.length : ""}
          </button>
        ))}
        <div className="search-input">
          <Search size={14} />
          <input
            aria-label="搜索资产"
            placeholder="搜索名称、别名…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>
      {view === "records" ? (
        <>
          <div className="asset-grid">
            {rows.map((a) => (
              <ImageCard
                key={a.id}
                image={a.thumbnail}
                title={a.name}
                subtitle={a.description?.slice(0, 80) || "视觉设定待填写"}
                badge={a.image ? "主参考图" : "待补参考图"}
                onOpen={() => setAssetEdit(a)}
              >
                <div className="card-meta">
                  <span className="badge">{a.kind}</span>
                  <span
                    className={
                      "badge " + (a.review === "已确认" ? "ok" : "warning")
                    }
                  >
                    {a.review}
                  </span>
                </div>
                <footer>
                  <span>关联 {new Set(a.uses).size} 个情节</span>
                  <button className="quiet" onClick={() => setAssetEdit(a)}>
                    编辑档案 ↗
                  </button>
                </footer>
              </ImageCard>
            ))}
          </div>
          {!rows.length && (
            <Empty
              title="这里还没有视觉资产"
              text="可手工新建，也可对已确认情节发起资产解析。模型输出需审核后入库。"
            />
          )}
          <p className="footnote">
            资产稳定设定、情节状态和参考图分别保存；没有参考图也可以继续编辑。
          </p>
        </>
      ) : view === "gallery" ? (
        <>
          {selected.size > 0 && (
            <div className="selection-bar">
              <span>已选 {selected.size} 张参考图</span>
              <button
                onClick={async () => {
                  if (
                    !window.confirm(
                      "将选中图片移入回收站？图片文件保留，可恢复。",
                    )
                  )
                    return;
                  for (const key of selected) {
                    const item = pictures.find(
                      (r) => r.asset + "|" + r.path === key,
                    );
                    if (item)
                      await run("reference", {
                        id: item.asset,
                        path: item.path,
                        action: "trash",
                      });
                  }
                  setSelected(new Set());
                }}
              >
                移入回收站
              </button>
            </div>
          )}
          <div className="asset-grid">
            {pictures.map((r) => (
              <ImageCard
                key={r.asset + "|" + r.path}
                image={r.thumbnail}
                title={r.name}
                subtitle={r.source || "参考图片"}
                badge={r.primary ? "主参考图" : r.kind}
                selected={selected.has(r.asset + "|" + r.path)}
                onSelect={() =>
                  setSelected((prev) => {
                    const next = new Set(prev),
                      key = r.asset + "|" + r.path;
                    next.has(key) ? next.delete(key) : next.add(key);
                    return next;
                  })
                }
                onOpen={() => setLarge({ path: r.path, title: r.name })}
              >
                <footer>
                  <button
                    className="quiet"
                    onClick={() =>
                      run("reference", {
                        id: r.asset,
                        path: r.path,
                        action: "primary",
                      })
                    }
                  >
                    设为主参考
                  </button>
                  <button
                    className="quiet"
                    onClick={() =>
                      setAssetEdit(s.assets.find((a) => a.id === r.asset))
                    }
                  >
                    编辑档案
                  </button>
                </footer>
              </ImageCard>
            ))}
          </div>
          {!pictures.length && (
            <Empty
              title="参考图画廊为空"
              text="在资产档案中上传参考图，或使用独立图片连接生成；多张图片可对应同一档案。"
            />
          )}
        </>
      ) : (
        <>
          <p className="muted small">
            回收站中的图片保留在项目目录，不按固定期限自动永久删除。
          </p>
          <div className="asset-grid">
            {trash.map((t) => (
              <ImageCard
                key={t.id}
                title={
                  s.assets.find((a) => a.id === t.asset)?.name || "参考图片"
                }
                image={t.thumbnail}
                subtitle={"移入时间：" + t.deleted}
                onOpen={() =>
                  setLarge({ path: t.reference.path, title: "回收站图片" })
                }
              >
                <button
                  onClick={async () => {
                    if (await run("restore_reference", { id: t.id })) {
                      setTrash(await api("trash"));
                      notify("参考图已恢复");
                    }
                  }}
                >
                  <RotateCcw size={14} />
                  恢复
                </button>
              </ImageCard>
            ))}
          </div>
        </>
      )}
    </>
  );
}

export function AssetEditor({ asset, onClose }) {
  const { s, run, notify, uploadFiles, setLarge, openAI, dirty } =
    useWorkspace();
  const [form, setForm] = useState(copy(asset)),
    [refs, setRefs] = useState([]),
    [advanced, setAdvanced] = useState(false),
    [structure, setStructure] = useState(
      JSON.stringify(
        {
          attributes: asset.attributes || [],
          states: asset.states || [],
          evidence: asset.evidence || [],
          missing: asset.missing || [],
        },
        null,
        2,
      ),
    );
  const live = s.assets.find((a) => a.id === asset.id) || asset;
  useEffect(() => {
    if (asset.id)
      api("gallery")
        .then((rows) => setRefs(rows.filter((r) => r.asset === asset.id)))
        .catch((e) => notify(e.message));
  }, [live.revision]);
  function set(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
    dirty.current = true;
  }
  async function save() {
    let parsed;
    try {
      parsed = JSON.parse(structure);
      for (const key of ["attributes", "states", "evidence", "missing"])
        if (!Array.isArray(parsed[key])) throw new Error();
    } catch {
      notify(
        "结构化属性需为包含 attributes/states/evidence/missing 数组的 JSON",
      );
      return;
    }
    const r = await run("save_asset", { ...form, ...parsed });
    if (r) {
      dirty.current = false;
      notify("资产已保存；关联方案会标记待复核");
      onClose();
    }
  }
  const close = () => {
    if (!dirty.current || window.confirm("放弃未保存的资产编辑？")) {
      dirty.current = false;
      onClose();
    }
  };
  return (
    <aside className="asset-editor" aria-label="资产编辑详情">
      <div className="drawer-heading">
        <div>
          <span className="eyebrow">{form.kind}资产档案</span>
          <h2>{form.name || "新建资产"}</h2>
        </div>
        <button
          className="icon quiet"
          aria-label="关闭资产详情"
          onClick={close}
        >
          <X size={18} />
        </button>
      </div>
      {live.thumbnail && (
        <button
          className="detail-image-hit"
          onClick={() => setLarge({ path: live.image, title: live.name })}
        >
          <img className="detail-image" src={live.thumbnail} alt={live.name} />
        </button>
      )}
      <label>
        名称
        <input
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          maxLength={100}
        />
      </label>
      <div className="field-pair">
        <label>
          分类
          <select
            value={form.kind}
            onChange={(e) => set("kind", e.target.value)}
          >
            <option>人物</option>
            <option>场景</option>
            <option>道具</option>
          </select>
        </label>
        <label>
          审核
          <select
            value={form.review}
            onChange={(e) => set("review", e.target.value)}
          >
            <option>待确认</option>
            <option>已确认</option>
            <option>已锁定</option>
          </select>
        </label>
      </div>
      <label>
        视觉设定
        <textarea
          rows={5}
          value={form.description}
          onChange={(e) => set("description", e.target.value)}
          placeholder="记录外貌、服装、环境结构或道具特征；未知信息保持未知"
        />
      </label>
      <label>
        来源
        <select
          value={form.source}
          onChange={(e) => set("source", e.target.value)}
        >
          <option>用户自定</option>
          <option>原文明确</option>
          <option>AI 建议</option>
        </select>
      </label>
      <div className="section-heading separated">
        <h3>参考图与版本</h3>
        <span className="small muted">{refs.length} 张 · 无自动到期删除</span>
      </div>
      {asset.id ? (
        <>
          <DropZone
            compact
            accept=".png,.jpg,.jpeg,.webp"
            label="上传或拖入参考图"
            onFiles={(files) => uploadFiles(files, "reference", asset.id)}
          />
          <div className="reference-strip">
            {refs.map((r) => (
              <div key={r.path}>
                <button
                  className="image-hit"
                  onClick={() => setLarge({ path: r.path, title: live.name })}
                >
                  <img src={r.thumbnail} alt="参考图" />
                </button>
                <span className="small">
                  {r.primary ? "主参考图" : "历史参考"}
                </span>
                <div className="actions">
                  <button
                    className="icon quiet"
                    aria-label="设为主参考"
                    onClick={() =>
                      run("reference", {
                        id: asset.id,
                        path: r.path,
                        action: "primary",
                      })
                    }
                  >
                    <Check size={13} />
                  </button>
                  <button
                    className="icon quiet"
                    aria-label="移入回收站"
                    onClick={() =>
                      run("reference", {
                        id: asset.id,
                        path: r.path,
                        action: "trash",
                      })
                    }
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>
          <div className="actions">
            <button onClick={() => openAI(5, asset.id)}>讨论此资产</button>
            <button
              disabled={s.busy}
              onClick={async () => {
                if (!form.description.trim()) {
                  notify("请先填写资产描述");
                  return;
                }
                const text = window.prompt(
                  "确认本次参考图提示词（可修改）",
                  `为${form.name}制作${form.kind}参考图。${form.description}。保留明确特征，不增加未经确认的设定。`,
                );
                if (text) run("generate", { asset: asset.id, prompt: text });
              }}
            >
              <ImagePlus size={14} />
              生成参考图
            </button>
          </div>
        </>
      ) : (
        <p className="muted small">先保存档案，再添加参考图或讨论。</p>
      )}
      <button
        className="quiet separated"
        onClick={() => setAdvanced(!advanced)}
      >
        {advanced ? "收起" : "展开"}结构化属性、状态与证据
      </button>
      {advanced && (
        <label>
          属性与证据 JSON
          <textarea
            className="code"
            rows={10}
            value={structure}
            onChange={(e) => {
              setStructure(e.target.value);
              dirty.current = true;
            }}
          />
        </label>
      )}
      <p className="muted small">
        稳定设定在此编辑。服装变化、伤势、天气等情节状态在“场景插图”的关联卡中单独设置。
      </p>
      <button className="primary full separated" onClick={save}>
        保存资产修改
      </button>
    </aside>
  );
}
