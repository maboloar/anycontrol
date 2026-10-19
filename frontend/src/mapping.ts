// 매핑 편집용 순수 함수 (백엔드 mapping/schema.py 와 같은 규칙)
import type {
  AxisSuggestion,
  GamepadAxis,
  GamepadButton,
  InputAxis,
  MapInput,
  Mapping,
  MapOutput,
  Profile,
  Transform,
} from "./protocol";
import { gameFns } from "./gameFunctions";
import { labels, t } from "./i18n";

export const INPUT_AXIS_LABEL: Record<InputAxis, string> = labels({
  x: ["좌우", "X"],
  y: ["상하", "Y"],
  depth: ["깊이", "Depth"],
  angle: ["기울기", "Tilt"],
  stretch: ["형태", "Shape"],
  contact: ["바닥선", "Base line"],
  desk_x: ["책상 좌우", "Desk X"],
  desk_z: ["책상 앞뒤", "Desk depth"],
  desk_yaw: ["책상 위 회전", "Desk rotation"],
});

export const PAD_AXIS_LABEL: Record<GamepadAxis, string> = labels({
  left_x: ["왼쪽 스틱 X", "Left stick X"],
  left_y: ["왼쪽 스틱 Y", "Left stick Y"],
  right_x: ["오른쪽 스틱 X", "Right stick X"],
  right_y: ["오른쪽 스틱 Y", "Right stick Y"],
  lt: ["왼쪽 트리거 LT", "Left trigger LT"],
  rt: ["오른쪽 트리거 RT", "Right trigger RT"],
});

export const PAD_BUTTON_LABEL: Record<GamepadButton, string> = {
  a: "A", b: "B", x: "X", y: "Y", lb: "LB", rb: "RB", back: "Back", start: "Start", ls: "LS", rs: "RS",
  up: "↑", down: "↓", left: "←", right: "→", home: "Home",
};

export const MOUSE_LABEL = labels({
  move_x: ["커서 좌우 속도", "Cursor X speed"],
  move_y: ["커서 상하 속도", "Cursor Y speed"],
  scroll: ["스크롤", "Scroll"],
  left: ["왼쪽 버튼", "Left button"],
  right: ["오른쪽 버튼", "Right button"],
});

export const KEY_RE = /^([a-z0-9]|space|enter|tab|escape|backspace|shift|ctrl|alt|meta|arrowup|arrowdown|arrowleft|arrowright|f([1-9]|1[0-2]))$/;

/** 입력 축별 기본 범위 (한 번에 편하게 움직이는 폭, 백엔드 learn.TYPICAL 과 같음) */
export const TYPICAL: Record<InputAxis, number> = {
  x: 0.3, y: 0.3, depth: 0.8, angle: 45, stretch: 0.5, contact: 0.2, desk_x: 0.5, desk_z: 0.5, desk_yaw: 45,
};

export type OutputKind = "bipolar" | "unipolar" | "digital";

export function outputKind(o: MapOutput): OutputKind {
  if (o.target === "gamepad_axis") return o.axis === "lt" || o.axis === "rt" ? "unipolar" : "bipolar";
  if (o.target === "mouse") return o.action === "left" || o.action === "right" ? "digital" : "bipolar";
  if (o.target === "control") return o.kind;
  return "digital";
}

export function inputLabel(i: MapInput): string {
  switch (i.source) {
    case "object":
      return `${i.object} · ${INPUT_AXIS_LABEL[i.axis]}`;
    case "visible":
      return `${i.object} · ${t("보임", "visible")}`;
    case "pen":
      return `${i.object} · ${t("펜촉 닿음", "tip touching")}`;
    case "hand":
      return i.gesture === "x" || i.gesture === "y" ? `${t("손 이동", "Hand motion")} ${i.gesture.toUpperCase()}` : i.gesture === "pinch" ? t("손 · 엄지+검지 집기", "Hand · thumb+index pinch") : t("손 · 엄지+중지 집기", "Hand · thumb+middle pinch");
    case "touch":
      return `${i.object} · ${t("손가락 닿음", "finger touch")}`;
  }
}

