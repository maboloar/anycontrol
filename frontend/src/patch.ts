// 패치 케이블 매핑: 데모 기능 잭과 물체 잭을 선으로 이으면 매핑 하나가 생긴다 (가상 신디사이저처럼).
// 기능 잭 하나에는 선 하나만 꽂힌다 (새 물체를 이으면 예전 선은 빠진다). 물체 잭에는 여러 선을 꽂을 수 있다.
import { GAME_FNS } from "./gameFunctions";
import { makeMapping, outputKind, PAD_AXIS_LABEL, PAD_BUTTON_LABEL, MOUSE_LABEL, TYPICAL } from "./mapping";
import type { InputAxis, MapInput, Mapping, MapOutput, Profile, Transform } from "./protocol";
import { t } from "./i18n";

export interface PatchFn {
  id: string;
  control?: string; // named game function; output is a real virtual gamepad channel
  label: () => string;
  /** 물체를 어떻게 움직이면 되는지 */
  hint: () => string;
  output: MapOutput;
  axis: InputAxis;
  transform: Partial<Transform>;
  /** 입력 종류: axis = 물체 축(기본), touch = 손가락이 물체에 닿음 */
  input?: "axis" | "touch" | "visible" | "pen";
  /** 사용자가 만든 잭이면 true (편집·삭제 가능) */
  custom?: boolean;
  handGesture?: Extract<MapInput, { source: "hand" }>["gesture"];
}

/** 사용자가 만든 잭 (localStorage). 이름·출력·입력을 정해 패치 베이에 추가한다. */
export interface CustomJack { id: string; label: string; output: MapOutput; input: "axis" | "touch" | "visible" | "pen"; axis: InputAxis; handGesture?: Extract<MapInput, { source: "hand" }>["gesture"]; transform?: Transform }
const CUSTOM_KEY = "anycontrol.customJacks";
export function loadCustomJacks(): CustomJack[] {
  try { const v = JSON.parse(localStorage.getItem(CUSTOM_KEY) ?? "[]"); return Array.isArray(v) ? v : []; } catch { return []; }
}
export function saveCustomJacks(list: CustomJack[]): void {
  try { localStorage.setItem(CUSTOM_KEY, JSON.stringify(list)); } catch { /* 이번 화면에서만 */ }
  window.dispatchEvent(new Event("anycontrol.custom-jacks.changed"));
}
export function customFn(c: CustomJack): PatchFn {
  const digital = c.output.target === "gamepad_button" || c.output.target === "key" || (c.output.target === "mouse" && (c.output.action === "left" || c.output.action === "right"));
  const r = TYPICAL[c.axis];
  return { id: c.id, label: () => c.label, hint: () => c.input === "touch" ? t("손가락 닿음", "Finger touch") : t("물체 움직임", "Object movement"),
    output: c.output, axis: c.axis, input: c.input, custom: true, handGesture: c.handGesture,
    transform: c.transform ?? (c.input === "touch" ? { range: [0, 1], deadzone: 0 } : digital ? { range: [0, r * 0.5], deadzone: 0, on: 0.6, off: 0.35 } : { range: [-r * 0.6, r * 0.6], deadzone: 0.05 }) };
}

/** 다른 데모(DJ 등)가 자기 잭을 등록한다. 매핑 해석(fnOf)에 쓰인다. */
const extraFns = new Map<string, PatchFn[]>();
export function registerFns(group: string, fns: PatchFn[]): void { extraFns.set(group, fns); }
export function unregisterFns(group: string): void { extraFns.delete(group); }
export function allFns(): PatchFn[] {
  return [...PATCH_FNS, ...GAME_FNS, ...[...extraFns.values()].flat(), ...loadCustomJacks().map(customFn)];
}

// 물체 위로 들기 = 누름: y 는 아래가 + 이므로 [-0.12, 0] 범위를 뒤집는다
const LIFT: Partial<Transform> = { range: [-0.12, 0], invert: true, deadzone: 0, on: 0.6, off: 0.35 };

