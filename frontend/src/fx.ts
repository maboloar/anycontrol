// 게임 공통 효과: 파티클, 떠오르는 글자, 화면 흔들림, 그리기 도우미. 상태는 순수 데이터라 게임 상태 안에 넣어 쓴다.

export interface Particle { x: number; y: number; vx: number; vy: number; life: number; max: number; size: number; color: string; g: number }
export interface Popup { x: number; y: number; text: string; life: number; color: string; size: number }
export interface Fx { parts: Particle[]; pops: Popup[]; shake: number; flash: number; flashColor: string }

export const newFx = (): Fx => ({ parts: [], pops: [], shake: 0, flash: 0, flashColor: "#fff" });

/** 터지는 파티클. g = 중력(px/s²) */
export function burst(fx: Fx, x: number, y: number, color: string | string[], n = 14, speed = 160, size = 3, g = 300, random = Math.random): void {
  for (let i = 0; i < n; i++) {
    const a = random() * Math.PI * 2, v = speed * (0.35 + random() * 0.65);
    const c = Array.isArray(color) ? color[Math.floor(random() * color.length)]! : color;
    const life = 0.4 + random() * 0.5;
    fx.parts.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v - speed * 0.3, life, max: life, size: size * (0.6 + random() * 0.8), color: c, g });
  }
  if (fx.parts.length > 500) fx.parts.splice(0, fx.parts.length - 500);
}

export function popup(fx: Fx, x: number, y: number, text: string, color = "#ffd166", size = 18): void {
  fx.pops.push({ x, y, text, life: 0.9, color, size });
}

export function shake(fx: Fx, amount: number): void { fx.shake = Math.max(fx.shake, amount); }
export function flash(fx: Fx, color: string, amount = 0.35): void { fx.flash = Math.max(fx.flash, amount); fx.flashColor = color; }

/** 효과 시간 진행 (게임 step 마다) */
export function stepFx(fx: Fx, dt: number): Fx {
  return {
    parts: fx.parts.filter((p) => p.life > dt).map((p) => ({ ...p, x: p.x + p.vx * dt, y: p.y + p.vy * dt, vy: p.vy + p.g * dt, vx: p.vx * (1 - 1.2 * dt), life: p.life - dt })),
    pops: fx.pops.filter((p) => p.life > dt).map((p) => ({ ...p, y: p.y - 40 * dt, life: p.life - dt })),
    shake: Math.max(0, fx.shake - 30 * dt), flash: Math.max(0, fx.flash - 1.6 * dt), flashColor: fx.flashColor,
  };
}

/** 화면 흔들림 적용 (save 한 뒤 호출, 그린 뒤 restore) */
export function applyShake(g: CanvasRenderingContext2D, fx: Fx): void {
  if (fx.shake > 0) g.translate((Math.random() - 0.5) * fx.shake, (Math.random() - 0.5) * fx.shake);
}

export function drawFx(g: CanvasRenderingContext2D, fx: Fx, W: number, H: number): void {
  for (const p of fx.parts) {
    g.globalAlpha = Math.max(0, p.life / p.max);
    g.fillStyle = p.color;
    g.beginPath(); g.arc(p.x, p.y, p.size, 0, Math.PI * 2); g.fill();
  }
  g.globalAlpha = 1;
  g.textAlign = "center"; g.textBaseline = "middle";
  for (const p of fx.pops) {
    g.globalAlpha = Math.min(1, p.life * 2.2);
    g.font = `900 ${p.size}px system-ui`;
    g.lineWidth = 4; g.strokeStyle = "#0008"; g.strokeText(p.text, p.x, p.y);
    g.fillStyle = p.color; g.fillText(p.text, p.x, p.y);
  }
  g.globalAlpha = 1; g.textAlign = "left"; g.textBaseline = "alphabetic";
  if (fx.flash > 0) { g.globalAlpha = Math.min(0.6, fx.flash); g.fillStyle = fx.flashColor; g.fillRect(0, 0, W, H); g.globalAlpha = 1; }
}

export function roundRect(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  g.beginPath();
  g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r);
  g.closePath();
}