export function outputLabel(o: MapOutput): string {
  switch (o.target) {
    case "gamepad_axis":
      return PAD_AXIS_LABEL[o.axis];
    case "gamepad_button":
      return `${t("버튼", "Button")} ${PAD_BUTTON_LABEL[o.button]}`;
    case "key":
      return `${t("키", "Key")} ${o.key}`;
    case "mouse":
      return MOUSE_LABEL[o.action];
    case "control":
      return `${t("데모", "Demo")} ${o.name}`;
  }
}

export function defaultTransform(input: MapInput, output: MapOutput): Transform {
  const kind = outputKind(output);
  const t: Transform = {
    mode: "absolute", range: [-1, 1], invert: false, deadzone: 0.05, curve: "linear", expo: 0.5,
    on: 0.6, off: 0.4, smoothing_ms: 0, on_lost: "center", lost_ms: 300,
  };
  if (input.source === "hand" && (input.gesture === "x" || input.gesture === "y")) {
    t.range = [-.3, .3]; t.on_lost = "release"; t.lost_ms = 0;
  } else if (input.source === "object") {
    const r = TYPICAL[input.axis];
    t.range = kind === "bipolar" ? [-r, r] : [0, r];
  } else {
    t.range = input.source === "hand" && kind === "bipolar" ? [-1, 1] : [0, 1];
    t.deadzone = 0;
  }
  if (kind === "digital") t.on_lost = "release";
  return t;
}

export function newId(existing: string[]): string {
  for (let i = 1; ; i++) {
    const id = `m${i}`;
    if (!existing.includes(id)) return id;
  }
}

export function makeMapping(existing: Mapping[], input: MapInput, output: MapOutput, label = ""): Mapping {
  return {
    id: newId(existing.map((m) => m.id)),
    label,
    enabled: true,
    input,
    output,
    transform: defaultTransform(input, output),
  };
}

/** 출력 종류가 바뀌면 범위가 맞지 않게 된다 (양방향 ↔ 한방향). 입력 축 기본값으로 다시 맞춘다. */
export function withOutput(m: Mapping, output: MapOutput): Mapping {
  const same = outputKind(m.output) === outputKind(output);
  return { ...m, output, transform: same ? m.transform : { ...defaultTransform(m.input, output), mode: m.transform.mode } };
}

export function withInput(m: Mapping, input: MapInput): Mapping {
  const motion = (gesture: string) => gesture === "x" || gesture === "y";
  const sameAxis = m.input.source === input.source &&
    (input.source === "object" ? m.input.source === "object" && m.input.axis === input.axis
      : input.source === "hand" ? m.input.source === "hand" && motion(m.input.gesture) === motion(input.gesture) : true);
  const next = defaultTransform(input, m.output);
  if (input.source !== "hand") { next.on_lost = m.transform.on_lost; next.lost_ms = m.transform.lost_ms; }
  return { ...m, input, transform: sameAxis ? m.transform : next };
}

/** 보여 주며 매핑하기 결과 적용 */
export function applySuggestion(m: Mapping, objectName: string, s: AxisSuggestion): Mapping {
  const input: MapInput = { source: "object", object: objectName, axis: s.axis };
  const kind = outputKind(m.output);
  const t = { ...m.transform, mode: "absolute" as const };
  if (kind === "bipolar") {
    t.range = s.range;
    t.invert = false;
  } else {
    t.range = s.range_positive;
    t.invert = s.invert_for_positive;
  }
  return { ...m, input, transform: t };
}

