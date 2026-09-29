/** 신호기 90: 자동 사격 + 전지 운반 + 충격파. 좌표는 640×400 경기장. */
export interface Unit { id: number; x: number; y: number; hp: number; fast: boolean; }
export interface Bullet { x: number; y: number; vx: number; vy: number; life: number; }
export interface Cell { x: number; y: number; }
export interface Survival {
  x: number; y: number; hp: number; time: number; score: number; kills: number; charge: number; carrying: number;
  zombies: Unit[]; bullets: Bullet[]; cells: Cell[]; spawnIn: number; fireIn: number; pulseIn: number;
  pulseRadius: number; invulnerable: number; nextId: number; over: boolean; won: boolean;
}
export function newSurvival(): Survival {
  return { x: 320, y: 200, hp: 5, time: 0, score: 0, kills: 0, charge: 0, carrying: 0,
    zombies: [], bullets: [], cells: [{ x: 140, y: 100 }, { x: 500, y: 300 }], spawnIn: .8, fireIn: 0,
    pulseIn: 0, pulseRadius: 0, invulnerable: 0, nextId: 1, over: false, won: false };
}
const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));
export function stepSurvival(old: Survival, dx: number, dy: number, pulse: boolean, dt: number, random = Math.random, position?: { x: number; y: number }): Survival {
  if (old.over) return old;
  dt = clamp(dt, 0, .05);
  const s: Survival = { ...old, zombies: old.zombies.map(z => ({ ...z })), bullets: old.bullets.map(b => ({ ...b })),
    cells: old.cells.map(c => ({ ...c })), time: old.time + dt, pulseIn: Math.max(0, old.pulseIn - dt),
    invulnerable: Math.max(0, old.invulnerable - dt), pulseRadius: Math.max(0, old.pulseRadius - 230 * dt) };
  const length = Math.max(1, Math.hypot(dx, dy));
  s.x = clamp(s.x + dx / length * 115 * dt, 14, 626); s.y = clamp(s.y + dy / length * 115 * dt, 14, 386);
  if (position && Number.isFinite(position.x) && Number.isFinite(position.y)) {
    s.x = clamp(position.x * 640, 14, 626);
    s.y = clamp(position.y * 400, 14, 386);
  }
  s.spawnIn -= dt;
  if (s.spawnIn <= 0 && s.zombies.length < 70) {
    const edge = Math.floor(random() * 4), along = random();
    const fast = s.time > 18 && random() < .3;
    s.zombies.push({ id: s.nextId++, x: edge < 2 ? (edge === 0 ? -12 : 652) : along * 640,
      y: edge >= 2 ? (edge === 2 ? -12 : 412) : along * 400, hp: fast ? 1 : 2, fast });
    s.spawnIn = Math.max(.24, 1.2 - s.time / 100);
  }
  s.fireIn -= dt;
  const target = s.zombies.reduce<Unit | null>((best, z) => !best || Math.hypot(z.x - s.x, z.y - s.y) < Math.hypot(best.x - s.x, best.y - s.y) ? z : best, null);
  if (target && s.fireIn <= 0) {
    const d = Math.max(.001, Math.hypot(target.x - s.x, target.y - s.y));
    s.bullets.push({ x: s.x, y: s.y, vx: (target.x - s.x) / d * 330, vy: (target.y - s.y) / d * 330, life: 2 });
    s.fireIn = Math.max(.16, .38 - s.charge * .015);
  }
  if (pulse && s.pulseIn <= 0) {
    s.pulseIn = 6; s.pulseRadius = 105;
    for (const z of s.zombies) if (Math.hypot(z.x - s.x, z.y - s.y) < 105) z.hp -= 3;
  }
  for (const z of s.zombies) {
    if (z.hp <= 0) continue;
    const d = Math.max(.01, Math.hypot(z.x - s.x, z.y - s.y));
    const speed = (z.fast ? 72 : 35) + Math.min(22, s.time * .15);
    z.x += (s.x - z.x) / d * speed * dt; z.y += (s.y - z.y) / d * speed * dt;
    if (d < 21 && s.invulnerable <= 0) { s.hp--; s.invulnerable = 1.1; }
  }
  for (const b of s.bullets) {
    b.life -= dt; b.x += b.vx * dt; b.y += b.vy * dt;
    const hit = s.zombies.find(z => z.hp > 0 && Math.hypot(z.x - b.x, z.y - b.y) < 14);
    if (hit) { hit.hp--; b.life = 0; }
  }
  s.bullets = s.bullets.filter(b => b.life > 0 && b.x > -20 && b.x < 660 && b.y > -20 && b.y < 420);
  for (const z of s.zombies) if (z.hp <= 0) {
    s.kills++;
    if (s.kills % 3 === 0 && s.cells.length < 20) s.cells.push({ x: clamp(z.x, 25, 615), y: clamp(z.y, 25, 375) });
  }
  s.zombies = s.zombies.filter(z => z.hp > 0);
  s.cells = s.cells.filter(c => {
    if (s.carrying < 3 && Math.hypot(c.x - s.x, c.y - s.y) < 24) { s.carrying++; return false; }
    return true;
  });
  if (Math.hypot(s.x - 320, s.y - 200) < 36 && s.carrying) {
    s.charge += s.carrying; s.carrying = 0; s.hp = Math.min(5, s.hp + 1);
  }
  s.won = s.time >= 90 && s.charge >= 8 && s.hp > 0;
  s.over = s.hp <= 0 || s.won;
  s.score = Math.floor(s.time) * 5 + s.kills * 25 + s.charge * 150 + (s.won ? 1500 : 0);
  return s;
}
