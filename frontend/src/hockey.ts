import { burst, flash, newFx, shake, stepFx, type Fx } from "./fx";
export const HW = 640, HH = 440, RAIL = 24, MALLET = 24, PUCK = 11, GOAL = 92, HOCKEY_WIN = 7;
export type HockeyMode = "pc" | "2p";
export type HockeyDifficulty = "easy" | "normal" | "hard";
export const HOCKEY_AI_SPEED = { easy: 270, normal: 360, hard: 420 };
export interface Point { x: number; y: number }
export interface Disc extends Point { vx: number; vy: number }
export interface Hockey { mode: HockeyMode; difficulty: HockeyDifficulty; mallets: [Disc, Disc]; puck: Disc; trail: Point[]; points: [number, number]; serve: number; lastGoal: number | null; hits: number; score: number; over: boolean; winner: number | null; fx: Fx }
const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));
export const newHockey = (mode: HockeyMode = "pc", difficulty: HockeyDifficulty = "normal"): Hockey => ({ mode, difficulty, mallets: [{ x: HW * .24, y: HH / 2, vx: 0, vy: 0 }, { x: HW * .76, y: HH / 2, vx: 0, vy: 0 }], puck: { x: HW / 2, y: HH / 2, vx: 0, vy: 0 }, trail: [], points: [0, 0], serve: 1.2, lastGoal: null, hits: 0, score: 0, over: false, winner: null, fx: newFx() });
export function stepHockey(state: Hockey, targets: [Point, Point], dt: number): Hockey {
  if (state.over || dt <= 0) return state;
  dt = Math.min(.05, dt);
  const s: Hockey = { ...state, points: [...state.points], mallets: state.mallets.map(m => ({ ...m })) as [Disc, Disc], puck: { ...state.puck }, trail: [...state.trail.slice(-13), { x: state.puck.x, y: state.puck.y }], fx: stepFx(state.fx, dt) };
  const desired = targets.map(p => ({ ...p }));
  if (s.mode === "pc") {
    const active = s.puck.x > HW * .45;
    desired[1] = { x: active ? clamp(s.puck.x + 35, HW / 2 + MALLET, HW - 65) : HW * .78, y: active ? s.puck.y + s.puck.vy * (s.difficulty === "hard" ? .12 : s.difficulty === "easy" ? .04 : .08) : HH / 2 + (s.puck.y - HH / 2) * .45 };
  }
  for (const i of [0, 1] as const) {
    const m = s.mallets[i], p = desired[i]!;
    p.x = clamp(p.x, i === 0 ? RAIL + MALLET : HW / 2 + MALLET, i === 0 ? HW / 2 - MALLET : HW - RAIL - MALLET);
    p.y = clamp(p.y, RAIL + MALLET, HH - RAIL - MALLET);
    const dx = p.x - m.x, dy = p.y - m.y, distance = Math.hypot(dx, dy), limit = dt * (i === 1 && s.mode === "pc" ? HOCKEY_AI_SPEED[s.difficulty] : 1100);
    const k = distance > limit ? limit / distance : 1;
    m.vx = dx * k / dt; m.vy = dy * k / dt;
  }
  const n = Math.max(1, Math.ceil(dt * 200)), sub = dt / n;
  for (let step = 0; step < n; step++) {
    for (const m of s.mallets) { m.x += m.vx * sub; m.y += m.vy * sub; }
    if (s.serve > 0) continue;
    const p = s.puck;
    p.x += p.vx * sub; p.y += p.vy * sub;
    p.vx *= Math.exp(-.045 * sub); p.vy *= Math.exp(-.045 * sub);
    if (p.y < RAIL + PUCK) { p.y = RAIL + PUCK; p.vy = Math.abs(p.vy); }
    if (p.y > HH - RAIL - PUCK) { p.y = HH - RAIL - PUCK; p.vy = -Math.abs(p.vy); }
    const goalMouth = Math.abs(p.y - HH / 2) < GOAL - PUCK;
    if (!goalMouth && p.x < RAIL + PUCK) { p.x = RAIL + PUCK; p.vx = Math.abs(p.vx); }
    if (!goalMouth && p.x > HW - RAIL - PUCK) { p.x = HW - RAIL - PUCK; p.vx = -Math.abs(p.vx); }
    if (p.x < -PUCK || p.x > HW + PUCK) {
      const who = p.x > HW ? 0 : 1;
      s.points[who]++; s.lastGoal = who; s.serve = 1.2; s.trail = [];
      s.puck = { x: HW / 2, y: HH / 2, vx: 0, vy: 0 };
      s.over = s.points[who] >= HOCKEY_WIN; s.winner = s.over ? who : null;
      flash(s.fx, who === 0 ? '#67dfff' : '#ff8c9c', .28); shake(s.fx, 6);
      break;
    }
    for (const m of s.mallets) {
      const dx = p.x - m.x, dy = p.y - m.y, distance = Math.hypot(dx, dy), radius = MALLET + PUCK;
      if (distance >= radius) continue;
      const nx = distance > .01 ? dx / distance : m.x < HW / 2 ? 1 : -1, ny = distance > .01 ? dy / distance : 0;
      p.x = m.x + nx * (radius + .1); p.y = m.y + ny * (radius + .1);
      const closing = (p.vx - m.vx) * nx + (p.vy - m.vy) * ny;
      if (closing < 0) {
        p.vx -= 1.95 * closing * nx; p.vy -= 1.95 * closing * ny;
        const speed = Math.hypot(p.vx, p.vy); if (speed > 1000) { p.vx *= 1000 / speed; p.vy *= 1000 / speed; }
        s.hits++; burst(s.fx, p.x, p.y, ['#c7f5ff', '#88ddff'], 7, 85, 2, 0); shake(s.fx, 1.5);
      }
    }
  }
  if (s.serve > 0 && !s.over) {
    s.serve = Math.max(0, s.serve - dt);
    if (s.serve === 0) { const dir = (s.points[0] + s.points[1]) % 2 === 0 ? -1 : 1; s.puck.vx = 250 * dir; s.puck.vy = 95 * dir; }
  }
  s.score = s.points[0] * 100 + s.hits * 2;
  return s;
}