/** 예시 프로필. 물체 이름을 받아 만든다. */
export function preset(kind: "racing" | "wasd" | "mouse" | "joystick" | "race-stick" | "zombie", obj: string, desk = false): Profile {
  const ms: Mapping[] = [];
  const add = (label: string, input: MapInput, output: MapOutput, tr: Partial<Transform> = {}) => {
    const m = makeMapping(ms, input, output, label);
    m.transform = { ...m.transform, ...tr };
    ms.push(m);
  };
  const ax = (axis: InputAxis): MapInput => ({ source: "object", object: obj, axis });
  if (kind === "racing" || kind === "race-stick" || kind === "zombie") {
    const game = kind === "zombie" ? "survival" : "race";
    for (const f of gameFns(game).filter(f => f.id !== "race-steer2")) {
      const steering = f.id === "race-steer1";
      const axis = steering ? kind === "racing" ? "angle" : "x" : f.axis;
      add(f.label(), ax(desk && axis === "x" ? "desk_x" : desk && axis === "depth" ? "desk_z" : axis), f.output,
        { ...f.transform, ...(steering && axis === "angle" ? { range: [-30, 30] } : {}) });
    }
    return { version: 1, name: game === "race" ? t("레이싱", "Racing") : t("좀비", "Zombies"), description: "", mappings: ms };
  }
  if (kind === "joystick") {
    add(t("좌우 이동", "Move X"), ax(desk ? "desk_x" : "x"), { target: "gamepad_axis", axis: "left_x" }, { range: [-.2, .2] });
    add(t("앞뒤 이동", "Move Y"), ax(desk ? "desk_z" : "depth"), { target: "gamepad_axis", axis: "left_y" }, { range: [-.3, .3], invert: true });
    return { version: 1, name: t("일반 게임패드", "Generic gamepad"), description: "", mappings: ms };
  }
  if (kind === "wasd") {
    add(t("왼쪽 A", "Left A"), ax("x"), { target: "key", key: "a" }, { range: [-0.2, 0], invert: true, deadzone: 0, on: 0.4, off: 0.25 });
    add(t("오른쪽 D", "Right D"), ax("x"), { target: "key", key: "d" }, { range: [0, 0.2], deadzone: 0, on: 0.4, off: 0.25 });
    add(t("앞 W", "Forward W"), ax("depth"), { target: "key", key: "w" }, { range: [0, 0.4], deadzone: 0, on: 0.4, off: 0.25 });
    add(t("뒤 S", "Back S"), ax("depth"), { target: "key", key: "s" }, { range: [-0.4, 0], invert: true, deadzone: 0, on: 0.4, off: 0.25 });
    return { version: 1, name: "WASD", description: t(`${obj} 좌우 이동은 A/D, 앞뒤는 W/S`, `${obj}: left/right = A/D, forward/back = W/S`), mappings: ms };
  }
  add(t("커서 좌우", "Cursor X"), ax("x"), { target: "mouse", action: "move_x" }, { range: [-0.15, 0.15], deadzone: 0.1, curve: "expo", expo: 0.5 });
  add(t("커서 상하", "Cursor Y"), ax("y"), { target: "mouse", action: "move_y" }, { range: [-0.15, 0.15], deadzone: 0.1, curve: "expo", expo: 0.5 });
  add(t("클릭", "Click"), { source: "hand", gesture: "pinch" }, { target: "mouse", action: "left" });
  return { version: 1, name: t("조이스틱 마우스", "Joystick mouse"), description: t(`${obj} 을 조이스틱처럼 기울이면 커서가 그 방향으로 움직임`, `Tilt ${obj} like a joystick to move the cursor that way`), mappings: ms };
}

/** 백엔드와 같은 변환 (미리보기·테스트용) */
export function shape(v: number, t: Transform, kind: OutputKind): number {
  const [lo, hi] = t.range;
  if (kind === "bipolar") {
    const c = (lo + hi) / 2;
    const half = (hi - lo) / 2;
    let n = Math.max(-1, Math.min(1, (v - c) / half));
    if (t.invert) n = -n;
    let a = Math.abs(n);
    a = a <= t.deadzone ? 0 : (a - t.deadzone) / (1 - t.deadzone);
    if (t.curve === "expo") a = (1 - t.expo) * a + t.expo * a ** 3;
    return Math.sign(n) * a;
  }
  let n = Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
  if (t.invert) n = 1 - n;
  n = n <= t.deadzone ? 0 : (n - t.deadzone) / (1 - t.deadzone);
  if (t.curve === "expo") n = (1 - t.expo) * n + t.expo * n ** 3;
  return n;
}
