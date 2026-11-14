import React, { useState, useEffect } from "react";
import { Plus, X, Save, RotateCcw } from "lucide-react";
import { useWorkspace, copy, freshId } from "./context";
import { PageHeading } from "./App";
import { api } from "./api";

export default function SettingsPage() {
  const { s, run, notify, dirty } = useWorkspace();
  const [section, setSection] = useState("language"),
    [node, setNode] = useState(0),
    [params, setParams] = useState(null),
    [editor, setEditor] = useState(null),
    [task, setTask] = useState("illustration"),
    [image, setImage] = useState(null),
    [appearance, setAppearance] = useState(copy(s.settings)),
    [rules, setRules] = useState(s.rules || "");
  async function loadNode(n) {
    try {
      setParams(await api("node_parameters", { node: n }));
      dirty.current = false;
    } catch (e) {
      notify(e.message);
    }
  }
  useEffect(() => {
    loadNode(node);
  }, [node, s.account.id]);
  useEffect(() => {
    setImage({
      ...s.image_settings,
      ...s.image_settings.tasks?.[task],
      connection_id:
        s.image_settings.tasks?.[task]?.connection_id ||
        s.image_settings.connection_id ||
        "image-default",
    });
  }, [task, s.image_settings]);
  const canLeave = () =>
    !dirty.current || window.confirm("有尚未保存的设置，放弃这些修改吗？");
  const connections = s.connections.filter((c) =>
    section === "language"
      ? ["demo", "openai"].includes(c.kind)
      : ["comfy", "image_api"].includes(c.kind),
  );
  const connection = connections.find(
    (c) =>
      c.id ===
      (section === "language" ? params?.connection_id : image?.connection_id),
  );
  function setParam(k, v) {
    setParams((p) => ({ ...p, [k]: v }));
    dirty.current = true;
  }
  function setImageField(k, v) {
    setImage((p) => ({ ...p, [k]: v }));
    dirty.current = true;
  }
  async function saveLanguage() {
    if (!params?.connection_id) {
      notify("请选择此节点的独立连接");
      return;
    }
    if (await run("node_settings", { node, params })) {
      dirty.current = false;
      notify("此节点的独立连接与提示词已保存，对后续调用生效");
    }
  }
  async function saveImage() {
    if (!image?.connection_id) {
      notify("请为当前图片任务选择连接");
      return;
    }
    try {
      if (image.workflow?.trim()) JSON.parse(image.workflow);
      if (image.mapping?.trim()) JSON.parse(image.mapping);
    } catch {
      notify("工作流或映射不是有效 JSON");
      return;
    }
    const next = {
      ...s.image_settings,
      tasks: { ...s.image_settings.tasks, [task]: image },
    };
    if (task === "illustration")
      Object.assign(next, image, { tasks: next.tasks });
    if (await run("image_settings", next)) {
      dirty.current = false;
      notify("当前图片任务配置已保存");
    }
  }
  return (
    <>
      <PageHeading
        title="设置"
        subtitle="语言与图片连接分开配置；账户之间独立保存，密钥不随设置导出。"
      />
      <div className="settings-tabs">
        {[
          ["language", "语言模型配置"],
          ["image", "图片模型配置"],
          ["appearance", "外观与项目规则"],
          ["transfer", "导入与导出"],
        ].map(([id, label]) => (
          <button
            className={section === id ? "active" : ""}
            key={id}
            onClick={() => {
              if (canLeave()) {
                dirty.current = false;
                setSection(id);
              }
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {section === "language" && params && (
        <section className="settings-sheet">
          <label>
            任务节点
            <select
              aria-label="语言模型任务节点"
              value={node}
              onChange={(e) => {
                if (canLeave()) setNode(Number(e.target.value));
              }}
            >
              {[0, 1, 5, 2, 3, 4, 6, 7].map((n) => (
                <option key={n} value={n}>
                  {s.nodes[n]}
                  {n === 7 ? "（可选）" : ""}
                </option>
              ))}
            </select>
          </label>
          <div className="connection-row">
            <label>
              此节点独立连接
              <select
                value={params.connection_id || ""}
                onChange={(e) => setParam("connection_id", e.target.value)}
              >
                {connections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <button onClick={() => setEditor(connection)}>
              编辑连接 / 密钥
            </button>
            <button
              onClick={() =>
                setEditor({
                  id: "conn-" + freshId(),
                  name: s.nodes[node] + "连接",
                  kind: "openai",
                  endpoint: "http://127.0.0.1:11434/v1",
                  model: "",
                  vision: node === 6,
                  max_tokens: 4096,
                  temperature: 0.5,
                })
              }
            >
              <Plus size={14} />
              新建
            </button>
          </div>
          <p className="muted small">
            {connection?.kind === "demo"
              ? "演示连接 · 不联网，不代表真实解析"
              : connection?.endpoint +
                " · " +
                (connection?.model || "未填写模型")}{" "}
            ·{" "}
            {connection?.key_set
              ? "已保存独立凭据"
              : "未配置密钥（本地服务可留空）"}
          </p>
          <div className="field-pair">
            <label>
              最大输出 token
              <input
                type="number"
                min={1}
                max={131072}
                value={params.max_tokens}
                onChange={(e) => setParam("max_tokens", Number(e.target.value))}
              />
            </label>
            <label>
              温度
              <input
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={params.temperature}
                onChange={(e) =>
                  setParam("temperature", Number(e.target.value))
                }
              />
            </label>
          </div>
          <label>
            任务模板
            <select
              value={params.template.id}
              onChange={(e) => {
                const t = s.templates.find(
                  (t) => t.id === e.target.value && t.node === node,
                );
                if (t) setParam("template", copy(t));
              }}
            >
              {s.templates
                .filter((t) => t.node === node)
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            模板名称
            <input
              value={params.template.name}
              onChange={(e) =>
                setParam("template", {
                  ...params.template,
                  name: e.target.value,
                })
              }
            />
          </label>
          <label>
            背景提示词 / 任务目标
            <textarea
              rows={12}
              value={params.template.body}
              onChange={(e) =>
                setParam("template", {
                  ...params.template,
                  body: e.target.value,
                })
              }
            />
          </label>
          <label>
            节点补充要求
            <textarea
              rows={4}
              value={params.supplement || ""}
              onChange={(e) => setParam("supplement", e.target.value)}
            />
          </label>
          <p className="muted small">
            任务输出约定：{params.template.format}
            。通用规则与项目规则也会附带，可在 AI 助手“本次输入”查看。
          </p>
          <div className="actions separated">
            <button className="primary" onClick={saveLanguage}>
              <Save size={14} />
              保存此节点配置
            </button>
            <button
              onClick={async () => {
                const t = {
                  ...params.template,
                  id: "custom-" + freshId(),
                  node,
                  version: "用户自定义",
                };
                if (await run("save_template", { template: t })) {
                  setParam("template", t);
                  notify("已新增到账户模板库，请保存节点以绑定");
                }
              }}
            >
              新增为个人模板
            </button>
            <button
              onClick={async () => {
                if (
                  window.confirm("恢复此节点内置提示词？个人模板不删除。") &&
                  (await run("reset_template", { node }))
                )
                  loadNode(node);
              }}
            >
              <RotateCcw size={13} />
              恢复内置提示词
            </button>
          </div>
        </section>
      )}
      {section === "image" && image && (
        <section className="settings-sheet">
          <label>
            图片任务
            <select
              value={task}
              onChange={(e) => {
                if (canLeave()) {
                  dirty.current = false;
                  setTask(e.target.value);
                }
              }}
            >
              <option value="illustration">场景插图生成</option>
              <option>人物</option>
              <option>场景</option>
              <option>道具</option>
            </select>
          </label>
          <div className="connection-row">
            <label>
              独立图片连接
              <select
                value={image.connection_id || "image-default"}
                onChange={(e) => setImageField("connection_id", e.target.value)}
              >
                {connections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <button onClick={() => setEditor(connection || connections[0])}>
              编辑配置 / 密钥
            </button>
            <button
              onClick={() =>
                setEditor({
                  id: "image-" + freshId(),
                  name: "独立图片连接",
                  kind: "comfy",
                  endpoint: "http://127.0.0.1:8188",
                  model: "",
                  vision: false,
                  max_tokens: 4096,
                  temperature: 0.5,
                })
              }
            >
              新建图片连接
            </button>
          </div>
          <p className="muted small">
            图片任务不借用语言模型密钥。兼容图片 API
            当前仅文生图；参考图输入请使用已映射的 ComfyUI 工作流。
          </p>
          <div className="field-pair">
            <label>
              输出尺寸（图片 API）
              <select
                value={image.size || "1024x1024"}
                onChange={(e) => setImageField("size", e.target.value)}
              >
                <option>1024x1024</option>
                <option>1536x1024</option>
                <option>1024x1536</option>
                <option>1792x1024</option>
                <option>1024x1792</option>
              </select>
            </label>
            <label>
              Seed（ComfyUI）
              <input
                type="number"
                value={image.seed ?? 42}
                onChange={(e) => setImageField("seed", Number(e.target.value))}
              />
            </label>
          </div>
          <label>
            ComfyUI API 工作流
            <textarea
              className="code"
              rows={10}
              value={image.workflow || ""}
              onChange={(e) => setImageField("workflow", e.target.value)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={async (e) => {
                e.preventDefault();
                const file = e.dataTransfer.files[0];
                if (file?.name.endsWith(".json"))
                  setImageField("workflow", await file.text());
              }}
              placeholder="粘贴或拖入 API 格式 JSON；不是编辑器格式"
            />
          </label>
          <label>
            导入工作流 JSON
            <input
              type="file"
              accept=".json"
              onChange={async (e) => {
                if (e.target.files[0])
                  setImageField("workflow", await e.target.files[0].text());
              }}
            />
          </label>
          <label>
            节点映射
            <textarea
              className="code"
              rows={5}
              value={image.mapping || ""}
              onChange={(e) => setImageField("mapping", e.target.value)}
              placeholder={
                '{"prompt":["6","text"],"seed":["3","seed"],"reference_1":["10","image"]}'
              }
            />
          </label>
          <p className="muted small">
            reference_1、reference_2
            等按场景关联卡顺序对应。未映射的参考图不会上传，生成前会提示。
          </p>
          <label>
            默认生成约束
            <textarea
              rows={5}
              value={image.generation_rules || ""}
              onChange={(e) =>
                setImageField("generation_rules", e.target.value)
              }
              placeholder="只作用于此图片任务，不与人物三视图、空环境图等模板混用"
            />
          </label>
          <button className="primary" onClick={saveImage}>
            保存此图片任务配置
          </button>
        </section>
      )}
      {section === "appearance" && (
        <section className="settings-sheet">
          <div className="notice">
            显示跟随系统 DPI
            与显示缩放，窗口尺寸变化时重新排布卡片；不会将界面固定为 1920×1080。
          </div>
          <label>
            主题
            <select
              value={appearance.theme}
              onChange={(e) => {
                setAppearance({ ...appearance, theme: e.target.value });
                dirty.current = true;
              }}
            >
              <option value="system">跟随系统</option>
              <option value="light">明亮</option>
              <option value="dark">暗色</option>
            </select>
          </label>
          <label>
            界面字号
            <input
              type="number"
              min={11}
              max={24}
              value={appearance.font_size}
              onChange={(e) => {
                setAppearance({
                  ...appearance,
                  font_size: Number(e.target.value),
                });
                dirty.current = true;
              }}
            />
          </label>
          <div className="actions">
            <button onClick={() => run("background")}>
              选择自定义背景图片
            </button>
            <button
              onClick={async () => {
                if (await run("reset_appearance")) {
                  const next = await api("state");
                  setAppearance(copy(next.settings));
                  dirty.current = false;
                }
              }}
            >
              一键恢复纯色与默认外观
            </button>
          </div>
          <label>
            背景可见度 {appearance.background_opacity}%
            <input
              type="range"
              min={0}
              max={60}
              value={appearance.background_opacity}
              onChange={(e) => {
                setAppearance({
                  ...appearance,
                  background_opacity: Number(e.target.value),
                });
                dirty.current = true;
              }}
            />
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={appearance.confirm_attachments}
              onChange={(e) => {
                setAppearance({
                  ...appearance,
                  confirm_attachments: e.target.checked,
                });
                dirty.current = true;
              }}
            />
            真实 API 调用含附件时确认大小（包括历史附件）；纯文本默认不提示
          </label>
          <label>
            当前项目补充规则
            <textarea
              rows={5}
              value={rules}
              onChange={(e) => {
                setRules(e.target.value);
                dirty.current = true;
              }}
            />
          </label>
          <button
            className="primary"
            onClick={async () => {
              if (await run("settings", { ...appearance, rules })) {
                dirty.current = false;
                notify("外观、附件提示和项目规则已保存");
              }
            }}
          >
            保存外观与规则
          </button>
        </section>
      )}
      {section === "transfer" && (
        <section className="settings-sheet">
          <h2>账户设置</h2>
          <p className="muted prose">
            导出模板、节点与图片配置，严格排除凭据。导入后生成新的连接
            ID，需重新填写地址和密钥。
          </p>
          <div className="actions">
            <button onClick={() => run("export_settings")}>导出账户设置</button>
            <button onClick={() => run("import_settings")}>导入账户设置</button>
            <button onClick={() => run("reveal")}>打开资料目录</button>
          </div>
          <div className="separated">
            <h2>测试版本与许可</h2>
            <p className="muted small prose">
              v0.4.0-beta.1 · GPL-3.0。UI 标签交互与纸墨基础参考
              Pagekin；视觉资产卡参考 Story Asset
              Studio（MIT）。对应版权和完整许可随源码提供。此应用只做已有文本可视化，不提供小说创作功能。
            </p>
          </div>
        </section>
      )}
      {editor && (
        <ConnectionEditor
          key={editor.id}
          profile={editor}
          imageOnly={section === "image"}
          onClose={() => setEditor(null)}
          onSaved={(id) => {
            setEditor(null);
            if (section === "language") setParam("connection_id", id);
            else setImageField("connection_id", id);
          }}
        />
      )}
    </>
  );
}

function ConnectionEditor({ profile, imageOnly, onClose, onSaved }) {
  const { run, notify } = useWorkspace();
  const [p, setP] = useState(copy(profile)),
    [key, setKey] = useState(""),
    [remember, setRemember] = useState(false),
    [clear, setClear] = useState(false);
  const set = (k, v) => setP((p) => ({ ...p, [k]: v }));
  return (
    <div className="modal-shade">
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="独立连接与密钥"
      >
        <div className="modal-heading">
          <h2>独立连接与密钥</h2>
          <button
            className="icon quiet"
            aria-label="关闭连接设置"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>
        <label>
          配置名称
          <input value={p.name} onChange={(e) => set("name", e.target.value)} />
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
                value={p.endpoint || ""}
                onChange={(e) => set("endpoint", e.target.value)}
                placeholder="http://127.0.0.1:11434/v1"
              />
            </label>
            <label>
              模型标识
              <input
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
                  profile.key_set ? "已设置，不回显" : "本地无鉴权服务可留空"
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
        <p className="muted small">
          每个连接有独立凭据槽。保存后不会自动发送测试请求，也不会切换备用服务。
        </p>
        <div className="actions separated">
          <button
            className="primary"
            onClick={async () => {
              const data = { profile: p, remember };
              if (key || clear) data.key = clear ? "" : key;
              const ok = await run("connection_save", data);
              if (ok) {
                notify("连接已保存，请保存当前任务以完成绑定");
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
