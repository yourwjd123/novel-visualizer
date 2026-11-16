import React, { useState, useEffect, useRef } from "react";
import { api } from "./api";
import { useWorkspace } from "./context";
import { PageHeading, Empty } from "./App";
import ImageCard from "./components/ImageCard";

export function RenderEditor({ asset = null }) {
  const { s, run, notify, dirty, openCompletion } = useWorkspace();
  const [state, setState] = useState(null),
    [text, setText] = useState(""),
    [name, setName] = useState(""),
    [changed, setChanged] = useState(false),
    [preview, setPreview] = useState(null),
    [exported, setExported] = useState("");
  const latest = useRef("");
  latest.current = text;
  const key = asset ? "asset_" + asset : "scene_" + s.scene;
  const signature = JSON.stringify([
    s.scene,
    s.segment,
    s.assets.map((a) => [a.id, a.revision]),
    s.requirements,
    s.cast_omissions,
    s.scene_variant_choices,
    s.chapter_variant_choices,
    s.overrides,
  ]);
  useEffect(() => {
    let alive = true;
    api("render_state", { asset })
      .then((v) => {
        if (!alive) return;
        setState(v);
        setText(v.text || "");
        setName(v.saved.name || v.name);
        setChanged(false);
        dirty.current = false;
        setPreview(null);
        setExported("");
      })
      .catch((e) => notify(e.message));
    return () => {
      alive = false;
    };
  }, [key]);
  useEffect(() => {
    let alive = true;
    api("render_state", { asset })
      .then((v) => {
        if (!alive) return;
        setState(v);
      })
      .catch((e) => notify(e.message));
    return () => {
      alive = false;
    };
  }, [signature]);
  const node = asset ? 5 : 2;
  const proposal = s.jobs.find(
    (j) =>
      j.mode === "task" &&
      j.node === node &&
      (asset ? j.asset === asset : j.scene === s.scene),
  );
  async function save() {
    if (
      state?.stale &&
      !window.confirm(
        "资产或参考图已变化。已核对当前方案及参考图编号，采用当前清单保存吗？",
      )
    )
      return false;
    const result = await run("save_render_plan", { asset, text, name });
    if (result) {
      setChanged(false);
      dirty.current = false;
      return true;
    }
    return false;
  }
  function edit(v) {
    setText(v);
    setChanged(true);
    dirty.current = true;
    setPreview(null);
  }
  async function exportFiles() {
    if (!(await save())) return;
    const result = await run("export_render", { asset, text, name });
    if (result) {
      setExported(result.path);
      notify("生图素材已保存：" + result.path);
    }
  }
  return (
    <section
      className="render-editor"
      aria-label={asset ? "资产图方案工作区" : "场景图方案工作区"}
    >
      <div className="section-heading">
        <h2>生图方案（最终可提交文本）</h2>
        <button
          disabled={s.busy}
          onClick={() =>
            run("send", {
              node,
              asset,
              message:
                "生成可直接用于生图的最终画面描述，仅输出正文；使用提供的实际参考图编号，不输出分析、建议、推测或待确认清单。",
            })
          }
        >
          生成生图方案
        </button>
      </div>
      <label>
        拟生图名称
        <input
          aria-label="拟生图名称"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setChanged(true);
            dirty.current = true;
          }}
        />
      </label>
      {proposal?.output && (
        <details className="render-proposal">
          <summary>
            模型返回的方案
            {proposal.status === "invalid" ? "（需修正）" : "（待采用）"}
          </summary>
          <pre>{proposal.output}</pre>
          <button
            onClick={() => {
              if (
                text.trim() &&
                !window.confirm("载入方案将替换未保存的编辑，继续吗？")
              )
                return;
              edit(proposal.output);
            }}
          >
            载入生成方案
          </button>
          {proposal.validation_error && (
            <p className="notice warning">{proposal.validation_error}</p>
          )}
        </details>
      )}
      {(state?.stale || (changed && state?.saved?.text)) && (
        <p className="notice warning">
          方案或资产输入已有变化，请核对参考图编号并保存。
        </p>
      )}
      <textarea
        aria-label="最终生图方案"
        rows={10}
        value={text}
        onChange={(e) => edit(e.target.value)}
        onDragOver={(e) => e.preventDefault()}
        onDrop={async (e) => {
          e.preventDefault();
          for (const f of e.dataTransfer.files)
            if (/\.(txt|md)$/i.test(f.name))
              edit(latest.current + "\n" + (await f.text()));
        }}
        placeholder="仅描述要生成的画面，不包含推测、建议和待确认字段。"
      />
      <div className="actions">
        <button className="primary" onClick={save}>
          保存生图方案
        </button>
        <button
          disabled={s.busy}
          onClick={() =>
            openCompletion(
              { type: "prompt", id: key, text },
              ["text"],
              (changes, original) => {
                if (latest.current !== original.text) {
                  notify("方案已变化，请重新扩写");
                  return false;
                }
                const c = changes.find((c) => c.field === "text");
                if (c) edit(c.value);
              },
            )
          }
        >
          AI扩写
        </button>
        <button
          onClick={async () => {
            const result = await run("render_preview", { asset, text }, false);
            if (result) setPreview(result);
          }}
        >
          查看实际提交内容
        </button>
        <button
          disabled={s.busy}
          onClick={async () => {
            if (await save()) run("generate", { asset, plan: text });
          }}
        >
          开始生图
        </button>
        <button disabled={!text.trim() || s.busy} onClick={exportFiles}>
          保存生图资产到本地
        </button>
        {exported && (
          <button onClick={() => run("reveal", { path: exported })}>
            打开素材文件夹
          </button>
        )}
      </div>
      <p className="small muted">
        生成参数继承“设置 → 生图模型配置”；修改后对下一次调用生效。
      </p>
      {state?.rows.some((r) => r.asset && !r.asset.details) && (
        <p className="notice">
          部分资产沿用旧版描述，请在资产卡中分类整理，核对实际提交内容。
        </p>
      )}
      <h3>参考图编号（实际文件）</h3>
      <div className="render-references">
        {state?.references.map((ref) => (
          <figure key={ref.number}>
            <img src={ref.thumbnail} alt={ref.name} />
            <figcaption>
              参考图{ref.number} · {ref.name} · {ref.variant.title || "主卡"}
            </figcaption>
          </figure>
        ))}
      </div>
      {!state?.references.length && (
        <p className="muted">
          无参考图，使用文字生成；不会把文件名当作已上传图片。
        </p>
      )}
      <p className="muted small">
        有图仍需接口支持和工作流映射；普通兼容图片 API
        仅文生图。背景资料不自动混入最终画面文本。
      </p>
      {preview && (
        <details open className="submitted-plan">
          <summary>实际提交正文与参考图</summary>
          <pre>{preview.text}</pre>
          {preview.references.map((r) => (
            <p key={r.number}>
              参考图{r.number}：{r.name} / {r.path}
            </p>
          ))}
        </details>
      )}
    </section>
  );
}
export default function AssetRenderPage({ initial }) {
  const { s, run, notify, setLarge, dirty } = useWorkspace();
  const [asset, setAsset] = useState(initial || s.assets[0]?.id || "");
  useEffect(() => {
    if (initial) setAsset(initial);
  }, [initial]);
  const object = s.assets.find((a) => a.id === asset);
  const pictures = s.jobs
    .filter((j) => j.asset === asset && j.pictures?.length)
    .flatMap((j) => j.pictures.map((p) => ({ ...p, job: j })));
  return (
    <>
      <PageHeading
        title="资产图制作"
        subtitle="编辑资产／副卡设定图方案、参考图和生成候选。"
      />
      {!s.assets.length ? (
        <Empty title="请先建立资产" text="确认资产后可制作设定图。" />
      ) : (
        <>
          <label>
            当前资产
            <select
              aria-label="当前制图资产"
              value={asset}
              onChange={(e) => {
                if (!dirty.current || window.confirm("放弃未保存的生图方案？"))
                  setAsset(e.target.value);
              }}
            >
              {s.assets.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            使用状态
            <select
              aria-label="资产制图状态"
              value={s.chapter_variant_choices?.[asset] || "auto"}
              onChange={async (e) => {
                if (
                  dirty.current &&
                  !window.confirm("放弃未保存方案并切换状态？")
                )
                  return;
                dirty.current = false;
                await run("select_variant", {
                  id: asset,
                  variant: e.target.value,
                });
              }}
            >
              <option value="auto">自动继承</option>
              <option value="base">主卡</option>
              {(object?.variants || []).map((v) => (
                <option key={v.id} value={v.id}>
                  {v.title}
                </option>
              ))}
            </select>
          </label>
          <p>
            {object?.name} · 当前状态：
            {object?.effective?.selected_variant?.title || "主卡"}
          </p>
          {asset && (
            <RenderEditor
              key={asset + object?.effective?.selected_variant?.id}
              asset={asset}
            />
          )}
          <h2>参考图候选</h2>
          <div className="asset-grid">
            {pictures.map((p) => (
              <ImageCard
                key={p.path}
                image={p.thumbnail}
                title={object?.name}
                onOpen={() => setLarge({ path: p.path, title: object?.name })}
              >
                <button
                  onClick={async () => {
                    if (
                      await run("candidate_to_reference", {
                        asset,
                        path: p.path,
                        variant: object?.effective?.selected_variant?.id,
                      })
                    )
                      notify(
                        "已添加到资产参考图；副卡参考图请在资产编辑中明确选择。",
                      );
                  }}
                >
                  添加为资产参考图
                </button>
              </ImageCard>
            ))}
          </div>
        </>
      )}
    </>
  );
}
