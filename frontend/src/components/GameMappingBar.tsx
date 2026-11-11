import type { ReactNode } from "react";
import { GAME_AXES, gameFns, requiredControls } from "../gameFunctions";
import { sensitivity, withSensitivity } from "../mappingSensitivity";
import { useEffect, useState } from "react";
import { useMappingDraft, useDraftStore } from "../mappingDraft";
import { useApp } from "../store";
import { buildGameMapping, mappingWarning, useGameMappingView } from "../gameMapping";
import type { GameId, GameStyle } from "../gameFunctions";
import { t } from "../i18n";
import { objectLabel } from "../objectRefs";
import type { ObjectInfo } from "../protocol";

const GOAL: Record<GameId, () => string> = {
  race: () => t("코인·부스터를 모으고 다른 차와 기름을 피하세요.", "Collect coins and boosters; avoid cars and oil."),
  pong: () => t("공을 받아 넘기세요. 패들을 움직이며 치면 공이 휘어요.", "Return the ball. Hitting while moving curves it."),
  fruit: () => t("떨어지는 과일을 바구니로 받고 💣 폭탄은 피하세요.", "Catch falling fruit with the basket and avoid 💣 bombs."),
  hockey: () => t("말렛으로 퍽을 쳐서 상대 골대에 넣으세요. 7골 먼저 넣으면 승리.", "Hit the puck into the other goal with your mallet. First to 7 wins."),
  survival: () => t("좀비를 피해 다니세요. 가까운 적은 자동으로 쏴요.", "Dodge the zombies; nearby enemies are shot automatically."),
};
const THING: Record<GameId, () => string> = {
  race: () => t("자동차", "car"), pong: () => t("패들", "paddle"), fruit: () => t("바구니", "basket"),
  hockey: () => t("말렛", "mallet"), survival: () => t("주인공", "hero"),
};

/** 받침에 맞는 주격 조사 (패들이 / 바구니가) */
const ig = (w: string) => { const c = w.charCodeAt(w.length - 1); return w + (c >= 0xac00 && c <= 0xd7a3 && (c - 0xac00) % 28 ? "이" : "가"); };

