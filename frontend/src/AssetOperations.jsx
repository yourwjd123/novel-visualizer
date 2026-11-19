import React, { useEffect, useState } from "react";
import { X, RotateCcw } from "lucide-react";
import { api } from "./api";
import { useWorkspace } from "./context";

export default function AssetOperations({ request, onClose, onDone }) {
  const { s, run, notify } = useWorkspace();
  const [target, setTarget] = useState(request.target || ""),
    [preview, setPreview] = useState(null),
    [choices, setChoices] = useState({}),
    [history, setHistory] = useState([]),
    [restore, setRestore] = useState(null),
    [waiting, setWaiting] = useState(false);
  const source = s.assets.find((a) => a.id === request.source);
  const loadHistory = () =>
    api("asset_operations")
      .then(setHistory)
      .catch((e) => notify(e.message));
  useEffect(() => {
    if (request.mode === "history") loadHistory();
  }, [request.mode]);
  useEffect(() => {
    let alive = true;
    setPreview(null);
    setChoices({});
    if (request.mode === "merge" && target && source)
      api("asset_merge_preview", { source: source.id, target })
        .then((v) => alive && setPreview(v))
        .catch((e) => notify(e.message));
    return () => {
      alive = false;
    };
  }, [target, source?.id, request.mode]);
  useEffect(() => {
    if (request.restore) startRestore(request.restore);
  }, [request.restore]);
  async function startRestore(id) {
    try {
      const data = await api("asset_operation_restore", { id, preview: true });
      setRestore({ id, ...data });
    } catch (e) {
      notify(e.message);
    }
  }
  return (
    <div className="modal-shade">
      <section className="modal wide" role="dialog" aria-label="资产整理操作">
        <div className="modal-heading">
          <h2>
            {request.mode === "history"
              ? "资产操作记录"
              : request.mode === "merge"
                ? "合并资产"
                : "归入主卡的副卡"}
          </h2>
          <button
            className="icon"
            disabled={waiting}
            aria-label="关闭资产操作"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>
        {request.mode === "history" ? (
          <>
            {!history.length && <p>还没有归入或合并记录。</p>}
            {history.map((h) => (
              <div className="operation-row" key={h.id}>
                <span>
                  {h.source} → {h.target} ·{" "}
                  {h.mode === "variant" ? "归入副卡" : "合并"} ·{" "}
                  {h.status === "active"
                    ? "可恢复"
                    : h.status === "restored"
                      ? "已恢复"
                      : "已回滚"}
                </span>
                {h.status === "active" && (
                  <button onClick={() => startRestore(h.id)}>
                    <RotateCcw size={14} />
                    恢复为独立资产
                  </button>
                )}
              </div>
            ))}
          </>
        ) : (
          <>
            <p>
              原卡：{source?.name}。原图、来源和历史任务保留；锁定卡需先解锁。
            </p>
            <label>
              目标主卡
              <select
                aria-label="资产操作目标"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              >
                <option value="">选择同类型主卡</option>
                {s.assets
                  .filter((a) => a.kind === source?.kind && a.id !== source?.id)
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} · {a.id.slice(-6)}
                    </option>
                  ))}
              </select>
            </label>
            {request.mode === "variant" ? (
              <p className="notice">
                归入后原卡作为副卡保留，原关联情节明确采用该副卡。其他章节不会自动采用；原卡已有副卡时须先整理，不建立嵌套。
              </p>
            ) : (
              preview && (
                <>
                  <p>
                    影响 {preview.uses}{" "}
                    个关联情节。重复内容合并，冲突字段逐项选择；原卡归档，可恢复。
                  </p>
                  {preview.conflicts.map((c) => (
                    <fieldset key={c.field}>
                      <legend>{c.field}</legend>
                      <label>
                        <input
                          type="radio"
                          name={c.field}
                          checked={choices[c.field] === "target"}
                          onChange={() =>
                            setChoices((v) => ({ ...v, [c.field]: "target" }))
                          }
                        />
                        保留目标主卡：{c.target}
                      </label>
                      <label>
                        <input
                          type="radio"
                          name={c.field}
                          checked={choices[c.field] === "source"}
                          onChange={() =>
                            setChoices((v) => ({ ...v, [c.field]: "source" }))
                          }
                        />
                        采用原卡：{c.source}
                      </label>
                    </fieldset>
                  ))}
                </>
              )
            )}
            <div className="actions">
              <button onClick={onClose}>取消</button>
              <button
                className="primary"
                disabled={
                  !target ||
                  s.busy ||
                  waiting ||
                  (request.mode === "merge" &&
                    (!preview ||
                      preview.conflicts.some((c) => !choices[c.field])))
                }
                onClick={async () => {
                  setWaiting(true);
                  const result = await run("asset_operation", {
                    source: source.id,
                    target,
                    mode: request.mode,
                    choices,
                  });
                  setWaiting(false);
                  if (result) {
                    onDone(result);
                    onClose();
                  }
                }}
              >
                {request.mode === "merge" ? "确认合并" : "归入副卡"}
              </button>
            </div>
          </>
        )}
        {restore && (
          <section className="restore-review">
            <h3>恢复：{restore.source}</h3>
            <p>
              原目标：{restore.target}；原操作涉及 {restore.scenes} 个情节。
            </p>
            <p>{restore.note}</p>
            <div className="actions">
              <button onClick={() => setRestore(null)}>取消恢复</button>
              <button
                className="primary"
                disabled={waiting || s.busy}
                onClick={async () => {
                  setWaiting(true);
                  const result = await run("asset_operation_restore", {
                    id: restore.id,
                  });
                  setWaiting(false);
                  if (result) {
                    setRestore(null);
                    loadHistory();
                    onDone({ message: "已恢复独立资产" });
                    if (request.mode !== "history") onClose();
                  }
                }}
              >
                确认恢复为独立资产
              </button>
            </div>
          </section>
        )}
      </section>
    </div>
  );
}
