import { useRef, useState } from "react";
import { gameCanvas } from "../gameCanvas";
import { HH, HW, GOAL, HOCKEY_WIN, MALLET, PUCK, RAIL, newHockey, stepHockey, type Hockey, type HockeyMode, type HockeyDifficulty, type Point } from "../hockey";
import { applyShake, drawFx } from "../fx";
import { t } from "../i18n";
import { GameButtons } from "./GameButtons";
import { useGameMapping } from "./GameMappingBar";
import { useGameLoop, useGameSession } from "./gameSession";
import { Panel } from "./Panel";
export function HockeyDemo() {
  const [mode, setMode] = useState<HockeyMode>("pc"), modeRef = useRef(mode); modeRef.current = mode;
  const [difficulty, setDifficulty] = useState<HockeyDifficulty>("normal"), difficultyRef = useRef(difficulty); difficultyRef.current = difficulty;
  const setup = useGameMapping("hockey", mode === "2p" ? 2 : 1);
  const s = useGameSession("anycontrol.hockey.best", () => newHockey(modeRef.current, difficultyRef.current), setup.check);
  const keyboard = useRef<[Point, Point]>([{ x: HW * .24, y: HH / 2 }, { x: HW * .76, y: HH / 2 }]);
  useGameLoop(s, dt => {
    const targets = [0, 1].map(i => {
      const x = i === 0 ? Number(s.control('d')) - Number(s.control('a')) : Number(s.control('arrowright')) - Number(s.control('arrowleft'));
      const y = i === 0 ? Number(s.control('s')) - Number(s.control('w')) : Number(s.control('arrowdown')) - Number(s.control('arrowup'));
      const mapped = { x: HW * ((i === 0 ? .24 : .76) + .19 * s.demoControl(`hockey.x${i + 1}`)), y: HH * (.5 + .38 * s.demoControl(`hockey.y${i + 1}`)) };
      const old = keyboard.current[i]!;
      if (x || y) { old.x = Math.max(i === 0 ? RAIL + MALLET : HW / 2 + MALLET, Math.min(i === 0 ? HW / 2 - MALLET : HW - RAIL - MALLET, old.x + x * dt * 460)); old.y = Math.max(RAIL + MALLET, Math.min(HH - RAIL - MALLET, old.y + y * dt * 460)); return { ...old }; }
      keyboard.current[i] = mapped; return mapped;
    }) as [Point, Point];
    s.game.current = stepHockey(s.game.current, targets, dt);
  }, drawHockey);
  const g = s.snapshot;
  return <Panel title={t("에어 하키", "Air Hockey")} label="에어 하키 데모" className="demo" detail={t("원형 말렛으로 퍽을 쳐서 골 넣기", "Strike the puck with a circular mallet")}
    info={t("바닥에 물체를 놓고 좌우·앞뒤로 움직여 말렛을 조작하세요. 자동 매핑에서 컨트롤러와 바닥/들기 방식을 선택합니다. 1인은 컴퓨터, 2인은 왼쪽 1P와 오른쪽 2P가 대결하며 각자 자기 진영에서 움직입니다. 빠르게 밀면 퍽에 힘이 실립니다. 7골 선승, Space 일시정지. 입력·감도·방향은 매핑 패널에서 바꿉니다.", "Move objects sideways and near/far on the desk to control the mallets. Choose controllers and desk/held controls in Auto-map. Play the computer or a second player: P1 left, P2 right, each in their own half. Quick pushes add force to the puck. First to 7, Space pauses. Edit input, sensitivity and direction in Mapping.")}>
    <div ref={s.root} tabIndex={0} className="game-stage" aria-label={t("에어 하키 조작 영역", "Air hockey play area")} {...s.handlers}>
      <div className="row game-mode" role="radiogroup" aria-label={t("상대", "Opponent")}>{(["pc", "2p"] as HockeyMode[]).map(m => <button key={m} type="button" role="radio" aria-checked={mode === m} className={mode === m ? 'active' : ''} onClick={() => { s.pause(); setMode(m); modeRef.current = m; s.game.current = newHockey(m, difficultyRef.current); s.publish(); }}>{m === "pc" ? t("1인 · 컴퓨터와", "1P · vs computer") : t("2인 대결", "2P match")}</button>)}</div>
      {mode === "pc" && <label className="hockey-difficulty">{t("AI 난이도", "AI difficulty")} <select aria-label={t("AI 난이도", "AI difficulty")} value={difficulty} onChange={e => { const d = e.target.value as HockeyDifficulty; setDifficulty(d); difficultyRef.current = d; s.game.current = { ...s.game.current, difficulty: d }; s.publish(); }}><option value="easy">{t("쉬움", "Easy")}</option><option value="normal">{t("보통", "Normal")}</option><option value="hard">{t("어려움", "Hard")}</option></select></label>}
      {setup.bar(<GameButtons s={s} over={g.over} status={g.over ? t(`${g.winner === 0 ? "1P" : mode === "pc" ? "컴퓨터" : "2P"} 승리!`, `${g.winner === 0 ? "P1" : mode === "pc" ? "Computer" : "P2"} wins!`) : s.paused ? t("준비 / 일시정지", "Ready / Paused") : t(`${HOCKEY_WIN}골 먼저 · 자기 진영에서 퍽을 밀어 주세요`, `First to ${HOCKEY_WIN} · strike from your half`)} />)}
      <div className="game-hud"><span>1P <b>{g.points[0]}</b></span><span>{mode === "pc" ? t("컴퓨터", "Computer") : "2P"} <b>{g.points[1]}</b></span><span>{t("타격", "Hits")} <b>{g.hits}</b></span><span>{t("최고", "Best")} <b>{s.best}</b></span></div>
      <canvas ref={s.canvas} width={HW} height={HH} className="drawpad game-canvas" role="img" aria-label={t("에어 하키 테이블", "Air hockey table")} />

    </div>
  </Panel>;
}
export function drawHockey(c: HTMLCanvasElement | null, s: Hockey, paused: boolean) {
  const g = gameCanvas(c, HW, HH); if (!g) return;
  g.save(); applyShake(g, s.fx);
  g.fillStyle = '#09121e'; g.fillRect(-10, -10, HW + 20, HH + 20);
  const ice = g.createLinearGradient(0, RAIL, 0, HH - RAIL); ice.addColorStop(0, '#274456'); ice.addColorStop(.5, '#173849'); ice.addColorStop(1, '#204e62');
  g.fillStyle = ice; g.beginPath(); g.roundRect(RAIL, RAIL, HW - 2 * RAIL, HH - 2 * RAIL, 20); g.fill();
  // Air holes and rink markings are vector drawn at the display's pixel density.
  g.fillStyle = '#b5ecff18'; for (let y = 42; y < HH - 30; y += 14) for (let x = 40; x < HW - 30; x += 14) { g.beginPath(); g.arc(x, y, .8, 0, Math.PI * 2); g.fill(); }
  g.strokeStyle = '#c3efff65'; g.lineWidth = 2; g.beginPath(); g.moveTo(HW / 2, RAIL); g.lineTo(HW / 2, HH - RAIL); g.stroke();
  g.beginPath(); g.arc(HW / 2, HH / 2, 57, 0, Math.PI * 2); g.stroke();
  for (const x of [HW * .25, HW * .75]) { g.beginPath(); g.arc(x, HH / 2, 33, 0, Math.PI * 2); g.stroke(); }
  g.lineWidth = 7; g.strokeStyle = '#7bd5f0'; g.shadowColor = '#6edfff'; g.shadowBlur = 14;
  g.strokeRect(RAIL - 4, RAIL - 4, HW - 2 * RAIL + 8, HH - 2 * RAIL + 8); g.shadowBlur = 0;
  for (const [x, color] of [[RAIL - 6, '#64dfff'], [HW - RAIL - 4, '#ff8c9c']] as const) { g.fillStyle = '#050b13'; g.fillRect(x - 5, HH / 2 - GOAL, 16, GOAL * 2); g.fillStyle = color; g.fillRect(x + 7, HH / 2 - GOAL, 3, GOAL * 2); }
  s.trail.forEach((p, i) => { g.globalAlpha = i / Math.max(1, s.trail.length) * .22; g.fillStyle = '#e4faff'; g.beginPath(); g.arc(p.x, p.y, PUCK * i / Math.max(1, s.trail.length), 0, Math.PI * 2); g.fill(); }); g.globalAlpha = 1;
  s.mallets.forEach((m, i) => {
    const color = i === 0 ? '#64dfff' : '#ff8c9c';
    g.shadowColor = '#000a'; g.shadowBlur = 12; g.shadowOffsetY = 5; g.fillStyle = '#061923'; g.beginPath(); g.arc(m.x, m.y + 2, MALLET + 2, 0, Math.PI * 2); g.fill();
    g.shadowBlur = g.shadowOffsetY = 0; g.fillStyle = color; g.beginPath(); g.arc(m.x, m.y, MALLET, 0, Math.PI * 2); g.fill();
    g.strokeStyle = '#ffffffaa'; g.lineWidth = 2; g.stroke(); g.fillStyle = i === 0 ? '#266e8c' : '#8c4257'; g.beginPath(); g.arc(m.x, m.y - 3, 13, 0, Math.PI * 2); g.fill();
    g.fillStyle = '#ffffff45'; g.beginPath(); g.arc(m.x - 4, m.y - 7, 6, 0, Math.PI * 2); g.fill();
  });
  g.fillStyle = '#040b12'; g.shadowColor = '#000'; g.shadowBlur = 8; g.beginPath(); g.arc(s.puck.x, s.puck.y, PUCK, 0, Math.PI * 2); g.fill(); g.shadowBlur = 0;
  g.strokeStyle = '#e3f5ff'; g.lineWidth = 2.5; g.stroke(); g.fillStyle = '#ffffff33'; g.beginPath(); g.arc(s.puck.x - 3, s.puck.y - 3, 4, 0, Math.PI * 2); g.fill();
  drawFx(g, s.fx, HW, HH); g.restore();
  if (paused || s.over) { g.fillStyle = '#09121ee8'; g.fillRect(100, HH / 2 - 49, HW - 200, 98); g.fillStyle = '#edfaff'; g.textAlign = 'center'; g.font = '800 28px system-ui'; g.fillText(s.over ? t('경기 종료', 'MATCH OVER') : 'AIR HOCKEY', HW / 2, HH / 2 - 8); g.font = '14px system-ui'; g.fillText(t('자동 매핑 후 시작 · 바닥에서 좌우/앞뒤 조작', 'Auto-map, then Start · move sideways / near-far'), HW / 2, HH / 2 + 23); g.textAlign = 'left'; }
  else if (s.serve > 0) { g.fillStyle = '#fff'; g.textAlign = 'center'; g.font = '800 30px system-ui'; g.fillText(s.lastGoal === null ? String(Math.ceil(s.serve)) : 'GOAL!', HW / 2, HH / 2 - 40); g.textAlign = 'left'; }
}
