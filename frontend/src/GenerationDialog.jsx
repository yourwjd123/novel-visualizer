import React, { useEffect, useState } from "react";
import { X } from "lucide-react";
import { api } from "./api";
import { useWorkspace } from "./context";
export default function GenerationDialog({ asset, plan, onClose }) {
  const { run, notify, s } = useWorkspace();
  const [data, setData] = useState(null),
    [selected, setSelected] = useState(""),
    [saveDefault, setSaveDefault] = useState(false),
    [sending, setSending] = useState(false);
  useEffect(() => {
    let alive = true;
    api("generation_options", { asset, plan })
      .then((v) => {
        if (alive) {
          setData(v);
          setSelected(v.selected);
        }
      })
      .catch((e) => notify(e.message));
    return () => {
      alive = false;
    };
  }, [asset, plan]);
  const row = data?.options.find((r) => r.id === selected);
  return (
    <div className="modal-shade">
      <section className="modal" role="dialog" aria-label="本次生图">
        <div className="modal-heading">
          <h2>本次生图</h2>
          <button
            className="icon"
            disabled={sending}
            aria-label="关闭生图选择"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>
        <p className="muted">
          选择本次使用的图片服务及工作流；参考图与最终内容请在制作界面核对。确认前不会上传或提交。
        </p>
        {!data ? (
          <p>正在本地校验接口与工作流…</p>
        ) : (
          <>
            <label>
              接口与工作流
              <select
                aria-label="本次生图接口"
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
              >
                <option value="">请选择（不会自动切换服务）</option>
                {data.options.map((r) => (
                  <option key={r.id} value={r.id} disabled={!r.available}>
                    {r.name}
                    {!r.available ? " · 不适用" : ""}
                  </option>
                ))}
              </select>
            </label>
            {row?.warning && <p className="notice warning">{row.warning}</p>}
            {!data.selected && (
              <p className="notice">
                当前默认连接没有匹配项。请手动选择其他服务，或到设置中配置相应工作流。
              </p>
            )}
            <details>
              <summary>查看接口匹配情况</summary>
              {data.options.map((r) => (
                <p key={r.id}>
                  {r.name}：{r.available ? "可用" : "不可用"} {r.warning}
                </p>
              ))}
            </details>
            <label className="check-row">
              <input
                type="checkbox"
                checked={saveDefault}
                onChange={(e) => setSaveDefault(e.target.checked)}
              />
              设为此类制图节点的默认连接与首选预设
            </label>
          </>
        )}
        <div className="actions">
          <button disabled={sending} onClick={onClose}>
            取消
          </button>
          <button
            className="primary"
            disabled={!row?.available || s.busy || sending}
            onClick={async () => {
              setSending(true);
              const result = await run("generate", {
                asset,
                plan,
                selection: {
                  connection_id: row.connection_id,
                  preset_id: row.preset_id,
                },
                set_default: saveDefault,
              });
              setSending(false);
              if (result && !result.cancelled) onClose();
            }}
          >
            确认生成
          </button>
        </div>
      </section>
    </div>
  );
}
