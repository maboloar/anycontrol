import { HAND_CONNECTIONS, type FrameState, type HandInfo, type ObjectInfo, type PenSkeleton, type PenState, type TipInfo, type TrackStateName } from "./protocol";
import { labels } from "./i18n";

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

export const STATE_LABEL: Record<TrackStateName, string> = labels({
  tracking: ["추적 중", "Tracking"],
  grasped: ["쥔 상태", "Held"],
  occluded: ["가려짐", "Occluded"],
  searching: ["찾는 중", "Searching"],
  lost: ["놓침", "Lost"],
});

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
    if (o.anchor) {     // 커서를 움직이는 기준점 (물체 바닥 아래-가운데): 항상 표시
      const ax = viewX(o.anchor[0], mirrored) * w, ay = o.anchor[1] * h;
      const r = Math.max(5, w / 190);
      ctx.setLineDash([]);
      ctx.lineWidth = lw * 1.6;
      ctx.strokeStyle = "rgba(0,0,0,0.75)";
      ctx.beginPath(); ctx.arc(ax, ay, r + lw, 0, Math.PI * 2); ctx.stroke();
      ctx.fillStyle = o.color;
      ctx.beginPath(); ctx.arc(ax, ay, r, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = lw * 0.9;
      ctx.beginPath(); ctx.arc(ax, ay, r, 0, Math.PI * 2); ctx.stroke();
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

/** 검지(빨강)·중지(초록) 끝점: 직접 추적 중인 점. 눌림은 채운 원, 추적을 잃으면 그리지 않는다. */
export function drawTips(ctx: CanvasRenderingContext2D, tips: Record<string, TipInfo>, w: number, h: number, mirrored = false): void {
  ctx.save();
  const lw = Math.max(1.5, w / 600);
  for (const [name, t] of Object.entries(tips)) {
    if (!t.ok) continue;
    const x = viewX(t.x, mirrored) * w;
    const y = t.y * h;
    const color = name === "index" ? "#ff6b6b" : "#51cf66";
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = lw * 1.5;
    ctx.beginPath();
    ctx.arc(x, y, lw * 5, 0, Math.PI * 2);
    ctx.stroke();
    if (t.down) {
      ctx.beginPath();
      ctx.arc(x, y, lw * 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();
}

/** 펜 뼈대: 보이는 구간은 실선, 손에 가려 곧은 막대로 채운 구간은 점선. 가려진 끝은 속이 빈 원. */
export function drawPenSkeleton(ctx: CanvasRenderingContext2D, sk: PenSkeleton, frame: [number, number], w: number, h: number, mirrored = false): void {
  const px = (p: [number, number]): [number, number] => [viewX(p[0] / frame[0], mirrored) * w, (p[1] / frame[1]) * h];
  const lw = Math.max(2, w / 450);
  const seg = (a: [number, number], b: [number, number]) => {
    const [ax, ay] = px(a), [bx, by] = px(b);
    ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
  };
  ctx.save();
  ctx.lineCap = "round";
  ctx.lineWidth = lw;
  ctx.strokeStyle = "#37e6d0";
  ctx.setLineDash([]);
  for (const [a, b] of sk.visible) seg(a, b);
  ctx.strokeStyle = "#ff9f43";
  ctx.setLineDash([lw * 2.5, lw * 2.5]);
  for (const [a, b] of sk.hidden) seg(a, b);
  ctx.setLineDash([]);
  const r = Math.max(4, w / 200);
  const dot = (p: [number, number], hollow: boolean, color: string) => {
    const [x, y] = px(p);
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.lineWidth = lw; ctx.strokeStyle = color;
    if (hollow) ctx.stroke(); else { ctx.fillStyle = color; ctx.fill(); }
  };
  dot(sk.tail, sk.state === "tail_hidden", "#8ab4ff");
  dot(sk.tip, sk.state === "tip_hidden", "#ffd166");
  ctx.restore();
}

/** 펜촉 표시. tip 은 처리 해상도 px 이므로 frame 크기로 정규화한다. */
export function drawPen(ctx: CanvasRenderingContext2D, pen: PenState, frame: [number, number], w: number, h: number, mirrored = false): void {
  if (pen.skeleton) drawPenSkeleton(ctx, pen.skeleton, frame, w, h, mirrored);
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

const TOUCH_WHY: Record<string, string> = {
  "no-near-hand": "손이 인식되지 않음",
  "global-change": "조명·화면 전체가 바뀜",
  "surface-still-visible": "물체 무늬가 그대로 보임",
  "no-foreground-hand": "손이 물체 앞인지 불확실",
  "await-clear-object": "손을 치우면 기준 모습을 찍어요",
};

/** 물체 터치 피드백: 지켜보는 영역(점선), 바뀐 비율 막대(문턱 표시), 닿으면 초록 테두리와 "터치". */
export function drawTouch(ctx: CanvasRenderingContext2D, touch: NonNullable<import("./protocol").FrameState["touch"]>,
  w: number, h: number, mirrored = false): void {
  ctx.save();
  for (const t of Object.values(touch)) {
    if (!t.box) continue;
    const [bx0, by0, bx1, by1] = t.box;
    const x0 = (mirrored ? 1 - bx1 : bx0) * w, x1 = (mirrored ? 1 - bx0 : bx1) * w, y0 = by0 * h, y1 = by1 * h;
    ctx.lineWidth = t.on ? 4 : 1.5;
    ctx.setLineDash(t.on ? [] : [5, 4]);
    ctx.strokeStyle = t.on ? "#5ee08a" : "rgba(255,255,255,0.55)";
    ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    ctx.setLineDash([]);
    const v = Math.min(1, (t.occluded ?? 0) / Math.max(0.01, (t.min_change ?? 0.06) * 3));
    const th = 1 / 3;
    ctx.fillStyle = "rgba(0,0,0,0.6)"; ctx.fillRect(x0, y1 + 4, x1 - x0, 6);
    ctx.fillStyle = t.on ? "#5ee08a" : "#5b9dff"; ctx.fillRect(x0, y1 + 4, (x1 - x0) * v, 6);
    ctx.fillStyle = "#ffd166"; ctx.fillRect(x0 + (x1 - x0) * th - 1, y1 + 2, 2, 10);
    if (t.on) {
      ctx.fillStyle = "#5ee08a"; ctx.font = "bold 16px system-ui";
      ctx.fillText("터치", x0 + 4, y0 - 6);
    } else {
      // 게이지는 찼는데 터치가 아닐 때: 왜 아닌지 짧게 알려 준다
      const why = TOUCH_WHY[t.reason ?? ""];
      if (why && (v >= th || t.reason === "await-clear-object")) {
        ctx.font = "11px system-ui"; ctx.fillStyle = "rgba(0,0,0,0.6)";
        ctx.fillRect(x0, y1 + 12, ctx.measureText(why).width + 8, 16);
        ctx.fillStyle = "#ffd166"; ctx.fillText(why, x0 + 4, y1 + 24);
      }
    }
  }
  ctx.restore();
}
