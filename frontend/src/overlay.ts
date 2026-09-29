import { HAND_CONNECTIONS, type FrameState, type HandInfo, type ObjectInfo, type PenState, type TrackStateName } from "./protocol";

export type Norm = [number, number];

/** 드래그가 이 픽셀보다 짧으면 클릭(점 프롬프트)으로 본다. */
export const CLICK_TOLERANCE_PX = 6;

export type Selection =
  | { kind: "box"; box: [number, number, number, number] }
  | { kind: "point"; point: [number, number] };

/** 캔버스 CSS 좌표 → 0..1. 캔버스는 영상 종횡비를 그대로 유지한다고 가정한다. */
export function toNorm(clientX: number, clientY: number, rect: DOMRect, mirrored = false): Norm {
  const x = (clientX - rect.left) / rect.width;
  const y = (clientY - rect.top) / rect.height;
  return [mirrored ? 1 - clamp01(x) : clamp01(x), clamp01(y)];
}

const viewX = (x: number, mirrored: boolean) => mirrored ? 1 - x : x;

export function calibrationOpacity(now: number, shownAt: number, forced: boolean): number {
  return forced ? 1 : Math.max(0, Math.min(1, 2 - (now - shownAt) / 1000));
}

export function drawCalibration(ctx: CanvasRenderingContext2D, calibration: FrameState["calibration"] | null,
  w: number, h: number, opacity: number, mirrored = false): void {
  if (!calibration?.calibrated || opacity <= 0) return;
  const line = calibration.mode === "line" ? calibration.line : undefined;
  const quad = calibration.mode === "quad" ? calibration.quad : undefined;
  if (!line && !quad) return;
  ctx.save();
  ctx.globalAlpha = opacity;
  ctx.strokeStyle = "#63e6be";
  ctx.lineWidth = Math.max(2, w / 400);
  const points = quad ?? [line![0]!, line![1]!,
    [line![1]![0], Math.min(1, line![1]![1] + .08)] as Norm,
    [line![0]![0], Math.min(1, line![0]![1] + .08)] as Norm];
  const gradient = ctx.createLinearGradient(0, Math.min(...points.map((p) => p[1])) * h,
    0, Math.max(...points.map((p) => p[1])) * h);
  gradient.addColorStop(0, "rgba(99,230,190,.08)");
  gradient.addColorStop(1, "rgba(99,230,190,.3)");
  ctx.fillStyle = gradient;
  ctx.beginPath();
  points.forEach(([x, y], i) => i ? ctx.lineTo(viewX(x, mirrored) * w, y * h) : ctx.moveTo(viewX(x, mirrored) * w, y * h));
  ctx.closePath();
  ctx.fill();
  if (quad) ctx.stroke();
  if (line) {
    ctx.setLineDash([10, 5]);
    ctx.beginPath();
    ctx.moveTo(viewX(line[0]![0], mirrored) * w, line[0]![1] * h);
    ctx.lineTo(viewX(line[1]![0], mirrored) * w, line[1]![1] * h);
    ctx.stroke();
  }
  ctx.restore();
}

export function selectionFrom(start: Norm, end: Norm, rect: { width: number; height: number }): Selection {
  const dx = (end[0] - start[0]) * rect.width;
  const dy = (end[1] - start[1]) * rect.height;
  if (Math.hypot(dx, dy) < CLICK_TOLERANCE_PX) return { kind: "point", point: [end[0], end[1]] };
  return {
    kind: "box",
    box: [
      Math.min(start[0], end[0]),
      Math.min(start[1], end[1]),
      Math.max(start[0], end[0]),
      Math.max(start[1], end[1]),
    ],
  };
}

const STATE_DASH: Record<TrackStateName, number[]> = {
  tracking: [],
  grasped: [8, 4],
  occluded: [3, 5],
  searching: [2, 6],
  lost: [2, 10],
};

export const STATE_LABEL: Record<TrackStateName, string> = {
  tracking: "추적 중",
  grasped: "쥔 상태",
  occluded: "가려짐",
  searching: "찾는 중",
  lost: "놓침",
};

