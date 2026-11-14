// Adapted from Pagekin StageTabs, SHA 707d157e. GPL-3.0; see THIRD_PARTY_NOTICES.md.
import React, { useRef } from "react";
const pages = [
  ["source", "原文与情节"],
  ["assets", "视觉资产库"],
  ["images", "场景插图"],
  ["results", "成果集"],
];
export default function WorkspaceTabs({ active, onSelect, system, onClose }) {
  const list = useRef(null);
  function key(event, index) {
    const next =
      event.key === "ArrowRight"
        ? (index + 1) % pages.length
        : event.key === "ArrowLeft"
          ? (index - 1 + pages.length) % pages.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? pages.length - 1
              : null;
    if (next !== null) {
      event.preventDefault();
      onSelect(pages[next][0]);
      list.current.querySelectorAll('[role="tab"]')[next].focus();
    }
  }
  return (
    <nav
      className="workspace-tabs"
      role="tablist"
      aria-label="工作页面"
      ref={list}
    >
      {pages.map(([id, name], i) => (
        <button
          type="button"
          role="tab"
          id={"tab-" + id}
          key={id}
          aria-controls="workspace-content"
          aria-selected={active === id}
          tabIndex={active === id ? 0 : -1}
          onKeyDown={(e) => key(e, i)}
          onClick={() => onSelect(id)}
        >
          {name}
        </button>
      ))}
      {system && (
        <div className="system-tab">
          <button
            role="tab"
            aria-selected={!pages.some(([id]) => id === active)}
            onClick={() => onSelect(system.id)}
          >
            {system.name}
          </button>
          <button
            className="tab-close"
            aria-label="关闭系统标签"
            onClick={onClose}
          >
            ×
          </button>
        </div>
      )}
    </nav>
  );
}
