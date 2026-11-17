import React, { useEffect, useRef, useState } from "react";
import { Plus, X, Copy, Trash2 } from "lucide-react";
import { api } from "./api";
import { useWorkspace, freshId } from "./context";

export default function WorkflowPresets({
  connection,
  image,
  setImageField,
  onEditConnection,
}) {
  const { s, run, notify } = useWorkspace();
  const [rows, setRows] = useState([]),
    [editing, setEditing] = useState(null),
    [warnings, setWarnings] = useState([]),
    [analyzing, setAnalyzing] = useState(false),
    [waiting, setWaiting] = useState(false);
  const seq = useRef(0),
    mounted = useRef(true),
    timer = useRef(null);
  const load = () =>
    api("workflow_presets")
      .then(setRows)
      .catch((e) => notify(e.message));
  useEffect(() => {
    load();
  }, [s.image_settings]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      seq.current++;
      clearTimeout(timer.current);
    };
  }, []);
  const set = (k, v) => {
    seq.current++;
    clearTimeout(timer.current);
    setAnalyzing(false);
    setEditing((e) => ({ ...e, [k]: v }));
  };
  async function inspect(workflow) {
    const current = ++seq.current;
    setAnalyzing(true);
    setWarnings([]);
    const apply = (result) => {
      if (!mounted.current || current !== seq.current) return;
      if (result.done) {
        setEditing((e) => ({
          ...e,
          workflow,
          mapping: JSON.stringify(result.mapping, null, 2),
          reference_count: result.reference_count,
        }));
        setWarnings(result.warnings || []);
        setAnalyzing(false);
      } else
        timer.current = setTimeout(async () => {
          try {
            const r = await api("workflow_inspect_status");
            if (r?.token !== result.token) throw Error("识别任务已变化");
            apply(r);
          } catch (e) {
            if (current === seq.current) {
              setAnalyzing(false);
              notify(e.message);
            }
          }
        }, 350);
    };
    try {
      apply(await api("workflow_inspect", { workflow }));
    } catch (e) {
      if (current === seq.current) {
        setAnalyzing(false);
        notify(e.message);
      }
    }
  }
  const begin = (p) => {
    seq.current++;
    setAnalyzing(false);
    setWarnings(p.warnings || []);
    setEditing(p);
  };
  const connections = s.connections.filter((c) =>
    ["comfy", "image_api"].includes(c.kind),
  );
  return (
    <section className="workflow-presets">
      <h2>图片连接与工作流预设</h2>
      <p className="muted small">
        同一连接共用地址和密钥。工作流按实际参考图数量匹配；保存会校验有效图片输入，阻止残留旧图。
      </p>
      <div className="provider-list">
        {connections.map((c) => (
          <div
            className={
              "provider-card " +
              (c.id === image.connection_id ? "selected" : "")
            }
            key={c.id}
          >
            <div className="section-heading">
              <strong>{c.name}</strong>
              <span className="badge">
                {c.kind === "comfy" ? "ComfyUI" : "图片 API"} ·{" "}
                {c.endpoint ? "已填地址" : "未填地址"} ·{" "}
                {c.key_set ? "已设密钥" : "未设密钥"}
              </span>
            </div>
            <div className="actions">
              <button onClick={() => setImageField("connection_id", c.id)}>
                选择此连接
              </button>
              {onEditConnection && (
                <button onClick={() => onEditConnection(c)}>
                  编辑连接 / 密钥
                </button>
              )}
              {c.kind === "comfy" && (
                <button
                  onClick={() =>
                    begin({
                      id: freshId(),
                      name: "新工作流预设",
                      connection_id: c.id,
                      workflow: "",
                      mapping: "{}",
                      reference_count: 0,
                      default: false,
                    })
                  }
                >
                  <Plus size={14} />
                  添加工作流
                </button>
              )}
            </div>
            {c.kind === "comfy" && (
              <div className="preset-list">
                {rows
                  .filter((p) => p.connection_id === c.id)
                  .map((p) => (
                    <div className="preset-row" key={p.id}>
                      <div>
                        <strong>{p.name}</strong>
                        <small>
                          {p.reference_count} 张参考图{" "}
                          {p.default ? "· 默认" : ""}
                          {p.legacy ? " · 旧版兼容" : ""}
                          <span
                            title={
                              p.validation_error ||
                              "本地结构与参考图数量校验通过"
                            }
                          >
                            {" "}
                            · {p.validation_error ? "待修正" : "校验通过"}
                          </span>
                        </small>
                      </div>
                      <button
                        onClick={() => {
                          setImageField("connection_id", c.id);
                          setImageField("preset_id", p.id);
                        }}
                      >
                        {image.preset_id === p.id ? "已选预设" : "设为首选"}
                      </button>
                      <button onClick={() => begin({ ...p })}>编辑</button>
                      <button
                        aria-label={"复制预设 " + p.name}
                        onClick={() =>
                          begin({
                            ...p,
                            id: freshId(),
                            name: p.name + " 副本",
                            legacy: false,
                            default: false,
                          })
                        }
                      >
                        <Copy size={14} />
                      </button>
                      {!p.legacy && (
                        <button
                          aria-label={"删除预设 " + p.name}
                          className="danger"
                          onClick={async () => {
                            if (
                              window.confirm(
                                "删除此工作流预设？服务连接和历史任务保留。",
                              ) &&
                              (await run("workflow_preset_save", {
                                id: p.id,
                                delete: true,
                              }))
                            )
                              load();
                          }}
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                  ))}
              </div>
            )}
          </div>
        ))}
      </div>
      {editing && (
        <div className="modal-shade">
          <section
            className="modal wide"
            role="dialog"
            aria-label="工作流预设编辑"
          >
            <div className="modal-heading">
              <h2>工作流预设</h2>
              <button
                className="icon"
                aria-label="关闭工作流预设"
                onClick={() => {
                  seq.current++;
                  clearTimeout(timer.current);
                  setEditing(null);
                }}
              >
                <X size={18} />
              </button>
            </div>
            <div className="field-pair">
              <label>
                预设名称
                <input
                  value={editing.name}
                  onChange={(e) => set("name", e.target.value)}
                />
              </label>
              <label>
                参考图数量
                <input
                  type="number"
                  min="0"
                  max="64"
                  value={editing.reference_count}
                  onChange={(e) =>
                    set("reference_count", Number(e.target.value))
                  }
                />
              </label>
            </div>
            <label className="check-row">
              <input
                type="checkbox"
                checked={!!editing.default}
                onChange={(e) => set("default", e.target.checked)}
              />
              相同连接与参考图数量下优先使用此预设
            </label>
            <label>
              导入 API 工作流
              <input
                type="file"
                accept=".json"
                onChange={async (e) => {
                  if (e.target.files[0]) {
                    const text = await e.target.files[0].text();
                    set("workflow", text);
                    inspect(text);
                  }
                }}
              />
            </label>
            <label>
              工作流 JSON
              <textarea
                className="code"
                rows="7"
                value={editing.workflow}
                onPaste={(e) => {
                  const text = e.clipboardData.getData("text");
                  try {
                    JSON.parse(text);
                    e.preventDefault();
                    set("workflow", text);
                    inspect(text);
                  } catch {}
                }}
                onChange={(e) => set("workflow", e.target.value)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={async (e) => {
                  e.preventDefault();
                  const f = e.dataTransfer.files[0];
                  if (f) {
                    const text = await f.text();
                    set("workflow", text);
                    inspect(text);
                  }
                }}
              />
            </label>
            <button
              disabled={analyzing || s.busy}
              onClick={() => inspect(editing.workflow)}
            >
              {analyzing
                ? "正在识别映射…"
                : "识别映射" +
                  (s.settings.workflow_ai_assist
                    ? "（语言模型辅助）"
                    : "（本地）")}
            </button>
            <label>
              节点映射（可修改）
              <textarea
                aria-label="预设节点映射"
                className="code"
                rows="5"
                value={editing.mapping}
                onChange={(e) => set("mapping", e.target.value)}
              />
            </label>
            {!!warnings.length && (
              <div className="notice">
                {warnings.map((w, i) => (
                  <p key={i}>{w}</p>
                ))}
              </div>
            )}
            <div className="actions">
              <button onClick={() => setEditing(null)}>取消</button>
              <button
                className="primary"
                disabled={analyzing || s.busy || waiting}
                onClick={async () => {
                  setWaiting(true);
                  if (await run("workflow_preset_save", editing)) {
                    setEditing(null);
                    load();
                  }
                  setWaiting(false);
                }}
              >
                校验并保存预设
              </button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
