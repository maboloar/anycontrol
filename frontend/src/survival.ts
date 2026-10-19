// 좀비 서바이벌 (순수 함수). 640×400. 움직이기만 하면 가까운 좀비를 자동으로 쏜다.
// 웨이브 8개를 버티면 승리. 좀비 종류: 일반·달리기·탱크(체력 많음)·자폭(가까이 오면 터짐)·보스(웨이브 4·8).
// 아이템: 🔋 전지(무기 강화: 한 발 → 두 발 → 산탄 → 연사), ❤️ 회복, 🛡 보호막, 💥 화면 정리. 웨이브가 갈수록 어두워진다(손전등).
import { burst, flash, newFx, popup, shake, stepFx, type Fx } from "./fx";

export const SW = 640, SH = 400, WAVES = 8;
export type ZKind = "walker" | "runner" | "tank" | "bomber" | "boss";
export interface Unit { id: number; x: number; y: number; hp: number; max: number; kind: ZKind; hit: number; fast?: boolean }
export interface Bullet { x: number; y: number; vx: number; vy: number; life: number }
export type PickKind = "battery" | "heal" | "shield" | "nuke";
export interface Pickup { x: number; y: number; kind: PickKind; life: number }
export interface Decal { x: number; y: number; r: number; life: number; color: string }
export interface Survival {
  x: number; y: number; hp: number; maxHp: number; time: number; score: number; kills: number;
  wave: number; toSpawn: number; spawnIn: number; breakT: number; bannerT: number;
  power: number; xp: number; shield: number; aim: number; muzzle: number;
  zombies: Unit[]; bullets: Bullet[]; pickups: Pickup[]; decals: Decal[];
  fireIn: number; invulnerable: number; nextId: number; over: boolean; won: boolean; fx: Fx;
}
const ZSTAT: Record<ZKind, { hp: number; speed: number; r: number; pts: number; dmg: number }> = {
  walker: { hp: 2, speed: 36, r: 12, pts: 25, dmg: 1 }, runner: { hp: 1, speed: 78, r: 9, pts: 35, dmg: 1 },
  tank: { hp: 9, speed: 24, r: 18, pts: 120, dmg: 2 }, bomber: { hp: 2, speed: 52, r: 11, pts: 60, dmg: 2 },
  boss: { hp: 60, speed: 30, r: 30, pts: 1500, dmg: 3 },
};
export const zRadius = (k: ZKind) => ZSTAT[k].r;
export const WEAPON = ["한 발", "두 발", "산탄", "연사"] as const;

export function newSurvival(): Survival {
  return { x: 320, y: 200, hp: 5, maxHp: 5, time: 0, score: 0, kills: 0, wave: 1, toSpawn: waveSize(1), spawnIn: .8, breakT: 0, bannerT: 2.2,
    power: 0, xp: 0, shield: 0, aim: 0, muzzle: 0, zombies: [], bullets: [], pickups: [], decals: [],
    fireIn: 0, invulnerable: 0, nextId: 1, over: false, won: false, fx: newFx() };
}
export const waveSize = (w: number) => 8 + w * 5;
const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));

function pickZombie(wave: number, random: () => number): ZKind {
  const r = random();
  if (wave >= 3 && r < .12 + wave * .01) return "tank";
  if (wave >= 2 && r < .3 + wave * .02) return "runner";
  if (wave >= 4 && r < .42 + wave * .02) return "bomber";
  return "walker";
}

