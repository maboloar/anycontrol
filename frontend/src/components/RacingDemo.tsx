import { gameCanvas } from "../gameCanvas";
import { useRef, useState } from 'react';
import { useGameMapping } from "./GameMappingBar";
import { GameButtons } from './GameButtons';
import { Panel } from './Panel';
import { curveAt, FINISH, newDuel, newRace, STAGES, stepDuel, stepRace, type Duel, type Race } from '../racing';
import { applyShake, banner, drawFx } from '../fx';
import { useGameLoop, useGameSession, type GameObject } from './gameSession';
import { t } from '../i18n';

type Mode = '1p' | '2p';
interface RacingGame { mode: Mode; solo: Race; duel: Duel; score: number; over: boolean }
const fresh = (mode: Mode): RacingGame => ({ mode, solo: newRace(Math.floor(Math.random() * 1e9)), duel: newDuel(), score: 0, over: false });

export function RacingDemo() {
  const [mode, setModeState] = useState<Mode>('1p');
  const modeRef = useRef(mode); modeRef.current = mode;
  const setup = useGameMapping('race', mode === '2p' ? 2 : 1);
  const s = useGameSession('anycontrol.race.best', () => fresh(modeRef.current), setup.check);
  const [autoGas, setAutoGas] = useState(false);
  const autoGasRef = useRef(false); autoGasRef.current = autoGas;
  const lastObjects = useRef<GameObject[]>([]);
  useGameLoop(s, dt => {
    const g = s.game.current;
    const objs = s.objectsInput();
    lastObjects.current = objs;
    if (g.mode === '2p') {
      const steer = [0, 1].map(i => {
        const key = i === 0 ? Number(s.control('d')) - Number(s.control('a')) : Number(s.control('arrowright')) - Number(s.control('arrowleft'));
        return key || s.demoControl(`race.steer${i + 1}`);
      }) as [number, number];
      const duel = stepDuel(g.duel, steer, dt);
      s.game.current = { ...g, duel, score: duel.score, over: duel.over };
      return;
    }
    const p = s.padRef.current, active = s.inputActive();
    const left = s.control('a') || s.control('arrowleft') || active && p.buttons.left;
    const right = s.control('d') || s.control('arrowright') || active && p.buttons.right;
    const steer = left || right ? Number(right) - Number(left) : s.demoControl("race.steer1");
    const gas = autoGasRef.current || s.control('w') || s.control('arrowup') ? 1 : s.demoControl("race.gas");
    const brake = s.control('s') || s.control('arrowdown') ? 1 : s.demoControl("race.brake");
    const solo = stepRace(g.solo, steer, gas, brake, dt);
    s.game.current = { ...g, solo, score: solo.score, over: solo.over };
  }, drawRacing);
  const setMode = (m: Mode) => { s.pause(); setModeState(m); modeRef.current = m; s.game.current = fresh(m); s.publish(); };
  const g = s.snapshot;
  const duel = g.duel;
  const status = g.mode === '2p'
    ? g.over ? duel.winner === null ? t('둘 다 파손 · 무승부', 'Both wrecked · draw') : t(`${duel.winner + 1}P 승리!`, `Player ${duel.winner + 1} wins!`)
      : s.paused ? t('준비 / 일시정지', 'Ready / Paused') : `${Math.floor(duel.p[0].car.dist)} m : ${Math.floor(duel.p[1].car.dist)} m / ${FINISH} m`
    : g.over ? t(`차량 파손 · 최종 ${g.score}점`, `Car wrecked · final ${g.score} pts`) : s.paused ? t('준비 / 일시정지', 'Ready / Paused')
      : `${Math.round(g.solo.car.speed * 100)} km/h · ${Math.floor(g.solo.car.dist)} m${g.solo.boost > 0 ? ' · BOOST!' : ''}`;
  const visible = lastObjects.current.length;
  return <Panel title={t("코인 로드", "Coin Road")} label="레이싱 데모" className="demo" detail={g.mode === '2p' ? t(`2인 경주 · ${FINISH}m 먼저 도착`, `2-player race · first to ${FINISH} m`) : t("장애물 회피 · 코인 · 부스터", "Dodge · coins · boosters")}
    info={t(<><b>1인</b>: 자동 매핑 후 매핑 패널의 레이싱 조향·가속·브레이크 잭을 조절하거나 WASD·방향키. <b>2인</b>: 자동 매핑에서 두 컨트롤러와 좌우/기울기 조향을 선택합니다. 가속은 자동. Space = 일시정지.</>,
      <><b>1P</b>: auto-map, then adjust the Racing steering/gas/brake jacks in Mapping, or WASD / arrows. <b>2P</b>: choose two controllers and sideways/tilt steering in Auto-map; gas is automatic. Space = pause.</>)}>
    <div ref={s.root} tabIndex={0} className="game-stage" aria-label={t("레이싱 조작 영역", "Racing play area")} {...s.handlers}>
      <div className="row game-mode" role="radiogroup" aria-label={t("인원", "Players")}>
        {(['1p', '2p'] as Mode[]).map((m) => <button key={m} type="button" role="radio" aria-checked={mode === m} className={mode === m ? 'active' : ''} onClick={() => setMode(m)}>
          {m === '1p' ? t('1인 (매핑·키보드)', '1P (mapping / keys)') : t('2인 분할 화면 (컨트롤러 2개)', '2P split screen (2 controllers)')}</button>)}

      </div>
      {setup.bar(<GameButtons s={s} over={g.over} startLabel={t('주행 시작 / 계속', 'Start / Resume')} status={status}>
        {mode === '1p' && <label className="check small"><input type="checkbox" checked={autoGas} onChange={e => setAutoGas(e.target.checked)} />{t("자동 가속", "Auto accelerate")}</label>}
      </GameButtons>)}
      <div className="game-hud" aria-label={t("레이싱 점수", "Racing score")}>
        {g.mode === '1p' ? <>
          <span>{t('점수', 'Score')} <b>{g.score}</b></span><span>{t('최고', 'Best')} <b>{s.best}</b></span>
          <span>{t('차량', 'Car')} <b>{'♥'.repeat(Math.max(0, g.solo.health)) || '0'}</b></span><span>{t('코인', 'Coins')} <b>{g.solo.coins}</b></span>
          <span>{t('콤보', 'Combo')} <b>×{Math.min(5, 1 + Math.floor(g.solo.combo / 3))}</b></span>
        </> : <>
          <span>1P <b>{'♥'.repeat(Math.max(0, duel.p[0].health)) || '0'}</b> {Math.floor(duel.p[0].car.dist)}m</span>
          <span>2P <b>{'♥'.repeat(Math.max(0, duel.p[1].health)) || '0'}</b> {Math.floor(duel.p[1].car.dist)}m</span>
          <span>{t('카메라 물체', 'Objects seen')} <b>{visible}</b></span>
        </>}
      </div>
      <canvas ref={s.canvas} width={640} height={400} className="drawpad game-canvas" role="img" aria-label={t("코인과 장애물이 있는 레이싱 화면", "Racing screen with coins and obstacles")} />

      <p className="small muted">{t("코인 100점(연속이면 최대 ×5) · 코인 5개 = 니트로 · 초록 화살표 = 부스터 · 차선을 바꾸는 차와 기름(빙글 미끄러짐)을 피하세요 · 600m마다 스테이지(낮→노을→밤→폭풍)가 바뀌며 빨라집니다. W/↑ 가속 · S/↓ 브레이크 · Space 일시정지.", "Coins 100 pts (streaks up to ×5) · 5 coins = nitro · green arrows = boost · dodge lane-changing cars and oil (spin-out) · every 600 m the stage changes (day → sunset → night → storm) and gets faster. W/↑ gas · S/↓ brake · Space pause.")}</p>
    </div>
  </Panel>;
}

