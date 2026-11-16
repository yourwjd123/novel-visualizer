import React, { useState } from "react";
import { useWorkspace } from "./context";
export default function PromptManager({ onClose }) {
  const { s, run, notify } = useWorkspace();
  const [scope, setScope] = useState("language"),
    [text, setText] = useState(s.settings.language_preface || ""),
    [inherit, setInherit] = useState(false);
  const options = [
    ["language", "默认语言前置提示词"],
    ["image", "默认生图前置提示词"],
    ["advice", "第一轮：建卡建议"],
    ["completion", "AI补全固定指导"],
    ...s.nodes.flatMap((name, n) =>
      n === 3
        ? [["prefix:" + n, "方案扩写前置提示词"]]
        : [
            ["task:" + n, "任务模板：" + name],
            ["prefix:" + n, "节点前置：" + name],
          ],
    ),
  ];
  function select(key) {
    setScope(key);
    const [kind, id] = key.split(":");
    const defaults = s.defaults[id] || {};
    setInherit(!defaults.preface_override);
    setText(
      key === "language"
        ? s.settings.language_preface || ""
        : key === "image"
          ? s.image_settings.preface || ""
          : key === "advice"
            ? s.settings.asset_advice_prompt || s.asset_advice_default || ""
            : key === "completion"
              ? s.settings.completion_guidance ||
                s.completion_guidance_default ||
                ""
              : kind === "prefix"
                ? defaults.preface || ""
                : defaults.template?.body ||
                  s.templates.find((t) => t.node === Number(id))?.body ||
                  "",
    );
  }
  async function save() {
    let ok;
    const [kind, id] = scope.split(":");
    if (scope === "language")
      ok = await run("settings", { language_preface: text });
    else if (scope === "image")
      ok = await run("image_settings", { ...s.image_settings, preface: text });
    else if (scope === "advice")
      ok = await run("settings", { asset_advice_prompt: text });
    else if (scope === "completion")
      ok = await run("settings", { completion_guidance: text });
    else if (kind === "prefix")
      ok = await run("node_settings", {
        node: Number(id),
        params: {
          ...s.defaults[id],
          preface: text,
          preface_override: !inherit,
        },
      });
    else {
      const template =
        s.defaults[id]?.template ||
        s.templates.find((t) => t.node === Number(id));
      ok = await run("node_settings", {
        node: Number(id),
        params: { ...s.defaults[id], template: { ...template, body: text } },
      });
    }
    if (ok) {
      notify("提示词已保存，对后续请求生效");
      onClose();
    }
  }
  return (
    <div className="modal-shade">
      <section className="modal" role="dialog" aria-label="提示词管理">
        <div className="modal-heading">
          <h2>设置 / 提示词管理</h2>
          <button onClick={onClose}>关闭</button>
        </div>
        <label>
          二级分类
          <select value={scope} onChange={(e) => select(e.target.value)}>
            {options.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </label>
        {scope.startsWith("prefix:") && (
          <label>
            <input
              type="checkbox"
              checked={inherit}
              onChange={(e) => setInherit(e.target.checked)}
            />
            继承默认前置提示词
          </label>
        )}
        <textarea
          aria-label="提示词编辑"
          rows={14}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <p className="muted small">
          前置提示词首位发送；修改任务文字不会改变程序读取的字段结构。自由咨询不带自动任务模板。
        </p>
        <button
          onClick={() => {
            if (scope === "advice") setText(s.asset_advice_default || "");
            else if (scope === "completion")
              setText(s.completion_guidance_default || "");
            else if (scope.startsWith("task:"))
              setText(
                s.templates.find((t) => t.node === Number(scope.split(":")[1]))
                  ?.body || "",
              );
            else setText("");
          }}
        >
          载入默认值（保存后生效）
        </button>
        <button className="primary" onClick={save}>
          保存提示词
        </button>
      </section>
    </div>
  );
}
