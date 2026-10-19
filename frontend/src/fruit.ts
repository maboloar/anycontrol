// 과일 받기 (순수 함수). 640×400. 그물 = 두 손잡이(물체 두 개) 사이의 선분. 75초 동안 과일을 받고 폭탄은 피한다.
// 재미 요소: 12초마다 이벤트(한쪽에서 과일 폭포·폭탄 비·바람·황금 시간·번개 속도, 1.5초 전에 예고), 아이템(자석·슬로모션·넓은 그물·생명),
// 연속 받기 배수(최대 ×5), 마지막 10초 피버(점수 ×2), 시간이 갈수록 빨라짐.
import { burst, flash, newFx, popup, shake, stepFx, type Fx } from "./fx";

export const FW = 640, FH = 400, ROUND = 75, FEVER = 10;
export type DropKind = "apple" | "orange" | "grape" | "melon" | "star" | "bomb" | "magnet" | "slow" | "wide" | "heart";
export interface Drop { id: number; x: number; y: number; vx: number; vy: number; rot: number; vr: number; kind: DropKind }
export interface Net { a: { x: number; y: number }; b: { x: number; y: number } }
export type EventKind = "waterfall" | "bombs" | "wind" | "gold" | "rush";
export interface FruitEvent { kind: EventKind; side: -1 | 1; t: number; warn: number }
export interface Fruit {
  drops: Drop[]; net: Net; score: number; caught: number; missed: number; combo: number; bestCombo: number; lives: number; time: number;
  spawnIn: number; nextId: number; over: boolean; event: FruitEvent | null; eventIn: number; bannerT: number; bannerText: string;
  magnet: number; slow: number; wide: number; fx: Fx;
}
export const POINTS: Record<DropKind, number> = { apple: 10, orange: 15, grape: 20, melon: 40, star: 100, bomb: 0, magnet: 0, slow: 0, wide: 0, heart: 0 };
export const JUICE: Partial<Record<DropKind, string[]>> = {
  apple: ["#ff4d4d", "#ff8a8a", "#fff"], orange: ["#ffa53d", "#ffd28a"], grape: ["#9b5cff", "#c9a3ff"], melon: ["#3fd16b", "#ff5c7a", "#fff"],
  star: ["#ffd43b", "#fff3a3", "#fff"], magnet: ["#ff6b6b", "#c3d0e0"], slow: ["#7ad7ff", "#fff"], wide: ["#7dff9b", "#fff"], heart: ["#ff5c8a", "#fff"],
};
export const EVENT_TEXT: Record<EventKind, [string, string]> = {
  waterfall: ["과일 폭포!", "한쪽에서 과일이 쏟아져요"], bombs: ["폭탄 비!", "💣 를 피하고 ⭐ 를 노려요"],
  wind: ["돌풍!", "과일이 옆으로 날려요"], gold: ["황금 시간!", "⭐ 가 쏟아져요"], rush: ["번개 속도!", "과일이 빨리 떨어져요"],
};

export function newFruit(): Fruit {
  return { drops: [], net: { a: { x: 250, y: 330 }, b: { x: 390, y: 330 } }, score: 0, caught: 0, missed: 0, combo: 0, bestCombo: 0, lives: 3, time: 0,
    spawnIn: .6, nextId: 1, over: false, event: null, eventIn: 9, bannerT: 0, bannerText: "", magnet: 0, slow: 0, wide: 0, fx: newFx() };
}

/** 선분 위 x 에서의 y (x 가 선분 밖이면 null). tol = 양 끝 여유 */
export function netY(n: Net, x: number, tol = 6): number | null {
  const [l, r] = n.a.x <= n.b.x ? [n.a, n.b] : [n.b, n.a];
  if (x < l.x - tol || x > r.x + tol || r.x - l.x < 1) return null;
  return l.y + (r.y - l.y) * Math.max(0, Math.min(1, (x - l.x) / (r.x - l.x)));
}

export const multiplier = (s: Fruit) => Math.min(5, 1 + Math.floor(s.combo / 5)) * (ROUND - s.time <= FEVER ? 2 : 1);

function pickKind(s: Fruit, random: () => number): DropKind {
  const e = s.event && s.event.warn <= 0 ? s.event.kind : null;
  if (e === "gold") return random() < .8 ? "star" : "bomb";
  if (e === "bombs") return random() < .55 ? "bomb" : random() < .5 ? "star" : "apple";
  const r = random(), danger = Math.min(.14, .05 + s.time / 600);
  if (r < danger) return "bomb";
  if (r < danger + .025) return (["magnet", "slow", "wide"] as const)[Math.floor(random() * 3)]!;
  if (r < danger + .03 && s.lives < 3) return "heart";
  if (r < danger + .06) return "star";
  if (r < danger + .14) return "melon";
  return r < .5 ? "apple" : r < .75 ? "orange" : "grape";
}

