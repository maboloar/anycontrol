import { gameCanvas } from "../gameCanvas";
import { useRef, useState } from 'react';
import { useGameMapping } from "./GameMappingBar";
import { GameButtons } from './GameButtons';
import { Panel } from './Panel';
import { useGameLoop, useGameSession } from './gameSession';
import { H, newPong, paddleH, POWER_LABEL, stepPong, W, WIN, type Difficulty, type Pong, type PongMode } from '../pong';
import { applyShake, drawFx } from '../fx';
import { t } from '../i18n';

const POWER_ICON = { big: '+', fast: '»', multi: '×2', shrink: '−' } as const;

export function PongDemo() {
  const [mode, setModeState] = useState<PongMode>('pc');
  const [diff, setDiffState] = useState<Difficulty>('normal');
  const modeRef = useRef(mode); modeRef.current = mode;
  const diffRef = useRef(diff); diffRef.current = diff;
  const setup = useGameMapping('pong', mode === '2p' ? 2 : 1);
  const s = useGameSession('anycontrol.pong.best', () => newPong(modeRef.current, diffRef.current), setup.check);
  const keyTarget = useRef<[number, number]>([.5, .5]);
  const seen = useRef(0);
  useGameLoop(s, dt => {
    const g = s.game.current, objs = s.objectsInput();
    seen.current = objs.length;
    // 키보드: W/S = 왼쪽, ↑/↓ = 오른쪽. 물체: 크기(가까이 = 위). 2인은 화면 왼쪽 물체 = 왼쪽 패들
    const kL = Number(s.control('s')) - Number(s.control('w')), kR = Number(s.control('arrowdown')) - Number(s.control('arrowup'));
    keyTarget.current = [Math.max(0, Math.min(1, keyTarget.current[0] + kL * dt * 1.8)), Math.max(0, Math.min(1, keyTarget.current[1] + kR * dt * 1.8))];
    const left = kL ? keyTarget.current[0] : g.mode === 'pc' && kR ? keyTarget.current[1] : (s.demoControl("pong.left") + 1) / 2;   // 1인은 ↑/↓ 로도 왼쪽 패들
    const right = g.mode === 'pc' ? null : kR ? keyTarget.current[1] : (s.demoControl("pong.right") + 1) / 2;
    s.game.current = stepPong(g, left, right, dt);
  }, drawPong);
  const reset = (m: PongMode, d: Difficulty) => { s.pause(); modeRef.current = m; diffRef.current = d; s.game.current = newPong(m, d); s.publish(); };
  const g = s.snapshot;
  return <Panel title={t("퐁", "Pong")} label="퐁 데모" className="demo" detail={mode === 'pc' ? t('컴퓨터와 대결', 'vs computer') : t('2인 대결', '2 players')}
    info={t(<>물체를 카메라 쪽으로 <b>가까이 하면 패들이 위로</b>, 멀리 하면 아래로 갑니다(물체 크기). 패들을 <b>움직이면서 치면 공이 휘어</b> 나갑니다. 가운데 아이템에 공을 맞히면 마지막에 친 쪽이 가져요: ⬆ 큰 패들, ⚡ 빠른 공, ✖2 공 두 개, 🧊 상대 패들 작게. 자동 매핑에서 크기 또는 영상 상하 조작과 1P/2P 컨트롤러를 선택하세요. 키보드: W/S, ↑/↓. Space = 일시정지.</>,
      <>Bring the object <b>closer to move the paddle up</b>, farther to move it down. <b>Hit while moving</b> to curve the ball. Hit the middle item to claim it (last hitter): ⬆ big paddle, ⚡ fast ball, ✖2 multi-ball, 🧊 shrink opponent. Choose size or video Y and the P1/P2 controllers in Auto-map. Keys: W/S, ↑/↓. Space = pause.</>)}>
    <div ref={s.root} tabIndex={0} className="game-stage" aria-label={t("퐁 조작 영역", "Pong play area")} {...s.handlers}>
      <div className="row game-mode" role="radiogroup" aria-label={t("상대", "Opponent")}>
        {(['pc', '2p'] as PongMode[]).map((m) => <button key={m} type="button" role="radio" aria-checked={mode === m} className={mode === m ? 'active' : ''} onClick={() => { setModeState(m); reset(m, diff); }}>
          {m === 'pc' ? t('1인 · 컴퓨터와', '1P · vs computer') : t('2인 대결 (컨트롤러 2개)', '2P (2 controllers)')}</button>)}
        {mode === 'pc' && (['easy', 'normal', 'hard'] as Difficulty[]).map((d) => <button key={d} type="button" className={`small ${diff === d ? 'active' : ''}`} aria-pressed={diff === d}
          onClick={() => { setDiffState(d); reset(mode, d); }}>{({ easy: t('쉬움', 'Easy'), normal: t('보통', 'Normal'), hard: t('어려움', 'Hard') })[d]}</button>)}
      </div>
      {setup.bar(<GameButtons s={s} over={g.over} status={g.over ? (g.winner === 0 ? t('왼쪽 승리!', 'Left wins!') : mode === 'pc' ? t('컴퓨터 승리', 'Computer wins') : t('오른쪽 승리!', 'Right wins!')) : s.paused ? t('준비 / 일시정지', 'Ready / Paused') : t(`${WIN}점 먼저`, `First to ${WIN}`)} />)}
      <div className="game-hud" aria-label={t("퐁 점수", "Pong score")}>
        <span>{t('왼쪽', 'Left')} <b>{g.scoreL}</b></span><span>{mode === 'pc' ? t('컴퓨터', 'Computer') : t('오른쪽', 'Right')} <b>{g.scoreR}</b></span>
        <span>{t('랠리', 'Rally')} <b>{g.rally}</b></span><span>{t('최고 점수', 'Best')} <b>{s.best}</b></span><span>{t('카메라 물체', 'Objects seen')} <b>{seen.current}</b></span>
      </div>
      <canvas ref={s.canvas} width={W} height={H} className="drawpad game-canvas" role="img" aria-label={t("퐁 경기 화면", "Pong court")} />

    </div>
  </Panel>;
}