export function stepSurvival(old: Survival, dx: number, dy: number, dt: number, random = Math.random, position?: { x: number; y: number }): Survival {
  if (old.over) return old;
  dt = clamp(dt, 0, .05);
  const s: Survival = { ...old, zombies: old.zombies.map(z => ({ ...z, hit: Math.max(0, z.hit - dt) })), bullets: old.bullets.map(b => ({ ...b })),
    pickups: old.pickups.map(p => ({ ...p, life: p.life - dt })).filter(p => p.life > 0),
    decals: old.decals.map(d => ({ ...d, life: d.life - dt * .08 })).filter(d => d.life > 0),
    time: old.time + dt, invulnerable: Math.max(0, old.invulnerable - dt), shield: Math.max(0, old.shield - dt),
    muzzle: Math.max(0, old.muzzle - dt), bannerT: Math.max(0, old.bannerT - dt), fx: stepFx(old.fx, dt) };
  // 이동
  const length = Math.max(1, Math.hypot(dx, dy));
  s.x = clamp(s.x + dx / length * 130 * dt, 14, SW - 14); s.y = clamp(s.y + dy / length * 130 * dt, 14, SH - 14);
  if (position && Number.isFinite(position.x) && Number.isFinite(position.y)) { s.x = clamp(position.x * SW, 14, SW - 14); s.y = clamp(position.y * SH, 14, SH - 14); }
  // 웨이브: 다 나오고 다 쓰러지면 3초 쉬고 다음 웨이브 (4·8 웨이브는 보스)
  if (s.breakT > 0) {
    s.breakT -= dt;
    if (s.breakT <= 0) { s.wave++; s.toSpawn = waveSize(s.wave); s.bannerT = 2.2; s.spawnIn = .5; }
  } else {
    s.spawnIn -= dt;
    if (s.spawnIn <= 0 && s.toSpawn > 0) {
      const boss = (s.wave === 4 || s.wave === 8) && s.toSpawn === waveSize(s.wave);
      const kind: ZKind = boss ? "boss" : pickZombie(s.wave, random);
      const edge = Math.floor(random() * 4), along = random(), st = ZSTAT[kind];
      const hp = Math.round(st.hp * (1 + (s.wave - 1) * .12));
      s.zombies.push({ id: s.nextId++, x: edge < 2 ? (edge === 0 ? -20 : SW + 20) : along * SW, y: edge >= 2 ? (edge === 2 ? -20 : SH + 20) : along * SH, hp, max: hp, kind, hit: 0 });
      s.toSpawn--;
      s.spawnIn = Math.max(.18, .95 - s.wave * .08) * (random() * .6 + .7);
      if (boss) { s.bannerT = 2.2; shake(s.fx, 10); }
    }
    if (s.toSpawn === 0 && s.zombies.length === 0) {
      if (s.wave >= WAVES) { s.won = true; s.score += 3000; }
      else { s.breakT = 3; s.score += s.wave * 200; popup(s.fx, SW / 2, SH / 2 - 40, `웨이브 ${s.wave} 클리어!`, "#7dff9b", 24); }
    }
  }
  // 사격 (무기 단계: 0 한 발, 1 두 발, 2 산탄, 3 연사)
  s.fireIn -= dt;
  const target = s.zombies.reduce<Unit | null>((best, z) => !best || Math.hypot(z.x - s.x, z.y - s.y) < Math.hypot(best.x - s.x, best.y - s.y) ? z : best, null);
  if (target) s.aim = Math.atan2(target.y - s.y, target.x - s.x);
  if (target && s.fireIn <= 0 && Math.hypot(target.x - s.x, target.y - s.y) < 420) {
    const spread = s.power >= 2 ? [-.22, 0, .22] : s.power >= 1 ? [-.07, .07] : [0];
    for (const a of spread) s.bullets.push({ x: s.x, y: s.y, vx: Math.cos(s.aim + a) * 380, vy: Math.sin(s.aim + a) * 380, life: 1.4 });
    s.fireIn = s.power >= 3 ? .12 : .3;
    s.muzzle = .06;
  }
  // 좀비 이동·공격
  for (const z of s.zombies) {
    if (z.hp <= 0) continue;
    const st = ZSTAT[z.kind];
    const d = Math.max(.01, Math.hypot(z.x - s.x, z.y - s.y));
    const speed = st.speed + Math.min(20, s.wave * 2.2);
    z.x += (s.x - z.x) / d * speed * dt; z.y += (s.y - z.y) / d * speed * dt;
    if (z.kind === "bomber" && d < 34) { explode(s, z, random); continue; }
    if (d < st.r + 9 && s.invulnerable <= 0) {
      if (s.shield > 0) { z.hp = 0; burst(s.fx, z.x, z.y, ["#7ad7ff", "#fff"], 14, 200, 3, 0, random); continue; }
      s.hp -= st.dmg; s.invulnerable = 1.1; shake(s.fx, 10); flash(s.fx, "#ff2b2b", .35);
    }
  }
  // 총알
  for (const b of s.bullets) {
    b.life -= dt; b.x += b.vx * dt; b.y += b.vy * dt;
    const hit = s.zombies.find(z => z.hp > 0 && Math.hypot(z.x - b.x, z.y - b.y) < ZSTAT[z.kind].r + 3);
    if (hit) {
      hit.hp--; hit.hit = .08; b.life = 0;
      hit.x += b.vx * .012; hit.y += b.vy * .012;   // 맞으면 살짝 밀림
      burst(s.fx, b.x, b.y, ["#9bd16f", "#5a8a3a"], 4, 90, 2, 0, random);
    }
  }
  s.bullets = s.bullets.filter(b => b.life > 0 && b.x > -20 && b.x < SW + 20 && b.y > -20 && b.y < SH + 20);
  for (const z of s.zombies) if (z.hp <= 0) kill(s, z, random);
  s.zombies = s.zombies.filter(z => z.hp > 0);
  // 아이템 줍기
  s.pickups = s.pickups.filter(p => {
    if (Math.hypot(p.x - s.x, p.y - s.y) > 22) return true;
    if (p.kind === "battery") {
      s.xp++;
      const need = [3, 6, 10][s.power];
      if (need !== undefined && s.xp >= need) { s.power++; s.xp = 0; popup(s.fx, s.x, s.y - 30, `무기 강화: ${WEAPON[s.power]}!`, "#ffd43b", 20); flash(s.fx, "#ffd43b", .2); }
      else popup(s.fx, s.x, s.y - 24, "+🔋", "#ffd43b", 16);
    } else if (p.kind === "heal") { s.hp = Math.min(s.maxHp, s.hp + 2); popup(s.fx, s.x, s.y - 24, "❤️ +2", "#ff5c8a", 18); }
    else if (p.kind === "shield") { s.shield = 6; popup(s.fx, s.x, s.y - 24, "보호막!", "#7ad7ff", 18); }
    else { for (const z of s.zombies) if (z.kind !== "boss") z.hp = 0; else z.hp -= 15; flash(s.fx, "#ffffff", .6); shake(s.fx, 16); popup(s.fx, SW / 2, SH / 2, "💥 BOOM!", "#ff8a00", 30); }
    return false;
  });
  for (const z of s.zombies) if (z.hp <= 0) kill(s, z, random);
  s.zombies = s.zombies.filter(z => z.hp > 0);
  s.over = s.hp <= 0 || s.won;
  return s;
}

