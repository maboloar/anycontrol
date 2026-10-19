import { gameCanvas } from "../gameCanvas";
import { useRef, useState } from 'react';
import { useGameMapping } from "./GameMappingBar";
import { GameButtons } from './GameButtons';
import { Panel } from './Panel';
import { useGameLoop, useGameSession, type GameObject } from './gameSession';
import { EVENT_TEXT, FEVER, FH, FW, multiplier, newFruit, ROUND, stepFruit, type Fruit, type Net } from '../fruit';
import { applyShake, banner, drawFx, drawIcon } from '../fx';
import { t } from '../i18n';

const EVENT_EN: Record<keyof typeof EVENT_TEXT, [string, string]> = {
  waterfall: ['Fruit waterfall!', 'Fruit pours from one side'], bombs: ['Bomb rain!', 'Dodge 💣, grab ⭐'],
  wind: ['Gust!', 'Fruit blows sideways'], gold: ['Golden time!', '⭐ everywhere'], rush: ['Speed rush!', 'Fruit falls fast'],
};
const evText = (k: keyof typeof EVENT_TEXT) => t(EVENT_TEXT[k], EVENT_EN[k]);

export function FruitDemo() {
  const [players, setPlayers] = useState(1);
  const playersRef = useRef(players); playersRef.current = players;
  const setup = useGameMapping('fruit', players);
  const s = useGameSession('anycontrol.fruit.best', newFruit, setup.check);
  const keyX = useRef(FW / 2);
  const handles = useRef<GameObject[]>([]);
  useGameLoop(s, dt => {
    keyX.current = Math.max(70, Math.min(FW - 70, keyX.current + (Number(s.control('d') || s.control('arrowright')) - Number(s.control('a') || s.control('arrowleft'))) * 460 * dt));
    const ctl = (axis: string, player: number) => s.demoControl(`fruit.${axis}${player}`);
    const y = (player: number) => Math.max(120, Math.min(FH - 20, FH * (.72 + .24 * ctl('y', player))));
    const keyboard = Number(s.control('d') || s.control('arrowright')) - Number(s.control('a') || s.control('arrowleft'));
    const center = keyboard ? keyX.current : FW * (.5 + .4 * ctl('x', 1));
    const net: Net = playersRef.current === 2
      ? { a: { x: FW * (.25 + .24 * ctl('x', 1)), y: y(1) }, b: { x: FW * (.75 + .24 * ctl('x', 2)), y: y(2) } }
      : { a: { x: center - 70, y: y(1) }, b: { x: center + 70, y: y(1) } };
    handles.current = []; // Labels never choose or steer controllers; mappings are the only physical input.
    s.game.current = stepFruit(s.game.current, net, dt);
  }, (c, g, p) => drawFruit(c, g, p, handles.current));
  const g = s.snapshot;
  const n = players;
  return <Panel title={t("과일 받기", "Fruit Catch")} label="과일 받기 데모" className="demo" detail={t("매핑한 컨트롤러로 그물 조작", "Mapped controllers move the net")}
    info={t(<>자동 매핑에서 <b>1인/2인과 바닥/들기 조작</b>을 선택하면 매핑 패널에 손잡이 연결이 생깁니다. 두 물체를 함께 움직여 과일을 받으세요. 12초마다 <b>이벤트</b>(과일 폭포·폭탄 비·돌풍·황금 시간·번개 속도)가 예고 뒤 시작되고, 🧲 자석·🐢 슬로모션·🥅 넓은 그물·❤️ 생명 아이템이 떨어집니다. 연속으로 받으면 점수 배수, 마지막 10초는 피버(×2). 💣 는 피하세요. Space = 일시정지.</>,
      <>Choose <b>1P/2P and desk/held controls</b> in Auto-map to create handle connections in Mapping. Move both to catch fruit. Every 12 s an announced <b>event</b> (fruit waterfall, bomb rain, gust, golden time, speed rush) starts, and 🧲 magnet, 🐢 slow-mo, 🥅 wide net, ❤️ life items drop. Streaks multiply points; the last 10 s is fever (×2). Avoid 💣. Space = pause.</>)}>
    <div ref={s.root} tabIndex={0} className="game-stage" aria-label={t("과일 받기 조작 영역", "Fruit catch play area")} {...s.handlers}>
      <div className="row game-mode" role="radiogroup" aria-label={t("인원", "Players")}>{[1, 2].map(n => <button key={n} type="button" role="radio" aria-checked={players === n} className={players === n ? 'active' : ''} onClick={() => { s.pause(); setPlayers(n); }}>{n === 1 ? t("1인 · 컨트롤러 1개", "1P · 1 controller") : t("2인 · 컨트롤러 2개", "2P · 2 controllers")}</button>)}</div>
      {setup.bar(<GameButtons s={s} over={g.over} status={g.over ? t(`끝! ${g.score}점 · ${g.caught}개 · 최고 콤보 ${g.bestCombo}`, `Done! ${g.score} pts · ${g.caught} caught · best combo ${g.bestCombo}`) : s.paused ? t('준비 / 일시정지', 'Ready / Paused') : n >= 2 ? t('두 손잡이로 그물을 움직이세요', 'Move the net with both handles') : t('1인 손잡이 연결로 그물을 움직이세요', 'Move the net with the 1P handle mapping')} />)}
      <div className="game-hud" aria-label={t("과일 받기 점수", "Fruit catch score")}>
        <span>{t('점수', 'Score')} <b>{g.score}</b></span><span>{t('최고', 'Best')} <b>{s.best}</b></span>
        <span>{t('생명', 'Lives')} <b>{'♥'.repeat(Math.max(0, g.lives)) || '0'}</b></span><span>{t('콤보', 'Combo')} <b>{g.combo} (×{multiplier(g)})</b></span>
        <span>{t('손잡이', 'Handles')} <b>{n}/2</b></span>
      </div>
      <canvas ref={s.canvas} width={FW} height={FH} className="drawpad game-canvas" role="img" aria-label={t("떨어지는 과일과 그물", "Falling fruit and a net")} />

    </div>
  </Panel>;
}

