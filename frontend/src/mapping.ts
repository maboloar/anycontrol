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

export const INPUT_AXIS_LABEL: Record<InputAxis, string> = {
  x: "좌우",
  y: "상하",
  depth: "깊이",
  angle: "기울기",
  stretch: "형태",
  contact: "바닥선",
  desk_x: "책상 좌우",
  desk_z: "책상 앞뒤",
  desk_yaw: "책상 위 회전",
};

export const PAD_AXIS_LABEL: Record<GamepadAxis, string> = {
  left_x: "왼쪽 스틱 X",
  left_y: "왼쪽 스틱 Y",
  right_x: "오른쪽 스틱 X",
  right_y: "오른쪽 스틱 Y",
  lt: "왼쪽 트리거 LT",
  rt: "오른쪽 트리거 RT",
};

export const PAD_BUTTON_LABEL: Record<GamepadButton, string> = {
  a: "A", b: "B", x: "X", y: "Y", lb: "LB", rb: "RB", back: "Back", start: "Start", ls: "LS", rs: "RS",
  up: "↑", down: "↓", left: "←", right: "→", home: "Home",
};

export const MOUSE_LABEL = {
  move_x: "커서 좌우 속도",
  move_y: "커서 상하 속도",
  scroll: "스크롤",
  left: "왼쪽 버튼",
  right: "오른쪽 버튼",
} as const;

export const KEY_RE = /^([a-z0-9]|space|enter|tab|escape|backspace|shift|ctrl|alt|meta|arrowup|arrowdown|arrowleft|arrowright|f([1-9]|1[0-2]))$/;

/** 입력 축별 기본 범위 (한 번에 편하게 움직이는 폭, 백엔드 learn.TYPICAL 과 같음) */
export const TYPICAL: Record<InputAxis, number> = {
  x: 0.3, y: 0.3, depth: 0.8, angle: 45, stretch: 0.5, contact: 0.2, desk_x: 0.5, desk_z: 0.5, desk_yaw: 45,
};

export type OutputKind = "bipolar" | "unipolar" | "digital";

export function outputKind(o: MapOutput): OutputKind {
  if (o.target === "gamepad_axis") return o.axis === "lt" || o.axis === "rt" ? "unipolar" : "bipolar";
  if (o.target === "mouse") return o.action === "left" || o.action === "right" ? "digital" : "bipolar";
  return "digital";
}

export function inputLabel(i: MapInput): string {
  switch (i.source) {
    case "object":
      return `${i.object} · ${INPUT_AXIS_LABEL[i.axis]}`;
    case "visible":
      return `${i.object} · 보임`;
    case "pen":
      return `${i.object} · 펜촉 닿음`;
    case "hand":
      return i.gesture === "pinch" ? "손 · 엄지+검지 집기" : "손 · 엄지+중지 집기";
  }
}

export function outputLabel(o: MapOutput): string {
  switch (o.target) {
    case "gamepad_axis":
      return PAD_AXIS_LABEL[o.axis];
    case "gamepad_button":
      return `버튼 ${PAD_BUTTON_LABEL[o.button]}`;
    case "key":
      return `키 ${o.key}`;
    case "mouse":
      return MOUSE_LABEL[o.action];
  }
}

export function defaultTransform(input: MapInput, output: MapOutput): Transform {
  const kind = outputKind(output);
  const t: Transform = {
    mode: "absolute", range: [-1, 1], invert: false, deadzone: 0.05, curve: "linear", expo: 0.5,
    on: 0.6, off: 0.4, smoothing_ms: 0, on_lost: "center", lost_ms: 300,
  };
  if (input.source === "object") {
    const r = TYPICAL[input.axis];
    t.range = kind === "bipolar" ? [-r, r] : [0, r];
  } else {
    t.range = [0, 1];
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
  const sameAxis =
    m.input.source === input.source &&
    (input.source !== "object" || (m.input.source === "object" && m.input.axis === input.axis));
  return { ...m, input, transform: sameAxis ? m.transform : defaultTransform(input, m.output) };
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
  if (kind === "zombie") {
    add("충격파", { source: "hand", gesture: "pinch" }, { target: "gamepad_button", button: "a" });
    return { version: 1, name: "좀비 위치 대응", description: "물체 마우스 위치 = 캐릭터 위치 · 엄지+검지 = 충격파", mappings: ms };
  }
  if (kind === "joystick" || kind === "race-stick") {
    add("좌우 이동", ax(desk ? "desk_x" : "x"), { target: "gamepad_axis", axis: "left_x" }, { range: [-.2, .2], deadzone: .08, curve: "expo", expo: .25 });
    if (kind === "joystick") {
      add("앞뒤 이동", ax(desk ? "desk_z" : "depth"), { target: "gamepad_axis", axis: "left_y" }, { range: [-.3, .3], invert: true, deadzone: .08, curve: "expo", expo: .25 });
      add("충격파", { source: "hand", gesture: "pinch" }, { target: "gamepad_button", button: "a" });
    } else {
      add("가속", ax("depth"), { target: "gamepad_axis", axis: "rt" }, { range: [0, .4] });
      add("브레이크", ax("depth"), { target: "gamepad_axis", axis: "lt" }, { range: [-.4, 0], invert: true });
    }
    return { version: 1, name: kind === "joystick" ? "게임 조이스틱" : "레이싱 좌우 조향", description: "중립에서 움직인 거리만큼 부드럽게 조작", mappings: ms };
  }
  if (kind === "racing") {
    add("조향", ax("angle"), { target: "gamepad_axis", axis: "left_x" }, { range: [-45, 45], deadzone: 0.03, curve: "expo", expo: 0.3 });
    add("가속", ax("depth"), { target: "gamepad_axis", axis: "rt" }, { range: [0, 0.4], deadzone: 0.05 });
    add("브레이크", ax("depth"), { target: "gamepad_axis", axis: "lt" }, { range: [-0.4, 0], invert: true, deadzone: 0.05 });
    return { version: 1, name: "레이싱", description: `${obj} 을 핸들처럼 돌려 조향, 앞으로 밀면 가속, 당기면 브레이크`, mappings: ms };
  }
  if (kind === "wasd") {
    add("왼쪽 A", ax("x"), { target: "key", key: "a" }, { range: [-0.2, 0], invert: true, deadzone: 0, on: 0.4, off: 0.25 });
    add("오른쪽 D", ax("x"), { target: "key", key: "d" }, { range: [0, 0.2], deadzone: 0, on: 0.4, off: 0.25 });
    add("앞 W", ax("depth"), { target: "key", key: "w" }, { range: [0, 0.4], deadzone: 0, on: 0.4, off: 0.25 });
    add("뒤 S", ax("depth"), { target: "key", key: "s" }, { range: [-0.4, 0], invert: true, deadzone: 0, on: 0.4, off: 0.25 });
    return { version: 1, name: "WASD", description: `${obj} 좌우 이동은 A/D, 앞뒤는 W/S`, mappings: ms };
  }
  add("커서 좌우", ax("x"), { target: "mouse", action: "move_x" }, { range: [-0.15, 0.15], deadzone: 0.1, curve: "expo", expo: 0.5 });
  add("커서 상하", ax("y"), { target: "mouse", action: "move_y" }, { range: [-0.15, 0.15], deadzone: 0.1, curve: "expo", expo: 0.5 });
  add("클릭", { source: "hand", gesture: "pinch" }, { target: "mouse", action: "left" });
  return { version: 1, name: "조이스틱 마우스", description: `${obj} 을 조이스틱처럼 기울이면 커서가 그 방향으로 움직임`, mappings: ms };
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
