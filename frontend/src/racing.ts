// 미니 레이싱 물리 (순수 함수). x: 도로 중심 기준 가로 위치 -1..1 (벗어나면 이탈), speed: 0..MAX_SPEED
// 재미 요소: 굽은 길(원심력), 부스터 발판, 코인 연속 → 니트로, 차선을 바꾸는 느린 차, 기름(빙글 돌며 미끄러짐),
// 600m 마다 스테이지(낮 → 노을 → 밤 → 폭풍)와 함께 빨라짐. 파티클(불꽃·먼지)과 화면 흔들림.
import { burst, flash, newFx, popup, shake, stepFx, type Fx } from "./fx";

export const MAX_SPEED = 3;
export const BOOST_SPEED = 3.8;
/** 2인 경주 결승 거리 (m) */
export const FINISH = 2500;
export const STAGE_LEN = 600;
export const STAGES: [string, string][] = [["낮", "Day"], ["노을", "Sunset"], ["밤", "Night"], ["폭풍", "Storm"]];

export interface Car {
  x: number;
  speed: number;
  dist: number;
  heading: number;
  crashes: number;
}

/** 도로가 굽는 정도 (거리에 따라 천천히 좌우로). 화면에 그리는 곡선과 원심력에 같이 쓴다. */
export function curveAt(dist: number): number {
  return 0.55 * Math.sin(dist / 260) + 0.25 * Math.sin(dist / 97 + 1.3);
}

export function stepCar(c: Car, steer: number, throttle: number, brake: number, dt: number, boost = 0, top = MAX_SPEED): Car {
  const cap = boost > 0 ? BOOST_SPEED : top;
  let speed = c.speed + (throttle * 1.25 - brake * 2.2 - 0.12 * c.speed) * dt + (boost > 0 ? 2.5 * dt : 0);
  speed = Math.max(0, Math.min(Math.max(cap, boost > 0 ? BOOST_SPEED : 0), speed));
  const heading = steer * 0.55;
  const drift = (curveAt(c.dist + 6) - curveAt(c.dist)) * speed * 0.9;   // 굽은 길에서는 바깥으로 밀린다
  let x = c.x + (Math.sin(heading) * speed * 1.45 - drift) * dt;
  let crashes = c.crashes;
  if (Math.abs(x) > 1) {
    x = Math.sign(x) * 1;
    if (Math.abs(c.x) <= 1 - 1e-9) crashes += 1;
    speed *= 0.5;
  }
  return { x, speed, dist: c.dist + speed * dt * 34, heading, crashes };
}

export interface RoadItem { id: number; x: number; ahead: number; kind: 'barrier' | 'coin' | 'boost' | 'car' | 'oil'; vx?: number; tx?: number; color?: string }
export interface Race {
  car: Car; items: RoadItem[]; health: number; score: number; coins: number; combo: number;
  nextSpawn: number; invulnerable: number; boost: number; spin: number; nitro: number; nextId: number; over: boolean; finished: boolean;
  seed: number; stage: number; bannerT: number; fx: Fx;
}
export function newRace(seed = 1): Race {
  return { car: { x: 0, speed: 0, dist: 0, heading: 0, crashes: 0 }, items: [], health: 3,
    score: 0, coins: 0, combo: 0, nextSpawn: 18, invulnerable: 0, boost: 0, spin: 0, nitro: 0, nextId: 1, over: false, finished: false, seed,
    stage: 0, bannerT: 2, fx: newFx() };
}

/** 같은 seed 면 같은 길 (2인 경주에서 두 사람이 똑같은 장애물을 만난다). */
function rand(s: Race): number {
  s.seed = (s.seed + 0x6d2b79f5) | 0;
  let t = s.seed;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}
const CAR_COLORS = ["#f2c14e", "#e05d5d", "#9b7bff", "#5ee08a", "#f2f2f2"];
const LANE = (l: number) => (l - 1) * .65;

