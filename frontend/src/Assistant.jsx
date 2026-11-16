import React, {
  useEffect,
  useState,
  useRef,
  useImperativeHandle,
  forwardRef,
} from "react";
import { X, Send, Download, Square } from "lucide-react";
import { api } from "./api";
import { useWorkspace } from "./context";

export default forwardRef(function Assistant({ ai, onChange }, ref) {
  const { s, run, notify, setModal, navigate, setAssetEdit, openAssetRender } =
    useWorkspace();
  const [tab, setTab] = useState("status"),
    [question, setQuestion] = useState(""),
    [record, setRecord] = useState(null),
    [repair, setRepair] = useState(""),
    [position, setPosition] = useState(null),
    [clock, setClock] = useState(Date.now()),
    [chosen, setChosen] = useState(new Set()),
    [fields, setFields] = useState(["description"]),
    [drafts, setDrafts] = useState({});
  const panel = useRef(null),
    drag = useRef(null),
    sequence = useRef(0),
    current = useRef(null),
    geometryTimer = useRef(null);
  useImperativeHandle(ref, () => ({ flush: async () => {} }));
  const job = s.jobs.find((j) =>
    ai.job
      ? j.id === ai.job
      : j.segment === s.segment &&
        (tab === "consult"
          ? j.mode === "consult"
          : tab === "complete"
            ? j.mode === "complete"
            : true),
  );
  const scope = "consult_" + s.segment;
  const consultationKey = [
    s.account.id,
    s.project?.id,
    s.segment,
    tab,
    ai.target?.request_id,
  ].join(":");
  useEffect(() => {
    if (ai.open) setTab(ai.panel || "status");
  }, [ai.open, ai.panel]);
  useEffect(() => {
    setQuestion(drafts[consultationKey] || "");
    setRecord(null);
    current.current = consultationKey;
  }, [consultationKey]);
  useEffect(() => {
    if (current.current === consultationKey)
      setDrafts((d) => ({ ...d, [consultationKey]: question }));
  }, [question]);
  useEffect(() => {
    setRecord(null);
    if (!ai.open || !s.segment || tab !== "consult") return;
    const n = ++sequence.current;
    api("assistant_read", { node: 7, scope })
      .then((value) => {
        if (n === sequence.current) setRecord(value);
      })
      .catch((e) => notify(e.message));
    return () => {
      sequence.current++;
    };
  }, [
    ai.open,
    tab,
    scope,
    s.project?.id,
    JSON.stringify(s.jobs.map((j) => [j.id, j.status])),
  ]);
  useEffect(() => {
    setRepair(job?.output || "");
    setChosen(new Set((job?.changes || []).map((_, i) => i)));
  }, [job?.id, job?.output, JSON.stringify(job?.changes)]);
  useEffect(() => {
    setFields(
      ai.fields?.length
        ? ai.fields
        : ai.target?.type === "prompt"
          ? ["text"]
          : ["description"],
    );
  }, [ai.target]);
  useEffect(() => {
    if (!s.busy) return;
    const t = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(t);
  }, [s.busy]);
  function bound(r = {}) {
    const width = Math.min(r.width || 440, innerWidth - 20),
      height = Math.min(r.height || 700, innerHeight - 55);
    return {
      width,
      height,
      x: Math.max(
        10,
        Math.min(r.x ?? innerWidth - width - 25, innerWidth - width - 10),
      ),
      y: Math.max(40, Math.min(r.y ?? 70, innerHeight - height - 10)),
    };
  }
  const rect = bound(position || s.settings.workspace_layout?.assistant || {});
  async function geometry() {
    if (!panel.current || panel.current.hidden) return;
    const r = panel.current.getBoundingClientRect();
    await api("settings", {
      workspace_layout: {
        ...s.settings.workspace_layout,
        assistant: { x: r.x, y: r.y, width: r.width, height: r.height },
      },
    }).catch(() => {});
  }
  function close() {
    geometry();
    onChange({ ...ai, open: false });
  }
  useEffect(() => {
    const key = (e) => {
      if (ai.open && e.key === "Escape") {
        e.preventDefault();
        close();
      }
    };
    const resize = () => {
      if (panel.current && !panel.current.hidden) {
        const r = panel.current.getBoundingClientRect();
        setPosition(
          bound({ x: r.x, y: r.y, width: r.width, height: r.height }),
        );
      }
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
    const observer = new ResizeObserver(() => {
      clearTimeout(geometryTimer.current);
      geometryTimer.current = setTimeout(geometry, 400);
    });
    observer.observe(panel.current);
    return () => {
      observer.disconnect();
      clearTimeout(geometryTimer.current);
    };
  }, []);
  async function send(mode) {
    const d =
      mode === "consult"
        ? { node: 7, mode, message: question }
        : {
            node: ai.target?.type === "prompt" ? 3 : 5,
            mode,
            target: ai.target,
            fields,
            message: question || "请补全所选字段，保留其余内容。",
          };
    const sentScope = current.current;
    const result = await run("send", d);
    if (result && !result.cancelled && current.current === sentScope) {
      setQuestion("");
      setRecord(null);
    }
  }
  const summary = s.chapter_summary || {};
  const status =
    job?.status === "running"
      ? "运行中 · " + (job.phase || "等待模型响应")
      : job?.status === "invalid"
        ? "输出待修正"
        : job?.status === "success"
          ? job.mode === "consult"
            ? "咨询回复已保存"
            : job.mode === "complete"
              ? "补全建议待采用"
              : `任务完成 · ${job.result_count ?? ""}${job.node === 1 ? (job.asset_phase === "advice" ? " 项建卡建议待勾选" : " 项资产卡已建立，内容待核对") : job.node === 0 ? " 个情节候选待确认" : "结果待确认"}`
          : job?.status === "failed"
            ? "任务失败"
            : job?.status === "unknown"
              ? "任务状态未知"
              : job?.status || "尚未运行任务";
  const preface =
    s.defaults[
      String(tab === "consult" ? 7 : ai.target?.type === "prompt" ? 3 : 5)
    ] || {};
  const actualPreface = preface.preface_override
    ? preface.preface || ""
    : s.settings.language_preface || "";
  return (
    <section
      hidden={!ai.open}
      ref={panel}
      className="assistant"
      aria-label="可拖动缩放的 AI 助手"
      style={{
        left: rect.x,
        top: rect.y,
        right: "auto",
        width: rect.width,
        height: rect.height,
      }}
    >
      <header
        className="assistant-heading"
        onPointerDown={(e) => {
          if (e.target.closest("button")) return;
          const r = panel.current.getBoundingClientRect();
          drag.current = { x: e.clientX - r.x, y: e.clientY - r.y };
          e.currentTarget.setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (drag.current)
            setPosition(
              bound({
                x: e.clientX - drag.current.x,
                y: e.clientY - drag.current.y,
                width: panel.current.offsetWidth,
                height: panel.current.offsetHeight,
              }),
            );
        }}
        onPointerUp={() => {
          if (drag.current) {
            drag.current = null;
            geometry();
          }
        }}
        onPointerCancel={() => (drag.current = null)}
        onLostPointerCapture={() => (drag.current = null)}
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
      <div className="assistant-tabs">
        {[
          ["status", "任务状态"],
          ai.target ? ["complete", "AI 补全"] : ["consult", "自由咨询"],
        ].map(([id, label]) => (
          <button
            key={id}
            className={tab === id ? "active" : ""}
            onClick={() => {
              setTab(id);
              onChange({ ...ai, panel: id, job: null });
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="assistant-run-status" role="status">
        <strong>{status}</strong>
        {job && (
          <>
            <small>
              {job.kind} · {job.model || "演示模型"} · {job.created}
              {job.status === "running"
                ? " · 已等待 " +
                  Math.max(
                    0,
                    Math.floor((clock - Date.parse(job.created)) / 1000),
                  ) +
                  " 秒"
                : ""}
            </small>
            <small>
              实际输出上限：{job.effective_max_tokens ?? "未记录"} token
            </small>
            {job.request_summary && (
              <small>
                估算输入约 {job.request_summary.estimated_input_tokens}{" "}
                token（不含附件） · 本次 {job.request_summary.history_turns}{" "}
                条用户消息
              </small>
            )}
            {job.usage && <small>实际用量：{JSON.stringify(job.usage)}</small>}
            {job.error && <p>{job.error}</p>}
          </>
        )}
      </div>
      <div className="assistant-body">
        {tab === "status" ? (
          <>
            <p className="muted small">
              自动任务单轮运行，不附带历史聊天。请在工作区启动任务、查看和确认结果。
            </p>
            {job && (
              <>
                <p>
                  {s.segments.find((v) => v.id === job.segment)?.name} /{" "}
                  {job.scene && s.scenes.find((v) => v.id === job.scene)?.title}
                </p>
                {job.status === "success" && (
                  <button
                    onClick={async () => {
                      if (job.mode === "consult") {
                        setTab("consult");
                        return;
                      }
                      if (job.mode === "complete") {
                        if (ai.target?.request_id === job.target?.request_id)
                          setTab("complete");
                        else
                          notify(
                            "请从原编辑对象重新打开补全，防止覆盖已变化的内容",
                          );
                        return;
                      }
                      if (job.node === 5 && job.asset) {
                        await openAssetRender(job.asset);
                        close();
                        return;
                      }
                      await navigate(
                        job.node === 0
                          ? "source"
                          : [1, 5].includes(job.node)
                            ? "assets"
                            : "images",
                      );
                      if (job.node === 5 && job.asset)
                        setAssetEdit(s.assets.find((a) => a.id === job.asset));
                      close();
                    }}
                  >
                    查看任务结果
                  </button>
                )}
                {job.validation_error && (
                  <div className="notice warning">{job.validation_error}</div>
                )}
                {job.output_warning && (
                  <p className="notice warning">{job.output_warning}</p>
                )}
                <details>
                  <summary>本次实际输入与规则</summary>
                  <h3>前置与任务提示词</h3>
                  <pre>
                    {job.system_preview || "输入快照保存在项目任务目录。"}
                  </pre>
                  <h3>资料范围</h3>
                  <pre>{job.context_preview}</pre>
                </details>
                {job.output && (
                  <details open={!!job.validation_error}>
                    <summary>原始输出 / 手工校验</summary>
                    <textarea
                      aria-label="任务原始输出"
                      rows={9}
                      value={repair}
                      onChange={(e) => setRepair(e.target.value)}
                    />
                    {job.validation_error && (
                      <button
                        disabled={s.busy}
                        onClick={() =>
                          run("validate_task", { job: job.id, text: repair })
                        }
                      >
                        校验修改后的输出
                      </button>
                    )}
                  </details>
                )}
                <button
                  className="quiet small"
                  onClick={() =>
                    setModal({
                      type: "export",
                      data: {
                        node: job.node,
                        scope: job.scope,
                        asset: job.asset,
                      },
                    })
                  }
                >
                  <Download size={13} />
                  导出任务文本
                </button>
              </>
            )}
          </>
        ) : (
          <>
            <details>
              <summary>本轮背景与输入范围</summary>
              <h3>用户前置提示词</h3>
              <pre>{actualPreface || "未填写"}</pre>
              <h3>本章梗概</h3>
              <pre>{summary.text || "暂无梗概，可在原文页手工填写。"}</pre>
              {summary.stale && (
                <p className="notice warning">梗概对应的原文已变化，请更新。</p>
              )}
              <p>不附带章节全文或历史聊天；只有明确引用的回答参与本轮。</p>
              {tab === "complete" && (
                <>
                  <h3>目标全文</h3>
                  <pre>{JSON.stringify(ai.target, null, 2)}</pre>
                  <h3>补全指导</h3>
                  <pre>
                    {preface.completion_guidance ||
                      s.settings.completion_guidance ||
                      s.completion_guidance_default ||
                      "使用内置补全指导，可在设置中修改。"}
                  </pre>
                </>
              )}
            </details>
            {tab === "consult" ? (
              <div className="messages">
                {record?.messages?.map((m, i) => (
                  <section key={i} className={"message message-" + m.role}>
                    <small>
                      {m.role === "user" ? "用户" : "模型"} · {m.time}
                    </small>
                    <p>{m.content}</p>
                  </section>
                ))}
                <button
                  className="quiet small"
                  onClick={() =>
                    setModal({ type: "export", data: { node: 7, scope } })
                  }
                >
                  导出咨询记录 TXT / MD
                </button>
              </div>
            ) : (
              <>
                <h3>补全字段</h3>
                {(ai.target?.type === "prompt"
                  ? ["text"]
                  : ai.fields || ["description"]
                ).map((field) => (
                  <label className="check-row" key={field}>
                    <input
                      type="checkbox"
                      checked={fields.includes(field)}
                      onChange={(e) =>
                        setFields((v) =>
                          e.target.checked
                            ? [...v, field]
                            : v.filter((f) => f !== field),
                        )
                      }
                    />
                    {
                      {
                        text: "最终生图方案",
                        face: "面容",
                        body: "体型",
                        appearance_state: "外观与状态",
                        background: "背景信息",
                        relationships: "关系",
                        scene_description: "场景描述",
                        shape: "外形描述",
                        plot_context: "相关情节",
                        description: "描述",
                        notes: "备注",
                        attributes: "属性",
                        states: "状态",
                        missing: "缺失项",
                      }[field]
                    }
                  </label>
                ))}
                {job?.mode === "complete" &&
                  job.changes?.map((c, i) => (
                    <section className="completion-change" key={i}>
                      <label className="check-row">
                        <input
                          type="checkbox"
                          checked={chosen.has(i)}
                          onChange={(e) =>
                            setChosen((v) => {
                              const n = new Set(v);
                              e.target.checked ? n.add(i) : n.delete(i);
                              return n;
                            })
                          }
                        />
                        {c.field} · AI建议
                      </label>
                      <small>修改前</small>
                      <pre>
                        {JSON.stringify(job.target?.[c.field], null, 2)}
                      </pre>
                      <small>建议修改后</small>
                      <pre>
                        {typeof c.value === "string"
                          ? c.value
                          : JSON.stringify(c.value, null, 2)}
                      </pre>
                      <p>{c.reason}</p>
                    </section>
                  ))}
                {job?.mode === "complete" && job.status === "success" && (
                  <button
                    disabled={!chosen.size || !ai.onApply}
                    onClick={() => {
                      const changes = job.changes.filter((_, i) =>
                        chosen.has(i),
                      );
                      if (
                        job.segment !== s.segment ||
                        job.target?.request_id !== ai.target?.request_id
                      ) {
                        notify("编辑目标已变化，请重新发起补全");
                        return;
                      }
                      if (ai.onApply?.(changes, job.target) !== false) {
                        notify("已填入编辑器，仍需手工保存；来源为 AI 建议");
                        close();
                      }
                    }}
                  >
                    采用选中建议到编辑器
                  </button>
                )}
                {job?.mode === "complete" && job.validation_error && (
                  <div className="notice warning">
                    {job.validation_error}
                    <button onClick={() => setTab("status")}>
                      查看原始输出并修正
                    </button>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>
      <footer className="assistant-compose">
        {tab !== "status" && (
          <>
            <textarea
              aria-label="本轮对话输入"
              rows={3}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={
                tab === "consult"
                  ? "咨询当前章节；历史不会自动重发"
                  : "说明需要补全的空缺或简略部分…"
              }
            />
          </>
        )}
        <div className="actions">
          <button className="quiet small" onClick={() => setPosition(bound())}>
            重置位置
          </button>
          <span className="spacer" />
          {s.busy ? (
            <button className="danger small" onClick={() => run("stop")}>
              <Square size={12} />
              停止等待
            </button>
          ) : (
            tab !== "status" && (
              <button
                className="primary"
                disabled={
                  summary.stale ||
                  (tab === "consult" ? !question.trim() : !fields.length)
                }
                onClick={() => send(tab === "consult" ? "consult" : "complete")}
              >
                <Send size={13} />
                {tab === "consult" ? "发送" : "生成补全建议"}
              </button>
            )
          )}
        </div>
      </footer>
    </section>
  );
});
