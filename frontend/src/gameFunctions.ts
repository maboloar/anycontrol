import type { PatchFn } from "./patch";
import type { GamepadAxis, InputAxis, Profile } from "./protocol";
import { t } from "./i18n";
export type GameId = "race" | "pong" | "fruit" | "survival" | "hockey";
export type GameStyle = "x" | "angle" | "depth" | "y";
export const GAME_LABEL = { hockey: () => t("에어 하키", "Air Hockey"), race: () => t("레이싱", "Racing"), pong: () => t("퐁", "Pong"), fruit: () => t("과일 받기", "Fruit Catch"), survival: () => t("좀비", "Zombies") };
/** All games use this same standard virtual controller. */
export const GAME_AXES: Record<string, GamepadAxis> = {
  "race.steer1": "left_x", "race.steer2": "right_x", "race.gas": "rt", "race.brake": "lt",
  "pong.left": "left_y", "pong.right": "right_y",
  "fruit.x1": "left_x", "fruit.y1": "left_y", "fruit.x2": "right_x", "fruit.y2": "right_y",
  "hockey.x1": "left_x", "hockey.y1": "left_y", "hockey.x2": "right_x", "hockey.y2": "right_y",
  "survival.x": "left_x", "survival.y": "left_y",
};
/** Old named demo outputs become real pad channels; the last owner wins on migration. */
export function normalizeGameProfile(p: Profile): Profile {
  const legacy = new Set(p.mappings.flatMap(m => m.output.target === "control" && GAME_AXES[m.output.name] ? [GAME_AXES[m.output.name]!] : []));
  if (!legacy.size) return p;
  const mappings = p.mappings.map(m => m.output.target === "control" && GAME_AXES[m.output.name] ? { ...m, output: { target: "gamepad_axis" as const, axis: GAME_AXES[m.output.name]! } } : m);
  return { ...p, mappings: mappings.filter((m, i) => m.output.target !== "gamepad_axis" || !legacy.has(m.output.axis) || !mappings.slice(i + 1).some(n => n.output.target === "gamepad_axis" && n.output.axis === (m.output as { axis: GamepadAxis }).axis)) };
}
function fn(game: GameId, key: string, ko: string, en: string, axis: InputAxis, range: [number, number], invert = false): PatchFn {
  return { id: `${game}-${key}`, label: () => `${GAME_LABEL[game]()} · ${t(ko, en)}`, hint: () => t("자동 매핑 또는 카드 잭 연결", "Auto-map or connect a card jack"),
    output: { target: "gamepad_axis", axis: GAME_AXES[`${game}.${key}`]! }, control: `${game}.${key}`, axis, transform: { range, invert, deadzone: .04, on_lost: "release", lost_ms: 0 } };
}
export const GAME_FNS: PatchFn[] = [
  fn("hockey", "x1", "1P 말렛 좌우", "P1 mallet X", "x", [-.25, .25]),
  fn("hockey", "y1", "1P 말렛 앞뒤", "P1 mallet Y", "depth", [-.35, .35], true),
  fn("hockey", "x2", "2P 말렛 좌우", "P2 mallet X", "x", [-.25, .25]),
  fn("hockey", "y2", "2P 말렛 앞뒤", "P2 mallet Y", "depth", [-.35, .35], true),
  fn("race", "steer1", "1P 조향", "P1 steering", "x", [-.18, .18]),
  fn("race", "steer2", "2P 조향", "P2 steering", "x", [-.18, .18]),
  fn("race", "gas", "가속", "Gas", "depth", [0, .35], false),
  fn("race", "brake", "브레이크", "Brake", "depth", [-.35, 0], true),
  fn("pong", "left", "왼쪽 패들", "Left paddle", "depth", [-.35, .35], true),
  fn("pong", "right", "오른쪽 패들", "Right paddle", "depth", [-.35, .35], true),
  fn("fruit", "x1", "1P 손잡이 좌우", "P1 handle X", "x", [-.3, .3]),
  fn("fruit", "y1", "1P 손잡이 상하", "P1 handle Y", "depth", [-.35, .35], true),
  fn("fruit", "x2", "2P 손잡이 좌우", "P2 handle X", "x", [-.3, .3]),
  fn("fruit", "y2", "2P 손잡이 상하", "P2 handle Y", "depth", [-.35, .35], true),
  fn("survival", "x", "이동 좌우", "Move X", "x", [-.25, .25]),
  fn("survival", "y", "이동 상하", "Move Y", "depth", [-.35, .35], true),
];
export function gameFns(game: GameId): PatchFn[] { return GAME_FNS.filter(f => f.control?.startsWith(game + ".")); }
export function requiredControls(game: GameId, players: number): string[] {
  const keys = game === "race" ? players === 2 ? ["steer1", "steer2"] : ["steer1"]
    : game === "pong" ? players === 2 ? ["left", "right"] : ["left"]
    : game === "fruit" || game === "hockey" ? players === 2 ? ["x1", "y1", "x2", "y2"] : ["x1", "y1"] : ["x", "y"];
  return keys.map(k => `${game}.${k}`);
}

export const GAME_PRESETS = (Object.keys(GAME_LABEL) as GameId[]).flatMap(game =>
  (game === "survival" ? [1] : [1, 2]).flatMap(players =>
    (game === "race" ? ["x", "angle"] as const : ["depth", "y"] as const).map(style => ({
      id: `${game}-${players}-${style}`, game, players, style,
      label: () => `${GAME_LABEL[game]()} · ${players}P · ${style === "angle" ? t("기울기", "Tilt") : style === "x" ? t("좌우", "Sideways") : style === "depth" ? t("(바닥)", "(Desk)") : t("(영상XY)", "(Video XY)")}`,
    }))),
);
