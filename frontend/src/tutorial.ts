/** 시작 튜토리얼: 저장 키, 가리킬 영역 계산, 말풍선 카드 위치. (화면 그리기는 components/Tutorial.tsx) */

export const TOUR_KEY = "anycontrol.tour.v1";

/** 처음 여는 사람에게만 튜토리얼을 띄운다 (끝까지 보거나 건너뛰면 "done"). */
export function tourSeen(): boolean {
  try {
    return localStorage.getItem(TOUR_KEY) === "done";
  } catch {
    return false;
  }
}

export function markTourSeen(): void {
  try {
    localStorage.setItem(TOUR_KEY, "done");
  } catch {
    /* 저장 못 해도 동작에는 지장 없음 */
  }
}

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** 여러 영역을 감싸는 사각형. 크기가 0 인(숨은) 영역은 뺀다. 남는 게 없으면 null. */
export function unionBox(boxes: Box[]): Box | null {
  const vis = boxes.filter((b) => b.width > 0 && b.height > 0);
  if (!vis.length) return null;
  const left = Math.min(...vis.map((b) => b.left));
  const top = Math.min(...vis.map((b) => b.top));
  const right = Math.max(...vis.map((b) => b.left + b.width));
  const bottom = Math.max(...vis.map((b) => b.top + b.height));
  return { left, top, width: right - left, height: bottom - top };
}

export type Side = "center" | "below" | "above" | "right" | "left" | "overlap";

const GAP = 16;
const MARGIN = 12;

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(v, Math.max(lo, hi)));

/**
 * 말풍선 카드 위치. 가리킬 곳이 없으면 가운데, 있으면 아래 → 위 → 오른쪽 → 왼쪽 순으로 자리가 있는 곳.
 * 어디에도 안 들어가면(아주 큰 영역) 화면 아래쪽에 겹쳐 둔다. 항상 화면 안에 들어가게 당긴다.
 */
export function placeCard(target: Box | null, card: { width: number; height: number },
  vp: { width: number; height: number }): { left: number; top: number; side: Side } {
  const maxL = vp.width - card.width - MARGIN;
  const maxT = vp.height - card.height - MARGIN;
  if (!target)
    return { left: clamp((vp.width - card.width) / 2, MARGIN, maxL), top: clamp((vp.height - card.height) / 2, MARGIN, maxT), side: "center" };
  const cx = clamp(target.left + target.width / 2 - card.width / 2, MARGIN, maxL);
  const cy = clamp(target.top + target.height / 2 - card.height / 2, MARGIN, maxT);
  const bottom = target.top + target.height;
  const right = target.left + target.width;
  if (bottom + GAP + card.height <= vp.height - MARGIN) return { left: cx, top: bottom + GAP, side: "below" };
  if (target.top - GAP - card.height >= MARGIN) return { left: cx, top: target.top - GAP - card.height, side: "above" };
  if (right + GAP + card.width <= vp.width - MARGIN) return { left: right + GAP, top: cy, side: "right" };
  if (target.left - GAP - card.width >= MARGIN) return { left: target.left - GAP - card.width, top: cy, side: "left" };
  return { left: cx, top: clamp(maxT, MARGIN, maxT), side: "overlap" };
}
