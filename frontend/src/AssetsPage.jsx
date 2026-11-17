import React, { useState, useEffect, useRef } from "react";
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
  const {
    s,
    run,
    notify,
    setAssetEdit,
    setLarge,
    openAI,
    withProject,
    openAssetRender,
    setModal,
    uploadFiles,
  } = useWorkspace();
  const [filter, setFilter] = useState("全部"),
    [search, setSearch] = useState(""),
    [view, setView] = useState("records"),
    [gallery, setGallery] = useState([]),
    [trash, setTrash] = useState([]),
    [selected, setSelected] = useState(new Set()),
    [sort, setSort] = useState("等级");
  const [adviceOpen, setAdviceOpen] = useState(false);
  const adviceJob = s.jobs.find(
    (j) =>
      j.node === 1 &&
      j.asset_phase === "advice" &&
      j.segment === s.segment &&
      j.status === "success",
  )?.id;
  const seenAdvice = useRef({ segment: s.segment, job: adviceJob });
  useEffect(() => {
    if (
      seenAdvice.current.segment === s.segment &&
      adviceJob &&
      seenAdvice.current.job !== adviceJob &&
      !s.asset_ready
    )
      setAdviceOpen(true);
    else if (seenAdvice.current.segment !== s.segment) setAdviceOpen(false);
    seenAdvice.current = { segment: s.segment, job: adviceJob };
  }, [s.segment, adviceJob]);
  const [adviceSelection, setAdviceSelection] = useState(new Set()),
    [adviceItems, setAdviceItems] = useState([]),
    [adviceRaw, setAdviceRaw] = useState("");
  useEffect(() => {
    setAdviceItems(s.asset_advice?.items || []);
    setAdviceRaw(s.asset_advice?.raw || "");
    setAdviceSelection(
      (old) =>
        new Set(
          [...old].filter((id) =>
            (s.asset_advice?.items || []).some((i) => i.id === id),
          ),
        ),
    );
  }, [s.segment, JSON.stringify(s.asset_advice)]);
  const levels = ["核心", "重要", "建议"];
  const pending = (s.asset_candidates || []).filter(
    (a) =>
      !a.accepted &&
      !a.deleted &&
      (filter === "全部" || a.kind === filter) &&
      a.name.includes(search),
  );
  const level = (a) =>
    a.chapter_levels?.[s.segment]?.priority ||
    (a.chapter_levels ? "建议" : a.priority) ||
    "建议";
  const order = (a) =>
    Math.min(
      ...(a.appearances || [])
        .filter((e) => e.segment === s.segment)
        .map((e) => e.paragraph),
      a.first_paragraph || Infinity,
    );

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
  rows.sort(
    (a, b) =>
      (sort === "等级"
        ? levels.indexOf(level(a)) - levels.indexOf(level(b))
        : 0) || order(a) - order(b),
  );
  const pictures = gallery.filter(
    (r) => (filter === "全部" || r.kind === filter) && r.name.includes(search),
  );
  return (
    <div className="assets-workspace">
      <PageHeading
        title="视觉资产库"

        actions={
          <>
            <details
              className="toolbar-menu"
              onClick={(e) => {
                if (e.target.closest("button")) e.currentTarget.open = false;
              }}
            >
              <summary>导入原文 ▾</summary>
              <div>
                <button
                  disabled={s.busy}
                  onClick={() => setModal({ type: "import", method: "file" })}
                >
                  导入章节附件
                </button>
                <button
                  disabled={s.busy}
                  onClick={() => setModal({ type: "import", method: "paste" })}
                >
                  粘贴原文
                </button>
              </div>
            </details>
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
      {!s.segment && (
        <DropZone
          accept=".txt,.md,.docx,.epub"
          label="拖入章节附件；每个文件独立建章，导入不调用模型"
          onFiles={(files) => uploadFiles(files, "text")}
        />
      )}
      <div className="source-toolbar">
        <label>
          当前章节
          <select
            value={s.segment || ""}
            disabled={s.busy}
            onChange={(e) => run("select", { segment: e.target.value })}
          >
            {s.segments.map((seg) => (
              <option key={seg.id} value={seg.id}>
                {seg.name}
              </option>
            ))}
          </select>
        </label>
        <span
          className={"asset-stage-status " + (s.asset_ready ? "ready" : "")}
        >
          {s.asset_ready ? "● 本章整理已完成，可解析情节" : "○ 本章资产待整理"}
        </span>
        <details
          className="toolbar-menu"
          onClick={(e) => {
            if (e.target.closest("button")) e.currentTarget.open = false;
          }}
        >
          <summary>建卡建议 ▾</summary>
          <div>
            <button onClick={() => setAdviceOpen(true)}>
              查看／编辑建卡建议
            </button>
            <button
              disabled={!s.segment || s.busy}
              onClick={() => {
                if (
                  !s.asset_advice ||
                  window.confirm("重新获取本章建议将调用模型，继续吗？")
                )
                  run("send", {
                    node: 1,
                    asset_phase: "advice",
                    message: "阅读本章，提出简短建卡建议和三级分级。",
                  });
              }}
            >
              获取本章建卡建议
            </button>
            <button
              disabled={s.busy}
              onClick={() => {
                if (
                  window.confirm(
                    "确认本章资产整理完成，并将本章待确认资产批量确认为已确认？未选条目不建卡。",
                  )
                )
                  run("asset_finish", {
                    selected: [...adviceSelection],
                    confirm_pending: true,
                  });
              }}
            >
              完成本章资产整理
            </button>
            <p className="small muted">
              整章阅读 → 勾选建议 → 正式建卡 →
              确认完成；无图或未知外观不阻止完成。
            </p>
          </div>
        </details>
      </div>
      <section className="asset-workflow">
        {adviceOpen && (
          <div className="modal-shade">
            <section className="modal" role="dialog" aria-label="建卡建议选择">
              <div className="modal-heading">
                <h2>第一轮建议 / 勾选后建立资产卡</h2>
                <button onClick={() => setAdviceOpen(false)}>关闭建议</button>
              </div>{" "}
              {s.asset_advice?.raw && (
                <details>
                  <summary>第一轮原始建议 / 手工整理</summary>
                  <textarea
                    rows={6}
                    value={adviceRaw}
                    onChange={(e) => setAdviceRaw(e.target.value)}
                  />
                  <button
                    onClick={() => run("save_advice", { text: adviceRaw })}
                  >
                    从逐项文本重新整理建议
                  </button>
                </details>
              )}
              {adviceItems.map((item, i) => (
                <div className="advice-row" key={item.id}>
                  <input
                    aria-label={"勾选 " + item.name}
                    type="checkbox"
                    disabled={(s.assets_created || []).includes(item.id)}
                    checked={
                      adviceSelection.has(item.id) &&
                      !(s.assets_created || []).includes(item.id)
                    }
                    onChange={(e) =>
                      setAdviceSelection((v) => {
                        const n = new Set(v);
                        e.target.checked ? n.add(item.id) : n.delete(item.id);
                        return n;
                      })
                    }
                  />
                  <input
                    aria-label={"建议名称 " + i}
                    value={item.name}
                    onChange={(e) =>
                      setAdviceItems((v) =>
                        v.map((a, j) =>
                          j === i ? { ...a, name: e.target.value } : a,
                        ),
                      )
                    }
                  />
                  <select
                    value={item.kind}
                    onChange={(e) =>
                      setAdviceItems((v) =>
                        v.map((a, j) =>
                          j === i ? { ...a, kind: e.target.value } : a,
                        ),
                      )
                    }
                  >
                    {["人物", "场景", "道具"].map((k) => (
                      <option key={k}>{k}</option>
                    ))}
                  </select>
                  <select
                    value={item.priority}
                    onChange={(e) =>
                      setAdviceItems((v) =>
                        v.map((a, j) =>
                          j === i ? { ...a, priority: e.target.value } : a,
                        ),
                      )
                    }
                  >
                    {["核心", "重要", "建议"].map((k) => (
                      <option key={k}>{k}</option>
                    ))}
                  </select>
                  <select
                    aria-label={"建卡方式 " + item.name}
                    value={item.action || "auto"}
                    onChange={(e) =>
                      setAdviceItems((v) =>
                        v.map((a, j) =>
                          j === i ? { ...a, action: e.target.value } : a,
                        ),
                      )
                    }
                  >
                    <option value="auto">新建或关联已有档案</option>
                    <option value="variant">建立本章状态副卡</option>
                  </select>
                  {item.action === "variant" && (
                    <input
                      aria-label="副卡标题"
                      value={item.variant_title || ""}
                      placeholder="副卡名称"
                      onChange={(e) =>
                        setAdviceItems((v) =>
                          v.map((a, j) =>
                            j === i
                              ? { ...a, variant_title: e.target.value }
                              : a,
                          ),
                        )
                      }
                    />
                  )}
                  <span>
                    {(s.assets_created || []).includes(item.id)
                      ? "已建卡 · "
                      : ""}
                    {item.reason}
                  </span>
                  <button
                    onClick={() =>
                      setAdviceItems((v) => v.filter((_, j) => j !== i))
                    }
                  >
                    移除建议
                  </button>
                </div>
              ))}
              <div className="actions">
                <button
                  onClick={() =>
                    setAdviceItems((v) => [
                      ...v,
                      {
                        id: "manual-" + Date.now(),
                        name: "新资产",
                        kind: "人物",
                        priority: "建议",
                        reason: "用户添加",
                      },
                    ])
                  }
                >
                  手工增加建卡建议
                </button>
                <button
                  disabled={
                    s.busy ||
                    ![...adviceSelection].some(
                      (id) => !(s.assets_created || []).includes(id),
                    )
                  }
                  onClick={async () => {
                    if (
                      !(await run("save_advice", {
                        text: adviceRaw,
                        items: adviceItems,
                      }))
                    )
                      return;
                    setAdviceOpen(false);
                    await run("send", {
                      node: 1,
                      asset_phase: "build",
                      selected: [...adviceSelection].filter(
                        (id) => !(s.assets_created || []).includes(id),
                      ),
                      message: "仅为用户勾选项建立简洁档案。",
                    });
                  }}
                >
                  为选中项建立资产卡
                </button>
              </div>
            </section>
          </div>
        )}
      </section>
      <div className="view-switch" role="group" aria-label="资产视图">
        {[
          ["records", "资产档案"],
          ["gallery", "参考图画廊"],
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
      <details className="asset-more toolbar-menu">
        <summary aria-label="资产库更多选项">⋯</summary>
        <div>
          <button
            onClick={() => {
              setView("trash");
              setSelected(new Set());
            }}
          >
            资产回收站
          </button>
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
          {(s.asset_candidates || []).some((a) => a.accepted) && (
            <details>
              <summary>本章已处理候选（保留原始建议）</summary>
              {s.asset_candidates
                .filter((a) => a.accepted)
                .map((a) => (
                  <section key={a.id}>
                    <h3>{a.name}</h3>
                    <pre>
                      {JSON.stringify(
                        {
                          description: a.description,
                          attributes: a.attributes,
                          states: a.states,
                        },
                        null,
                        2,
                      )}
                    </pre>
                    <button
                      onClick={() => {
                        const asset = s.assets.find((v) => v.id === a.accepted);
                        if (asset) setAssetEdit(asset);
                        else notify("档案已归档，可在回收站恢复");
                      }}
                    >
                      编辑对应档案
                    </button>
                  </section>
                ))}
            </details>
          )}
        </div>
      </details>
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
        <label>
          排序
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            <option>等级</option>
            <option>出现顺序</option>
          </select>
        </label>
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
          {pending.length > 0 && (
            <section className="asset-candidates">
              <h2>本章资产候选 · {pending.length} 项待审核</h2>
              <p className="muted small">
                模型建议等级仅针对本章；确认前可编辑或删除，不自动覆盖同名档案。
              </p>
              <div className="asset-grid">
                {pending
                  .sort(
                    (a, b) =>
                      (sort === "等级"
                        ? levels.indexOf(a.priority) -
                          levels.indexOf(b.priority)
                        : 0) || a.first_paragraph - b.first_paragraph,
                  )
                  .map((a) => (
                    <ImageCard
                      key={a.id}
                      title={a.name}
                      subtitle={a.description}
                      badge={a.priority + " · 待审核"}
                      onOpen={() => setAssetEdit({ ...a, _candidate: true })}
                    >
                      <p>
                        {a.kind} · 首现段落 {a.first_paragraph}
                      </p>
                      <p className="small muted">{a.priority_reason}</p>
                      {s.assets.some(
                        (v) => v.name === a.name && v.kind === a.kind,
                      ) && (
                        <p className="notice">
                          请对比已有主卡和副卡；状态发生变化时可在已有档案中建立副卡，候选确认不会覆盖旧设定。
                        </p>
                      )}
                      {s.assets.some(
                        (v) => v.name === a.name && v.kind === a.kind,
                      ) && (
                        <p className="notice small">
                          匹配已有档案。确认仅补充出现位置和本章等级，新增描述与属性保留为建议，不覆盖已有设定。
                        </p>
                      )}
                      {s.assets.some(
                        (v) => v.name === a.name && v.kind === a.kind,
                      ) && (
                        <div className="notice">
                          <p>
                            当前状态：
                            {
                              s.assets.find(
                                (v) => v.name === a.name && v.kind === a.kind,
                              )?.effective?.description
                            }
                          </p>
                          <p>本章建议：{a.description}</p>
                          <button
                            disabled={s.busy}
                            onClick={async () => {
                              const base = s.assets.find(
                                (v) => v.name === a.name && v.kind === a.kind,
                              );
                              const title =
                                window.prompt(
                                  "为此状态副卡命名，例如：伤愈状态",
                                );
                              if (!title) return;
                              if (
                                await run("save_variant", {
                                  id: base.id,
                                  title,
                                  data: a,
                                })
                              )
                                await run("asset_candidate", {
                                  id: a.id,
                                  action: "approve",
                                });
                            }}
                          >
                            建立状态副卡并关联本章
                          </button>
                        </div>
                      )}
                      <footer>
                        <button
                          onClick={() =>
                            setAssetEdit({ ...a, _candidate: true })
                          }
                        >
                          编辑候选
                        </button>
                        <button
                          disabled={s.busy}
                          onClick={() =>
                            run("asset_candidate", {
                              id: a.id,
                              action: "approve",
                            })
                          }
                        >
                          {s.assets.some(
                            (v) => v.name === a.name && v.kind === a.kind,
                          )
                            ? "关联已有档案"
                            : "确认入库"}
                        </button>
                        <button
                          disabled={s.busy}
                          onClick={() =>
                            run("asset_candidate", {
                              id: a.id,
                              action: "delete",
                            })
                          }
                        >
                          删除候选
                        </button>
                      </footer>
                    </ImageCard>
                  ))}
              </div>
            </section>
          )}
          <div
            className={
              "actions asset-batch " + (!selected.size ? "inactive" : "")
            }
          >
            {!!selected.size && <span>已选 {selected.size} 项</span>}
            <button onClick={() => setSelected(new Set(rows.map((a) => a.id)))}>
              全选当前资产
            </button>
            {!!selected.size && (
              <button onClick={() => setSelected(new Set())}>取消选择</button>
            )}
            {!!selected.size && (
              <select
                aria-label="批量资产状态"
                value=""
                disabled={!selected.size || s.busy}
                onChange={(e) =>
                  e.target.value &&
                  run("asset_review", {
                    ids: [...selected],
                    status: e.target.value,
                  })
                }
              >
                <option value="">批量设置状态…</option>
                <option value="待确认">待确认（取消确认／解锁）</option>
                <option value="已确认">已确认</option>
                <option value="已锁定">已锁定</option>
              </select>
            )}
          </div>
          <div className="asset-grid">
            {rows.map((a) => (
              <ImageCard
                key={a.id}
                image={a.thumbnail}
                selected={selected.has(a.id)}
                onSelect={() =>
                  setSelected((v) => {
                    const n = new Set(v);
                    n.has(a.id) ? n.delete(a.id) : n.add(a.id);
                    return n;
                  })
                }
                title={a.name}
                subtitle={a.description?.slice(0, 80) || "视觉设定待填写"}
                badge={a.image ? "主参考图" : "待补参考图"}
                onOpen={() => setAssetEdit(a)}
              >
                <div className="card-meta">
                  <span className="badge">
                    {a.kind} · {level(a)}
                  </span>
                  <span className="small muted">
                    {Number.isFinite(order(a))
                      ? "首现段落 " + order(a)
                      : "出现位置待核对"}
                  </span>
                  <select
                    className="asset-status"
                    aria-label={"资产状态 " + a.name}
                    title="已确认表示已审核；已锁定会冻结内容，需先解锁才能编辑。"
                    value={a.review || "待确认"}
                    disabled={s.busy}
                    onChange={(e) =>
                      run("asset_review", {
                        ids: [a.id],
                        status: e.target.value,
                      })
                    }
                  >
                    <option value="待确认">待确认</option>
                    <option value="已确认">已确认</option>
                    <option value="已锁定">已锁定</option>
                  </select>
                  <button onClick={() => openAssetRender(a.id)}>
                    制作资产图
                  </button>
                </div>
                <label>
                  本章采用
                  <select
                    aria-label={"副卡选择 " + a.name}
                    value={s.chapter_variant_choices?.[a.id] || "auto"}
                    onChange={(e) =>
                      run("select_variant", {
                        id: a.id,
                        variant: e.target.value,
                      })
                    }
                  >
                    <option value="auto">自动继承此前最新确认副卡</option>
                    <option value="base">主卡</option>
                    {(a.variants || []).map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.title}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="small muted">
                  当前有效：{a.effective?.selected_variant?.title || "主卡"}
                </p>
                <footer>
                  <span>关联 {new Set(a.uses).size} 个情节</span>
                  <button
                    disabled={s.busy}
                    onClick={() => {
                      if (
                        window.confirm(
                          "删除资产档案到回收站？原文、图片与历史保留，相关情节将显示缺失。",
                        )
                      )
                        run("archive_asset", { id: a.id });
                    }}
                  >
                    删除
                  </button>
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
              text="可手工新建，或直接从当前章节构建候选；不需要先解析情节。"
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
      {view === "trash" && (
        <section>
          <h2>已删除资产与候选</h2>
          {(s.asset_trash || []).map((a) => (
            <p key={a.id}>
              {a.name}
              <button
                onClick={() =>
                  run("archive_asset", { id: a.id, restore: true })
                }
              >
                恢复资产
              </button>
            </p>
          ))}
          {(s.asset_candidates || [])
            .filter((a) => a.deleted && !a.accepted)
            .map((a) => (
              <p key={a.id}>
                {a.name}
                <button
                  onClick={() =>
                    run("asset_candidate", { id: a.id, action: "restore" })
                  }
                >
                  恢复候选
                </button>
              </p>
            ))}
        </section>
      )}
    </div>
  );
}

export const assetFields = {
  人物: [
    ["face", "面容"],
    ["body", "体型"],
    ["appearance_state", "外观与状态"],
    ["background", "背景信息"],
    ["relationships", "关系"],
  ],
  场景: [
    ["scene_description", "场景描述"],
    ["plot_context", "相关情节"],
  ],
  道具: [
    ["shape", "外形描述"],
    ["plot_context", "相关情节"],
  ],
};

export function AssetEditor({ asset, onClose }) {
  const {
    s,
    run,
    notify,
    uploadFiles,
    setLarge,
    openAI,
    openCompletion,
    dirty,
    openAssetRender,
  } = useWorkspace();
  const [form, setForm] = useState(
      copy({
        ...asset,
        details: asset.details,
        priority:
          asset.chapter_levels?.[s.segment]?.priority ||
          (asset.chapter_levels ? "建议" : asset.priority) ||
          "建议",
        priority_reason:
          asset.chapter_levels?.[s.segment]?.reason ||
          asset.priority_reason ||
          "",
      }),
    ),
    [refs, setRefs] = useState([]),
    [advanced, setAdvanced] = useState(false),
    [structure, setStructure] = useState(
      JSON.stringify(
        {
          attributes: asset.attributes || [],
          states: asset.states || [],
          evidence: asset.evidence || [],
          appearances: asset.appearances || [],
          missing: asset.missing || [],
        },
        null,
        2,
      ),
    );
  const latest = useRef(null);
  latest.current = { form, structure };
  const live = s.assets.find((a) => a.id === asset.id) || asset;
  useEffect(() => {
    if (asset.id && !asset._candidate)
      api("gallery")
        .then((rows) => setRefs(rows.filter((r) => r.asset === asset.id)))
        .catch((e) => notify(e.message));
  }, [live.revision]);
  function set(key, value) {
    if (key === "kind") {
      if (!window.confirm("更改分类后将清空本次编辑中的分类字段，继续吗？"))
        return;
      setForm((f) => ({ ...f, kind: value, details: {} }));
    } else setForm((f) => ({ ...f, [key]: value }));
    dirty.current = true;
  }
  async function save() {
    let parsed;
    try {
      parsed = JSON.parse(structure);
      for (const key of [
        "attributes",
        "states",
        "evidence",
        "missing",
        "appearances",
      ])
        if (!Array.isArray(parsed[key])) throw new Error();
    } catch {
      notify(
        "结构化属性需为包含 attributes/states/evidence/missing 数组的 JSON",
      );
      return;
    }
    const r = asset._candidate
      ? await run("asset_candidate", {
          id: asset.id,
          action: "edit",
          data: { ...form, ...parsed },
        })
      : await run("save_asset", { ...form, ...parsed });
    if (r) {
      dirty.current = false;
      notify("资产已保存；关联方案会标记待复核");
      if (asset._linkScene)
        await run("scene_assets_edit", {
          scene: asset._linkScene,
          id: r.id,
          action: "add",
        });
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
      {live.review === "已锁定" && (
        <p className="notice">
          资产已锁定。
          <button
            onClick={async () => {
              await run("asset_review", { ids: [asset.id], status: "已确认" });
              setForm((f) => ({ ...f, review: "已确认" }));
            }}
          >
            解锁以编辑
          </button>
        </p>
      )}
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
      <label>
        别名（逗号分隔；不建议登记“他、父亲”等泛称）
        <input
          value={(form.aliases || []).join(",")}
          onChange={(e) =>
            set(
              "aliases",
              e.target.value
                .split(/[,，]/)
                .map((v) => v.trim())
                .filter(Boolean),
            )
          }
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
            disabled={!!asset._candidate}
            value={form.review}
            onChange={(e) => set("review", e.target.value)}
          >
            {asset._candidate && <option>待审核</option>}
            <option>待确认</option>
            <option>已确认</option>
            <option>已锁定</option>
          </select>
        </label>
      </div>
      <div className="field-pair">
        <label>
          本章建议等级
          <select
            aria-label="资产等级"
            value={
              form.priority ||
              form.chapter_levels?.[s.segment]?.priority ||
              "建议"
            }
            onChange={(e) => set("priority", e.target.value)}
          >
            {["核心", "重要", "建议"].map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
        <label>
          等级理由
          <input
            value={form.priority_reason || ""}
            onChange={(e) => set("priority_reason", e.target.value)}
          />
        </label>
      </div>
      <button
        disabled={s.busy}
        onClick={() => {
          let structured;
          try {
            structured = JSON.parse(structure);
          } catch {
            return notify("先修正结构化属性 JSON");
          }
          const snapshot = {
            ...form,
            ...structured,
            ...form.details,
            type: "asset",
          };
          openCompletion(
            snapshot,
            assetFields[form.kind].map(([k]) => k),
            (changes, original) => {
              const current = latest.current;
              let parsed;
              try {
                parsed = JSON.parse(current.structure);
              } catch {
                return false;
              }
              if (
                changes.some(
                  (c) =>
                    JSON.stringify(
                      { ...current.form, ...parsed, ...current.form.details }[
                        c.field
                      ],
                    ) !== JSON.stringify(original[c.field]),
                )
              ) {
                notify("目标字段已变化，请重新补全，避免覆盖新编辑。");
                return false;
              }
              const patch = {},
                annotations = [...(current.form.completion_annotations || [])];
              for (const c of changes) {
                if (["attributes", "states", "missing"].includes(c.field))
                  parsed[c.field] = c.value;
                else if (
                  assetFields[current.form.kind].some(([k]) => k === c.field)
                )
                  patch.details = {
                    ...(patch.details || current.form.details),
                    [c.field]: c.value,
                  };
                else patch[c.field] = c.value;
                annotations.push({
                  field: c.field,
                  source: "AI建议",
                  previous_source: current.form.source,
                  reason: c.reason,
                  time: new Date().toISOString(),
                });
              }
              setForm((f) => ({
                ...f,
                ...patch,
                source: changes.some((c) => c.field === "description")
                  ? "用户自定"
                  : f.source,
                completion_annotations: annotations,
              }));
              setStructure(JSON.stringify(parsed, null, 2));
              dirty.current = true;
            },
          );
        }}
      >
        AI补全
      </button>
      {asset._candidate && (
        <label>
          首次出现段落
          <input
            type="number"
            min="1"
            max={s.paragraphs.length}
            value={form.first_paragraph || 1}
            onChange={(e) => set("first_paragraph", Number(e.target.value))}
          />
        </label>
      )}
      {s.jobs
        .filter(
          (j) =>
            j.mode === "task" &&
            j.node === 5 &&
            j.asset === asset.id &&
            j.status === "success",
        )
        .slice(0, 1)
        .map((j) => (
          <details key={j.id}>
            <summary>资产设定图方案 · 待人工采用</summary>
            <pre>{j.output}</pre>
          </details>
        ))}
      {form.completion_annotations?.length > 0 && (
        <p className="notice">
          含用户采纳的 AI 建议；不代表原文明确。请核对后保存。
        </p>
      )}
      {!asset.details && asset.description && (
        <details>
          <summary>旧版描述（请分类整理；原文保留）</summary>
          <p>{asset.description}</p>
        </details>
      )}
      {assetFields[form.kind].map(([key, label]) => (
        <label key={key}>
          {label}
          <textarea
            rows={3}
            value={form.details?.[key] || ""}
            onChange={(e) =>
              set("details", { ...form.details, [key]: e.target.value })
            }
          />
        </label>
      ))}
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
      {asset.id && !asset._candidate ? (
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
          <button
            onClick={async () => {
              if (dirty.current) {
                notify("请先保存资产再进入制作工作区");
                return;
              }
              onClose();
              await openAssetRender(asset.id);
            }}
          >
            进入资产图制作工作区
          </button>
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
      {asset.id && !asset._candidate && (
        <section className="variant-editor">
          <h3>状态副卡</h3>
          <p>
            将当前编辑内容保存为副卡；主卡保持原设定。可留空参考图，按文字参与生图。
          </p>
          <button
            disabled={s.busy}
            onClick={async () => {
              const title = window.prompt("副卡名称，例如：伤愈状态");
              if (!title) return;
              let data;
              try {
                data = { ...form, ...JSON.parse(structure) };
              } catch {
                return notify("请先修正结构化字段");
              }
              if (await run("save_variant", { id: asset.id, title, data })) {
                dirty.current = false;
                notify("副卡已建立并用于本章；之后章节可自动继承");
                onClose();
              }
            }}
          >
            将当前编辑保存为新副卡
          </button>
          {(live.variants || []).map((v) => (
            <div key={v.id}>
              <strong>{v.title}</strong>
              <button
                onClick={() => {
                  setForm((f) => ({ ...f, ...v.data }));
                  setStructure(
                    JSON.stringify(
                      {
                        attributes: v.data.attributes || [],
                        states: v.data.states || [],
                        evidence: form.evidence || [],
                        appearances: form.appearances || [],
                        missing: v.data.missing || [],
                      },
                      null,
                      2,
                    ),
                  );
                  dirty.current = true;
                }}
              >
                载入副卡到编辑器
              </button>
              <button
                onClick={async () => {
                  let data;
                  try {
                    data = { ...form, ...JSON.parse(structure) };
                  } catch {
                    return;
                  }
                  if (
                    window.confirm("用当前编辑更新此副卡？历史任务快照保留。")
                  )
                    await run("save_variant", {
                      id: asset.id,
                      variant_id: v.id,
                      title: v.title,
                      data,
                      image: v.image || "",
                    });
                }}
              >
                更新此副卡
              </button>
              <select
                value={v.image || ""}
                onChange={(e) =>
                  run("save_variant", {
                    id: asset.id,
                    variant_id: v.id,
                    title: v.title,
                    data: v.data,
                    image: e.target.value,
                  })
                }
              >
                <option value="">仅文字，不沿用旧状态图片</option>
                {(live.images || []).map((im) => (
                  <option key={im.path} value={im.path}>
                    {im.path.split("/").at(-1)}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </section>
      )}
      <button className="primary full separated" onClick={save}>
        保存资产修改
      </button>
    </aside>
  );
}
