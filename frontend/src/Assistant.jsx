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
    [position, setPosition] = useState(null),
    [clock, setClock] = useState(Date.now());
  const current = useRef(null),
    values = useRef({ message: "", final: "" }),
    timer = useRef(null),
    drag = useRef(null),
    panel = useRef(null),
    geometryTimer = useRef(null),
    loadSequence = useRef(0),
    desiredTarget = useRef(null);
  values.current = { message, final };
  async function flush() {
    clearTimeout(timer.current);
    const target = current.current;
    const snapshot = { ...values.current };
    const draftKey = target
      ? "novelviz-draft:" +
        s.account.id +
        ":" +
        target._project +
        ":" +
        target.node +
        ":" +
        target.scope
      : null;
    if (draftKey) {
      try {
        sessionStorage.setItem(draftKey, JSON.stringify(snapshot));
      } catch {}
    }
    if (target)
      try {
        await api("save_chat", {
          ...target,
          draft: snapshot.message,
          final: snapshot.final,
        });
        if (
          draftKey &&
          values.current.message === snapshot.message &&
          values.current.final === snapshot.final
        )
          sessionStorage.removeItem(draftKey);
      } catch (e) {
        notify("草稿暂存于当前窗口；本地保存失败：" + e.message);
      }
  }
  useImperativeHandle(ref, () => ({ flush }));
  const scope = ai.asset
    ? "asset_" + ai.asset
    : ai.node === 0 || ai.node === 7
      ? s.segment
      : s.scene;
  const targetKey = [s.project?.id, ai.node, scope].join(":");
  desiredTarget.current = targetKey;
  async function load(preserve = false) {
    if (!s.project || !scope) return;
    const sequence = ++loadSequence.current;
    try {
      const target = {
        node: ai.node,
        asset: ai.asset,
        scope,
        _project: s.project.id,
      };
      const value = await api("node_read", target);
      if (
        sequence !== loadSequence.current ||
        desiredTarget.current !== targetKey
      )
        return;
      if (
        !preserve ||
        !current.current ||
        current.current.scope !== scope ||
        current.current.node !== ai.node ||
        current.current._project !== s.project.id
      ) {
        current.current = target;
        let fallback = null;
        try {
          fallback = JSON.parse(
            sessionStorage.getItem(
              "novelviz-draft:" +
                s.account.id +
                ":" +
                target._project +
                ":" +
                target.node +
                ":" +
                target.scope,
            ),
          );
        } catch {}
        setMessage(fallback?.message ?? value.record.draft ?? "");
        setFinal(fallback?.final ?? value.record.final ?? "");
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
      load();
    }
    return () => clearTimeout(timer.current);
  }, [targetKey, ai.open]);
  useEffect(() => {
    if (!s.busy) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [s.busy]);
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
  function bounded(value = {}) {
    const width = Math.max(
      260,
      Math.min(value.width || 400, window.innerWidth - 20),
    );
    const height = Math.max(
      240,
      Math.min(value.height || 650, window.innerHeight - 50),
    );
    return {
      width,
      height,
      x: Math.max(
        10,
        Math.min(
          value.x ?? window.innerWidth - width - 30,
          window.innerWidth - width - 10,
        ),
      ),
      y: Math.max(
        40,
        Math.min(value.y ?? 80, window.innerHeight - height - 10),
      ),
    };
  }
  const rect = bounded(position || geometry || {});
  const style = {
    left: rect.x,
    top: rect.y,
    right: "auto",
    width: rect.width,
    height: rect.height,
  };
  function close() {
    onChange({ ...ai, open: false });
    flush();
    storeGeometry();
  }
  useEffect(() => {
    const key = (e) => {
      if (e.key === "Escape" && ai.open) {
        e.preventDefault();
        close();
      }
    };
    const resize = () => {
      const r = panel.current?.getBoundingClientRect();
      if (r)
        setPosition(
          bounded({ x: r.x, y: r.y, width: r.width, height: r.height }),
        );
    };
    window.addEventListener("keydown", key);
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("keydown", key);
      window.removeEventListener("resize", resize);
    };
  }, [ai.open]);
  useEffect(() => {
    if (!panel.current) return;
    let first = true;
    const observer = new ResizeObserver(() => {
      if (first) {
        first = false;
        return;
      }
      clearTimeout(geometryTimer.current);
      geometryTimer.current = setTimeout(storeGeometry, 400);
    });
    observer.observe(panel.current);
    return () => {
      observer.disconnect();
      clearTimeout(geometryTimer.current);
    };
  }, []);
  async function storeGeometry() {
    if (!panel.current || panel.current.hidden) return;
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
            setPosition(
              bounded({
                x: e.clientX - drag.current.x,
                y: e.clientY - drag.current.y,
                width: panel.current.offsetWidth,
                height: panel.current.offsetHeight,
              }),
            );
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
        onLostPointerCapture={() => {
          drag.current = null;
        }}
        onPointerUp={() => {
          if (drag.current) {
            drag.current = null;
            storeGeometry();
          }
        }}
      >
        <h2>✧ AI 助手</h2>
        <button
          className="icon quiet"
          aria-label="收起 AI 助手"
          onClick={close}
        >
          <X size={17} /> 收起
        </button>
      </header>
      {lastJob && (
        <div className="assistant-run-status" role="status">
          <strong>
            {lastJob.status === "running"
              ? "运行中 · " + (lastJob.phase || "等待模型响应")
              : lastJob.status === "success"
                ? "任务完成 · 请审核输出"
                : lastJob.status === "failed"
                  ? "任务失败"
                  : lastJob.status}
          </strong>
          <small>
            {lastJob.model || "演示模型"} · {lastJob.created?.slice(11, 19)}{" "}
            {lastJob.status === "running"
              ? " · 已等待 " +
                Math.max(
                  0,
                  Math.floor((clock - Date.parse(lastJob.created)) / 1000),
                ) +
                " 秒"
              : ""}
          </small>
          {lastJob.error && <p>{lastJob.error}</p>}
          {lastJob.output_warning && <p>{lastJob.output_warning}</p>}
          {lastJob.request_summary && (
            <small>
              估算输入约 {lastJob.request_summary.estimated_input_tokens}{" "}
              token（不含附件） · {lastJob.request_summary.history_turns} 条历史
              · {lastJob.request_summary.attachments} 个附件
            </small>
          )}
          {lastJob.usage && Object.keys(lastJob.usage).length > 0 && (
            <small>实际用量：{JSON.stringify(lastJob.usage)}</small>
          )}
        </div>
      )}
      <div className="assistant-context">
        <strong>{object}</strong>
        <button
          className="quiet small"
          onClick={() => setPosition(bounded({ width: 400, height: 650 }))}
        >
          重置位置
        </button>
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
              <section key={i} className={"message message-" + m.role}>
                <span className="eyebrow">
                  {m.role === "assistant" ? "模型" : "用户"} ·{" "}
                  {m.time?.slice(11, 19)}
                </span>
                <p>{m.content}</p>
                {(m.attachments || []).map((path) => (
                  <button
                    key={path}
                    className="quiet small"
                    onClick={() =>
                      setAttachments((files) =>
                        files.includes(path)
                          ? files.filter((p) => p !== path)
                          : [...files, path],
                      )
                    }
                  >
                    {attachments.includes(path)
                      ? "取消本轮引用："
                      : "本轮引用附件："}
                    {path.split("/").at(-1)}
                  </button>
                ))}
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
              默认仅附带必要历史和本轮附件，完整对话保存在本地；关闭精简请求后会附带全部历史。参数按发送时冻结到任务快照。
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
