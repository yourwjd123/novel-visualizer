import React, {
  useState,
  useEffect,
  useRef,
  useImperativeHandle,
  forwardRef,
} from "react";
import { X, Send, Download, Paperclip, Square } from "lucide-react";
import { api, upload } from "./api";
import { useWorkspace } from "./context";
import { DropZone } from "./App";

export default forwardRef(function Assistant({ ai, onChange }, ref) {
  const { s, run, notify, setModal } = useWorkspace();
  const [record, setRecord] = useState(null),
    [message, setMessage] = useState(""),
    [final, setFinal] = useState(""),
    [params, setParams] = useState(null),
    [context, setContext] = useState(""),
    [tab, setTab] = useState("chat"),
    [attachments, setAttachments] = useState([]),
    [candidateSelection, setCandidateSelection] = useState(new Set()),
    [position, setPosition] = useState(null);
  const current = useRef(null),
    values = useRef({ message: "", final: "" }),
    timer = useRef(null),
    drag = useRef(null),
    panel = useRef(null);
  values.current = { message, final };
  async function flush() {
    clearTimeout(timer.current);
    const target = current.current;
    if (target)
      try {
        await api("save_chat", {
          ...target,
          draft: values.current.message,
          final: values.current.final,
        });
      } catch (e) {
        notify(e.message);
      }
  }
  useImperativeHandle(ref, () => ({ flush }));
  const scope = ai.asset
    ? "asset_" + ai.asset
    : ai.node === 0 || ai.node === 7
      ? s.segment
      : s.scene;
  const targetKey = [s.project?.id, ai.node, scope].join(":");
  async function load(preserve = false) {
    if (!s.project || !scope) return;
    try {
      const target = {
        node: ai.node,
        asset: ai.asset,
        scope,
        _project: s.project.id,
      };
      const value = await api("node_read", target);
      if (!preserve) {
        current.current = target;
        setMessage(value.record.draft || "");
        setFinal(value.record.final || "");
        setAttachments(ai.reference ? [ai.reference] : []);
        setTab("chat");
      }
      setRecord(value.record);
      setParams(value.parameters);
      setContext(value.context);
    } catch (e) {
      notify(e.message);
    }
  }
  useEffect(() => {
    if (ai.open) {
      flush().then(() => load());
    }
    return () => clearTimeout(timer.current);
  }, [targetKey, ai.open]);
  const lastJob = s.jobs.find((j) => j.node === ai.node && j.scope === scope);
  useEffect(() => {
    if (ai.open && lastJob && !s.busy) load(true);
  }, [lastJob?.id, lastJob?.status]);
  useEffect(() => {
    if (ai.open && scope) load(true);
  }, [
    JSON.stringify(s.defaults?.[String(ai.node)]),
    JSON.stringify(s.connections),
  ]);
  useEffect(() => {
    if (!current.current) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(flush, 650);
    return () => clearTimeout(timer.current);
  }, [message, final]);
  let candidates = [];
  if (ai.node === 1)
    try {
      let body = final.trim();
      if (body.startsWith("```"))
        body = body.split("\n").slice(1, -1).join("\n");
      candidates = JSON.parse(body).assets || [];
    } catch {}
  useEffect(() => {
    setCandidateSelection(new Set(candidates.map((_, i) => i)));
  }, [final]);
  async function addFiles(files) {
    try {
      const next = [];
      for (const file of files) {
        const r = await upload(file, "attachment");
        next.push(r.path);
      }
      setAttachments((a) => [...a, ...next]);
      notify("附件已加入，发送时将按设置确认实际大小");
    } catch (e) {
      notify(e.message);
    }
  }
  async function send() {
    await flush();
    const result = await run("send", {
      node: ai.node,
      asset: ai.asset,
      message,
      attachments,
    });
    if (result && !result.cancelled) {
      setMessage("");
      setAttachments([]);
      load(true);
    }
  }
  async function apply() {
    await flush();
    const result = await run("apply_output", {
      node: ai.node,
      asset: ai.asset,
      text: final,
      ...(ai.node === 1 ? { selected: [...candidateSelection] } : {}),
    });
    if (result) {
      notify(
        ai.node === 0
          ? "已载入待确认拆分，请到原文页核对"
          : ai.node === 1
            ? "选定候选已入库为待审核资产；同名档案未覆盖"
            : "最终方案已确认",
      );
    }
  }
  const object = ai.asset
    ? s.assets.find((a) => a.id === ai.asset)?.name
    : s.scenes.find((r) => r.id === s.scene)?.title ||
      s.segments.find((seg) => seg.id === s.segment)?.name ||
      "未选择原文";
  const geometry = s.settings.workspace_layout?.assistant;
  const style = position
    ? { left: position.x, top: position.y, right: "auto" }
    : geometry
      ? {
          left: Math.min(geometry.x, Math.max(0, window.innerWidth - 320)),
          top: Math.min(geometry.y, Math.max(40, window.innerHeight - 300)),
          right: "auto",
          width: geometry.width,
          height: geometry.height,
        }
      : {};
  async function storeGeometry() {
    if (!panel.current) return;
    const r = panel.current.getBoundingClientRect();
    await api("settings", {
      workspace_layout: {
        ...s.settings.workspace_layout,
        assistant: { x: r.x, y: r.y, width: r.width, height: r.height },
      },
    }).catch(() => {});
  }
  return (
    <section
      hidden={!ai.open}
      ref={panel}
      className="assistant"
      aria-label="可拖动缩放的 AI 助手"
      style={style}
      onPointerUp={() => {
        if (!drag.current) storeGeometry();
      }}
    >
      <header
        className="assistant-heading"
        onPointerDown={(e) => {
          if (e.target.closest("button,select")) return;
          const rect = panel.current.getBoundingClientRect();
          drag.current = { x: e.clientX - rect.x, y: e.clientY - rect.y };
          e.currentTarget.setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (drag.current)
            setPosition({
              x: Math.max(
                0,
                Math.min(window.innerWidth - 280, e.clientX - drag.current.x),
              ),
              y: Math.max(
                34,
                Math.min(window.innerHeight - 100, e.clientY - drag.current.y),
              ),
            });
        }}
        onPointerUp={() => {
          drag.current = null;
          storeGeometry();
        }}
      >
        <h2>✧ AI 助手</h2>
        <button
          className="icon quiet"
          aria-label="收起 AI 助手"
          onClick={async () => {
            await flush();
            await storeGeometry();
            onChange({ ...ai, open: false });
          }}
        >
          <X size={17} />
        </button>
      </header>
      <div className="assistant-context">
        <strong>{object}</strong>
        <select
          aria-label="当前 AI 任务"
          value={ai.node}
          disabled={s.busy}
          onChange={async (e) => {
            await flush();
            onChange({ ...ai, node: Number(e.target.value) });
          }}
        >
          {[0, 1, 5, 2, 3, 4, 6, 7].map((node) => (
            <option key={node} value={node}>
              {s.nodes[node]}
            </option>
          ))}
        </select>
        <span className="small muted">
          {params?.provider === "demo"
            ? "演示 · 不联网"
            : params?.model || "尚未配置模型"}
        </span>
      </div>
      <div className="assistant-tabs">
        {[
          ["chat", "讨论"],
          ["final", "方案与确认"],
          ["input", "本次输入"],
        ].map(([id, label]) => (
          <button
            key={id}
            className={tab === id ? "active" : ""}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="assistant-body">
        {tab === "chat" ? (
          <div className="messages">
            {record?.messages.map((m, i) => (
              <section key={i} className={"message " + m.role}>
                <span className="eyebrow">
                  {m.role === "assistant" ? "模型" : "用户"} ·{" "}
                  {m.time?.slice(11, 19)}
                </span>
                <p>{m.content}</p>
                {m.role === "assistant" && (
                  <button
                    className="quiet small"
                    onClick={() => {
                      setFinal(m.content);
                      setTab("final");
                    }}
                  >
                    采用到待确认方案 →
                  </button>
                )}
              </section>
            ))}
            {!record?.messages.length && (
              <p className="muted small">
                每个任务可多轮讨论，也可在“方案与确认”直接手工填写。只有主动发送才会调用模型。
              </p>
            )}
          </div>
        ) : tab === "final" ? (
          <>
            <label>
              可编辑的最终方案
              <textarea
                rows={10}
                value={final}
                onChange={(e) => setFinal(e.target.value)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={async (e) => {
                  e.preventDefault();
                  for (const f of e.dataTransfer.files) {
                    if (/\.(txt|md)$/i.test(f.name)) {
                      const text = await f.text();
                      setFinal((v) => v + "\n" + text);
                    } else await addFiles([f]);
                  }
                }}
              />
            </label>
            {candidates.length > 0 && (
              <div className="candidate-approval">
                <p className="small muted">
                  选择入库项；同名同类档案只建立关联，不自动覆盖。
                </p>
                {candidates.map((c, i) => (
                  <label className="check-row" key={i}>
                    <input
                      type="checkbox"
                      checked={candidateSelection.has(i)}
                      onChange={(e) =>
                        setCandidateSelection((prev) => {
                          const next = new Set(prev);
                          e.target.checked ? next.add(i) : next.delete(i);
                          return next;
                        })
                      }
                    />
                    <span>
                      {c.name} · {c.kind}
                      <small>{c.source || "AI 建议"}</small>
                    </span>
                  </label>
                ))}
              </div>
            )}
            <button
              className="primary"
              disabled={s.busy || !final.trim()}
              onClick={apply}
            >
              {ai.node === 0
                ? "校验并载入拆分候选"
                : ai.node === 1
                  ? "校验选中候选并入库"
                  : "确认最终方案"}
            </button>
          </>
        ) : (
          <>
            <h3>实际任务提示词</h3>
            <pre>{params?.system}</pre>
            <h3>原文、情节与关联资产</h3>
            <pre>{context}</pre>
            <p className="muted small">
              对话历史与附件也会附带；参数按发送时设置冻结到任务快照。
            </p>
          </>
        )}
      </div>
      <footer className="assistant-compose">
        <textarea
          aria-label="本轮对话输入"
          rows={3}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="继续讨论，或提出本轮调整要求…"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            addFiles(Array.from(e.dataTransfer.files));
          }}
        />
        <div className="attached-files">
          {attachments.map((path) => (
            <span key={path}>
              {path.split("/").at(-1)}
              <button
                className="quiet icon"
                aria-label="移除附件"
                onClick={() =>
                  setAttachments((files) => files.filter((p) => p !== path))
                }
              >
                ×
              </button>
            </span>
          ))}
        </div>
        <div className="actions">
          <DropZone
            compact
            onFiles={addFiles}
            accept=".txt,.md,.docx,.epub,.png,.jpg,.jpeg,.webp"
            label="附件"
          />
          <button
            className="quiet small"
            onClick={async () => {
              await flush();
              setModal({
                type: "export",
                data: { node: ai.node, asset: ai.asset, scope },
              });
            }}
          >
            <Download size={13} />
            TXT / MD
          </button>
          <span className="spacer" />
          {s.busy ? (
            <button className="danger small" onClick={() => run("stop")}>
              <Square size={12} />
              停止等待
            </button>
          ) : (
            <button
              className="primary"
              disabled={!message.trim()}
              onClick={send}
            >
              <Send size={13} />
              发送
            </button>
          )}
        </div>
      </footer>
    </section>
  );
});