const COLORS = ['#62c7e7', '#ff9f6b'];

const PALETTE = [
  { grass: ['#2f6b47', '#2a5f40'], road: '#363c48', tint: null },
  { grass: ['#5a6b35', '#4f5f2f'], road: '#3b3a44', tint: 'rgba(255,120,60,0.18)' },
  { grass: ['#163126', '#122a20'], road: '#22262f', tint: 'rgba(5,10,30,0.55)' },
  { grass: ['#26413a', '#203833'], road: '#2b3038', tint: 'rgba(30,40,60,0.35)' },
];

function drawCarSprite(g: CanvasRenderingContext2D, color: string, glow = false) {
  g.fillStyle = '#0008'; g.beginPath(); g.ellipse(2, 4, 17, 27, 0, 0, Math.PI * 2); g.fill();   // 그림자
  g.fillStyle = '#111'; for (const [x, y] of [[-15, -15], [11, -15], [-15, 9], [11, 9]]) g.fillRect(x!, y!, 4, 10);   // 바퀴
  g.fillStyle = color; g.beginPath(); if (g.roundRect) g.roundRect(-12, -24, 24, 48, 7); else g.rect(-12, -24, 24, 48); g.fill();
  g.fillStyle = '#0b1a26cc'; g.beginPath(); if (g.roundRect) g.roundRect(-9, -12, 18, 11, 3); else g.rect(-9, -12, 18, 11); g.fill();   // 앞유리
  g.fillStyle = '#0b1a2699'; g.fillRect(-8, 8, 16, 7);
  g.fillStyle = '#ffffff40'; g.fillRect(-10, -22, 4, 40);   // 하이라이트
  g.fillStyle = glow ? '#fff8c4' : '#fff4ba'; g.fillRect(-10, -24, 5, 4); g.fillRect(5, -24, 5, 4);
  g.fillStyle = '#ff4d4d'; g.fillRect(-10, 21, 5, 3); g.fillRect(5, 21, 5, 3);
}

