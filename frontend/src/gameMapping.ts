import { create } from "zustand";
import { GAME_AXES, gameFns, requiredControls, type GameId, type GameStyle } from "./gameFunctions";
import { connect } from "./patch";
import type { ObjectInfo, Profile } from "./protocol";
import { t } from "./i18n";
export const useGameMappingView = create<{ game: GameId; setGame: (game: GameId) => void; dj: boolean; setDj: (dj: boolean) => void }>(set => ({ game: "race", setGame: game => set({ game }), dj: false, setDj: dj => set({ dj }) }));
/** DJ 셋의 연결(데모 조작 dj.*): 매핑 패널에서는 보이지 않고 DJ 패널에서만 다룬다 */
export const isDjMapping = (m: { output: { target: string; name?: string } }) => m.output.target === "control" && Boolean(m.output.name?.startsWith("dj."));
export function buildGameMapping(p: Profile, game: GameId, players: number, style: GameStyle, sources: string[]): Profile {
  if (!sources[0] || players === 2 && (!sources[1] || sources[0] === sources[1])) throw new Error(t("인원에 맞게 서로 다른 물체·맨손을 선택하세요.", "Choose a different object or hand for each player."));
  // A preset owns the controller axes: avoid leftover P2/triggers or sums from old games.
  let next = { ...p, mappings: p.mappings.filter(m => m.output.target !== "gamepad_axis" && !(m.output.target === "control" && GAME_AXES[m.output.name])) };
  const wanted = requiredControls(game, players);
  for (const f of gameFns(game)) {
    if (!f.control || !wanted.includes(f.control) && !(game === "race" && players === 1 && ["race.gas", "race.brake"].includes(f.control))) continue;
    const second = /2$/.test(f.control) || f.control === "pong.right";
    const source = sources[second ? 1 : 0]!;
    next = connect(next, source, f.id);
    const m = next.mappings[next.mappings.length - 1]!;
    let axis = f.axis, invert = Boolean(f.transform.invert), range = f.transform.range!;
    if (game === "race" && f.control.includes("steer")) { axis = style === "angle" ? "angle" : "x"; range = axis === "angle" ? [-30, 30] : [-.18, .18]; }
    if ((game === "pong" || (game === "fruit" || game === "hockey") && /y[12]$/.test(f.control) || game === "survival" && f.control.endsWith(".y")) && style === "y") { axis = "y"; invert = false; range = [-.3, .3]; }
    m.input = source === "@hand" ? { source: "hand", gesture: axis === "x" || axis === "angle" ? "x" : "y" } : { source: "object", object: source, axis };
    m.transform = { ...m.transform, range: source === "@hand" ? [-.3, .3] : range, invert: source === "@hand" ? false : invert, smoothing_ms: 0, on_lost: "release", lost_ms: 0 };
    if (source === "@hand" && (f.control === "race.gas" || f.control === "race.brake")) {
      m.transform.range = f.control === "race.gas" ? [-.3, 0] : [0, .3];
      m.transform.invert = f.control === "race.gas";
    }
  }
  if (next.mappings.length > 64) throw new Error(t("매핑이 64개를 넘습니다. 사용하지 않는 연결을 먼저 지워 주세요.", "More than 64 mappings. Remove unused connections first."));
  return next;
}
export function mappingWarning(p: Profile | null, game: GameId, players: number, objects: ObjectInfo[], handEnabled: boolean): string | null {
  const valid = (m: Profile["mappings"][number]) => {
    const input = m.input;
    return m.enabled && (input.source === "hand" ? handEnabled : "object" in input && objects.some(o => input.object === `#${o.id}` || input.object === o.name));
  };
  const required = requiredControls(game, players);
  if (!p || !required.every(name => p.mappings.some(m => m.output.target === "gamepad_axis" && m.output.axis === GAME_AXES[name] && valid(m)))) return t("게임 연결이 부족합니다. 위의 자동 매핑을 누르거나 매핑 패널에서 게임 잭을 연결하세요.", "Game controls are missing. Press Auto-map above or connect the game jacks in Mapping.");
  return null;
}
