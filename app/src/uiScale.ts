// 화면 배율 — 글씨와 화면 요소를 함께 키우고 줄인다.
// 값은 core/settings.py 의 ui_scale 허용 목록과 같아야 한다. 앱 서버 주소의 포트가 실행할
// 때마다 바뀌어 브라우저 저장소(localStorage)는 매번 비므로 설정 파일에 저장한다.
export const SCALES = [85, 90, 100, 110, 120, 135, 150] as const;
export const DEFAULT_SCALE = 100;

export function normalizeScale(value: unknown): number {
  return SCALES.includes(value as (typeof SCALES)[number]) ? (value as number) : DEFAULT_SCALE;
}

export function applyScale(value: unknown): number {
  const scale = normalizeScale(value);
  const root = document.documentElement.style;
  root.setProperty("zoom", String(scale / 100));
  // vh·vw로 잡은 크기는 배율만큼 커지므로 CSS에서 이 값으로 나눠 창 크기에 맞춘다 (index.css)
  root.setProperty("--ui-zoom", String(scale / 100));
  return scale;
}

/** 한 단계 크게(+1) / 작게(-1). 끝에 닿으면 그대로. */
export function stepScale(current: number, direction: 1 | -1): number {
  const i = SCALES.indexOf(normalizeScale(current) as (typeof SCALES)[number]);
  const next = Math.min(SCALES.length - 1, Math.max(0, i + direction));
  return SCALES[next];
}