function drawRoadView(g: CanvasRenderingContext2D, s: Race, x0: number, W: number, H: number, color: string, label?: string) {
  g.save();
  g.beginPath(); g.rect(x0, 0, W, H); g.clip();
  const k = W / 640;
  g.save();
  applyShake(g, s.fx);
  const pal = PALETTE[s.stage % PALETTE.length]!;
  const road = W * 0.48, cy = H - 62;
  const centerAt = (ahead: number) => x0 + W / 2 + (curveAt(s.car.dist + ahead) - curveAt(s.car.dist)) * W * 0.45 * Math.min(1, ahead / 120);
  const scroll = s.car.dist * 2.3;
  // 도로를 위(멀리)→아래(가까이) 띠로 그려 굽은 길을 표현
  for (let y = 0; y < H; y += 8) {
    const ahead = (cy - y) / 2.3, cx = centerAt(Math.max(0, ahead)), band = scroll + (H - y);
    g.fillStyle = pal.grass[Math.floor(band / 40) % 2]!; g.fillRect(x0, y, W, 8);
    g.fillStyle = pal.road; g.fillRect(cx - road / 2, y, road, 8);
    g.fillStyle = Math.floor(band / 24) % 2 ? '#e05d5d' : '#f2f2f2';
    g.fillRect(cx - road / 2 - 7 * k, y, 7 * k, 8); g.fillRect(cx + road / 2, y, 7 * k, 8);
    if (Math.floor(band / 23) % 2) { g.fillStyle = '#d9dccf'; g.fillRect(cx - road / 6 - 1.5, y, 3, 8); g.fillRect(cx + road / 6 - 1.5, y, 3, 8); }
  }
  // 길가: 나무와 가로등
  for (let i = 0; i < 12; i++) {
    const ahead = ((i * 26 - s.car.dist) % 312 + 312) % 312 - 30, y = cy - ahead * 2.3;
    if (y < -30 || y > H + 30) continue;
    const cx = centerAt(Math.max(0, ahead)), side = i % 2 ? 1 : -1, x = cx + side * (road / 2 + 34 * k + (i % 3) * 10 * k);
    if (i % 3 === 0) {
      g.fillStyle = '#555c66'; g.fillRect(x - 2, y - 26, 4, 30);
      if (s.stage % PALETTE.length >= 2) { g.fillStyle = '#ffe9a855'; g.beginPath(); g.arc(x, y - 26, 16, 0, Math.PI * 2); g.fill(); }
      g.fillStyle = '#ffe9a8'; g.beginPath(); g.arc(x, y - 26, 4, 0, Math.PI * 2); g.fill();
    } else {
      g.fillStyle = '#0004'; g.beginPath(); g.ellipse(x + 4, y + 6, 14 * k + 6, 6, 0, 0, Math.PI * 2); g.fill();
      g.fillStyle = i % 2 ? '#2f7d4f' : '#3b8d5a'; g.beginPath(); g.arc(x, y, 12 * k + 6, 0, Math.PI * 2); g.fill();
      g.fillStyle = '#ffffff22'; g.beginPath(); g.arc(x - 4, y - 4, 5 * k + 2, 0, Math.PI * 2); g.fill();
    }
  }
  if (s.boost > 0) { // 속도선
    g.strokeStyle = '#ffffff66'; g.lineWidth = 2;
    for (let i = 0; i < 16; i++) { const lx = x0 + ((i * 97 + s.car.dist * 13) % W); g.beginPath(); g.moveTo(lx, (i * 53) % H); g.lineTo(lx, (i * 53) % H + 46); g.stroke(); }
  }
  for (const item of s.items) {
    const y = cy - item.ahead * 2.3; if (y < -30 || y > H + 30) continue;
    const x = centerAt(Math.max(0, item.ahead)) + item.x * road / 2;
    if (item.kind === 'coin') {
      const spin = Math.abs(Math.sin(s.car.dist / 6 + item.id));
      g.fillStyle = '#b8860b'; g.beginPath(); g.ellipse(x, y, (9 * k + 2) * Math.max(.25, spin), 9 * k + 2, 0, 0, Math.PI * 2); g.fill();
      g.fillStyle = '#ffd43b'; g.beginPath(); g.ellipse(x, y, (7 * k + 1.5) * Math.max(.2, spin), 7 * k + 1.5, 0, 0, Math.PI * 2); g.fill();
    } else if (item.kind === 'boost') {
      g.fillStyle = '#5ee08a'; g.shadowColor = '#5ee08a'; g.shadowBlur = 10;
      for (const dy of [0, 10]) { g.beginPath(); g.moveTo(x, y - 12 + dy); g.lineTo(x + 12, y + dy); g.lineTo(x + 6, y + dy); g.lineTo(x, y - 6 + dy); g.lineTo(x - 6, y + dy); g.lineTo(x - 12, y + dy); g.closePath(); g.fill(); }
      g.shadowBlur = 0;
    } else if (item.kind === 'oil') {
      g.fillStyle = '#0b0b10dd'; g.beginPath(); g.ellipse(x, y, 22 * k + 6, 10, 0.2, 0, Math.PI * 2); g.ellipse(x + 10 * k, y + 4, 12 * k + 4, 7, 0, 0, Math.PI * 2); g.fill();
      g.strokeStyle = '#7a5cff66'; g.lineWidth = 2; g.beginPath(); g.ellipse(x - 4, y - 2, 10 * k + 3, 4, 0.2, 0, Math.PI * 2); g.stroke();
    } else if (item.kind === 'car') {
      g.save(); g.translate(x, y); g.scale(k * .9 + .1, k * .9 + .1); drawCarSprite(g, item.color ?? '#f2c14e'); g.restore();
      if ((item.tx ?? item.x) !== item.x) { g.fillStyle = Math.floor(s.car.dist / 3) % 2 ? '#ffb000' : '#ffb00044'; g.fillRect(x + Math.sign((item.tx ?? 0) - item.x) * 12 - 2, y + 18, 4, 4); }   // 깜빡이
    } else {
      g.fillStyle = '#0005'; g.fillRect(x - 23 * k - 2, y - 8, 46 * k + 8, 24);
      g.fillStyle = '#e67651'; g.fillRect(x - 23 * k - 4, y - 12, 46 * k + 8, 24);
      g.fillStyle = '#ffe6aa'; for (let i = -16; i < 20; i += 15) g.fillRect(x + i * k, y - 9, 5, 18);
    }
  }
  // 내 차
  g.save();
  g.translate(x0 + W / 2 + s.car.x * road / 2, cy); g.rotate(s.car.heading * .5 + (s.spin > 0 ? s.spin * 9 : 0));
  g.globalAlpha = s.invulnerable > 0 && Math.floor(s.invulnerable * 10) % 2 ? .35 : 1;
  if (s.boost > 0) { g.fillStyle = Math.random() < .5 ? '#ffb347' : '#21e6ff'; g.beginPath(); g.moveTo(-6, 24); g.lineTo(6, 24); g.lineTo(0, 40 + Math.random() * 14); g.closePath(); g.fill(); }
  drawCarSprite(g, color, true);
  g.restore();
  // 날씨·시간 색조
  if (pal.tint) { g.fillStyle = pal.tint; g.fillRect(x0, 0, W, H); }
  if (s.stage % PALETTE.length >= 2) {   // 밤: 전조등 불빛
    const px = x0 + W / 2 + s.car.x * road / 2;
    const gr = g.createRadialGradient?.(px, cy - 90, 10, px, cy - 90, 150);
    if (gr) { gr.addColorStop(0, 'rgba(255,240,190,0.28)'); gr.addColorStop(1, 'rgba(255,240,190,0)'); g.fillStyle = gr; g.fillRect(x0, 0, W, H); }
  }
  if (s.stage % PALETTE.length === 3) {   // 폭풍: 비
    g.strokeStyle = '#c9d7ff55'; g.lineWidth = 1;
    for (let i = 0; i < 60; i++) { const rx = x0 + ((i * 53 + s.car.dist * 7) % W), ry = (i * 97 + s.car.dist * 23) % H; g.beginPath(); g.moveTo(rx, ry); g.lineTo(rx - 4, ry + 14); g.stroke(); }
  }
  g.save(); g.translate(x0, 0); g.scale(k, 1); drawFx(g, s.fx, 640, H); g.restore();
  g.restore();
  // HUD: 속도·스테이지·니트로 게이지
  g.fillStyle = '#0008'; g.fillRect(x0 + 8, 8, 150, 44);
  g.fillStyle = '#fff'; g.font = 'bold 15px system-ui';
  g.fillText(`${label ? label + ' · ' : ''}${Math.round(s.car.speed * 100)} km/h`, x0 + 14, 26);
  g.font = '600 11px system-ui'; g.fillStyle = '#ffd43b';
  g.fillText(`STAGE ${s.stage + 1} · ${t(...STAGES[s.stage % STAGES.length]!)}`, x0 + 14, 42);
  g.fillStyle = '#ffffff22'; g.fillRect(x0 + 8, 54, 150, 5);
  g.fillStyle = '#21e6ff'; g.fillRect(x0 + 8, 54, 150 * s.nitro, 5);
  if (s.bannerT > 0) banner(g, W, H, `STAGE ${s.stage + 1}`, t(...STAGES[s.stage % STAGES.length]!), s.bannerT);
  g.restore();
}