/** 자동 매핑(지금 고른 인원·컨트롤러·조작법)으로 연결했을 때의 조작법을 쉬운 말로 */
export function controlGuide(game: GameId, players: number, style: GameStyle, sources: string[], objects: ObjectInfo[]): string[] {
  const thing = THING[game]();
  const lines = sources.map((ref, i) => {
    const who = `${players > 1 ? `${i + 1}P ` : ""}${ref ? objectLabel(ref, objects) : t("컨트롤러 미선택", "no controller")}`;
    if (!ref) return `${who}: ${t("위에서 컨트롤러를 고르세요", "choose a controller above")}`;
    const hand = ref === "@hand";
    let how: string;
    if (game === "race") {
      how = hand ? t("손바닥을 좌우로 움직여 조향", "move your palm sideways to steer")
        : style === "angle" ? t("물체를 좌우로 기울여 조향", "tilt the object left/right to steer") : t("물체를 좌우로 움직여 조향", "move the object sideways to steer");
      if (players === 1) how += hand ? t(" · 손을 위로 올리면 가속, 내리면 브레이크", " · raise your hand to speed up, lower it to brake")
        : t(" · 카메라 쪽으로 밀면 가속, 몸 쪽으로 당기면 브레이크 ('자동 가속'을 켜면 조향만)", " · push toward the camera to speed up, pull back to brake ('Auto accelerate' = steering only)");
    } else if (game === "pong") {
      how = hand ? t(`손바닥을 위아래로 움직이면 ${thing}도 위아래`, `move your palm up/down to move the ${thing}`)
        : style === "y" ? t(`물체를 들고 위아래로 움직이면 ${thing}도 위아래`, `hold the object up and move it up/down`)
        : t(`바닥의 물체를 카메라 쪽으로 밀면 ${ig(thing)} 위로, 당기면 아래로`, `push the object on the desk toward the camera to move the ${thing} up, pull back for down`);
    } else {
      how = hand ? t(`손바닥을 좌우·위아래로 움직이면 ${ig(thing)} 따라와요`, `move your palm sideways and up/down to move the ${thing}`)
        : style === "y" ? t(`물체를 들고 좌우·위아래로 움직이면 ${ig(thing)} 따라와요`, `hold the object up and move it sideways and up/down`)
        : t(`바닥의 물체를 좌우로 움직이면 좌우, 카메라 쪽으로 밀면 위, 당기면 아래`, `on the desk: sideways = left/right, push toward the camera = up, pull back = down`);
    }
    return `${who}: ${how}`;
  });
  if (game === "race" && players === 2) lines.push(t("2인은 가속이 자동이에요.", "In 2-player mode the gas is automatic."));
  return lines;
}
export function useGameMapping(game: GameId, players: number) {
  const { draft, edit, err } = useMappingDraft();
  const objects = useApp(s => s.objects), handEnabled = useApp(s => s.handInputEnabled), conn = useApp(s => s.conn);
  const [style, setStyle] = useState<GameStyle>(game === "race" ? "x" : "depth");
  const [chosen, choose] = useState<string[]>([]), [error, setError] = useState("");
  const refs = objects.filter(o => o.kind !== "pen").map(o => `#${o.id}`);
  const sources = Array.from({ length: players }, (_, i) => chosen[i] ?? refs[i] ?? (i === 0 && handEnabled ? "@hand" : ""));
  useEffect(() => { useGameMappingView.getState().setGame(game); }, [game]);
  const check = () => mappingWarning(useDraftStore.getState().draft, game, players, useApp.getState().objects, useApp.getState().handInputEnabled);
  const options: [GameStyle, string][] = game === "race" ? [["x", t("좌우 이동으로 조향", "Steer by moving sideways")], ["angle", t("기울기로 조향", "Steer by tilting")]]
    : [["depth", t("바닥에 놓고 · 크기/앞뒤로 상하", "On desk · size/near-far for Y")], ["y", t("들고 · 영상 위아래로 상하", "Held up · video up/down for Y")]];
  const channels = new Set(gameFns(game).filter(f => f.control && (requiredControls(game, players).includes(f.control) || game === "race" && players === 1)).map(f => GAME_AXES[f.control!]));
  const relevant = (m: NonNullable<typeof draft>["mappings"][number]) => m.output.target === "gamepad_axis" && channels.has(m.output.axis);
  const values = draft?.mappings.filter(relevant).map(sensitivity) ?? [];
  const sens = values.length ? values.reduce((a, b) => a + b, 0) / values.length : 1;
  const mixed = values.some(v => Math.abs(v - sens) > .05);
  const bar = (actions: ReactNode) => <section className="game-mapping" data-tour="automap" aria-label={t("게임 자동 매핑", "Game auto-mapping")}>
    <div className="row"><label>{t("조작법", "Controls")} <select aria-label={t("자동 매핑 조작법", "Auto-map control style")} value={style} onChange={e => setStyle(e.target.value as GameStyle)}>{options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}</select></label>
      {sources.map((ref, i) => <label key={i}>{players > 1 ? `${i + 1}P` : t("컨트롤러", "Controller")} <select aria-label={`${i + 1}P ${t("컨트롤러", "controller")}`} value={ref} onChange={e => { const next = [...sources]; next[i] = e.target.value; choose(next); }}>
        <option value="">{t("선택하세요", "Select")}</option>{refs.map(ref => <option key={ref} value={ref}>{objectLabel(ref, objects)}</option>)}{handEnabled && <option value="@hand">{t("맨손 (영상 XY)", "Bare hand (video XY)")}</option>}
      </select></label>)}
      <button type="button" className="act-config" disabled={!draft || conn !== "open"} onClick={() => { try { edit(buildGameMapping(useDraftStore.getState().draft!, game, players, style, sources), true); setError(""); } catch (e) { setError(String(e instanceof Error ? e.message : e)); } }}>{t("자동 매핑", "Auto-map")}</button>
      <label className="game-sensitivity">{t("민감도", "Sensitivity")} {`×${sens.toFixed(1)}`} {mixed && t("(축별 설정)", "(mixed axes)")}
        <input type="range" aria-label={t("게임 민감도", "Game sensitivity")} min="0.3" max="4" step="0.1" value={Math.max(.3, Math.min(4, sens))} disabled={!values.length} onChange={e => { const p = useDraftStore.getState().draft; if (p) edit({ ...p, mappings: p.mappings.map(m => relevant(m) ? withSensitivity(m, sensitivity(m) * Number(e.target.value) / sens) : m) }); }} />
      </label>
      {actions}
    </div>
    <p className="small muted">{t("자동 매핑은 가상 게임패드 축 연결을 선택한 프리셋으로 교체합니다. 민감도는 모든 조작 축을 함께 조절하며 축별 비율·방향은 유지합니다. 매핑 패널의 수정도 게임 중 반영됩니다.", "Auto-map replaces virtual gamepad axis connections with the selected preset. Sensitivity adjusts all control axes together and keeps their relative tuning and directions. Mapping edits also apply during play.")}</p>
    {(error || err) && <p role="alert" className="error small">{error || err}</p>}
    {mappingWarning(draft, game, players, objects, handEnabled) && <p className="warn small">{t("연결 대기 · 자동 매핑을 누르세요", "Not connected · press Auto-map")}</p>}
  </section>;
  /** 시작 화면: 처음 시작하기 전(또는 연결 없이 시작을 눌렀을 때) 게임 위에 조작법과 연결 경고를 띄운다 */
  const autoMap = () => { try { edit(buildGameMapping(useDraftStore.getState().draft!, game, players, style, sources), true); setError(""); return true; } catch (e) { setError(String(e instanceof Error ? e.message : e)); return false; } };
  const guide = (s: { fresh: boolean; paused: boolean; warning: string; clearWarning: () => void; play: () => void }, over: boolean) => {
    const missing = mappingWarning(draft, game, players, objects, handEnabled);
    if (!s.paused || over || !(s.fresh || s.warning)) return null;
    return <div className="game-guide" role="dialog" aria-label={t("게임 시작 안내", "Game start guide")}>
      <h3>{t("조작법", "How to play")} <small>{t("자동 매핑 기준", "with Auto-map")}</small></h3>
      <ul>{controlGuide(game, players, style, sources, objects).map((line, i) => <li key={i}>{line}</li>)}</ul>
      <p className="game-guide-goal">{GOAL[game]()}</p>
      {missing ? <div className="game-guide-warn" role="alert">
        <b>{t("⚠ 아직 게임에 연결된 컨트롤러가 없어요", "⚠ No controller is connected to this game yet")}</b>
        <span>{t("물체를 등록하고 [자동 매핑]을 누르거나, 매핑 패널에서 게임 잭을 연결한 뒤 시작하세요.", "Register an object and press Auto-map, or connect the game jacks in the Mapping panel, then start.")}</span>
        <button type="button" className="act-config" disabled={!draft || conn !== "open" || !sources[0]} onClick={() => { if (autoMap()) s.clearWarning(); }}>{t("자동 매핑", "Auto-map")}</button>
      </div> : <button type="button" className="act-go game-guide-start" onClick={() => s.play()}>{t("시작 (Space)", "Start (Space)")}</button>}
      {(error || err) && <p role="alert" className="error small">{error || err}</p>}
    </div>;
  };
  return { bar, check, guide };
}
