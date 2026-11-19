import React, { useEffect, useState } from "react";
import { Plus, X, Trash2 } from "lucide-react";
import { api } from "./api";
import { useWorkspace, freshId } from "./context";
import ConnectionEditor from "./ConnectionEditor";
import WorkflowPresets from "./WorkflowPresets";

export default function ConnectionsPanel({ category }) {
  const { s, run, notify } = useWorkspace();
  const [data, setData] = useState(null),
    [editing, setEditing] = useState(null),
    [deleting, setDeleting] = useState(null),
    [replacement, setReplacement] = useState(""),
    [workflow, setWorkflow] = useState(null),
    [saving, setSaving] = useState(false),
    [rebind, setRebind] = useState({});
  const load = () =>
    api("connection_cards")
      .then(setData)
      .catch((e) => notify(e.message));
  useEffect(() => {
    load();
  }, [
    s.account.id,
    JSON.stringify(s.connections),
    JSON.stringify(s.defaults),
    JSON.stringify(s.settings),
    JSON.stringify(s.image_settings),
  ]);
  const rows = (data?.cards || []).filter((c) =>
    category === "language"
      ? ["demo", "openai"].includes(c.kind)
      : ["comfy", "image_api"].includes(c.kind),
  );
  rows.sort((a, b) => Number(a.kind === "demo") - Number(b.kind === "demo"));
  const fresh = () => ({
    id: "conn-" + freshId(),
    name: category === "language" ? "新语言连接" : "新图片连接",
    kind: category === "language" ? "openai" : "comfy",
    endpoint:
      category === "language"
        ? "http://127.0.0.1:11434/v1"
        : "http://127.0.0.1:8188",
    model: "",
    max_tokens: 10000,
    temperature: 0.5,
  });
  return (
    <section className="connections-hub">
      <div className="section-heading">
        <h2>{category === "language" ? "语言模型连接" : "图片服务连接"}</h2>
        <button className="primary" onClick={() => setEditing(fresh())}>
          <Plus size={14} />
          新建连接
        </button>
      </div>
      <p className="muted small">
        点击卡片编辑；参数与默认节点一次保存，密钥不回显。默认节点可在卡片内调整。
      </p>
      <div className="connection-card-grid">
        {rows.map((c) => (
          <article className="connection-card" key={c.id}>
            <button
              className="connection-card-open quiet"
              aria-label={"编辑连接 " + c.name}
              onClick={() => setEditing(c)}
            >
              <strong>{c.name}</strong>
              <span className="badge">
                {c.kind === "demo"
                  ? "演示"
                  : c.kind === "openai"
                    ? "语言 API / 本地"
                    : c.kind === "comfy"
                      ? "ComfyUI"
                      : "图片 API"}
              </span>
              <span>
                {c.model ||
                  (c.kind === "comfy" ? "按工作流模型运行" : "未填写模型")}
              </span>
              <small>{c.endpoint || "不联网"}</small>
              <small>
                {c.key_storage === "system"
                  ? "密钥：系统安全存储"
                  : c.key_set
                    ? "密钥：仅当前会话"
                    : "未设置密钥"}
              </small>
              <div className="binding-tags">
                {c.bindings.length ? (
                  c.bindings.map((k) => (
                    <span className="badge" key={k}>
                      {data.catalog.find((t) => t.id === k)?.name}
                    </span>
                  ))
                ) : (
                  <span className="muted">未指定默认节点</span>
                )}
              </div>
            </button>
            <div className="actions">
              {c.kind === "comfy" && (
                <button onClick={() => setWorkflow(c)}>工作流预设</button>
              )}
              <button
                className="danger"
                aria-label={"删除连接 " + c.name}
                disabled={s.busy}
                onClick={() => {
                  setDeleting(c);
                  setReplacement("");
                }}
              >
                <Trash2 size={14} />
                删除
              </button>
            </div>
          </article>
        ))}
      </div>
      {category === "image" &&
        (s.image_settings.presets || []).some((p) => !p.connection_id) && (
          <details>
            <summary>未绑定的工作流预设</summary>
            {(s.image_settings.presets || [])
              .filter((p) => !p.connection_id)
              .map((p) => (
                <div className="preset-row" key={p.id}>
                  <strong>
                    {p.name} · {p.reference_count}图
                  </strong>
                  <select
                    aria-label={"重新绑定 " + p.name}
                    value={rebind[p.id] || ""}
                    onChange={(e) =>
                      setRebind((v) => ({ ...v, [p.id]: e.target.value }))
                    }
                  >
                    <option value="">选择ComfyUI连接</option>
                    {rows
                      .filter((c) => c.kind === "comfy")
                      .map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                  </select>
                  <button
                    disabled={!rebind[p.id] || s.busy}
                    onClick={async () => {
                      if (
                        await run("workflow_preset_save", {
                          ...p,
                          connection_id: rebind[p.id],
                        })
                      )
                        load();
                    }}
                  >
                    确认重新绑定
                  </button>
                </div>
              ))}
          </details>
        )}
      {editing && data && (
        <ConnectionEditor
          key={editing.id}
          profile={editing}
          imageOnly={category !== "language"}
          catalog={data.catalog}
          ownedBindings={editing.bindings || []}
          owners={data.bindings}
          profiles={data.cards}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      )}
      {deleting && (
        <div className="modal-shade">
          <section className="modal" role="dialog" aria-label="删除连接">
            <h2>删除连接：{deleting.name}</h2>
            <p>
              历史任务、成果保留。当前凭据将清除，工作流预设保留为未绑定记录，不自动转移到其他服务。
            </p>
            <p>
              受影响节点：
              {deleting.bindings
                .map((k) => data.catalog.find((c) => c.id === k)?.name)
                .join("、") || "无显式默认绑定（旧项目引用也会解除）"}
            </p>
            <label>
              替代连接
              <select
                aria-label="删除连接替代项"
                value={replacement}
                onChange={(e) => setReplacement(e.target.value)}
              >
                <option value="">解除绑定，不自动切换服务</option>
                {rows
                  .filter((c) => c.id !== deleting.id)
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
              </select>
            </label>
            <div className="actions">
              <button disabled={saving} onClick={() => setDeleting(null)}>
                取消
              </button>
              <button
                className="danger"
                disabled={saving || s.busy}
                onClick={async () => {
                  setSaving(true);
                  if (
                    await run("connection_delete", {
                      id: deleting.id,
                      replacement,
                    })
                  ) {
                    setDeleting(null);
                    load();
                  }
                  setSaving(false);
                }}
              >
                删除连接及凭据
              </button>
            </div>
          </section>
        </div>
      )}
      {workflow && (
        <div className="modal-shade">
          <section
            className="modal wide"
            role="dialog"
            aria-label="连接工作流预设"
          >
            <div className="modal-heading">
              <h2>{workflow.name} · 工作流</h2>
              <button
                className="icon"
                aria-label="关闭预设列表"
                onClick={() => setWorkflow(null)}
              >
                <X size={18} />
              </button>
            </div>
            <WorkflowPresets
              onlyConnection={workflow.id}
              image={{ connection_id: workflow.id }}
              setImageField={() => {}}
            />
          </section>
        </div>
      )}
    </section>
  );
}
