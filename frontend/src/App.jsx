import React, { useState, useEffect, useRef } from "react";
import {
  PanelLeftClose,
  PanelLeftOpen,
  FolderOpen,
  UserRound,
  Settings,
  History,
  Files,
  SunMoon,
  Plus,
  Download,
  Archive,
  X,
  ImageOff,
} from "lucide-react";
import { api, connect, upload } from "./api";
import { WorkspaceContext } from "./context";
import WorkspaceTabs from "./components/WorkspaceTabs";
import SourcePage from "./SourcePage";
import AssetsPage, { AssetEditor } from "./AssetsPage";
import ImagesPage, { ResultsPage, ImageViewer } from "./ImagesPage";
import SettingsPage from "./SettingsPage";
import AssetRenderPage from "./RenderWorkspace";
import Assistant from "./Assistant";
import ReadingPage, { Bookshelf } from "./ReadingPage";

export default function App() {
  const [s, setState] = useState(null),
    [error, setError] = useState(""),
    [page, setPage] = useState("bookshelf"),
    [modal, setModal] = useState(null),
    [ai, setAI] = useState({ open: false, node: 0, asset: null }),
    [toast, setToast] = useState(""),
    [compact, setCompact] = useState(false),
    [mobileExpanded, setMobileExpanded] = useState(false),
    [system, setSystem] = useState(null),
    [assetEdit, setAssetEdit] = useState(null),
    [large, setLarge] = useState(null),
    [assetForRender, setAssetForRender] = useState(null),
    [guestDark, setGuestDark] = useState(null),
    [importReports, setImportReports] = useState([]);
  const current = useRef(s),
    pending = useRef(null),
    assistant = useRef(null),
    readerFlush = useRef(null),
    dirty = useRef(false),
    toastTimer = useRef(null);
  const notify = (text) => {
    setToast(text);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 4500);
  };
  async function refresh() {
    const next = await api("state");
    current.current = next;
    setState(next);
    return next;
  }
  async function run(op, data = {}, reload = true) {
    if (["send", "generate"].includes(op))
      setAI((v) => ({
        ...v,
        open: true,
        node: op === "send" ? data.node : 4,
        asset: data.asset || null,
        panel:
          data.mode === "consult"
            ? "consult"
            : data.mode === "complete"
              ? "complete"
              : "status",
        job: null,
      }));
    try {
      if (
        [
          "select",
          "project_open",
          "logout",
          "login",
          "account_create",
        ].includes(op)
      )
        await flush();
      const r = await api(op, data);
      if (r?.import_estimate)
        setImportReports((v) => [...v, r.import_estimate]);
      if (r?.job) setAI((v) => ({ ...v, job: r.job }));
      if (reload) await refresh();
      return r ?? true;
    } catch (e) {
      notify(e.message);
      return false;
    }
  }
  useEffect(() => {
    let alive = true;
    connect()
      .then((bridge) => {
        bridge.changed.connect((raw) => {
          if (!alive) return;
          const event = JSON.parse(raw);
          refresh()
            .then((next) => {
              if (event.type !== "finished") return;
              const job = next.jobs.find((j) => j.id === event.job);
              if (
                event.error ||
                job?.status === "failed" ||
                job?.status === "unknown"
              )
                notify("任务未完成；输入与记录已保留");
              else if (job?.status === "invalid")
                notify("输出未通过校验；请在任务状态查看原因和原始输出");
              else if (job?.mode === "consult") notify("咨询回复已保存");
              else if (job?.mode === "complete")
                notify("AI补全建议已生成，请逐项审核采用");
              else if (job?.node === 1)
                notify(
                  job.asset_phase === "advice"
                    ? `已生成 ${job.result_count ?? 0} 项建卡建议，请勾选`
                    : `已建立 ${job.result_count ?? 0} 项资产卡，请核对并完成本章整理`,
                );
              else if (job?.node === 0)
                notify("情节候选与本章梗概已生成，请核对");
              else notify("任务完成，请在对应工作区查看结果");
            })
            .catch((e) => setError(e.message));
        });
        return refresh();
      })
      .catch((e) => setError(e.message));
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => setImportReports([]), [s?.account?.id, s?.project?.id]);
  async function resume() {
    const next = await refresh();
    if (!next.project) {
      setModal({ type: "projects" });
      return;
    }
    setModal(null);
    const fn = pending.current;
    pending.current = null;
    if (fn) fn();
  }
  function withProject(fn) {
    const now = current.current;
    if (!now?.account) {
      pending.current = fn;
      setModal({ type: "accounts" });
      return false;
    }
    if (!now.project) {
      pending.current = fn;
      setModal({ type: "projects" });
      return false;
    }
    fn();
    return true;
  }
  async function flush() {
    await readerFlush.current?.();
    await assistant.current?.flush();
  }
  async function navigate(next) {
    if (
      dirty.current &&
      !window.confirm("有尚未保存的编辑，放弃这些输入并切换页面吗？")
    )
      return;
    dirty.current = false;
    await flush();
    setPage(next);
    if (["bookshelf", "reader"].includes(next))
      setAI((v) => ({ ...v, open: false }));
    setAssetEdit(null);
    return true;
  }
  async function openAssetRender(identity) {
    if (await navigate("asset_images")) setAssetForRender(identity);
  }
  function openAI(node = 0, asset = null, reference = null) {
    withProject(() =>
      setAI({
        open: true,
        node,
        asset,
        reference,
        panel: "status",
        job: current.current?.jobs?.find(
          (j) =>
            j.node === node &&
            j.segment === current.current.segment &&
            (!asset || j.asset === asset),
        )?.id,
      }),
    );
  }
  function openCompletion(target, fields, onApply) {
    withProject(() =>
      setAI({
        open: true,
        node: target.type === "prompt" ? 3 : 5,
        panel: "complete",
        target: {
          ...target,
          segment: s.segment,
          project: s.project.id,
          request_id: Date.now() + "-" + Math.random(),
        },
        fields,
        onApply,
      }),
    );
  }
  function openConsult() {
    withProject(() => setAI({ open: true, node: 7, panel: "consult" }));
  }
  function openSystem(id, name) {
    if (!current.current?.account) {
      pending.current = () => {
        setSystem({ id, name });
        navigate(id);
      };
      setModal({ type: "accounts" });
      return;
    }
    setSystem({ id, name });
    navigate(id);
  }
  async function uploadFiles(files, target, asset) {
    try {
      for (const file of files) {
        const result = await upload(file, target, asset);
        if (result?.import_estimate)
          setImportReports((v) => [...v, result.import_estimate]);
      }
      await refresh();
      notify(
        target === "text"
          ? "原文已导入；尚未调用模型"
          : target === "reference"
            ? "参考图已保存"
            : target === "scene_image"
              ? "已导入为当前情节的插图候选，确认后进入成果集"
              : "附件已保存到项目",
      );
      return true;
    } catch (e) {
      notify(e.message);
      return false;
    }
  }
  async function switchAccount(op, d) {
    if (dirty.current && !window.confirm("放弃未保存的输入并切换吗？"))
      return false;
    await flush();
    const ok = await run(op, d);
    if (ok) {
      setAI({ open: false, node: 0, asset: null });
      setAssetEdit(null);
      setPage("bookshelf");
      dirty.current = false;
      return true;
    }
    return false;
  }
  useEffect(() => {
    window.__novelvizRequestClose = async () => {
      if (
        dirty.current &&
        !window.confirm("有尚未保存的编辑，放弃这些输入并关闭吗？")
      )
        return;
      await flush();
      await api("close_ready");
    };
    return () => delete window.__novelvizRequestClose;
  }, []);
  useEffect(() => {
    if (s?.account) setCompact(s.settings.sidebar_visible === false);
  }, [s?.account?.id]);
  const context = {
    s,
    run,
    refresh,
    notify,
    registerReaderFlush: (fn) => {
      readerFlush.current = fn;
    },
    page,
    navigate,
    withProject,
    openAI,
    openCompletion,
    openAssetRender,
    openConsult,
    modal,
    setModal,
    assetEdit,
    setAssetEdit,
    setLarge,
    uploadFiles,
    dirty,
  };
  if (error && !s)
    return (
      <main className="startup-error">
        <h1>工作区未能启动</h1>
        <p>{error}</p>
        <p>请使用下载包中的墨境程序或 start_windows.bat 启动。</p>
      </main>
    );
  if (!s)
    return (
      <main className="startup-error">
        <h1>墨境</h1>
        <p>正在打开本地工作区…</p>
      </main>
    );
  const dark = s.account
    ? s.settings.theme === "dark" ||
      (s.settings.theme === "system" && s.system_dark)
    : (guestDark ?? s.system_dark);
  return (
    <WorkspaceContext.Provider value={context}>
      <div
        className={
          "app " +
          (compact ? "sidebar-collapsed " : "") +
          (mobileExpanded ? "sidebar-mobile-expanded" : "")
        }
        data-theme={dark ? "dark" : "light"}
        style={{ "--ui-size": s.settings.font_size + "px" }}
      >
        {s.background_image && (
          <div
            className="custom-background"
            style={{
              backgroundImage: `url(${s.background_image})`,
              opacity: s.settings.background_opacity / 100,
            }}
          />
        )}
        <header className="topbar">
          <span>{s.account ? s.account.name : "访客 · 未登录"}</span>
          <button
            className="quiet theme-toggle"
            aria-label="切换明暗主题"
            onClick={() =>
              s.account
                ? run("settings", { theme: dark ? "light" : "dark" })
                : setGuestDark(!dark)
            }
          >
            <SunMoon size={14} />明 / 暗
          </button>
        </header>
        {mobileExpanded && (
          <button
            className="mobile-dismiss"
            aria-label="收起系统侧栏"
            onClick={() => setMobileExpanded(false)}
          />
        )}
        <div className="app-shell">
          <aside className="system-sidebar" aria-label="系统与项目">
            <div
              className="brand"
              role="button"
              tabIndex={0}
              title="返回书架"
              onClick={() => navigate("bookshelf")}
              onKeyDown={(e) => {
                if (e.key === "Enter") navigate("bookshelf");
              }}
            >
              <span className="brand-mark">墨</span>
              <span className="side-label">
                墨境 <small>文本可视化</small>
              </span>
            </div>
            <button
              aria-label="收起或展开侧栏"
              onClick={() => {
                if (window.innerWidth <= 800) {
                  setMobileExpanded(!mobileExpanded);
                  return;
                }
                setCompact(!compact);
                if (s.account) run("settings", { sidebar_visible: compact });
              }}
            >
              {compact ? (
                <PanelLeftOpen size={17} />
              ) : (
                <PanelLeftClose size={17} />
              )}
              <span className="side-label">收起侧栏</span>
            </button>
            <button
              className="project-picker"
              onClick={() =>
                s.account
                  ? setModal({ type: "projects" })
                  : setModal({ type: "accounts" })
              }
            >
              <strong>
                {s.project?.name || "选择小说项目"} <span>⌄</span>
              </strong>
              <small>
                {s.project ? "当前小说 · 资料保存在本地" : "创建账户后开始操作"}
              </small>
              {s.progress && page !== "bookshelf" && (
                <>
                  <div className="project-progress">
                    <span
                      style={{
                        width:
                          Math.min(
                            100,
                            (s.progress.results /
                              Math.max(1, s.progress.scenes)) *
                              100,
                          ) + "%",
                      }}
                    />
                  </div>
                  <small>
                    {s.progress.scenes} 个情节 · {s.progress.results} 张已选插图
                  </small>
                </>
              )}
            </button>
            <button
              className="project-icon"
              aria-label="项目与进度"
              onClick={() =>
                setModal({ type: s.account ? "projects" : "accounts" })
              }
            >
              <FolderOpen size={17} />
            </button>
            <button
              aria-label="账户 / 登录"
              onClick={() => setModal({ type: "accounts" })}
            >
              <UserRound size={17} />
              <span className="side-label">账户 / 登录</span>
            </button>
            <button
              aria-label="设置"
              onClick={() => openSystem("settings", "设置")}
            >
              <Settings size={17} />
              <span className="side-label">设置</span>
            </button>
            <button
              aria-label="任务与历史"
              onClick={() => openSystem("history", "任务与历史")}
            >
              <History size={17} />
              <span className="side-label">任务与历史</span>
            </button>
            <button
              onClick={() => withProject(() => openSystem("files", "项目文件"))}
            >
              <Files size={17} />
              <span className="side-label">项目文件</span>
            </button>
            <div className="sidebar-spacer" />
            <p className="side-label sidebar-note">
              v0.10.0-beta.1 · 测试版
              <br />
              既有文本 → 视觉资产 → 插图
            </p>
          </aside>
          <main className="workspace">
            {!["bookshelf", "reader"].includes(page) && (
              <WorkspaceTabs
                active={page}
                onSelect={navigate}
                system={system}
                onClose={() => {
                  setSystem(null);
                  navigate("source");
                }}
              />
            )}
            <div
              className={
                "workspace-content " +
                (page === "reader" ? "reader-content" : "")
              }
              id="workspace-content"
              role={
                ["bookshelf", "reader"].includes(page) ? "region" : "tabpanel"
              }
              aria-label={
                page === "bookshelf"
                  ? "书架"
                  : page === "reader"
                    ? "阅读"
                    : undefined
              }
              aria-labelledby={
                ["bookshelf", "reader"].includes(page)
                  ? undefined
                  : "tab-" + page
              }
            >
              {page === "bookshelf" ? (
                <Bookshelf />
              ) : page === "reader" && s.project ? (
                <ReadingPage key={s.project.id} />
              ) : !s.project &&
                !["settings", "history", "files"].includes(page) ? (
                <Guest page={page} />
              ) : page === "source" ? (
                <SourcePage />
              ) : page === "assets" ? (
                <AssetsPage />
              ) : page === "asset_images" ? (
                <AssetRenderPage initial={assetForRender} />
              ) : page === "images" ? (
                <ImagesPage />
              ) : page === "results" ? (
                <ResultsPage />
              ) : page === "settings" ? (
                <SettingsPage />
              ) : page === "history" ? (
                <TaskHistory />
              ) : page === "files" ? (
                <ProjectFiles />
              ) : null}
            </div>
            {assetEdit && (
              <AssetEditor
                key={assetEdit.id || "new"}
                asset={assetEdit}
                onClose={() => setAssetEdit(null)}
              />
            )}
          </main>
        </div>
        {!["bookshelf", "reader"].includes(page) && (
          <button
            className="ai-launch primary"
            onClick={() =>
              ai.open ? setAI((v) => ({ ...v, open: false })) : openConsult()
            }
          >
            ✧ AI 助手{s.busy && <span className="busy-dot" />}
          </button>
        )}
        {s.account && <Assistant ref={assistant} ai={ai} onChange={setAI} />}
        {modal && (
          <div
            className="modal-shade"
            onMouseDown={(e) => {
              if (e.target === e.currentTarget && !pending.current)
                setModal(null);
            }}
          >
            <section
              className="modal"
              role="dialog"
              aria-modal="true"
              aria-label={modal.title || "工作区操作"}
            >
              <div className="modal-heading">
                <h2>
                  {{
                    accounts: "本地账户",
                    projects: "项目与制作进度",
                    import: "导入原文片段",
                    export: "导出文本",
                    links: "关联本情节资产",
                    override: "本情节资产状态",
                  }[modal.type] ||
                    modal.title ||
                    "操作"}
                </h2>
                <button
                  className="icon quiet"
                  aria-label="关闭"
                  onClick={() => {
                    setModal(null);
                    pending.current = null;
                  }}
                >
                  <X size={18} />
                </button>
              </div>
              {modal.type === "accounts" ? (
                <Accounts
                  onLogin={async (id) => {
                    if (await switchAccount("login", { id })) resume();
                  }}
                  onCreate={async (name) => {
                    if (await switchAccount("account_create", { name }))
                      resume();
                  }}
                  onLogout={async () => {
                    if (await switchAccount("logout", {})) {
                      setModal(null);
                      navigate("bookshelf");
                    }
                  }}
                />
              ) : modal.type === "projects" ? (
                <Projects
                  onOpen={async (path) => {
                    await flush();
                    if (await run("project_open", { path })) {
                      const hadPending = !!pending.current;
                      setAI({ open: false, node: 0, asset: null });
                      await resume();
                      if (!hadPending && ["bookshelf", "reader"].includes(page))
                        navigate("reader");
                    }
                  }}
                  onCreate={async (name) => {
                    if (await run("project_create", { name })) {
                      const hadPending = !!pending.current;
                      await resume();
                      if (!hadPending && page === "bookshelf")
                        navigate("reader");
                    }
                  }}
                />
              ) : modal.type === "import" ? (
                <ImportText
                  method={modal.method}
                  onDone={() => setModal(null)}
                />
              ) : modal.type === "links" ? (
                <Links onDone={() => setModal(null)} />
              ) : modal.type === "override" ? (
                <Override asset={modal.asset} onDone={() => setModal(null)} />
              ) : modal.type === "export" ? (
                <ExportText data={modal.data} onDone={() => setModal(null)} />
              ) : (
                modal.content || null
              )}
            </section>
          </div>
        )}
        {importReports.length > 0 && (
          <div className="modal-shade">
            <section
              className="modal"
              role="dialog"
              aria-modal="true"
              aria-label="导入字数与用量预估"
            >
              <div className="modal-heading">
                <h2>导入完成 · 字数与输入用量</h2>
                <button onClick={() => setImportReports((v) => v.slice(1))}>
                  关闭用量提示
                </button>
              </div>
              <p>
                {importReports[0].name} · 本次导入{" "}
                {importReports[0].import_characters.toLocaleString()}{" "}
                字（不含空白） · 当前章节共{" "}
                {importReports[0].chapter_characters.toLocaleString()} 字
              </p>
              <table>
                <thead>
                  <tr>
                    <th>操作</th>
                    <th>预计输入 token（约）</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["source", "章节原文自身"],
                    ["advice", "整章建卡建议"],
                    ["build", "正式建卡（依勾选范围）"],
                    ["split", "整章情节拆分及关联"],
                  ].map(([key, label]) => (
                    <tr key={key}>
                      <td>{label}</td>
                      <td>
                        {importReports[0][key]
                          .map((n) => n.toLocaleString())
                          .join("—")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted small">{importReports[0].method}</p>
              <p>
                各操作分别估算，不能视为总费用。导入没有调用模型；尚未自动建立资产或拆分情节。
              </p>
              {importReports.length > 1 && (
                <small>另有 {importReports.length - 1} 份导入报告待查看</small>
              )}
            </section>
          </div>
        )}
        {large && <ImageViewer image={large} onClose={() => setLarge(null)} />}
        {toast && (
          <div className="toast" role="status" aria-live="polite">
            {toast}
            <button
              className="icon quiet"
              aria-label="关闭通知"
              onClick={() => setToast("")}
            >
              ×
            </button>
          </div>
        )}
      </div>
    </WorkspaceContext.Provider>
  );
}

function Guest({ page }) {
  const { s, withProject, setModal } = React.useContext(WorkspaceContext);
  return (
    <div className="empty-workspace">
      <span className="eyebrow">墨境 · 小说文本可视化</span>
      <h1>
        {page === "source"
          ? "从你已有的文字开始"
          : page === "assets"
            ? "把人物、场景与道具整理成视觉资产"
            : page === "images"
              ? "让原文中的情节成为画面"
              : "按情节整理你的插图成果"}
      </h1>
      <p>原文保留在本地。分段整理、确认资产，再制作插图。</p>
      <div className="actions">
        <button
          className="primary"
          onClick={() => withProject(() => setModal({ type: "import" }))}
        >
          <Plus size={16} />
          导入原文并开始
        </button>
        <button
          onClick={() =>
            setModal({ type: s.account ? "projects" : "accounts" })
          }
        >
          打开已有项目
        </button>
      </div>
      <p className="muted small">
        可以先浏览四个工作标签；实际操作时再选择或创建本地账户。
      </p>
    </div>
  );
}
function Accounts({ onLogin, onCreate, onLogout }) {
  const { s, run, refresh } = React.useContext(WorkspaceContext);
  const [name, setName] = useState("");
  return (
    <>
      <p className="muted small">
        账户在本机管理，各账户独立保存项目、设置与密钥。
      </p>
      <div className="account-list">
        {s.accounts.map((a) => (
          <button key={a.id} onClick={() => onLogin(a.id)}>
            <UserRound size={16} />
            {a.name}
            {s.account?.id === a.id && <span className="badge">当前</span>}
          </button>
        ))}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) onCreate(name.trim());
        }}
      >
        <label>
          新账户名称
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={70}
          />
        </label>
        <button className="primary" type="submit">
          创建并登录
        </button>
      </form>
      {s.account && (
        <div className="actions separated">
          <button
            onClick={async () => {
              const value = window.prompt("新的账户名称", s.account.name);
              if (value) run("account_rename", { name: value });
            }}
          >
            修改账户名
          </button>
          <button onClick={onLogout}>退出登录</button>
          <button
            className="danger"
            onClick={async () => {
              if (await run("account_delete")) {
                await refresh();
                onLogout();
              }
            }}
          >
            归档删除账户
          </button>
        </div>
      )}
      <div className="separated">
        <button onClick={() => run("choose_root")}>更改用户资料根目录</button>
      </div>
    </>
  );
}
function Projects({ onOpen, onCreate }) {
  const { s, run } = React.useContext(WorkspaceContext);
  const [name, setName] = useState("");
  return (
    <>
      <div className="project-list">
        {s.projects.map((p) => (
          <button key={p.id} onClick={() => onOpen(p.path)}>
            <FolderOpen size={19} />
            <span>
              <strong>{p.name}</strong>
              <small>
                {p.created?.slice(0, 10)}
                {s.project?.id === p.id ? " · 当前项目" : ""}
              </small>
            </span>
            <span>→</span>
          </button>
        ))}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) onCreate(name);
        }}
      >
        <label>
          新小说项目名称
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={70}
          />
        </label>
        <button className="primary">新建项目</button>
      </form>
      <div className="actions separated">
        <button disabled={!s.project || s.busy} onClick={() => run("backup")}>
          <Archive size={15} />
          备份当前项目
        </button>
        <button disabled={s.busy} onClick={() => run("restore_backup")}>
          从备份恢复独立副本
        </button>
      </div>
      <p className="muted small">
        新项目不自动共享另一部小说的资产。恢复保留原项目。
      </p>
    </>
  );
}
function ImportText({ onDone, method }) {
  const { s, run, uploadFiles } = React.useContext(WorkspaceContext);
  const [name, setName] = useState(""),
    [text, setText] = useState(""),
    [placement, setPlacement] = useState(null);
  return (
    <>
      <p className="muted small">
        可逐段导入 TXT、MD、DOCX、EPUB，同项目共享资产。
      </p>
      {method !== "paste" && (
        <>
          <DropZone
            onFiles={async (files) => {
              if (await uploadFiles(files, "text")) onDone();
            }}
            accept=".txt,.md,.docx,.epub"
            label="拖入原文文件，或点击选择"
          />
          <button
            onClick={async () => {
              if (await run("import_file")) onDone();
            }}
          >
            从文件导入
          </button>
        </>
      )}
      {placement !== null && (
        <section
          role="dialog"
          aria-label="粘贴文本归属"
          className="paste-placement"
        >
          <h3>这段文本属于哪一章？</h3>
          <select
            aria-label="粘贴归属"
            value={placement}
            onChange={(e) => setPlacement(e.target.value)}
          >
            <option value="new">独立章节</option>
            {s.segments.map((ch) => (
              <React.Fragment key={ch.id}>
                <option value={"append:" + ch.id}>
                  归入上一章末尾：{ch.name}
                </option>
                <option value={"prepend:" + ch.id}>
                  归入下一章开头：{ch.name}
                </option>
              </React.Fragment>
            ))}
          </select>
          <button
            onClick={async () => {
              const parts = placement.split(":");
              if (
                await run("import_text", {
                  name: name || "粘贴章节",
                  text,
                  target: parts[1],
                  prepend: parts[0] === "prepend",
                })
              )
                onDone();
            }}
          >
            确认章节归属
          </button>
          <button onClick={() => setPlacement(null)}>取消</button>
        </section>
      )}
      {method !== "file" && (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setPlacement("new");
          }}
        >
          <label>
            片段名称
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：第一章 · 雨夜渡口"
            />
          </label>
          <label>
            或直接粘贴原文
            <textarea
              rows={7}
              value={text}
              onChange={(e) => setText(e.target.value)}
              required
            />
          </label>
          <button className="primary">保留为原文片段</button>
        </form>
      )}
    </>
  );
}
export function DropZone({ onFiles, accept, label, compact = false }) {
  const input = useRef(null);
  const [over, setOver] = useState(false);
  return (
    <div
      className={
        "drop-zone " + (over ? "drag-over " : "") + (compact ? "compact" : "")
      }
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        onFiles(Array.from(e.dataTransfer.files));
      }}
    >
      <input
        ref={input}
        type="file"
        accept={accept}
        multiple
        hidden
        onChange={(e) => {
          onFiles(Array.from(e.target.files));
          e.target.value = "";
        }}
      />
      <button className="quiet" onClick={() => input.current.click()}>
        <Plus size={15} />
        {label || "添加或拖入文件"}
      </button>
    </div>
  );
}
function Links({ onDone }) {
  const { s, run } = React.useContext(WorkspaceContext);
  const [selected, setSelected] = useState(
    new Set(s.requirements.filter((r) => r.asset_id).map((r) => r.asset_id)),
  );
  return (
    <>
      <p className="muted small">
        选择本情节使用的档案。缺失项可保留，生成时再确认。
      </p>
      {s.assets.map((a) => (
        <label className="check-row" key={a.id}>
          <input
            type="checkbox"
            checked={selected.has(a.id)}
            onChange={(e) =>
              setSelected((prev) => {
                const next = new Set(prev);
                e.target.checked ? next.add(a.id) : next.delete(a.id);
                return next;
              })
            }
          />
          {a.name}
          <span className="badge">{a.kind}</span>
        </label>
      ))}
      <button
        className="primary"
        onClick={async () => {
          const rows = s.assets
            .filter((a) => selected.has(a.id))
            .map((a) => ({ name: a.name, kind: a.kind, asset_id: a.id }));
          rows.push(...s.requirements.filter((r) => !r.asset_id));
          if (await run("requirements", { rows })) onDone();
        }}
      >
        保存关联
      </button>
    </>
  );
}
function Override({ asset, onDone }) {
  const { s, run } = React.useContext(WorkspaceContext);
  const [text, setText] = useState(s.overrides?.[asset.id] || "");
  return (
    <>
      <p className="muted small">
        仅影响当前情节的服装、伤势、位置、天气等状态，不覆盖资产稳定设定。
      </p>
      <h3>{asset.name}</h3>
      <textarea
        rows={6}
        value={text}
        onChange={(e) => setText(e.target.value)}
        style={{ width: "100%" }}
      />
      <button
        className="primary"
        onClick={async () => {
          if (await run("scene_override", { asset: asset.id, text })) onDone();
        }}
      >
        保存本情节状态
      </button>
    </>
  );
}
function ExportText({ data, onDone }) {
  const { run, notify } = React.useContext(WorkspaceContext);
  const [format, setFormat] = useState("md"),
    [mode, setMode] = useState("dialogue");
  return (
    <>
      <label>
        导出内容
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="dialogue">完整对话记录</option>
          <option value="outputs">全部模型输出</option>
          <option value="final">手工或已确认方案</option>
        </select>
      </label>
      <label>
        格式
        <select value={format} onChange={(e) => setFormat(e.target.value)}>
          <option value="md">Markdown (.md)</option>
          <option value="txt">纯文本 (.txt)</option>
        </select>
      </label>
      <button
        className="primary"
        onClick={async () => {
          const r = await run("export_text", { ...data, mode, format });
          if (r) {
            notify("已导出：" + r.path);
            onDone();
          }
        }}
      >
        导出到项目目录
      </button>
    </>
  );
}
function TaskHistory() {
  const { s, run } = React.useContext(WorkspaceContext);
  return (
    <>
      <PageHeading
        title="任务与历史"
        subtitle="查看真实调用状态、远端任务号和结果；失败不自动重试。"
      />
      <div className="task-list">
        {s.jobs.map((j) => (
          <details key={j.id}>
            <summary>
              <span className={"status " + j.status}>{j.status}</span>
              <strong>{j.kind}</strong>
              <span className="muted small">
                {j.created} · {j.model || "未指定模型"}
              </span>
            </summary>
            <p>{j.error || j.validation_error || "输出保留在项目目录中。"}</p>
            {j.remote_id && <p>远端任务号：{j.remote_id}</p>}
            {j.output && <pre>{j.output}</pre>}
            <button
              onClick={() => run("reveal", { path: "05_生成任务/" + j.id })}
            >
              打开任务目录
            </button>
          </details>
        ))}
      </div>
      {!s.jobs.length && (
        <Empty
          title="还没有任务记录"
          text="发起分析或图片生成后，可在这里查看任务与结果。"
        />
      )}
    </>
  );
}
function ProjectFiles() {
  const { s, run, notify } = React.useContext(WorkspaceContext);
  const [rows, setRows] = useState([]);
  useEffect(() => {
    api("files")
      .then(setRows)
      .catch((e) => notify(e.message));
  }, [s.project?.id]);
  return (
    <>
      <PageHeading
        title="项目文件"
        subtitle="原文、参考图、过程文档、对话和成果按目录保存。"
        actions={<button onClick={() => run("reveal")}>打开项目目录</button>}
      />
      <div className="file-list">
        {rows.map((r) => (
          <button
            key={r.path}
            className="file-row quiet"
            onClick={() => run("reveal", { path: r.path })}
          >
            <FolderOpen size={14} />
            <span>{r.path}</span>
            <small>
              {r.directory ? "目录" : (r.size / 1024).toFixed(1) + " KB"}
            </small>
          </button>
        ))}
      </div>
    </>
  );
}
export function PageHeading({ title, subtitle, actions }) {
  const { s } = React.useContext(WorkspaceContext);
  return (
    <>
      <div className="breadcrumb">
        {s.project?.name || "本地账户"} / {title}
      </div>
      <div className="page-heading">
        <div>
          <h1>{title}</h1>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <div className="actions">{actions}</div>
      </div>
    </>
  );
}
export function Empty({ title, text, action }) {
  return (
    <section className="empty-state">
      <ImageOff size={26} />
      <h2>{title}</h2>
      <p>{text}</p>
      {action}
    </section>
  );
}
