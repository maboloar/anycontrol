import { ActionIcon } from "./ActionIcon";
import { useRef, useState } from 'react';
import { GameControls, type GameControlMode } from './GameControls';
import { positionTarget } from '../gameInput';
import { Panel } from './Panel';
import { useGameLoop, useGameSession } from './gameSession';
import { newSurvival, stepSurvival, type Survival } from '../survival';

export function SurvivalDemo() {
  const [mode, setMode] = useState<GameControlMode>('position');
  const modeRef = useRef(mode); modeRef.current = mode;
  const s = useGameSession('anycontrol.survival.best', newSurvival);
  useGameLoop(s, dt => {
    const p = s.padRef.current, active = s.inputActive();
    const x = Number(s.control('d') || s.control('arrowright') || active && p.buttons.right) - Number(s.control('a') || s.control('arrowleft') || active && p.buttons.left);
    const y = Number(s.control('s') || s.control('arrowdown') || active && p.buttons.down) - Number(s.control('w') || s.control('arrowup') || active && p.buttons.up);
    const stickX = active && modeRef.current === 'joystick' ? p.axes.left_x : 0;
    const stickY = active && modeRef.current === 'joystick' ? p.axes.left_y : 0;
    s.game.current = stepSurvival(s.game.current, x || stickX, y || stickY, s.control(' ') || active && p.buttons.a, dt, Math.random, modeRef.current === 'position' ? positionTarget(s.cursorInput()) : undefined);
  }, drawSurvival);
  const g = s.snapshot;
  return <Panel title="신호기 90" label="좀비 서바이벌 데모" className="demo" detail="전지를 운반하고 구조 신호를 보내세요" info={<>기본은 <b>커서 위치 = 주인공 위치</b>입니다. 물체를 연결하면 물체로 움직이고, Space(게임패드 A)로 충격파를 씁니다. P = 일시정지.</>}>
    <div className="game-layout">
    <div ref={s.root} tabIndex={0} className="game-stage" aria-label="좀비 게임 조작 영역" {...s.handlers}>
      <div className="game-hud" aria-label="좀비 게임 점수">
        <span>점수 <b>{g.score}</b></span><span>최고 <b>{s.best}</b></span><span>생명 <b>{'♥'.repeat(Math.max(0, g.hp)) || '0'}</b></span>
        <span>생존 <b>{Math.floor(g.time)}초</b></span><span>충전 <b>{g.charge}/8</b></span><span>운반 <b>{g.carrying}/3</b></span>
      </div>
      <canvas ref={s.canvas} width={640} height={400} className="drawpad game-canvas" role="img" aria-label="전지와 신호기, 추격하는 좀비가 있는 탑다운 게임 화면" />
      <div className="row game-actions">
        <button type="button" className={s.paused || g.over ? "act-go" : "act-pause"} onClick={() => s.paused || g.over ? s.play() : s.pause()}><ActionIcon name={s.paused || g.over ? 'play' : 'pause'} />{g.over ? '다시 도전' : s.paused ? '생존 시작 / 계속' : '일시정지'}</button>
        <button type="button" className="act-reset" onClick={() => s.play(true)}><ActionIcon name="reset" />처음부터</button>
        <span className="small" role="status">{g.over ? g.won ? `구조 성공! ${g.score}점` : `생존 종료 · ${g.score}점` : s.paused ? '준비 / 일시정지' : g.pulseIn > 0 ? `충격파 ${g.pulseIn.toFixed(1)}초 후` : '충격파 준비 완료'}</span>
      </div>
      <p className="small muted">기본은 커서 위치 대응입니다. 조이스틱 이동도 선택할 수 있습니다. 가까운 좀비를 자동 사격합니다. Space / 게임패드 A: 충격파(6초 재충전). P: 일시정지.</p>
      <p className="small muted">노란 전지를 모아 중앙 신호기로 운반하세요. 운반하면 생명 1칸 회복·사격 강화! 좀비 3마리마다 전지 1개가 나오며, 90초 이상 생존하고 전지 8개를 충전하면 구조됩니다. 처치 25점 · 충전 150점 · 구조 보너스 1,500점.</p>
      <p className="small muted">옆에서 물체를 고르고 [이 물체로 게임 연결]을 누르세요. 위치를 놓치면 마지막 위치에 머뭅니다. 카메라 없이 WASD / 방향키로도 이동할 수 있습니다.</p>
    </div>
    <GameControls mode={mode} onMode={m => { s.pause(); setMode(m); }} />
    </div>
  </Panel>;
}

