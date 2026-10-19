// 퐁 (순수 함수). 640×400 경기장. 7점 먼저 내면 승리.
// 재미 요소: 컴퓨터 난이도(쉬움·보통·어려움), 패들을 움직이며 치면 회전(공이 휘어 나감), 랠리가 길수록 빨라지고 8번부터 불꽃 공,
// 가운데에 아이템(큰 패들·빠른 공·공 두 개·상대 패들 작게)이 나타나 공이 지나가면 마지막에 친 쪽이 가진다.
import { burst, flash, newFx, popup, shake, stepFx, type Fx } from "./fx";

export const W = 640, H = 400, PADDLE = 84, WIN = 7;
export type PongMode = 'pc' | '2p';
export type Difficulty = 'easy' | 'normal' | 'hard';
export type PowerKind = 'big' | 'fast' | 'multi' | 'shrink';
export interface Ball { x: number; y: number; vx: number; vy: number; trail: [number, number][] }
export interface Pong {
  mode: PongMode; diff: Difficulty; balls: Ball[]; left: number; right: number; vl: number; vr: number;
  big: [number, number]; small: [number, number];
  power: { x: number; y: number; kind: PowerKind; t: number } | null; powerIn: number; lastHit: 0 | 1;
  scoreL: number; scoreR: number; serveIn: number; rally: number; score: number; over: boolean; winner: 0 | 1 | null; fx: Fx;
  /** 호환: 첫 번째 공 */
  ball: Ball;
}
export const POWER_LABEL: Record<PowerKind, [string, string]> = {
  big: ['큰 패들', 'Big paddle'], fast: ['빠른 공', 'Fast ball'], multi: ['공 두 개', 'Multi-ball'], shrink: ['상대 패들 작게', 'Shrink opponent'],
};
const AI: Record<Difficulty, { speed: number; error: number }> = { easy: { speed: 210, error: 40 }, normal: { speed: 290, error: 18 }, hard: { speed: 420, error: 4 } };

const idle = (): Ball => ({ x: W / 2, y: H / 2, vx: 0, vy: 0, trail: [] });
export function newPong(mode: PongMode = 'pc', diff: Difficulty = 'normal'): Pong {
  const b = idle();
  return { mode, diff, balls: [b], ball: b, left: H / 2, right: H / 2, vl: 0, vr: 0, big: [0, 0], small: [0, 0], power: null, powerIn: 6, lastHit: 0,
    scoreL: 0, scoreR: 0, serveIn: 1.5, rally: 0, score: 0, over: false, winner: null, fx: newFx() };
}
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
export const paddleH = (s: Pong, side: 0 | 1) => PADDLE * (s.big[side] > 0 ? 1.6 : 1) * (s.small[side] > 0 ? 0.6 : 1);