export function drawRacing(c: HTMLCanvasElement | null, s: RacingGame, paused: boolean) {
  const g = gameCanvas(c, 640, 400); if (!c || !g) return;
  const W = 640, H = 400;
  if (s.mode === '2p') {
    drawRoadView(g, s.duel.p[0], 0, W / 2, H, COLORS[0]!, '1P');
    drawRoadView(g, s.duel.p[1], W / 2, W / 2, H, COLORS[1]!, '2P');
    g.fillStyle = '#0b1118'; g.fillRect(W / 2 - 2, 0, 4, H);
    for (const i of [0, 1]) { // 진행 막대
      const r = s.duel.p[i]!; g.fillStyle = '#ffffff22'; g.fillRect(i * W / 2 + 10, H - 10, W / 2 - 20, 5);
      g.fillStyle = COLORS[i]!; g.fillRect(i * W / 2 + 10, H - 10, (W / 2 - 20) * Math.min(1, r.car.dist / FINISH), 5);
    }
  } else drawRoadView(g, s.solo, 0, W, H, COLORS[0]!);
  if (paused || s.over) {
    g.fillStyle = '#09111bd9'; g.fillRect(0, 130, W, 115);
    g.textAlign = 'center'; g.fillStyle = '#edf5ff'; g.font = 'bold 26px system-ui';
    const title = s.mode === '2p'
      ? s.over ? s.duel.winner === null ? t('무승부', 'Draw') : t(`${s.duel.winner + 1}P 승리!`, `Player ${s.duel.winner + 1} wins!`) : t('2인 경주', '2-PLAYER RACE')
      : s.over ? t('FINISH · 다시 도전!', 'FINISH · Try again!') : 'COIN ROAD';
    g.fillText(title, W / 2, 178);
    g.font = '15px system-ui';
    g.fillText(s.mode === '2p' ? t('자동 매핑에서 고른 1P/2P 연결로 조향 · 가속 자동', 'Steer with the selected P1/P2 mappings · auto gas')
      : s.over ? t(`${s.score}점 · 코인 ${s.solo.coins}개`, `${s.score} pts · ${s.solo.coins} coins`) : t('시작을 누르고 W 또는 ↑로 가속 · Space 일시정지', 'Press Start, then W or ↑ to accelerate · Space pauses'), W / 2, 211);
    g.textAlign = 'left';
  }
}