/** 가운데 큰 글자 배너 (이벤트·웨이브 알림). t = 남은 시간(초), 처음 0.3초는 커지며 나타난다 */
export function banner(g: CanvasRenderingContext2D, W: number, H: number, title: string, sub: string, t: number, color = "#ffd166"): void {
  if (t <= 0) return;
  const a = Math.min(1, t * 2), grow = Math.min(1, (2.2 - Math.min(2.2, t)) / 0.3);
  g.save();
  g.globalAlpha = a;
  g.fillStyle = "#0009"; g.fillRect(0, H * 0.36, W, H * 0.2);
  g.textAlign = "center"; g.textBaseline = "middle";
  g.font = `900 ${Math.round(28 + 6 * (1 - Math.min(1, grow)))}px system-ui`;
  g.lineWidth = 5; g.strokeStyle = "#000a"; g.strokeText(title, W / 2, H * 0.43);
  g.fillStyle = color; g.fillText(title, W / 2, H * 0.43);
  g.font = "600 14px system-ui"; g.fillStyle = "#e8edf5"; g.fillText(sub, W / 2, H * 0.51);
  g.restore();
}

/** 간단한 결정적 난수 (seed 고정 시 같은 결과, 테스트용) */
export function rng(seed: number): () => number {
  let s = seed | 0;
  return () => { s = (s + 0x6d2b79f5) | 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

/** 벡터로 그린 아이콘 (이모지 글꼴이 없어도 같은 모양). (0,0) 중심, r = 반지름 */
export type Icon = "apple" | "orange" | "grape" | "melon" | "star" | "bomb" | "magnet" | "slow" | "wide" | "heart" | "battery" | "shield" | "nuke";
export function drawIcon(g: CanvasRenderingContext2D, kind: Icon, r: number, time = 0): void {
  const circle = (x: number, y: number, rr: number, c: string) => { g.fillStyle = c; g.beginPath(); g.arc(x, y, rr, 0, Math.PI * 2); g.fill(); };
  const shine = () => { g.fillStyle = "#ffffff70"; g.beginPath(); g.ellipse(-r * .35, -r * .35, r * .28, r * .18, -.6, 0, Math.PI * 2); g.fill(); };
  const badge = (c: string) => { circle(0, 0, r, "#ffffffee"); g.strokeStyle = c; g.lineWidth = 3; g.beginPath(); g.arc(0, 0, r - 1.5, 0, Math.PI * 2); g.stroke(); };
  switch (kind) {
    case "apple":
      circle(-r * .3, 0, r * .72, "#e63946"); circle(r * .3, 0, r * .72, "#e63946"); circle(0, r * .15, r * .75, "#d62839");
      g.strokeStyle = "#5b3a1a"; g.lineWidth = 2.5; g.beginPath(); g.moveTo(0, -r * .5); g.lineTo(r * .1, -r * 1.05); g.stroke();
      g.fillStyle = "#3fbf5f"; g.beginPath(); g.ellipse(r * .35, -r * .85, r * .35, r * .16, -.5, 0, Math.PI * 2); g.fill(); shine(); break;
    case "orange":
      circle(0, 0, r, "#ff9f1c"); g.fillStyle = "#e88a0a"; for (let i = 0; i < 6; i++) { g.beginPath(); g.arc(Math.cos(i) * r * .5, Math.sin(i * 1.7) * r * .5, 1.4, 0, Math.PI * 2); g.fill(); }
      g.fillStyle = "#3fbf5f"; g.beginPath(); g.ellipse(0, -r * .95, r * .3, r * .14, .3, 0, Math.PI * 2); g.fill(); shine(); break;
    case "grape":
      for (const [x, y] of [[-.45, -.45], [.05, -.5], [.5, -.4], [-.25, 0], [.25, 0], [0, .45], [-.5, .35], [.45, .35]]) circle(x! * r, y! * r, r * .36, "#7b3fd1");
      for (const [x, y] of [[-.55, -.55], [-.35, -.1], [.15, -.6]]) circle(x! * r, y! * r, r * .1, "#c8a6ff");
      g.strokeStyle = "#5b3a1a"; g.lineWidth = 2; g.beginPath(); g.moveTo(0, -r * .8); g.lineTo(0, -r * 1.1); g.stroke(); break;
    case "melon":
      circle(0, 0, r, "#2d8a3e"); g.strokeStyle = "#1b5e2a"; g.lineWidth = 2.5;
      for (const a of [-.9, -.3, .3, .9]) { g.beginPath(); g.ellipse(0, 0, r * Math.abs(Math.cos(a)) * .9 + 1, r * .97, 0, 0, Math.PI * 2); g.stroke(); }
      shine(); break;
    case "star": {
      g.shadowColor = "#ffd43b"; g.shadowBlur = 14; g.fillStyle = "#ffd43b"; g.beginPath();
      for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + i * Math.PI / 5, rr = i % 2 ? r * .45 : r; g.lineTo(Math.cos(a) * rr, Math.sin(a) * rr); }
      g.closePath(); g.fill(); g.shadowBlur = 0; g.fillStyle = "#fff3a3"; g.beginPath(); g.arc(-r * .15, -r * .2, r * .18, 0, Math.PI * 2); g.fill(); break;
    }
    case "bomb":
      circle(0, r * .1, r * .9, "#22252b"); g.fillStyle = "#3a3f49"; g.fillRect(-r * .25, -r * .95, r * .5, r * .35);
      g.strokeStyle = "#a0805a"; g.lineWidth = 2; g.beginPath(); g.moveTo(0, -r * .95); g.quadraticCurveTo(r * .4, -r * 1.3, r * .55, -r * 1.15); g.stroke();
      circle(r * .6, -r * 1.2, 3 + Math.sin(time * 30) * 1.2, "#ffb000"); circle(-r * .3, -r * .15, r * .18, "#ffffff40"); break;
    case "magnet":
      badge("#ff6b6b"); g.strokeStyle = "#e63946"; g.lineWidth = r * .32; g.beginPath(); g.arc(0, -r * .05, r * .42, Math.PI, 0); g.stroke();
      g.fillStyle = "#c3c9d4"; g.fillRect(-r * .58, -r * .1, r * .32, r * .35); g.fillRect(r * .26, -r * .1, r * .32, r * .35); break;
    case "slow":
      badge("#4dabf7"); g.strokeStyle = "#1c7ed6"; g.lineWidth = 2.5; g.beginPath(); g.arc(0, 0, r * .55, 0, Math.PI * 2); g.stroke();
      g.beginPath(); g.moveTo(0, 0); g.lineTo(0, -r * .4); g.moveTo(0, 0); g.lineTo(r * .3, r * .1); g.stroke(); break;
    case "wide":
      badge("#40c057"); g.strokeStyle = "#2b8a3e"; g.lineWidth = 3; g.beginPath();
      g.moveTo(-r * .6, 0); g.lineTo(r * .6, 0); g.moveTo(-r * .6, 0); g.lineTo(-r * .3, -r * .3); g.moveTo(-r * .6, 0); g.lineTo(-r * .3, r * .3);
      g.moveTo(r * .6, 0); g.lineTo(r * .3, -r * .3); g.moveTo(r * .6, 0); g.lineTo(r * .3, r * .3); g.stroke(); break;
    case "heart":
      g.fillStyle = "#ff4d7a"; g.beginPath(); g.moveTo(0, r * .8);
      g.bezierCurveTo(-r * 1.2, -r * .1, -r * .6, -r * 1.05, 0, -r * .35); g.bezierCurveTo(r * .6, -r * 1.05, r * 1.2, -r * .1, 0, r * .8); g.fill(); shine(); break;
    case "battery":
      g.fillStyle = "#ffd43b"; g.fillRect(-r * .45, -r * .8, r * .9, r * 1.6); g.fillStyle = "#c99a00"; g.fillRect(-r * .2, -r, r * .4, r * .22);
      g.fillStyle = "#1b1b1b"; g.fillRect(-r * .08, -r * .4, r * .16, r * .6); g.fillRect(-r * .3, -r * .18, r * .6, r * .16); break;
    case "shield":
      g.fillStyle = "#4dabf7"; g.beginPath(); g.moveTo(0, -r); g.lineTo(r * .85, -r * .6); g.lineTo(r * .7, r * .3); g.lineTo(0, r); g.lineTo(-r * .7, r * .3); g.lineTo(-r * .85, -r * .6); g.closePath(); g.fill();
      g.fillStyle = "#d0ebff"; g.beginPath(); g.moveTo(0, -r * .65); g.lineTo(r * .5, -r * .4); g.lineTo(0, r * .6); g.closePath(); g.fill(); break;
    case "nuke":
      circle(0, 0, r, "#ff8a00"); circle(0, 0, r * .7, "#ffd43b");
      g.fillStyle = "#1b1b1b"; g.font = `900 ${Math.round(r * 1.2)}px system-ui`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText("!", 0, r * .05); break;
  }
}