function kill(s: Survival, z: Unit, random: () => number): void {
  if ((z as Unit & { dead?: boolean }).dead) return;
  (z as Unit & { dead?: boolean }).dead = true;
  s.kills++; s.score += ZSTAT[z.kind].pts;
  burst(s.fx, z.x, z.y, z.kind === "boss" ? ["#b04bff", "#ff5c8a", "#fff"] : ["#7fb35a", "#4d7a35", "#a33"], z.kind === "boss" ? 60 : 14, z.kind === "boss" ? 320 : 150, 3, 0, random);
  s.decals.push({ x: z.x, y: z.y, r: ZSTAT[z.kind].r * (1 + random() * .5), life: 1, color: random() < .5 ? "#3a5a2a" : "#5a1f1f" });
  if (s.decals.length > 60) s.decals.shift();
  if (z.kind === "boss") { shake(s.fx, 18); popup(s.fx, z.x, z.y - 40, "BOSS DOWN!", "#ffd43b", 28); for (let i = 0; i < 4; i++) s.pickups.push({ x: z.x + (i - 1.5) * 24, y: z.y, kind: i === 0 ? "heal" : "battery", life: 12 }); return; }
  if (z.kind === "bomber") explode(s, z, random);
  const r = random();
  const drop: PickKind | null = r < .14 ? "battery" : r < .17 ? "heal" : r < .19 ? "shield" : r < .2 ? "nuke" : null;
  if (z.kind === "tank" || drop) s.pickups.push({ x: z.x, y: z.y, kind: z.kind === "tank" && !drop ? "battery" : drop!, life: 9 });
}

function explode(s: Survival, z: Unit, random: () => number): void {
  const zz = z as Unit & { boom?: boolean };
  if (zz.boom) return;
  zz.boom = true;
  z.hp = 0;
  burst(s.fx, z.x, z.y, ["#ff8a00", "#ffd43b", "#ff3b3b", "#333"], 36, 280, 4, 0, random);
  shake(s.fx, 12);
  for (const o of s.zombies) if (o !== z && o.hp > 0 && Math.hypot(o.x - z.x, o.y - z.y) < 70) o.hp -= 4;
  if (Math.hypot(s.x - z.x, s.y - z.y) < 60 && s.invulnerable <= 0 && s.shield <= 0) { s.hp -= ZSTAT.bomber.dmg; s.invulnerable = 1.1; flash(s.fx, "#ff8a00", .4); }
}