function sky(g: CanvasRenderingContext2D, p: number) {
  // p: 0 (낮) → 1 (노을)
  const top = mix([70, 150, 230], [60, 40, 110], p), bot = mix([170, 220, 255], [255, 150, 90], p);
  const gr = g.createLinearGradient?.(0, 0, 0, FH);
  if (gr) { gr.addColorStop(0, `rgb(${top})`); gr.addColorStop(1, `rgb(${bot})`); g.fillStyle = gr; } else g.fillStyle = `rgb(${top})`;
  g.fillRect(0, 0, FW, FH);
  g.fillStyle = `rgba(255, ${Math.round(240 - 80 * p)}, ${Math.round(150 - 80 * p)}, 0.9)`;
  g.beginPath(); g.arc(520, 70 + 170 * p, 34, 0, Math.PI * 2); g.fill();
}
const mix = (a: number[], b: number[], p: number) => a.map((v, i) => Math.round(v + (b[i]! - v) * p)).join(',');

export function drawFruit(c: HTMLCanvasElement | null, s: Fruit, paused: boolean, handles: GameObject[] = []) {
  const g = gameCanvas(c, FW, FH); if (!c || !g) return;
  g.save();
  applyShake(g, s.fx);
  sky(g, Math.min(1, s.time / ROUND));
  // 구름
  g.fillStyle = '#ffffffb0';
  for (let i = 0; i < 4; i++) {
    const x = ((i * 190 + s.time * (8 + i * 3)) % (FW + 160)) - 80, y = 40 + i * 28;
    g.beginPath(); g.ellipse(x, y, 42, 14, 0, 0, Math.PI * 2); g.ellipse(x + 26, y - 8, 28, 12, 0, 0, Math.PI * 2); g.fill();
  }
  // 언덕과 풀밭
  g.fillStyle = '#3f8f5a'; g.beginPath(); g.moveTo(0, FH);
  for (let x = 0; x <= FW; x += 20) g.lineTo(x, FH - 70 - Math.sin(x / 90) * 18 - Math.sin(x / 37) * 6);
  g.lineTo(FW, FH); g.fill();
  g.fillStyle = '#2d6e44'; g.fillRect(0, FH - 26, FW, 26);
  // 이벤트 예고: 쏟아질 쪽 깜빡이는 화살표
  const ev = s.event;
  if (ev && ev.warn > 0 && Math.floor(ev.warn * 6) % 2 === 0) {
    const x = ev.kind === 'waterfall' ? (ev.side < 0 ? 100 : FW - 100) : FW / 2;
    g.fillStyle = ev.kind === 'bombs' ? '#ff5c5c' : '#ffd43b';
    g.font = '900 34px system-ui'; g.textAlign = 'center';
    g.fillText(ev.kind === 'wind' ? (ev.side > 0 ? '➡➡' : '⬅⬅') : '⬇', x, 40);
    g.font = '700 14px system-ui'; g.fillText(evText(ev.kind)[0], x, 62); g.textAlign = 'left';
  }
  if (ev && ev.warn <= 0 && ev.kind === 'wind') {   // 바람 줄무늬
    g.strokeStyle = '#ffffff55'; g.lineWidth = 2;
    for (let i = 0; i < 10; i++) { const y = 60 + i * 30, x = ((i * 70 + s.time * 400 * ev.side) % FW + FW) % FW; g.beginPath(); g.moveTo(x, y); g.lineTo(x + 40 * ev.side, y); g.stroke(); }
  }
  // 과일 (그림자 + 회전)
  g.textAlign = 'center'; g.textBaseline = 'middle';
  for (const d of s.drops) {
    const size = d.kind === 'melon' ? 34 : d.kind === 'star' ? 30 : 26;
    g.fillStyle = '#0003'; g.beginPath(); g.ellipse(d.x, FH - 20, size / 3, 4, 0, 0, Math.PI * 2); g.fill();
    g.save(); g.translate(d.x, d.y); g.rotate(['magnet', 'slow', 'wide', 'heart'].includes(d.kind) ? 0 : d.rot);
    drawIcon(g, d.kind, size / 2, s.time);
    g.restore();
  }
  // 그물: 밧줄 + 그물코, 넓은 그물이면 초록 빛
  const { a, b } = s.net;
  const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2 + 26;
  g.strokeStyle = s.wide > 0 ? '#7dff9b' : '#f2e6c9'; g.lineWidth = s.wide > 0 ? 6 : 4;
  if (s.wide > 0) { g.shadowColor = '#7dff9b'; g.shadowBlur = 12; }
  g.beginPath(); g.moveTo(a.x, a.y); g.quadraticCurveTo(mx, my, b.x, b.y); g.stroke(); g.shadowBlur = 0;
  g.strokeStyle = '#f2e6c977'; g.lineWidth = 1;
  for (let i = 1; i < 10; i++) {
    const u = i / 10, x = (1 - u) ** 2 * a.x + 2 * (1 - u) * u * mx + u * u * b.x, y = (1 - u) ** 2 * a.y + 2 * (1 - u) * u * my + u * u * b.y;
    g.beginPath(); g.moveTo(x, y); g.lineTo(x + (i % 2 ? 4 : -4), y + 18); g.stroke();
  }
  if (s.magnet > 0) { g.strokeStyle = `rgba(255,107,107,${0.4 + 0.3 * Math.sin(s.time * 12)})`; g.lineWidth = 2; g.beginPath(); g.arc(mx, my - 26, 60 + 10 * Math.sin(s.time * 6), 0, Math.PI * 2); g.stroke(); }
  [a, b].forEach((p, i) => {
    const h = handles.length >= 2 ? handles[i] : undefined;
    g.fillStyle = h?.color ?? '#9aa4b2'; g.shadowColor = h?.color ?? '#000'; g.shadowBlur = 10;
    g.beginPath(); g.arc(p.x, p.y, 12, 0, Math.PI * 2); g.fill(); g.shadowBlur = 0;
    if (h) { g.fillStyle = '#fff'; g.font = '700 12px system-ui'; g.fillText(h.name, p.x, p.y - 22); }
  });
  g.textAlign = 'left'; g.textBaseline = 'alphabetic';
  drawFx(g, s.fx, FW, FH);
  g.restore();
  // 남은 시간 막대 + 활성 아이템
  const left = Math.max(0, ROUND - s.time), fever = left <= FEVER;
  g.fillStyle = '#0006'; g.fillRect(0, 0, FW, 6);
  g.fillStyle = fever ? '#ff6b6b' : '#ffd43b'; g.fillRect(0, 0, FW * left / ROUND, 6);
  g.font = '700 13px system-ui'; g.fillStyle = '#fff';
  const active = [s.magnet > 0 && `🧲 ${s.magnet.toFixed(0)}`, s.slow > 0 && `🐢 ${s.slow.toFixed(0)}`, s.wide > 0 && `🥅 ${s.wide.toFixed(0)}`].filter(Boolean).join('  ');
  if (active) g.fillText(active, 10, 24);
  if (fever && !s.over) { g.textAlign = 'right'; g.fillStyle = '#ffd43b'; g.fillText(`FEVER ×2  ${left.toFixed(1)}`, FW - 10, 24); g.textAlign = 'left'; }
  if (s.bannerT > 0) {
    const [title, sub] = s.bannerText === 'fever' ? [t('피버 타임!', 'FEVER TIME!'), t('마지막 10초, 점수 ×2', 'Last 10 s, points ×2')] : s.bannerText in EVENT_TEXT ? evText(s.bannerText as keyof typeof EVENT_TEXT) : ['', ''];
    banner(g, FW, FH, title, sub, s.bannerT);
  }
  if (paused || s.over) {
    g.fillStyle = '#09111bd9'; g.fillRect(0, 130, FW, 130); g.fillStyle = '#edf5ff'; g.font = 'bold 28px system-ui'; g.textAlign = 'center';
    g.fillText(s.over ? t(`${s.score}점!`, `${s.score} pts!`) : t('과일 받기', 'FRUIT CATCH'), FW / 2, 175);
    g.font = '15px system-ui';
    g.fillText(s.over ? t(`받은 과일 ${s.caught} · 최고 콤보 ${s.bestCombo}`, `Caught ${s.caught} · best combo ${s.bestCombo}`) : t('자동 매핑에서 인원·조작법을 고른 뒤 연결하세요', 'Choose players and controls, then Auto-map'), FW / 2, 207);
    g.fillText(t('💣 피하기 · ⭐ 100점 · 이벤트 예고를 잘 보세요 · Space 시작', 'Avoid 💣 · ⭐ 100 pts · watch for event warnings · Space to start'), FW / 2, 232);
    g.textAlign = 'left';
  }
}
