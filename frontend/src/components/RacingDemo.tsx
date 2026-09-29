import { ActionIcon } from "./ActionIcon";
import { useRef, useState } from 'react';
import { GameControls, type GameControlMode } from './GameControls';
import { Panel } from './Panel';
import { newRace, stepRace, type Race } from '../racing';
import { useGameLoop, useGameSession } from './gameSession';

export function RacingDemo() {
  const s = useGameSession('anycontrol.race.best', newRace);
  const [mode, setMode] = useState<GameControlMode>('race-stick');
  const [autoGas, setAutoGas] = useState(false);
  const autoGasRef = useRef(false); autoGasRef.current = autoGas;
  useGameLoop(s, dt => {
    const p = s.padRef.current, active = s.inputActive();
    const left = s.control('a') || s.control('arrowleft') || active && p.buttons.left;
    const right = s.control('d') || s.control('arrowright') || active && p.buttons.right;
    const steer = left || right ? Number(right) - Number(left) : active ? p.axes.left_x : 0;
    const gas = autoGasRef.current || s.control('w') || s.control('arrowup') ? 1 : active ? p.axes.rt : 0;
    const brake = s.control('s') || s.control('arrowdown') || s.control(' ') ? 1 : active ? p.axes.lt : 0;
    s.game.current = stepRace(s.game.current, steer, gas, brake, dt);
  }, drawRace);
  const g = s.snapshot;
  return <Panel title="코인 로드" label="레이싱 데모" className="demo" detail="장애물 회피 · 코인 수집" info={<>게임 옆에서 물체를 고르고 <b>연결</b>을 누르면 물체 움직임이 조향·가속이 됩니다. 키보드(WASD·방향키)로도 됩니다. P = 일시정지.</>}>
    <div className="game-layout">
    <div ref={s.root} tabIndex={0} className="game-stage" aria-label="레이싱 조작 영역" {...s.handlers}>
      <div className="game-hud" aria-label="레이싱 점수">
        <span>점수 <b>{g.score}</b></span><span>최고 <b>{s.best}</b></span>
        <span>차량 <b>{'♥'.repeat(Math.max(0, g.health)) || '0'}</b></span><span>코인 <b>{g.coins}</b></span>
      </div>
      <canvas ref={s.canvas} width={640} height={400} className="drawpad game-canvas" role="img" aria-label="코인과 무작위 장애물이 있는 레이싱 화면" />
      <div className="row game-actions">
        <button type="button" className={s.paused || g.over ? "act-go" : "act-pause"} onClick={() => s.paused || g.over ? s.play() : s.pause()}><ActionIcon name={s.paused || g.over ? 'play' : 'pause'} />{g.over ? '다시 도전' : s.paused ? '주행 시작 / 계속' : '일시정지'}</button>
        <button type="button" className="act-reset" onClick={() => s.play(true)}><ActionIcon name="reset" />처음부터</button>
        <label className="check small"><input type="checkbox" checked={autoGas} onChange={e => setAutoGas(e.target.checked)} />자동 가속 (조향만)</label>
        <span className="small" role="status">{g.over ? `차량 파손 · 최종 ${g.score}점` : s.paused ? '준비 / 일시정지' : `${Math.round(g.car.speed * 100)} km/h · ${Math.floor(g.car.dist)} m`}</span>
      </div>
      <p className="small muted">WASD / 방향키: 조향·가속·브레이크 · Space: 브레이크 · P: 일시정지. 코인은 100점, 충돌·도로 이탈은 차량 1칸 감소. 멀리 갈수록 장애물 간격이 좁아집니다.</p>
      <p className="small muted">카메라 입력: 옆에서 물체를 연결하면 좌우 이동으로 조향합니다. 회전 조향도 선택할 수 있습니다. 자동 가속을 켜면 조향만으로 플레이할 수 있습니다. 게임을 클릭하면 키보드 조작이 활성화됩니다.</p>
    </div>
    <GameControls mode={mode} onMode={m => { s.pause(); setMode(m); }} />
    </div>
  </Panel>;
}

export function drawRace(c: HTMLCanvasElement | null, s: Race, paused: boolean) {
  const g = c?.getContext('2d'); if (!c || !g) return;
  const W = c.width, H = c.height, road = 310, cy = H - 62;
  g.fillStyle = '#19352e'; g.fillRect(0, 0, W, H);
  for (let y = -40; y < H; y += 70) {
    const yy = y + (s.car.dist * 2.3) % 70;
    g.fillStyle = '#2a5343'; g.fillRect(60, yy, 22, 30); g.fillRect(W - 80, yy + 20, 22, 30);
  }
  g.fillStyle = '#303744'; g.fillRect((W - road) / 2, 0, road, H);
  g.strokeStyle = '#c5cbb7'; g.lineWidth = 3;
  g.setLineDash([22, 24]); g.lineDashOffset = -(s.car.dist * 2.3) % 46;
  for (const x of [W / 2 - road / 6, W / 2 + road / 6]) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke(); }
  g.setLineDash([]);
  for (const item of s.items) {
    const x = W / 2 + item.x * road / 2, y = cy - item.ahead * 2.3;
    if (item.kind === 'coin') {
      g.fillStyle = '#ffd166'; g.beginPath(); g.arc(x, y, 9, 0, Math.PI * 2); g.fill();
      g.fillStyle = '#654913'; g.font = 'bold 12px system-ui'; g.fillText('+', x - 4, y + 4);
    } else {
      g.fillStyle = '#e67651'; g.fillRect(x - 23, y - 12, 46, 24);
      g.fillStyle = '#ffe6aa'; for (let i = -16; i < 20; i += 15) g.fillRect(x + i, y - 9, 6, 18);
    }
  }
  g.save(); g.translate(W / 2 + s.car.x * road / 2, cy); g.rotate(s.car.heading * .5);
  g.globalAlpha = s.invulnerable > 0 && Math.floor(s.invulnerable * 10) % 2 ? .35 : 1;
  g.fillStyle = '#0c1520'; g.fillRect(-18, -16, 36, 33);
  g.fillStyle = '#62c7e7'; g.fillRect(-13, -24, 26, 48);
  g.fillStyle = '#17384b'; g.fillRect(-9, -13, 18, 12);
  g.fillStyle = '#fff4ba'; g.fillRect(-10, -23, 5, 5); g.fillRect(5, -23, 5, 5); g.restore();
  if (paused || s.over) {
    g.fillStyle = '#09111bd9'; g.fillRect(0, 130, W, 115);
    g.textAlign = 'center'; g.fillStyle = '#edf5ff'; g.font = 'bold 26px system-ui';
    g.fillText(s.over ? 'FINISH · 다시 도전!' : 'COIN ROAD', W / 2, 178);
    g.font = '15px system-ui'; g.fillText(s.over ? `${s.score}점 · 코인 ${s.coins}개` : '주행 시작을 누르고 W 또는 ↑로 가속하세요', W / 2, 211); g.textAlign = 'left';
  }
}
