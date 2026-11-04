import { useEffect, useState } from "react";
import { getSettings, putSettings } from "./api";
import { applyScale, DEFAULT_SCALE, normalizeScale, SCALES, stepScale } from "./uiScale";

/** 사이드바 아래 글씨 크기 조절 — 가− / 배율 / 가+. Ctrl + / − / 0 단축키도 같이. */
export default function ScaleControl() {
  const [scale, setScale] = useState<number>(DEFAULT_SCALE);

  useEffect(() => {
    getSettings().then(s => setScale(normalizeScale(s.ui_scale))).catch(() => undefined);
  }, []);

  function change(next: number) {
    setScale(applyScale(next));
    putSettings({ ui_scale: next }).catch(() => undefined);
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
      if (e.key === "=" || e.key === "+") change(stepScale(scale, 1));
      else if (e.key === "-" || e.key === "_") change(stepScale(scale, -1));
      else if (e.key === "0") change(DEFAULT_SCALE);
      else return;
      e.preventDefault();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [scale]);

  const min = scale <= SCALES[0];
  const max = scale >= SCALES[SCALES.length - 1];
  return (
    <div className="scale-control" role="group" aria-label="글씨 크기">
      <span className="scale-label">글씨 크기</span>
      <button type="button" className="scale-btn small" disabled={min}
              onClick={() => change(stepScale(scale, -1))}
              title="작게 (Ctrl + −)" aria-label="글씨 작게">가−</button>
      <button type="button" className="scale-value" onClick={() => change(DEFAULT_SCALE)}
              title="기본 크기로 (Ctrl + 0)">{scale}%</button>
      <button type="button" className="scale-btn large" disabled={max}
              onClick={() => change(stepScale(scale, 1))}
              title="크게 (Ctrl + +)" aria-label="글씨 크게">가+</button>
    </div>
  );
}
