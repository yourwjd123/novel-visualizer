import React, { useState, useEffect, useRef } from "react";
import { Plus, X, Save, RotateCcw } from "lucide-react";
import { useWorkspace, copy, freshId } from "./context";
import { PageHeading } from "./App";
import { BookTrash } from "./BookManagement";
import ConnectionsPanel from "./ConnectionsPanel";
import WorkflowPresets from "./WorkflowPresets";
import ConnectionEditor from "./ConnectionEditor";
import PromptManager from "./PromptManager";
import { api } from "./api";

export default function SettingsPage() {
  const { s, run, refresh, notify, dirty } = useWorkspace();
  const [promptManager, setPromptManager] = useState(false);
  const [customKind, setCustomKind] = useState("language");
  useEffect(() => {
    setShared((v) => ({
      ...v,
      language_connection_id: s.settings.language_connection_id,
    }));
  }, [s.settings.language_connection_id]);
  const [shared, setShared] = useState({ ...s.settings });
  const [section, setSection] = useState("language"),
    [node, setNode] = useState(0),
    [params, setParams] = useState(null),
    [editor, setEditor] = useState(null),
    [task, setTask] = useState("illustration"),
    [image, setImage] = useState(null),
    [appearance, setAppearance] = useState(copy(s.settings));
  const textMode =
    section === "language" ||
    (section === "custom" && customKind === "language");
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
  }, [
    node,
    s.account.id,
    JSON.stringify(s.defaults?.[String(node)]),
    s.settings.language_connection_id,
  ]);
  useEffect(() => {
    setImage({
      ...s.image_settings,
      ...(section === "custom" ? s.image_settings.tasks?.[task] : {}),
      connection_id:
        (section === "custom"
          ? s.image_settings.tasks?.[task]?.connection_id
          : "") ||
        s.image_settings.connection_id ||
        "image-default",
    });
  }, [task, JSON.stringify(s.image_settings), section, customKind]);
  const inference = useRef(0);
  useEffect(() => {
    inference.current++;
  }, [section, task, image?.connection_id]);
  useEffect(
    () => () => {
      inference.current++;
    },
    [],
  );
  async function importWorkflow(text) {
    const seq = ++inference.current;
    setImageField("workflow", text);
    try {
      let result = await api("workflow_inspect", { workflow: text });
      while (!result.done && seq === inference.current) {
        await new Promise((resolve) => setTimeout(resolve, 350));
        result = await api("workflow_inspect_status");
      }
      if (seq !== inference.current) return;
      setImage((p) => ({
        ...p,
        workflow: text,
        mapping: JSON.stringify(result.mapping, null, 2),
      }));
      notify(
        result.warnings?.length
          ? result.warnings.join("；")
          : "映射已自动填入，可自行修改",
      );
    } catch (e) {
      notify(e.message);
    }
  }
  const canLeave = () =>
    !dirty.current || window.confirm("有尚未保存的设置，放弃这些修改吗？");
  const connections = s.connections
    .filter((c) =>
      textMode
        ? ["demo", "openai"].includes(c.kind)
        : ["comfy", "image_api"].includes(c.kind),
    )
    .filter(
      (c) =>
        section !== "language" ||
        c.kind !== "demo" ||
        c.id === "node-0" ||
        c.id === shared.language_connection_id,
    );
  const connection = connections.find(
    (c) =>
      c.id ===
      (textMode
        ? section === "language"
          ? shared.language_connection_id
          : params?.connection_id
        : image?.connection_id),
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
      notify("节点提示词与继承／覆盖设置已保存，对后续调用生效");
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
    const next =
      section === "image"
        ? { ...image, tasks: s.image_settings.tasks || {} }
        : {
            ...s.image_settings,
            tasks: { ...s.image_settings.tasks, [task]: image },
          };
    if (await run("image_settings", next)) {
      dirty.current = false;
      notify("当前图片任务配置已保存");
    }
  }
  return (
    <>
      {promptManager && (
        <PromptManager onClose={() => setPromptManager(false)} />
      )}
      <PageHeading
        actions={
          <button onClick={() => setPromptManager(true)}>提示词管理</button>
        }
        title="设置"
        subtitle="语言与图片连接分开配置；账户之间独立保存，密钥不随设置导出。"
      />
      <div className="settings-tabs">
        {[
          ["language", "语言模型配置"],
          ["image", "生图模型配置"],
          ["custom", "自定义节点接口"],
          ["ai_options", "AI 选项"],
          ["appearance", "外观"],
          ["transfer", "导入与导出"],
          ["book_trash", "小说回收站"],
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
      {section === "book_trash" && <BookTrash />}
      {section === "ai_options" && (
        <section className="settings-sheet">
          <h2>工作流映射</h2>
          <label className="check-row">
            <input
              type="checkbox"
              checked={!!s.settings.workflow_ai_assist}
              onChange={(e) =>
                run("settings", { workflow_ai_assist: e.target.checked })
              }
            />
            使用默认语言模型辅助解析工作流映射
          </label>
          <p className="muted">
            默认关闭，仅本地解析。开启后在导入或主动识别时调用默认语言模型，只发送节点结构，不附带原文、历史对话、图片或旧提示词。
          </p>
          <h2>情节与资产关联</h2>
          <label>
            关联方式
            <select
              aria-label="资产关联方式"
              value={s.settings.asset_association_mode || "ai"}
              onChange={(e) =>
                run("settings", { asset_association_mode: e.target.value })
              }
            >
              <option value="ai">AI 关联（默认，与情节拆分同次调用）</option>
              <option value="local">本地名称／别名匹配</option>
              <option value="manual">仅手工关联</option>
            </select>
          </label>
          <p>
            AI
            使用简短资产索引识别第一人称、代词和间接称谓，不新建资产；不确定可留空。修改对后续操作生效，不会自动重跑旧章节。手工增删关联保留；关联不等于必须出镜。
          </p>
          <p className="muted">
            本地匹配不调用模型，但无法判断代词含义。可在情节卡中随时手动修正。
          </p>
        </section>
      )}
      {section === "language" && (
        <section className="settings-sheet">
          <h2>默认大语言模型</h2>
          <p className="muted">
            所有文本节点默认使用此连接；API
            与本地兼容服务均可。各节点的任务提示词保持独立。
          </p>
          <ConnectionsPanel category="language" />
          <div className="field-pair">
            <label>
              默认最大输出 token
              <input
                type="number"
                min="1"
                max="131072"
                value={shared.language_max_tokens}
                onChange={(e) => {
                  setShared({
                    ...shared,
                    language_max_tokens: Number(e.target.value),
                  });
                  dirty.current = true;
                }}
              />
            </label>
            <label>
              默认温度
              <input
                type="number"
                min="0"
                max="2"
                step="0.1"
                value={shared.language_temperature}
                onChange={(e) => {
                  setShared({
                    ...shared,
                    language_temperature: Number(e.target.value),
                  });
                  dirty.current = true;
                }}
              />
            </label>
          </div>
          <label>
            用户前置提示词（首位发送，所有文本任务默认继承）
            <textarea
              aria-label="默认语言前置提示词"
              rows={5}
              value={shared.language_preface || ""}
              onChange={(e) => {
                setShared({ ...shared, language_preface: e.target.value });
                dirty.current = true;
              }}
            />
          </label>
          <label>
            AI补全固定指导（可编辑）
            <textarea
              aria-label="AI补全指导"
              rows={6}
              value={
                shared.completion_guidance ||
                s.completion_guidance_default ||
                ""
              }
              onChange={(e) => {
                setShared({ ...shared, completion_guidance: e.target.value });
                dirty.current = true;
              }}
            />
          </label>
          <p className="muted small">
            自动任务、咨询和补全均为单轮请求，不发送历史对话。咨询只附带本章梗概及本轮问题；补全另带当前编辑对象全文和固定指导。
          </p>
          <button
            className="primary"
            onClick={async () => {
              if (!shared.language_connection_id)
                return notify("请选择默认语言连接");
              if (
                await run("settings", {
                  language_connection_id: shared.language_connection_id,
                  language_max_tokens: shared.language_max_tokens,
                  language_temperature: shared.language_temperature,
                  language_preface: shared.language_preface || "",
                  completion_guidance:
                    shared.completion_guidance ||
                    s.completion_guidance_default ||
                    "",
                })
              ) {
                for (let n = 0; n < s.nodes.length; n++) {
                  const previous = s.defaults[String(n)] || {};
                  if (
                    previous.connection_override !== true &&
                    !previous.connection_id
                  )
                    await run(
                      "node_settings",
                      {
                        node: n,
                        params: {
                          ...previous,
                          connection_override: false,
                          parameter_override: false,
                        },
                      },
                      false,
                    );
                }
                await refresh();
                dirty.current = false;
                notify("默认语言配置已保存；未启用自定义覆盖的节点自动继承");
              }
            }}
          >
            保存默认语言配置
          </button>
        </section>
      )}
      {section === "custom" && (
        <div className="actions separated">
          <button
            onClick={() => {
              if (canLeave()) {
                setCustomKind("language");
                dirty.current = false;
              }
            }}
          >
            文本节点与提示词
          </button>
          <button
            onClick={() => {
              if (canLeave()) {
                setCustomKind("image");
                dirty.current = false;
              }
            }}
          >
            生图节点
          </button>
          <span className="muted small">
            未启用覆盖时继承对应默认接口；旧版独立配置仍保留。
          </span>
        </div>
      )}
      {section === "custom" && customKind === "language" && params && (
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
                  {n === 7 ? "实时咨询" : s.nodes[n]}
                </option>
              ))}
            </select>
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={!!params.connection_override}
              onChange={(e) =>
                setParam("connection_override", e.target.checked)
              }
            />
            为此节点启用独立接口（否则继承默认语言模型）
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={params.parameter_override !== false}
              onChange={(e) => setParam("parameter_override", e.target.checked)}
            />
            为此节点启用独立输出上限和温度
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
          <label className="check-row">
            <input
              type="checkbox"
              checked={!!params.preface_override}
              onChange={(e) => setParam("preface_override", e.target.checked)}
            />
            使用此节点独立前置提示词（关闭时继承默认；启用后可明确留空）
          </label>
          <label>
            节点前置提示词
            <textarea
              rows={4}
              value={params.preface || ""}
              onChange={(e) => setParam("preface", e.target.value)}
            />
          </label>
          {node === 7 && (
            <p className="notice">
              实时咨询仅使用此节点前置提示词、本章梗概与本轮问题；下方自动任务模板及补充要求不参与咨询请求。
            </p>
          )}
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
            。任务提示词仅用于自动任务；自由咨询不会附带。前置提示词始终位于任务规则之前。
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
      {(section === "image" ||
        (section === "custom" && customKind === "image")) &&
        image && (
          <section className="settings-sheet">
            {section === "image" && (
              <p className="muted">
                默认承担人物、场景、道具参考图和场景插图。支持云端 API 或本地
                ComfyUI。节点覆盖在“自定义节点接口”中设置。
              </p>
            )}
            {section === "custom" && (
              <>
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={
                      image.connection_override ??
                      !!s.image_settings.tasks?.[task]?.connection_id
                    }
                    onChange={(e) =>
                      setImageField("connection_override", e.target.checked)
                    }
                  />
                  为此图片任务启用独立配置
                </label>
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
              </>
            )}
            {section === "image" ? (
              <ConnectionsPanel category="image" />
            ) : (
              <>
                {" "}
                <div className="connection-row">
                  <label>
                    {section === "image" ? "默认图片连接" : "独立图片连接"}
                    <select
                      value={image.connection_id || "image-default"}
                      onChange={(e) =>
                        setImageField("connection_id", e.target.value)
                      }
                    >
                      {connections.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    onClick={() => setEditor(connection || connections[0])}
                  >
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
              </>
            )}
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
                  onChange={(e) =>
                    setImageField("seed", Number(e.target.value))
                  }
                />
              </label>
            </div>
            {section === "custom" && (
              <WorkflowPresets
                connection={connection}
                image={image}
                setImageField={setImageField}
                onEditConnection={setEditor}
              />
            )}
            <details className="legacy-workflow">
              <summary>旧版工作流与手动映射（兼容保留）</summary>
              <label>
                ComfyUI API 工作流
                <textarea
                  className="code"
                  rows={10}
                  value={image.workflow || ""}
                  onPaste={(e) => {
                    const text = e.clipboardData.getData("text");
                    try {
                      JSON.parse(text);
                      e.preventDefault();
                      importWorkflow(text);
                    } catch {}
                  }}
                  onChange={(e) => setImageField("workflow", e.target.value)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={async (e) => {
                    e.preventDefault();
                    const file = e.dataTransfer.files[0];
                    if (file?.name.endsWith(".json"))
                      importWorkflow(await file.text());
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
                      importWorkflow(await e.target.files[0].text());
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
            </details>
            {section === "custom" && (
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={!!image.preface_override}
                  onChange={(e) =>
                    setImageField("preface_override", e.target.checked)
                  }
                />
                使用此生图节点独立前置提示词
              </label>
            )}
            <label>
              用户前置提示词（作为生图提示词首段或工作流 prompt 输入）
              <textarea
                aria-label="生图前置提示词"
                rows={5}
                value={image.preface ?? image.generation_rules ?? ""}
                onChange={(e) => setImageField("preface", e.target.value)}
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
          {s.rules && (
            <details>
              <summary>旧项目规则存档（不再发送）</summary>
              <pre>{s.rules}</pre>
              <p>可复制到接口前置提示词中，不会自动迁移或重复发送。</p>
            </details>
          )}
          <button
            className="primary"
            onClick={async () => {
              if (
                await run("settings", {
                  theme: appearance.theme,
                  background_opacity: appearance.background_opacity,
                  font_size: appearance.font_size,
                  confirm_attachments: appearance.confirm_attachments,
                })
              ) {
                dirty.current = false;
                notify("外观与附件提示已保存");
              }
            }}
          >
            保存外观
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
              v0.12.0-beta.1 · GPL-3.0。UI 标签交互与纸墨基础参考
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
          imageOnly={!textMode}
          onClose={() => setEditor(null)}
          onSaved={(id) => {
            setEditor(null);
            if (textMode) {
              if (section === "language")
                setShared((v) => ({ ...v, language_connection_id: id }));
              else setParam("connection_id", id);
            } else setImageField("connection_id", id);
          }}
        />
      )}
    </>
  );
}