/** targetL/targetR: 패들 중심 목표 (0 위 .. 1 아래). null 이면 그대로 (PC 모드에서 오른쪽은 컴퓨터) */
export function stepPong(old: Pong, targetL: number | null, targetR: number | null, dt: number, random = Math.random): Pong {
  if (old.over) return old;
  dt = clamp(dt, 0, .05);
  const s: Pong = { ...old, balls: old.balls.map((b) => ({ ...b, trail: b.trail })), fx: stepFx(old.fx, dt),
    big: [Math.max(0, old.big[0] - dt), Math.max(0, old.big[1] - dt)], small: [Math.max(0, old.small[0] - dt), Math.max(0, old.small[1] - dt)] };
  const move = (cur: number, target: number | null, speed: number) => target === null ? cur : cur + clamp(target * H - cur, -speed * dt, speed * dt);
  const hl = paddleH(s, 0), hr = paddleH(s, 1);
  const pl = s.left, pr = s.right;
  s.left = clamp(move(s.left, targetL, 1000), hl / 2, H - hl / 2);
  if (s.mode === 'pc') {
    const ai = AI[s.diff];
    const coming = s.balls.filter((b) => b.vx > 0).sort((a, b) => b.x - a.x)[0];
    const aim = coming ? (coming.y + Math.sin(s.rally * 1.7) * ai.error) / H : 0.5;
    s.right = clamp(move(s.right, aim, ai.speed + s.rally * 8), hr / 2, H - hr / 2);
  } else s.right = clamp(move(s.right, targetR, 1000), hr / 2, H - hr / 2);
  s.vl = dt > 0 ? (s.left - pl) / dt : 0; s.vr = dt > 0 ? (s.right - pr) / dt : 0;
  // 서브
  if (s.serveIn > 0) {
    s.serveIn -= dt;
    if (s.serveIn <= 0) {
      const dir = (s.scoreL + s.scoreR) % 2 ? -1 : 1, a = (random() - .5) * .8;
      s.balls = [{ x: W / 2, y: H / 2, vx: dir * 320 * Math.cos(a), vy: 320 * Math.sin(a), trail: [] }];
    }
    s.ball = s.balls[0]!;
    return s;
  }
  // 아이템
  if (s.power) { s.power = { ...s.power, t: s.power.t - dt }; if (s.power.t <= 0) s.power = null; }
  else { s.powerIn -= dt; if (s.powerIn <= 0) { s.power = { x: W / 2 + (random() - .5) * 120, y: 70 + random() * (H - 140), kind: (['big', 'fast', 'multi', 'shrink'] as const)[Math.floor(random() * 4)]!, t: 7 }; s.powerIn = 9; } }
  let scored: 0 | 1 | null = null;
  for (const b of s.balls) {
    b.trail = [...b.trail.slice(-11), [b.x, b.y]];
    b.x += b.vx * dt; b.y += b.vy * dt;
    if (b.y < 8) { b.y = 8; b.vy = Math.abs(b.vy); }
    if (b.y > H - 8) { b.y = H - 8; b.vy = -Math.abs(b.vy); }
    const hit = (px: number, py: number, ph: number, side: number, pv: number, who: 0 | 1) => {
      if (Math.abs(b.x - px) < 12 && Math.abs(b.y - py) < ph / 2 + 8 && Math.sign(b.vx) === -side) {
        const off = (b.y - py) / (ph / 2), speed = Math.min(820, Math.hypot(b.vx, b.vy) * 1.05 + 6);
        b.vx = side * speed * Math.cos(off); b.vy = speed * Math.sin(off) + pv * 0.25;   // 패들 움직임 = 회전
        b.x = px + side * 12;
        s.rally++; s.lastHit = who;
        burst(s.fx, b.x, b.y, who === 0 ? ['#62c7e7', '#fff'] : ['#ff9f6b', '#fff'], 12, 180, 2.5, 0, random);
        if (s.rally > 0 && s.rally % 5 === 0) popup(s.fx, W / 2, 60, `랠리 ${s.rally}!`, '#ffd43b', 20);
      }
    };
    hit(28, s.left, hl, 1, s.vl, 0); hit(W - 28, s.right, hr, -1, s.vr, 1);
    if (s.power && Math.hypot(b.x - s.power.x, b.y - s.power.y) < 22) {
      const k = s.power.kind, who = s.lastHit, other = (1 - who) as 0 | 1;
      if (k === 'big') s.big[who] = 8;
      else if (k === 'shrink') s.small[other] = 7;
      else if (k === 'fast') { b.vx *= 1.4; b.vy *= 1.4; }
      else if (k === 'multi' && s.balls.length < 3) s.balls.push({ x: b.x, y: b.y, vx: b.vx, vy: -b.vy || 160, trail: [] });
      popup(s.fx, s.power.x, s.power.y - 20, POWER_LABEL[k][0], '#7dff9b', 18);
      burst(s.fx, s.power.x, s.power.y, ['#7dff9b', '#fff'], 18, 200, 3, 0, random);
      s.power = null;
    }
    if (b.x < -12) scored = 1; else if (b.x > W + 12) scored = 0;
  }
  s.balls = s.balls.filter((b) => b.x >= -12 && b.x <= W + 12);
  if (scored !== null) {   // 공이 여러 개면 점수만 주고 남은 공으로 계속, 다 나가면 다시 서브
    if (scored === 0) s.scoreL++; else s.scoreR++;
    burst(s.fx, scored === 0 ? W - 10 : 10, H / 2, scored === 0 ? ['#62c7e7', '#fff'] : ['#ff9f6b', '#fff'], 40, 320, 3.5, 0, random);
    shake(s.fx, 12); flash(s.fx, scored === 0 ? '#62c7e7' : '#ff9f6b', .25);
    if (s.balls.length === 0) { s.balls = [idle()]; s.serveIn = 1.5; s.rally = 0; }
  }
  s.ball = s.balls[0]!;
  s.score = s.mode === 'pc' ? s.scoreL * 100 + (s.diff === 'hard' ? s.scoreL * 50 : 0) : 0;
  if (s.scoreL >= WIN || s.scoreR >= WIN) {
    s.over = true; s.winner = s.scoreL >= WIN ? 0 : 1;
    if (s.mode === 'pc' && s.winner === 0) s.score += s.diff === 'hard' ? 1500 : s.diff === 'normal' ? 800 : 400;
  }
  return s;
}
/** 물체 크기(깊이 축, 카메라 쪽으로 오면 +) → 패들 위치. 가까이 = 위. ±0.35 면 끝까지. */
export function sizeToPaddle(depth: number | null | undefined): number | null {
  if (depth === null || depth === undefined || !Number.isFinite(depth)) return null;
  return clamp(0.5 - depth / 0.7, 0, 1);
}