export function stepFruit(old: Fruit, net: Net, dt: number, random = Math.random): Fruit {
  if (old.over) return old;
  dt = Math.max(0, Math.min(.05, dt));
  const slowF = old.slow > 0 ? .45 : 1;
  const gdt = dt * slowF;                       // 슬로모션: 과일만 느려진다
  const s: Fruit = { ...old, net, time: old.time + dt, drops: [], fx: stepFx(old.fx, dt), bannerT: Math.max(0, old.bannerT - dt),
    magnet: Math.max(0, old.magnet - dt), slow: Math.max(0, old.slow - dt), wide: Math.max(0, old.wide - dt) };
  // 이벤트: 예고(warn) → 진행(t) → 끝
  if (s.event) {
    const e = { ...s.event };
    if (e.warn > 0) { e.warn -= dt; if (e.warn <= 0) { s.bannerT = 2.2; s.bannerText = e.kind; } }
    else e.t -= dt;
    s.event = e.t > 0 ? e : null;
  } else if (ROUND - s.time > FEVER + 4) {
    s.eventIn -= dt;
    if (s.eventIn <= 0) {
      const kinds: EventKind[] = ["waterfall", "waterfall", "bombs", "wind", "gold", "rush"];
      const kind = kinds[Math.floor(random() * kinds.length)]!;
      s.event = { kind, side: random() < .5 ? -1 : 1, t: kind === "wind" ? 5 : 4, warn: 1.5 };
      s.eventIn = 12;
    }
  }
  if (ROUND - s.time <= FEVER && ROUND - old.time > FEVER) { s.bannerT = 2.2; s.bannerText = "fever"; flash(s.fx, "#ffd43b", .3); }
  const ev = s.event && s.event.warn <= 0 ? s.event : null;
  // 생성
  s.spawnIn -= gdt;
  if (s.spawnIn <= 0) {
    const n = ev?.kind === "waterfall" ? 2 : 1;
    for (let k = 0; k < n; k++) {
      const kind = pickKind(s, random);
      const x = ev?.kind === "waterfall" ? (ev.side < 0 ? 30 + random() * 150 : FW - 30 - random() * 150) : 30 + random() * (FW - 60);
      const speed = (95 + random() * 55 + s.time * 1.6) * (ev?.kind === "rush" ? 1.8 : 1) * (kind === "melon" ? 1.25 : 1);
      s.drops.push({ id: s.nextId++, x, y: -16, vx: (random() - .5) * 30, vy: speed, rot: random() * 6, vr: (random() - .5) * 4, kind });
    }
    const fever = ROUND - s.time <= FEVER;
    s.spawnIn = ev?.kind === "waterfall" ? .14 : ev?.kind === "gold" || ev?.kind === "bombs" ? .22 : Math.max(.26, (.9 - s.time / 110) * (fever ? .55 : 1));
  }
  const wind = ev?.kind === "wind" ? ev.side * 150 : 0;
  const tol = s.wide > 0 ? 26 : 6;
  const mid = { x: (net.a.x + net.b.x) / 2, y: (net.a.y + net.b.y) / 2 };
  for (const d0 of [...old.drops, ...s.drops.splice(0)]) {
    const d = { ...d0 };
    const before = netY(net, d.x, tol), prevY = d.y;
    if (s.magnet > 0 && d.kind !== "bomb" && d.y < mid.y) d.vx += Math.sign(mid.x - d.x) * 260 * gdt;   // 자석: 그물 가운데로 끌림
    d.vx += wind * gdt; d.vx *= 1 - .6 * gdt;
    d.x = Math.max(10, Math.min(FW - 10, d.x + d.vx * gdt)); d.y += d.vy * gdt; d.rot += d.vr * gdt;
    const y = netY(net, d.x, tol);
    if (before !== null && y !== null && prevY <= before && d.y >= y) { catchDrop(s, d, y); continue; }
    if (d.y > FH + 20) {
      if (d.kind !== "bomb" && POINTS[d.kind] > 0) { s.combo = 0; s.missed++; }
      continue;
    }
    s.drops.push(d);
  }
  s.over = s.lives <= 0 || s.time >= ROUND;
  return s;
}

function catchDrop(s: Fruit, d: Drop, y: number): void {
  if (d.kind === "bomb") {
    s.lives--; s.combo = 0;
    burst(s.fx, d.x, y, ["#ff8a00", "#ffd43b", "#555", "#222"], 34, 260, 4);
    shake(s.fx, 14); flash(s.fx, "#ff3b3b", .45); popup(s.fx, d.x, y - 20, "💥 -1", "#ff6b6b", 22);
    return;
  }
  if (d.kind === "magnet") { s.magnet = 6; popup(s.fx, d.x, y - 20, "자석!", "#ff8a8a"); }
  else if (d.kind === "slow") { s.slow = 5; popup(s.fx, d.x, y - 20, "슬로모션!", "#7ad7ff"); }
  else if (d.kind === "wide") { s.wide = 7; popup(s.fx, d.x, y - 20, "넓은 그물!", "#7dff9b"); }
  else if (d.kind === "heart") { s.lives = Math.min(5, s.lives + 1); popup(s.fx, d.x, y - 20, "♥ +1", "#ff5c8a"); }
  else {
    s.combo++; s.caught++; s.bestCombo = Math.max(s.bestCombo, s.combo);
    const pts = POINTS[d.kind] * multiplier(s);
    s.score += pts;
    popup(s.fx, d.x, y - 22, `+${pts}`, d.kind === "star" ? "#ffd43b" : "#ffffff", d.kind === "star" ? 24 : 18);
    if (s.combo > 0 && s.combo % 10 === 0) popup(s.fx, d.x, y - 50, `${s.combo} 콤보!`, "#7dff9b", 22);
  }
  burst(s.fx, d.x, y, JUICE[d.kind] ?? ["#fff"], d.kind === "star" || d.kind === "melon" ? 24 : 14, 170, 3);
}