export const PATCH_FNS: PatchFn[] = [
  { id: "steer", label: () => t("일반 스틱 X", "Generic stick X"), hint: () => t("물체를 좌우로", "Move left/right"),
    output: { target: "gamepad_axis", axis: "left_x" }, axis: "x", transform: { range: [-0.2, 0.2], deadzone: 0.08, curve: "expo", expo: 0.25 } },
  { id: "forward", label: () => t("일반 스틱 Y", "Generic stick Y"), hint: () => t("물체를 앞뒤로", "Push/pull"),
    output: { target: "gamepad_axis", axis: "left_y" }, axis: "depth", transform: { range: [-0.3, 0.3], invert: true, deadzone: 0.08, curve: "expo", expo: 0.25 } },
  { id: "gas", label: () => t("일반 트리거 RT", "Generic trigger RT"), hint: () => t("카메라 쪽으로 밀기", "Push toward camera"),
    output: { target: "gamepad_axis", axis: "rt" }, axis: "depth", transform: { range: [0, 0.4], deadzone: 0.05 } },
  { id: "brake", label: () => t("일반 트리거 LT", "Generic trigger LT"), hint: () => t("뒤로 당기기", "Pull back"),
    output: { target: "gamepad_axis", axis: "lt" }, axis: "depth", transform: { range: [-0.4, 0], invert: true, deadzone: 0.05 } },
  { id: "button-a", label: () => t("A 버튼", "A button"), hint: () => t("위로 들기", "Lift up"),
    output: { target: "gamepad_button", button: "a" }, axis: "y", transform: LIFT },
  { id: "space", label: () => t("스페이스 키", "Space key"), hint: () => t("위로 들기", "Lift up"),
    output: { target: "key", key: "space" }, axis: "y", transform: LIFT },
  { id: "click", label: () => t("마우스 클릭", "Mouse click"), hint: () => t("위로 들기", "Lift up"),
    output: { target: "mouse", action: "left" }, axis: "y", transform: LIFT },
];

export function sameOutput(a: MapOutput, b: MapOutput): boolean {
  const key = (v: MapOutput) => JSON.stringify(Object.entries(v).sort(([a], [b]) => a.localeCompare(b)));
  return key(a) === key(b);
}

/** 매핑이 어느 기능 잭에 꽂힌 선인지 (물체 입력이고 출력이 같은 잭). 아니면 null */
export function fnOf(m: Mapping, fns: PatchFn[] = allFns()): PatchFn | null {
  const matches = fns.filter(f => sameOutput(f.output, m.output));
  return matches.find(f => f.label() === m.label) ?? matches[0] ?? null;
}

/** Derive missing jacks from the profile itself, so row edits/load/reset stay in sync. */
export function inferredFns(p: Profile, known: PatchFn[]): PatchFn[] {
  const out: PatchFn[] = [];
  for (const m of p.mappings) {
    if (fnOf(m, [...known, ...out])) continue;
    const o = m.output;
    const label = m.label || (o.target === "gamepad_axis" ? PAD_AXIS_LABEL[o.axis] : o.target === "gamepad_button" ? PAD_BUTTON_LABEL[o.button] : o.target === "key" ? o.key : o.target === "mouse" ? MOUSE_LABEL[o.action] : o.name);
    const axis = m.input.source === "object" ? m.input.axis : m.input.source === "hand" && m.input.gesture === "x" ? "x" : "y";
    out.push({ id: `auto-${encodeURIComponent(JSON.stringify(Object.entries(o).sort(([a], [b]) => a.localeCompare(b))))}`, label: () => label, hint: () => t("매핑에서 추가됨", "Added in mappings"), output: o, axis,
      input: m.input.source === "touch" || m.input.source === "visible" || m.input.source === "pen" ? m.input.source : "axis", transform: m.transform });
  }
  return out;
}

export interface Cable { id: string; object: string; fn: string }

export function cables(p: Profile, fns: PatchFn[] = allFns()): Cable[] {
  return p.mappings.flatMap((m) => {
    const f = fnOf(m, fns);
    return f ? [{ id: m.id, object: m.input.source === "hand" ? "@hand" : "object" in m.input ? m.input.object : "", fn: f.id }] : [];
  });
}

/** 물체 → 기능 잭 연결. 그 잭에 꽂혀 있던 선(같은 출력)은 모두 빼고 새 선 하나를 꽂는다. */
export function connect(p: Profile, object: string, fnId: string): Profile {
  const f = allFns().find((x) => x.id === fnId);
  if (!f) return p;
  const rest = p.mappings.filter((m) => !sameOutput(m.output, f.output));
  const input: MapInput = object === "@hand" ? { source: "hand", gesture: f.handGesture ?? (outputKind(f.output) === "digital" ? "pinch" : f.axis === "x" ? "x" : "y") } : (f.input === "touch" || f.input === "visible" || f.input === "pen") ? { source: f.input, object } : { source: "object", object, axis: f.axis };
  const m = makeMapping(rest, input, f.output, f.label());
  m.transform = object === "@hand" ? { ...m.transform, range: input.source === "hand" && (input.gesture === "x" || input.gesture === "y") ? [-.3, .3] : outputKind(f.output) === "bipolar" ? [-1, 1] : [0, 1], deadzone: 0, on: .6, off: .35, on_lost: "release", lost_ms: 0 } : { ...m.transform, ...f.transform };
  if (object === "@hand" && f.custom && f.handGesture) m.transform = { ...m.transform, ...f.transform };
  return { ...p, mappings: [...rest, m] };
}

export function disconnect(p: Profile, mappingId: string): Profile {
  return { ...p, mappings: p.mappings.filter((m) => m.id !== mappingId) };
}