function glowRect(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, color: string) {
  g.shadowColor = color; g.shadowBlur = 18; g.fillStyle = color;
  g.beginPath(); if (g.roundRect) g.roundRect(x, y, w, h, 6); else g.rect(x, y, w, h); g.fill(); g.shadowBlur = 0;
}

export function drawPong(c: HTMLCanvasElement | null, s: Pong, paused: boolean) {
  const g = gameCanvas(c, W, H); if (!c || !g) return;
  g.save();
  applyShake(g, s.fx);
  g.fillStyle = '#070b14'; g.fillRect(-20, -20, W + 40, H + 40);
  // 네온 격자 바닥
  g.strokeStyle = '#13213a'; g.lineWidth = 1;
  for (let x = 0; x <= W; x += 32) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke(); }
  for (let y = 0; y <= H; y += 32) { g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); }
  g.strokeStyle = '#2b4c7a'; g.lineWidth = 3; g.setLineDash([12, 12]);
  g.beginPath(); g.moveTo(W / 2, 0); g.lineTo(W / 2, H); g.stroke(); g.setLineDash([]);
  g.beginPath(); g.arc(W / 2, H / 2, 50, 0, Math.PI * 2); g.stroke();
  g.fillStyle = '#ffffff14'; g.font = '900 92px system-ui'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(String(s.scoreL), W / 2 - 110, H / 2); g.fillText(String(s.scoreR), W / 2 + 110, H / 2);
  // 아이템
  if (s.power) {
    const p = s.power, pulse = 1 + 0.12 * Math.sin(p.t * 8);
    g.strokeStyle = '#7dff9b'; g.lineWidth = 3; g.shadowColor = '#7dff9b'; g.shadowBlur = 16;
    g.beginPath(); g.arc(p.x, p.y, 18 * pulse, 0, Math.PI * 2); g.stroke(); g.shadowBlur = 0;
    g.fillStyle = '#eafff1'; g.font = '700 16px system-ui'; g.fillText(POWER_ICON[p.kind], p.x, p.y + 1);
    g.font = '600 11px system-ui'; g.fillStyle = '#7dff9b'; g.fillText(t(...POWER_LABEL[p.kind]), p.x, p.y + 30);
  }
  // 패들
  const hl = paddleH(s, 0), hr = paddleH(s, 1);
  glowRect(g, 18, s.left - hl / 2, 12, hl, s.big[0] > 0 ? '#7dff9b' : s.small[0] > 0 ? '#9aa4b2' : '#21e6ff');
  glowRect(g, W - 30, s.right - hr / 2, 12, hr, s.big[1] > 0 ? '#7dff9b' : s.small[1] > 0 ? '#9aa4b2' : s.mode === 'pc' ? '#c3c9d4' : '#ff3dd8');
  // 공 + 꼬리 (랠리 8 이상이면 불꽃)
  const fire = s.rally >= 8;
  for (const b of s.balls) {
    b.trail.forEach(([x, y], i) => {
      g.globalAlpha = (i + 1) / b.trail.length * 0.5;
      g.fillStyle = fire ? (i % 2 ? '#ff8a00' : '#ffd43b') : '#ffd166';
      g.beginPath(); g.arc(x, y, 3 + i * 0.45, 0, Math.PI * 2); g.fill();
    });
    g.globalAlpha = 1;
    g.shadowColor = fire ? '#ff8a00' : '#ffd166'; g.shadowBlur = fire ? 24 : 14;
    g.fillStyle = fire ? '#fff3c4' : '#ffe08a'; g.beginPath(); g.arc(b.x, b.y, 8, 0, Math.PI * 2); g.fill(); g.shadowBlur = 0;
  }
  g.textAlign = 'left'; g.textBaseline = 'alphabetic';
  drawFx(g, s.fx, W, H);
  g.restore();
  if (s.serveIn > 0 && !paused && !s.over) {
    g.fillStyle = '#ffffffcc'; g.font = '900 48px system-ui'; g.textAlign = 'center';
    g.fillText(String(Math.ceil(s.serveIn / 0.5)), W / 2, H / 2 - 70); g.textAlign = 'left';
  }
  if (paused || s.over) {
    g.fillStyle = '#05080fdd'; g.fillRect(0, 135, W, 125); g.fillStyle = '#edf5ff'; g.font = 'bold 28px system-ui'; g.textAlign = 'center';
    g.fillText(s.over ? (s.winner === 0 ? t('왼쪽 승리!', 'Left wins!') : s.mode === 'pc' ? t('컴퓨터 승리', 'Computer wins') : t('오른쪽 승리!', 'Right wins!')) : 'PONG', W / 2, 178);
    g.font = '15px system-ui';
    g.fillText(t('매핑 패널의 퐁 패들 연결로 조작 · 움직이며 치면 공이 휨', 'Control the Pong paddle jacks in Mapping · hit while moving to curve'), W / 2, 210);
    g.fillText(t('가운데 아이템을 맞혀 보세요 · Space 시작', 'Hit the middle items · Space to start'), W / 2, 234);
    g.textAlign = 'left';
  }
}
