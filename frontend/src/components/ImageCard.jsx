// Adapted from Story Asset Studio AssetImageCard, SHA 612f83b1. MIT notice retained.
import React, { useState, useEffect } from "react";
import { ImageOff, Check } from "lucide-react";
export default function ImageCard({
  image,
  title,
  subtitle,
  selected,
  onSelect,
  onOpen,
  children,
  badge,
}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [image]);
  return (
    <article className={"image-card " + (selected ? "selected" : "")}>
      <button
        className="image-hit"
        onClick={onOpen}
        aria-label={"查看 " + title}
      >
        {image && !failed ? (
          <img
            src={image}
            alt={title}
            loading="lazy"
            onError={() => setFailed(true)}
          />
        ) : (
          <div className="image-placeholder">
            <ImageOff />
            <span>暂无参考图</span>
          </div>
        )}
        {badge && <span className="picture-badge">{badge}</span>}
      </button>
      {onSelect && (
        <button
          className="image-check"
          aria-label={"选择 " + title}
          aria-pressed={!!selected}
          onClick={onSelect}
        >
          {selected ? <Check size={14} /> : null}
        </button>
      )}
      <div className="image-info">
        <h3>{title}</h3>
        {subtitle && <p className="muted small">{subtitle}</p>}
        {children}
      </div>
    </article>
  );
}