export function drawObjects(
  ctx: CanvasRenderingContext2D,
  objects: ObjectInfo[],
  selectedId: number | null,
  w: number,
  h: number,
  mirrored = false,
): void {
  const lw = Math.max(2, w / 400);
  ctx.save();
  ctx.font = `${Math.round(w / 55)}px -apple-system, sans-serif`;
  for (const o of objects) {
    const sel = o.id === selectedId;
    ctx.strokeStyle = o.color;
    ctx.lineWidth = sel ? lw * 1.8 : lw;
    ctx.setLineDash(STATE_DASH[o.state] ?? []);
    if (o.contour.length >= 3) {
      ctx.beginPath();
      o.contour.forEach(([x, y], i) => (i ? ctx.lineTo(viewX(x, mirrored) * w, y * h) : ctx.moveTo(viewX(x, mirrored) * w, y * h)));
      ctx.closePath();
      ctx.globalAlpha = 0.18;
      ctx.fillStyle = o.color;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.stroke();
    } else if (o.box) {
      const [x1, y1, x2, y2] = o.box;
      ctx.strokeRect((mirrored ? 1 - x2 : x1) * w, y1 * h, (x2 - x1) * w, (y2 - y1) * h);
    }
    const anchor = o.box ?? (o.contour[0] ? [...o.contour[0], ...o.contour[0]] : null);
    if (anchor) {
      const label = `${o.name} · ${STATE_LABEL[o.state] ?? o.state}`;
      const tx = (mirrored ? 1 - anchor[2]! : anchor[0]!) * w;
      const ty = Math.max(anchor[1] * h - 6, 16);
      ctx.setLineDash([]);
      ctx.lineWidth = 4;
      ctx.strokeStyle = "rgba(0,0,0,0.7)";
      ctx.strokeText(label, tx, ty);
      ctx.fillStyle = o.color;
      ctx.fillText(label, tx, ty);
    }
  }
  ctx.restore();
}

export function drawHands(ctx: CanvasRenderingContext2D, hands: HandInfo[], w: number, h: number, gesture?: string, mirrored = false): void {
  ctx.save();
  const lw = Math.max(1.5, w / 600);
  for (const hd of hands) {
    ctx.strokeStyle = "rgba(255,255,255,0.85)";
    ctx.lineWidth = lw;
    ctx.beginPath();
    for (const [a, b] of HAND_CONNECTIONS) {
      const pa = hd.points[a];
      const pb = hd.points[b];
      if (!pa || !pb) continue;
      ctx.moveTo(viewX(pa[0], mirrored) * w, pa[1] * h);
      ctx.lineTo(viewX(pb[0], mirrored) * w, pb[1] * h);
    }
    ctx.stroke();
    const tipColor = gesture === "left" ? "#ff4d6d" : gesture === "right" ? "#ffd166" : gesture === "scroll" ? "#74c0fc" : "#8ce99a";
    for (const i of [4, 8, 12]) {
      const p = hd.points[i];
      if (!p) continue;
      ctx.fillStyle = tipColor;
      ctx.beginPath();
      ctx.arc(viewX(p[0], mirrored) * w, p[1] * h, lw * 2.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();
}

/** 펜촉 표시. tip 은 처리 해상도 px 이므로 frame 크기로 정규화한다. */
export function drawPen(ctx: CanvasRenderingContext2D, pen: PenState, frame: [number, number], w: number, h: number, mirrored = false): void {
  if (!pen.tip) return;
  const x = viewX(pen.tip[0] / frame[0], mirrored) * w;
  const y = (pen.tip[1] / frame[1]) * h;
  ctx.save();
  if (pen.axis) {
    ctx.strokeStyle = "rgba(255,255,255,0.6)";
    ctx.lineWidth = Math.max(1, w / 800);
    ctx.beginPath();
    ctx.moveTo(x - pen.axis[0] * (mirrored ? -1 : 1) * w * 0.08, y - pen.axis[1] * w * 0.08);
    ctx.lineTo(x, y);
    ctx.stroke();
  }
  ctx.fillStyle = pen.contact ? "#ff4d6d" : "#ffd166";
  ctx.strokeStyle = "#000";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(x, y, Math.max(4, w / 180), 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}

export function drawPendingPoint(ctx: CanvasRenderingContext2D, p: Norm, w: number, h: number, mirrored = false): void {
  p = [viewX(p[0], mirrored), p[1]];
  ctx.save();
  ctx.strokeStyle = "#ff4d6d";
  ctx.lineWidth = 2;
  const r = Math.max(6, w / 120);
  ctx.beginPath();
  ctx.moveTo(p[0] * w - r, p[1] * h);
  ctx.lineTo(p[0] * w + r, p[1] * h);
  ctx.moveTo(p[0] * w, p[1] * h - r);
  ctx.lineTo(p[0] * w, p[1] * h + r);
  ctx.stroke();
  ctx.restore();
}

export function drawDrag(ctx: CanvasRenderingContext2D, a: Norm, b: Norm, w: number, h: number, mirrored = false): void {
  a = [viewX(a[0], mirrored), a[1]];
  b = [viewX(b[0], mirrored), b[1]];
  ctx.save();
  ctx.setLineDash([6, 4]);
  ctx.lineWidth = Math.max(2, w / 500);
  ctx.strokeStyle = "#ffffff";
  ctx.strokeRect(a[0] * w, a[1] * h, (b[0] - a[0]) * w, (b[1] - a[1]) * h);
  ctx.restore();
}

function clamp01(v: number): number {
  return Math.min(1, Math.max(0, v));
}
