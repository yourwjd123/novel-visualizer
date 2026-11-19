import React, { useState } from "react";
import { X } from "lucide-react";
import { useWorkspace, copy, freshId } from "./context";

export default function ConnectionEditor({
  profile,
  imageOnly,
  onClose,
  onSaved,
  catalog = null,
  ownedBindings = [],
  owners = {},
  profiles = [],
}) {
  const { run, notify } = useWorkspace();
  const [p, setP] = useState(copy(profile)),
    [key, setKey] = useState(""),
    [remember, setRemember] = useState(profile.key_storage === "system"),
    [clear, setClear] = useState(false);
  const [bindings, setBindings] = useState(ownedBindings),
    [saving, setSaving] = useState(false);
  const set = (k, v) => setP((p) => ({ ...p, [k]: v }));
  return (
    <div className="modal-shade">
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="连接与密钥"
      >
        <div className="modal-heading">
          <h2>连接与密钥</h2>
          <button
            className="icon quiet"
            aria-label="关闭连接设置"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>
        {!imageOnly && (
          <label className="check-row">
            <input
              type="checkbox"
              checked={!!p.structured_output}
              onChange={(e) => set("structured_output", e.target.checked)}
            />
            此服务明确支持 JSON 对象输出模式（不支持时请勿启用）
          </label>
        )}
        <label>
          配置名称
          <input
            aria-label="连接名称"
            value={p.name}
            onChange={(e) => set("name", e.target.value)}
          />
        </label>
        <label>
          类型
          <select value={p.kind} onChange={(e) => set("kind", e.target.value)}>
            {imageOnly ? (
              <>
                <option value="comfy">本地 / 远端 ComfyUI</option>
                <option value="image_api">图片 · OpenAI 兼容 API</option>
              </>
            ) : (
              <>
                <option value="demo">演示（不联网）</option>
                <option value="openai">文本 / 视觉 · OpenAI 兼容</option>
              </>
            )}
          </select>
        </label>
        {p.kind !== "demo" && (
          <>
            <label>
              服务地址
              <input
                aria-label="连接地址"
                value={p.endpoint || ""}
                onChange={(e) => set("endpoint", e.target.value)}
                placeholder="http://127.0.0.1:11434/v1"
              />
            </label>
            <label>
              模型标识
              <input
                aria-label="连接模型"
                value={p.model || ""}
                onChange={(e) => set("model", e.target.value)}
              />
            </label>
            <label>
              API 密钥（留空保留既有凭据）
              <input
                type="password"
                autoComplete="off"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder={
                  p.id === profile.id && profile.key_set
                    ? "已设置，不回显"
                    : "本地无鉴权服务可留空"
                }
              />
            </label>
            <label className="check-row">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
              />
              保存到系统安全凭据库，否则仅本次会话有效
            </label>
            <label className="check-row">
              <input
                type="checkbox"
                checked={clear}
                onChange={(e) => setClear(e.target.checked)}
              />
              清除此连接的密钥
            </label>
            {!imageOnly && (
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={!!p.vision}
                  onChange={(e) => set("vision", e.target.checked)}
                />
                该模型支持图片输入（视觉任务）
              </label>
            )}
          </>
        )}
        {catalog && (
          <fieldset className="connection-bindings">
            <legend>默认对应节点</legend>
            {catalog
              .filter((c) => c.kind === (imageOnly ? "image" : "language"))
              .map((c) => (
                <label className="check-row" key={c.id}>
                  <input
                    type="checkbox"
                    aria-label={"绑定 " + c.id}
                    checked={bindings.includes(c.id)}
                    onChange={(e) =>
                      setBindings((v) =>
                        e.target.checked
                          ? [...v, c.id]
                          : v.filter((k) => k !== c.id),
                      )
                    }
                  />
                  {c.name}
                  {owners[c.id] && owners[c.id] !== p.id && (
                    <small>
                      当前：
                      {profiles.find((x) => x.id === owners[c.id])?.name ||
                        "其他连接"}
                    </small>
                  )}
                </label>
              ))}
            <p className="muted small">
              勾选将设为该节点默认；生图时仍可临时选择。取消独立绑定后使用默认连接；无默认时保持未配置。
            </p>
          </fieldset>
        )}
        <p className="muted small">
          每个连接有独立凭据槽。保存后不会自动发送测试请求，也不会切换备用服务。
        </p>
        <div className="actions separated">
          <button
            className="primary"
            disabled={saving}
            onClick={async () => {
              const conflicts = bindings.filter(
                (k) => owners[k] && owners[k] !== p.id,
              );
              if (
                conflicts.length &&
                !window.confirm(
                  "将替换以下节点的默认连接：" +
                    conflicts
                      .map((k) => catalog.find((c) => c.id === k)?.name)
                      .join("、") +
                    "。继续吗？",
                )
              )
                return;
              setSaving(true);
              const data = { profile: p, remember, bindings };
              if (key || clear) data.key = clear ? "" : key;
              const ok = await run(
                catalog ? "connection_card_save" : "connection_save",
                data,
              );
              setSaving(false);
              if (ok) {
                notify(
                  catalog
                    ? "连接及默认节点绑定已保存"
                    : "连接已保存，请保存当前任务以完成绑定",
                );
                onSaved(p.id);
              }
            }}
          >
            保存独立连接
          </button>
          <button
            onClick={() => {
              const next = {
                ...p,
                id: "conn-" + freshId(),
                name: p.name + " · 独立副本",
              };
              setP(next);
              setBindings([]);
              setRemember(false);
              setKey("");
              setClear(false);
              notify("已改为独立副本，保存时不会复制原密钥。");
            }}
          >
            复制为独立连接
          </button>
        </div>
      </section>
    </div>
  );
}
