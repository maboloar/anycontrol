import { gameCanvas } from "../gameCanvas";
import { GameButtons } from './GameButtons';
import { useGameMapping } from "./GameMappingBar";
import { Panel } from './Panel';
import { useGameLoop, useGameSession } from './gameSession';
import { newSurvival, stepSurvival, SH, SW, WAVES, WEAPON, zRadius, type Survival } from '../survival';
import { applyShake, banner, drawFx, drawIcon } from '../fx';
import { t } from '../i18n';

const WEAPON_EN = ['Single', 'Double', 'Spread', 'Rapid'];

export function SurvivalDemo() {
  const setup = useGameMapping('survival', 1);
  const s = useGameSession('anycontrol.survival.best', newSurvival, setup.check);
  useGameLoop(s, dt => {
    const p = s.padRef.current, active = s.inputActive();
    const x = Number(s.control('d') || s.control('arrowright') || active && p.buttons.right) - Number(s.control('a') || s.control('arrowleft') || active && p.buttons.left);
    const y = Number(s.control('s') || s.control('arrowdown') || active && p.buttons.down) - Number(s.control('w') || s.control('arrowup') || active && p.buttons.up);
    s.game.current = stepSurvival(s.game.current, x || s.demoControl("survival.x"), y || s.demoControl("survival.y"), dt);

  }, drawSurvival);
  const g = s.snapshot;
  return <Panel title={t("좀비 서바이벌", "Zombie Survival")} label="좀비 서바이벌 데모" className="demo" detail={t(`웨이브 ${WAVES}개를 버티세요 · 사격은 자동`, `Survive ${WAVES} waves · auto fire`)}
    info={t(<>움직이기만 하면 가까운 좀비를 자동으로 쏩니다. 자동 매핑에서 <b>영상 XY 또는 좌우+크기</b>를 골라 연결하세요. 매핑 패널의 <b>좀비 이동 좌우·상하</b> 잭과 WASD·방향키로 조작합니다. 🔋 를 모으면 무기가 두 발 → 산탄 → 연사로 강해지고, ❤️ 회복·🛡️ 보호막·💥 화면 정리가 떨어집니다. 달리는 좀비·탱크·자폭 좀비(가까이 오면 터짐)·보스(웨이브 4·8)를 조심하세요. Space = 일시정지.</>,
      <>Just move; the nearest zombie is shot automatically. Choose <b>video XY or sideways + size</b> in Auto-map, then adjust the <b>Zombie move X/Y</b> jacks in Mapping. WASD also works. Collect 🔋 to upgrade double → spread → rapid fire; ❤️ heal, 🛡️ shield and 💥 clear-screen also drop. Watch out for runners, tanks, bombers (explode up close) and bosses (waves 4 and 8). Space = pause.</>)}>
    <div ref={s.root} tabIndex={0} className="game-stage" aria-label={t("좀비 게임 조작 영역", "Zombie game play area")} {...s.handlers}>
      {setup.bar(<GameButtons s={s} over={g.over} startLabel={t('생존 시작 / 계속', 'Start / Resume')}
        status={g.over ? g.won ? t(`생존 성공! ${g.score}점`, `You survived! ${g.score} pts`) : t(`웨이브 ${g.wave}에서 쓰러짐 · ${g.score}점`, `Fell on wave ${g.wave} · ${g.score} pts`) : s.paused ? t('준비 / 일시정지', 'Ready / Paused') : g.breakT > 0 ? t(`다음 웨이브까지 ${g.breakT.toFixed(1)}초`, `Next wave in ${g.breakT.toFixed(1)} s`) : t('이동해서 좀비를 피하세요', 'Move to dodge zombies')} />)}
      <div className="game-hud" aria-label={t("좀비 게임 점수", "Zombie game score")}>
        <span>{t('점수', 'Score')} <b>{g.score}</b></span><span>{t('최고', 'Best')} <b>{s.best}</b></span>
        <span>{t('생명', 'Lives')} <b>{'♥'.repeat(Math.max(0, g.hp)) || '0'}</b></span>
        <span>{t('웨이브', 'Wave')} <b>{g.wave}/{WAVES}</b></span><span>{t('처치', 'Kills')} <b>{g.kills}</b></span>
        <span>{t('무기', 'Weapon')} <b>{t(WEAPON[g.power]!, WEAPON_EN[g.power]!)}</b></span>
      </div>
      <canvas ref={s.canvas} width={SW} height={SH} className="drawpad game-canvas" role="img" aria-label={t("좀비와 아이템이 있는 탑다운 게임 화면", "Top-down game screen with zombies and items")} />

    </div>
  </Panel>;
}

