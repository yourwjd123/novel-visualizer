import React, { useEffect, useState } from "react";
import { X, Trash2, RotateCcw } from "lucide-react";
import { api } from "./api";
import { useWorkspace } from "./context";

export function DeleteBook({ book, onClose, onDone }) {
  const { run, notify, s } = useWorkspace();
  const [name, setName] = useState(""),
    [permanent, setPermanent] = useState(false),
    [info, setInfo] = useState(null),
    [waiting, setWaiting] = useState(false);
  useEffect(() => {
    let alive = true;
    api("book_info", { id: book.id })
      .then((v) => alive && setInfo(v))
      .catch((e) => notify(e.message));
    return () => {
      alive = false;
    };
  }, [book.id]);
  return (
    <div className="modal-shade">
      <section className="modal" role="dialog" aria-label="删除小说">
        <div className="modal-heading">
          <h2>删除《{book.name}》</h2>
          <button
            className="icon"
            aria-label="关闭删除窗口"
            disabled={waiting}
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>
        <p>
          范围包含本小说的原文、资产、成果、历史任务和过程文件。项目外自行复制的文件不受影响。
        </p>
        <p className="muted">
          {info
            ? `占用 ${(info.bytes / 1024 / 1024).toFixed(2)} MB`
            : "正在统计项目资料…"}
        </p>
        <label>
          输入完整书名验证
          <input
            aria-label="删除小说书名验证"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="check-row">
          <input
            type="radio"
            checked={!permanent}
            onChange={() => setPermanent(false)}
          />
          移入小说回收站，保留全部存档，可恢复（默认）
        </label>
        <label className="check-row">
          <input
            type="radio"
            checked={permanent}
            onChange={() => setPermanent(true)}
          />
          永久删除全部文件，不可恢复
        </label>
        {permanent && (
          <p className="notice warning">永久删除不会保留可恢复的存档。</p>
        )}
        <div className="actions">
          <button disabled={waiting} onClick={onClose}>
            取消
          </button>
          <button
            className="danger"
            disabled={!info || name !== book.name || s.busy || waiting}
            onClick={async () => {
              setWaiting(true);
              if (await run("book_delete", { id: book.id, name, permanent })) {
                onDone();
                onClose();
              }
              setWaiting(false);
            }}
          >
            {permanent ? "永久删除全部文件" : "移入回收站"}
          </button>
        </div>
      </section>
    </div>
  );
}
export function BookTrash() {
  const { s, run, notify } = useWorkspace();
  const [rows, setRows] = useState([]),
    [removing, setRemoving] = useState(null),
    [name, setName] = useState("");
  const load = () =>
    api("book_trash")
      .then(setRows)
      .catch((e) => notify(e.message));
  useEffect(() => {
    load();
  }, [s.account?.id, JSON.stringify(s.projects)]);
  return (
    <section className="settings-sheet">
      <h2>小说回收站</h2>
      <p className="muted">
        保留整本小说及全部成果、资产和过程资料；恢复后重新出现在书架。此处与资产回收站独立。
      </p>
      {!rows.length ? (
        <p>回收站为空</p>
      ) : (
        rows.map((r) => (
          <div className="trash-book" key={r.trash_id}>
            <div>
              <strong>{r.name}</strong>
              <small>
                {r.deleted} · {(r.bytes / 1024 / 1024).toFixed(2)} MB
              </small>
            </div>
            <button
              disabled={s.busy}
              onClick={async () => {
                if (
                  await run("book_trash_action", {
                    id: r.trash_id,
                    name: r.name,
                    restore: true,
                  })
                )
                  load();
              }}
            >
              <RotateCcw size={14} />
              恢复
            </button>
            <button
              className="danger"
              disabled={s.busy}
              onClick={() => {
                setRemoving(r);
                setName("");
              }}
            >
              <Trash2 size={14} />
              永久删除
            </button>
          </div>
        ))
      )}
      {removing && (
        <div className="modal-shade">
          <section className="modal" role="dialog" aria-label="永久删除存档">
            <h2>永久删除《{removing.name}》</h2>
            <p>所有项目文件将被删除，不可恢复。请输入完整书名。</p>
            <input
              aria-label="永久删除书名验证"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <div className="actions">
              <button onClick={() => setRemoving(null)}>取消</button>
              <button
                className="danger"
                disabled={name !== removing.name || s.busy}
                onClick={async () => {
                  if (
                    await run("book_trash_action", {
                      id: removing.trash_id,
                      name,
                    })
                  ) {
                    setRemoving(null);
                    load();
                  }
                }}
              >
                永久删除全部文件
              </button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}

export function NameDialog({ title, value, onClose, onSave }) {
  const [name, setName] = useState(value),
    [waiting, setWaiting] = useState(false);
  return (
    <div className="modal-shade">
      <section className="modal" role="dialog" aria-label={title}>
        <div className="modal-heading">
          <h2>{title}</h2>
          <button
            className="icon"
            disabled={waiting}
            aria-label="关闭更名窗口"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setWaiting(true);
            if (await onSave(name.trim())) onClose();
            setWaiting(false);
          }}
        >
          <label>
            名称
            <input
              aria-label="新名称"
              autoFocus
              required
              maxLength={100}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <div className="actions">
            <button type="button" onClick={onClose}>
              取消
            </button>
            <button className="primary" disabled={waiting || !name.trim()}>
              保存名称
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