export function drawSurvival(c: HTMLCanvasElement | null, s: Survival, paused: boolean) {
  const g = c?.getContext('2d'); if (!c || !g) return;
  g.fillStyle = '#14232c'; g.fillRect(0, 0, 640, 400);
  g.strokeStyle = '#23363e'; g.lineWidth = 1; g.beginPath();
  for (let x = 0; x <= 640; x += 40) { g.moveTo(x, 0); g.lineTo(x, 400); }
  for (let y = 0; y <= 400; y += 40) { g.moveTo(0, y); g.lineTo(640, y); } g.stroke();
  g.fillStyle = '#204e51'; g.beginPath(); g.arc(320, 200, 36, 0, Math.PI * 2); g.fill();
  g.strokeStyle = '#60dac1'; g.lineWidth = 4; g.beginPath(); g.arc(320, 200, 36, -Math.PI / 2, -Math.PI / 2 + Math.min(1, s.charge / 8) * Math.PI * 2); g.stroke();
  g.fillStyle = '#8be7d1'; g.fillRect(314, 184, 12, 26); g.fillRect(306, 184, 28, 5);
  g.font = '11px system-ui'; g.fillText('신호기', 304, 251);
  for (const cell of s.cells) { g.fillStyle = '#ffd166'; g.fillRect(cell.x - 6, cell.y - 9, 12, 18); g.fillRect(cell.x - 3, cell.y - 12, 6, 3); }
  for (const z of s.zombies) {
    g.fillStyle = z.fast ? '#ea9372' : '#8aad75'; g.beginPath(); g.arc(z.x, z.y, z.fast ? 9 : 12, 0, Math.PI * 2); g.fill();
    g.fillStyle = '#192633'; g.fillRect(z.x - 5, z.y - 3, 3, 3); g.fillRect(z.x + 2, z.y - 3, 3, 3);
  }
  g.fillStyle = '#fff4bd'; for (const b of s.bullets) { g.beginPath(); g.arc(b.x, b.y, 3, 0, Math.PI * 2); g.fill(); }
  if (s.pulseRadius > 0) { g.strokeStyle = '#b3ddff'; g.lineWidth = 3; g.beginPath(); g.arc(s.x, s.y, 105 - s.pulseRadius + 10, 0, Math.PI * 2); g.stroke(); }
  g.fillStyle = s.invulnerable > 0 && Math.floor(s.invulnerable * 12) % 2 ? '#ffffff' : '#64c6f1';
  g.beginPath(); g.arc(s.x, s.y, 11, 0, Math.PI * 2); g.fill();
  g.fillStyle = '#ffe388'; for (let i = 0; i < s.carrying; i++) g.fillRect(s.x - 9 + i * 7, s.y - 19, 5, 5);
  if (paused || s.over) {
    g.fillStyle = '#09111bdf'; g.fillRect(0, 120, 640, 135); g.textAlign = 'center'; g.fillStyle = '#eaf8ff'; g.font = 'bold 26px system-ui';
    g.fillText(s.over ? s.won ? '구조 신호 수신 완료!' : '신호가 끊겼습니다' : '신호기 90', 320, 169);
    g.font = '15px system-ui'; g.fillText(s.over ? `${s.score}점 · 처치 ${s.kills} · 생존 ${Math.floor(s.time)}초` : '전지 8개 충전 + 90초 생존 → 구조 성공', 320, 202);
    if (!s.over) g.fillText('생존 시작을 누르고 이동하세요 · 사격은 자동', 320, 231);
    g.textAlign = 'left';
  }
}