const ZCOLOR = { walker: ['#7fae5c', '#5c8a3f'], runner: ['#e39b6d', '#b8704a'], tank: ['#5f7d8c', '#405866'], bomber: ['#d65151', '#9a2f2f'], boss: ['#8d4bd6', '#5d2a99'] } as const;

export function drawSurvival(c: HTMLCanvasElement | null, s: Survival, paused: boolean) {
  const g = gameCanvas(c, SW, SH); if (!c || !g) return;
  g.save();
  applyShake(g, s.fx);
  // 바닥: 타일 + 얼룩
  g.fillStyle = '#1b2a2f'; g.fillRect(-20, -20, SW + 40, SH + 40);
  for (let y = 0; y < SH; y += 40) for (let x = 0; x < SW; x += 40) {
    g.fillStyle = (x / 40 + y / 40) % 2 ? '#1f3036' : '#1c2c31'; g.fillRect(x, y, 40, 40);
    if (((x * 7 + y * 13) % 11) === 0) { g.fillStyle = '#ffffff08'; g.fillRect(x + 8, y + 12, 10, 3); }
  }
  for (const d of s.decals) { g.globalAlpha = d.life * .6; g.fillStyle = d.color; g.beginPath(); g.ellipse(d.x, d.y, d.r, d.r * .7, 0, 0, Math.PI * 2); g.fill(); }
  g.globalAlpha = 1;
  // 아이템
  g.textAlign = 'center'; g.textBaseline = 'middle';
  for (const p of s.pickups) {
    if (p.life < 2 && Math.floor(p.life * 8) % 2) continue;   // 사라지기 전 깜빡임
    const bob = Math.sin(s.time * 5 + p.x) * 3;
    g.fillStyle = '#0005'; g.beginPath(); g.ellipse(p.x, p.y + 10, 9, 3, 0, 0, Math.PI * 2); g.fill();
    g.save(); g.translate(p.x, p.y + bob); g.shadowColor = p.kind === 'battery' ? '#ffd43b' : '#fff'; g.shadowBlur = 12;
    drawIcon(g, p.kind === 'heal' ? 'heart' : p.kind, 9, s.time); g.restore();
  }
  // 좀비
  for (const z of s.zombies) {
    const r = zRadius(z.kind), [c1, c2] = ZCOLOR[z.kind];
    g.fillStyle = '#0006'; g.beginPath(); g.ellipse(z.x + 2, z.y + r * .7, r, r * .45, 0, 0, Math.PI * 2); g.fill();
    if (z.kind === 'bomber') { g.fillStyle = `rgba(255,80,60,${0.25 + 0.25 * Math.sin(s.time * 14 + z.id)})`; g.beginPath(); g.arc(z.x, z.y, r + 7, 0, Math.PI * 2); g.fill(); }
    const gr = g.createRadialGradient?.(z.x - r * .3, z.y - r * .3, 1, z.x, z.y, r);
    if (gr) { gr.addColorStop(0, c1); gr.addColorStop(1, c2); g.fillStyle = z.hit > 0 ? '#fff' : gr; } else g.fillStyle = z.hit > 0 ? '#fff' : c1;
    g.beginPath(); g.arc(z.x, z.y, r, 0, Math.PI * 2); g.fill();
    const a = Math.atan2(s.y - z.y, s.x - z.x);
    g.fillStyle = z.kind === 'boss' ? '#ffd43b' : '#ff3b3b';
    for (const off of [-.45, .45]) { g.beginPath(); g.arc(z.x + Math.cos(a + off) * r * .55, z.y + Math.sin(a + off) * r * .55, Math.max(2, r * .16), 0, Math.PI * 2); g.fill(); }
    if (z.kind === 'tank' || z.kind === 'boss') {
      const w = r * 2; g.fillStyle = '#0009'; g.fillRect(z.x - w / 2, z.y - r - 10, w, 5);
      g.fillStyle = z.kind === 'boss' ? '#b04bff' : '#ff6b6b'; g.fillRect(z.x - w / 2, z.y - r - 10, w * Math.max(0, z.hp / z.max), 5);
    }
  }
  // 총알 (빛나는 꼬리)
  for (const b of s.bullets) {
    g.strokeStyle = '#fff4bd'; g.lineWidth = 3; g.shadowColor = '#ffd43b'; g.shadowBlur = 8;
    g.beginPath(); g.moveTo(b.x, b.y); g.lineTo(b.x - b.vx * .025, b.y - b.vy * .025); g.stroke(); g.shadowBlur = 0;
  }
  // 주인공
  const blink = s.invulnerable > 0 && Math.floor(s.invulnerable * 12) % 2;
  if (s.shield > 0) { g.strokeStyle = `rgba(122,215,255,${0.5 + 0.3 * Math.sin(s.time * 10)})`; g.lineWidth = 3; g.beginPath(); g.arc(s.x, s.y, 22, 0, Math.PI * 2); g.stroke(); }
  g.fillStyle = '#0006'; g.beginPath(); g.ellipse(s.x + 2, s.y + 9, 11, 5, 0, 0, Math.PI * 2); g.fill();
  g.save(); g.translate(s.x, s.y); g.rotate(s.aim);
  g.fillStyle = '#2b3440'; g.fillRect(4, -3, 16, 6);   // 총
  if (s.muzzle > 0) { g.fillStyle = '#ffe08a'; g.beginPath(); g.moveTo(20, 0); g.lineTo(32, -7); g.lineTo(30, 0); g.lineTo(32, 7); g.closePath(); g.fill(); }
  g.fillStyle = blink ? '#ffffff' : '#64c6f1'; g.beginPath(); g.arc(0, 0, 11, 0, Math.PI * 2); g.fill();
  g.fillStyle = '#e9f7ff'; g.beginPath(); g.arc(4, 0, 4, 0, Math.PI * 2); g.fill();
  g.restore();
  g.textAlign = 'left'; g.textBaseline = 'alphabetic';
  drawFx(g, s.fx, SW, SH);
  // 손전등: 웨이브가 갈수록 주변이 어두워진다
  const dark = Math.min(.82, .15 + s.wave * .085);
  const lg = g.createRadialGradient?.(s.x, s.y, 40, s.x, s.y, 230);
  if (lg) { lg.addColorStop(0, 'rgba(0,0,0,0)'); lg.addColorStop(1, `rgba(0,0,0,${dark})`); g.fillStyle = lg; g.fillRect(0, 0, SW, SH); }
  g.restore();
  // 웨이브 진행 막대
  const total = s.toSpawn + s.zombies.length;
  g.fillStyle = '#0007'; g.fillRect(0, 0, SW, 6);
  g.fillStyle = '#7dff9b'; g.fillRect(0, 0, SW * (1 - total / Math.max(1, 8 + s.wave * 5)), 6);
  if (s.bannerT > 0) {
    const boss = (s.wave === 4 || s.wave === 8) && s.zombies.some((z) => z.kind === 'boss');
    banner(g, SW, SH, boss ? t('보스 등장!', 'BOSS INCOMING!') : t(`웨이브 ${s.wave}`, `WAVE ${s.wave}`), boss ? t('보라색 거대 좀비를 처치하세요', 'Take down the giant purple zombie') : t(`좀비 ${8 + s.wave * 5}마리`, `${8 + s.wave * 5} zombies`), s.bannerT, boss ? '#b04bff' : '#ffd43b');
  }
  if (paused || s.over) {
    g.fillStyle = '#09111bdf'; g.fillRect(0, 120, SW, 145); g.textAlign = 'center'; g.fillStyle = '#eaf8ff'; g.font = 'bold 28px system-ui';
    g.fillText(s.over ? s.won ? t('생존 성공!', 'YOU SURVIVED!') : t('쓰러졌습니다', 'You fell') : t('좀비 서바이벌', 'ZOMBIE SURVIVAL'), SW / 2, 165);
    g.font = '15px system-ui';
    g.fillText(s.over ? t(`${s.score}점 · 처치 ${s.kills} · 웨이브 ${s.wave}`, `${s.score} pts · ${s.kills} kills · wave ${s.wave}`) : t(`웨이브 ${WAVES}개를 버티면 승리 · 사격은 자동`, `Survive ${WAVES} waves · shooting is automatic`), SW / 2, 198);
    if (!s.over) g.fillText(t('🔋 무기 강화 · ❤️ 회복 · 🛡️ 보호막 · 💥 화면 정리 · Space 시작', '🔋 upgrade · ❤️ heal · 🛡️ shield · 💥 clear · Space to start'), SW / 2, 226);
    g.textAlign = 'left';
  }
}