/** 도로 한 줄에 막힘은 최대 두 차선이라 항상 지나갈 길이 있다. finish 를 주면 그 거리에서 완주. */
export function stepRace(old: Race, steer: number, throttle: number, brake: number, dt: number, finish?: number): Race {
  if (old.over) return old;
  dt = Math.max(0, Math.min(.05, dt));
  const stage = Math.floor(old.car.dist / STAGE_LEN);
  const top = MAX_SPEED + Math.min(0.6, stage * 0.15);
  // 기름: 빙글 돌며 조향이 듣지 않고 옆으로 미끄러진다
  const spinSteer = old.spin > 0 ? Math.sin(old.spin * 14) * 0.9 : steer;
  const car = stepCar(old.car, spinSteer, old.spin > 0 ? 0 : throttle, brake, dt, old.boost, top);
  const moved = car.dist - old.car.dist;
  const s: Race = { ...old, car, fx: stepFx(old.fx, dt), invulnerable: Math.max(0, old.invulnerable - dt), boost: Math.max(0, old.boost - dt),
    spin: Math.max(0, old.spin - dt), bannerT: Math.max(0, old.bannerT - dt),
    items: old.items.map(o => {
      if (o.kind !== 'car') return { ...o, ahead: o.ahead - moved };
      // 느린 차: 앞으로 가면서 가끔 차선을 바꾼다
      const tx = o.tx ?? o.x, x = o.x + Math.sign(tx - o.x) * Math.min(Math.abs(tx - o.x), 0.9 * dt);
      return { ...o, x, ahead: o.ahead - moved + 1.1 * 34 * dt };
    }) };
  const reached = Math.floor(car.dist / STAGE_LEN);
  if (reached > old.stage) { s.stage = reached; s.bannerT = 2.2; popup(s.fx, 320, 120, `STAGE ${reached + 1}`, "#ffd43b", 26); }
  const hit = (strong = true) => {
    if (s.invulnerable > 0) return;
    s.health--; s.invulnerable = 1.3; s.car.speed *= .4; s.combo = 0; s.boost = 0;
    burst(s.fx, 320 + s.car.x * 150, 338, ["#ffd43b", "#ff8a00", "#fff"], strong ? 28 : 16, 240, 3);
    shake(s.fx, strong ? 14 : 8); flash(s.fx, "#ff3b3b", .3);
  };
  if (car.crashes > old.car.crashes) hit(false);
  if (Math.abs(car.x) > .92 && car.speed > .8) burst(s.fx, 320 + car.x * 150, 352, ["#7a6a4f", "#a8946b"], 2, 60, 2.5, 120);   // 길가 먼지
  for (const item of s.items) {
    const near = item.ahead < 4 && item.ahead > -4;
    const w = item.kind === 'car' ? .3 : item.kind === 'barrier' ? .27 : .25;
    if (!near || Math.abs(item.x - car.x) >= w) continue;
    if (item.kind === 'coin') {
      s.coins++; s.combo++; item.ahead = -20;
      s.nitro = Math.min(1, s.nitro + .2);
      if (s.nitro >= 1) { s.nitro = 0; s.boost = 2.2; popup(s.fx, 320, 200, "NITRO!", "#21e6ff", 26); flash(s.fx, "#21e6ff", .2); }
    } else if (item.kind === 'boost') { s.boost = 1.6; item.ahead = -20; popup(s.fx, 320, 220, "BOOST!", "#5ee08a", 22); }
    else if (item.kind === 'oil') { if (s.spin <= 0 && s.invulnerable <= 0) { s.spin = 1.1; s.combo = 0; popup(s.fx, 320, 220, "미끄러짐!", "#c3c9d4", 20); } item.ahead = -20; }
    else { hit(); item.ahead = -20; }
  }
  s.items = s.items.filter(o => o.ahead > -12 && o.ahead < 160);
  if (car.dist >= s.nextSpawn) {
    const lane = Math.min(2, Math.floor(rand(s) * 3));
    const free = (lane + 1 + Math.floor(rand(s) * 2)) % 3;
    const r = rand(s);
    if (r < .22 + Math.min(.2, stage * .06)) {
      const tl = rand(s) < .5 ? lane : (lane + 1) % 3;
      s.items.push({ id: s.nextId++, x: LANE(lane), ahead: 110, kind: 'car', tx: LANE(tl === free ? lane : tl), color: CAR_COLORS[Math.floor(rand(s) * CAR_COLORS.length)] });
    } else if (r < .32 + Math.min(.1, stage * .03)) s.items.push({ id: s.nextId++, x: LANE(lane), ahead: 105, kind: 'oil' });
    else s.items.push({ id: s.nextId++, x: LANE(lane), ahead: 105, kind: 'barrier' });
    s.items.push({ id: s.nextId++, x: LANE(free), ahead: 112, kind: rand(s) < .2 ? 'boost' : 'coin' });
    if (rand(s) < .45) s.items.push({ id: s.nextId++, x: LANE(free), ahead: 120, kind: 'coin' });
    s.nextSpawn = car.dist + Math.max(22, 54 - car.dist / 110) + rand(s) * 12;
  }
  // 코인 연속이면 배수 (최대 ×5), 스테이지 보너스
  s.score = Math.floor(car.dist) + s.coins * 100 * Math.min(5, 1 + Math.floor(s.combo / 3)) + s.stage * 500;
  if (finish !== undefined && car.dist >= finish) s.finished = true;
  s.over = s.health <= 0 || s.finished;
  return s;
}

/** 2인 경주 상태: 같은 길을 달리는 두 대. 먼저 결승선을 지나거나 상대가 모두 부서지면 승리. */
export interface Duel { p: [Race, Race]; score: number; over: boolean; winner: 0 | 1 | null; time: number }
export function newDuel(seed = Math.floor(Math.random() * 1e9)): Duel {
  return { p: [newRace(seed), newRace(seed)], score: 0, over: false, winner: null, time: 0 };
}
export function stepDuel(d: Duel, steer: [number, number], dt: number): Duel {
  if (d.over) return d;
  const p = d.p.map((r, i) => stepRace(r, steer[i]!, 1, 0, dt, FINISH)) as [Race, Race];
  let winner: 0 | 1 | null = null;
  if (p[0].finished || p[1].finished) winner = p[0].finished && p[1].finished ? (p[0].car.dist >= p[1].car.dist ? 0 : 1) : p[0].finished ? 0 : 1;
  else if (p[0].health <= 0 && p[1].health > 0) winner = 1;
  else if (p[1].health <= 0 && p[0].health > 0) winner = 0;
  const over = winner !== null || (p[0].health <= 0 && p[1].health <= 0);
  return { p, time: d.time + dt, winner, over, score: Math.max(p[0].score, p[1].score) };
}
