// 백엔드 vision_input/server/protocol.py 와 같은 형식.
export const PROTOCOL_VERSION = 1;
export const HEADER_SIZE = 24;
const MAGIC = [0x56, 0x49, 0x46, 0x31]; // "VIF1"
const KIND_PREVIEW = 1;

export interface PreviewHeader {
  seq: number;
  tWallMs: number;
  width: number;
  height: number;
  flags: number;
}

export function parsePreview(buf: ArrayBuffer): { header: PreviewHeader; jpeg: Uint8Array<ArrayBuffer> } {
  if (buf.byteLength < HEADER_SIZE) throw new Error("buffer shorter than header");
  const v = new DataView(buf);
  for (let i = 0; i < 4; i++) if (v.getUint8(i) !== MAGIC[i]) throw new Error("bad magic");
  const ver = v.getUint8(4);
  const kind = v.getUint8(5);
  if (ver !== PROTOCOL_VERSION || kind !== KIND_PREVIEW) throw new Error(`unsupported version/kind ${ver}/${kind}`);
  const header: PreviewHeader = {
    flags: v.getUint16(6, true),
    seq: v.getUint32(8, true),
    tWallMs: v.getFloat64(12, true),
    width: v.getUint16(20, true),
    height: v.getUint16(22, true),
  };
  return { header, jpeg: new Uint8Array(buf, HEADER_SIZE) };
}

export interface Envelope<T = unknown> {
  v: number;
  type: string;
  data: T;
}

export function parseMessage(text: string): Envelope<Record<string, unknown>> {
  const obj: unknown = JSON.parse(text);
  if (typeof obj !== "object" || obj === null) throw new Error("invalid envelope");
  const e = obj as Partial<Envelope>;
  if (e.v !== PROTOCOL_VERSION || typeof e.type !== "string") throw new Error("invalid envelope");
  const data = e.data ?? {};
  if (typeof data !== "object" || data === null || Array.isArray(data)) throw new Error("data must be an object");
  return { v: e.v, type: e.type, data: data as Record<string, unknown> };
}

export function encodeMessage(type: string, data: Record<string, unknown> = {}): string {
  return JSON.stringify({ v: PROTOCOL_VERSION, type, data });
}

// ---- 텔레메트리 타입 (백엔드 Engine.telemetry) ----
export interface Quantiles {
  p50: number | null;
  p95: number | null;
  max: number | null;
  n: number;
}
export interface Rate {
  fps: number | null;
  interval_ms: Quantiles;
}
export interface SourceInfo {
  kind: "camera" | "synthetic" | "file";
  status: "idle" | "running" | "error" | "ended" | "off";
  error: string | null;
  size: [number, number] | null;
  rate: Rate;
  dropped: number;
  name?: string | null;
  index?: number;
  active_fps?: number | null;
  pts_lag_ms?: number | null;
  late_drops?: number;
  requested?: { width: number; height: number; fps: number };
  mirror?: boolean;
  paused?: boolean;
  enabled?: boolean;
  desk_view?: boolean;
  device_id?: string | null;
  parent_id?: string | null;
}
export interface Telemetry {
  t_wall_ms: number;
  source: SourceInfo | null;
  engine: { proc_ms: Quantiles; age_ms: Quantiles; rate: Rate; frames: number };
  preview: { encode_ms: Quantiles; rate: Rate; kb_per_frame: number | null };
  clients: number;
}

export interface CameraDevice {
  index: number;
  name: string;
  unique_id: string;
  model: string;
  is_continuity: boolean;
  is_desk_view?: boolean;
  companion_id?: string | null;
  parent_id?: string | null;
  formats: { width: number; height: number; max_fps: number }[];
}

// ---- 물체 상태 (백엔드 VisionProcessor.object_info) ----
export type TrackStateName = "tracking" | "grasped" | "occluded" | "searching" | "lost";
export const AXIS_NAMES = ["x", "y", "depth", "angle", "stretch", "contact"] as const;
export type AxisName = (typeof AXIS_NAMES)[number];

export interface ObjectInfo {
  id: number;
  name: string;
  color: string;
  state: TrackStateName;
  confidence: number;
  kind: "object" | "pen";
  box: [number, number, number, number] | null; // 0..1
  contour: [number, number][]; // 0..1
  axes: Record<AxisName, number | null>;
  texture: number;
  contrast: number;
  warnings: string[];
  candidates: number;
  candidate_index: number;
  debug: Record<string, number | string | boolean>;
}

export interface VisionState {
  seq: number;
  size: [number, number] | null;
  objects: ObjectInfo[];
}

// ---- 마우스·손·펜 (백엔드 pipeline.process) ----
export type MouseMode = "off" | "hand" | "object";

export interface MouseEvent {
  type: "down" | "up";
  button: "left" | "right";
  x: number;
  y: number;
}

export interface MouseState {
  mode: MouseMode;
  desk_view?: boolean;
  hand_visible?: boolean;
  cursor_active?: boolean;
  touching?: boolean;
  surface_mode?: "quad" | "line" | "deskview" | null;
  /** 깊이 커서가 쓴 신호: desk = 종이(책상 면) 좌표, size = 크기 기반 */
  depth_source?: "desk" | "size";
  /** 이번 프레임에 크기 기반 원근 보정을 썼나 */
  perspective_active?: boolean;
  gesture?: "move" | "left" | "right" | "scroll" | "none" | "pen" | "object-tap";
  freeze?: boolean;
  pinch_index?: number | null;
  pinch_middle?: number | null;
  pinch_on?: number;
  x: number;
  y: number;
  left: boolean;
  right: boolean;
  scroll: number;
  events: MouseEvent[];
}

export interface HandInfo {
  points: [number, number][]; // 0..1
  handedness: string;
  score: number;
}

export interface PenState {
  shadow_assist?: boolean;
  shadow_veto?: boolean;
  desk_near?: number | null;
  draw_point?: [number, number] | null; // 획과 동일한 책상 좌표, 비접촉 중에도 제공
  tip: [number, number] | null; // 처리 해상도 px
  axis: [number, number] | null;
  contact: boolean;
  uncertain?: boolean;
  desk_view?: boolean;
  contact_mode?: 'auto' | 'manual';
  contact_score?: number | null;
  touch_samples?: number;
  lift_samples?: number;
  height: number | null;
  calibrated: boolean;
  manual_calibration: boolean;
  samples: number;
  horizon: number;
  settings?: { touch_on: number; touch_off: number; tip_min_cutoff: number; tip_beta: number;
    edge_span: number; refined_max_age: number; desk_contact_margin?: number };
  current: [number, number][] | null;
  stroke_count: number;
  events: { type: "down" | "up" | "clear"; stroke?: [number, number][] | null }[];
  debug: Record<string, string | number | boolean | null>;
}

export interface HandDrawingState {
  enabled: boolean;
  hand_visible: boolean;
  contact: boolean;
  point: [number, number] | null;
  pinch_index: number | null;
  current: [number, number][] | null;
  stroke_count: number;
  events: { type: "down" | "up" | "clear"; stroke?: [number, number][] | null }[];
  error?: string | null;
}

export interface RealInfo {
  state: 'off' | 'arming' | 'on'; remaining_s: number | null; trusted: boolean;
  stopped_by: string | null; supports: string[];
}

export interface FrameState extends VisionState {
  real?: RealInfo;
  input_mirror?: boolean;
  auto_calibration?: AutoCalibrationState | null;
  paused?: boolean;
  calibration?: { calibrated: boolean; mode?: "quad" | "line" | "deskview" | null;
    quad?: [number, number][]; line?: [number, number][]; tilt?: number; yaw_ok?: boolean };
  mouse?: MouseState;
  hands?: HandInfo[];
  pens?: Record<string, PenState>;
  hand_drawing?: HandDrawingState;
  controller?: ControllerOut;
  mapping?: { live: MappingLive[]; computed: ControllerComputed };
}

// ---- 매핑 (백엔드 vision_input/mapping/schema.py) ----
export const GAMEPAD_AXES = ["left_x", "left_y", "right_x", "right_y", "lt", "rt"] as const;
export type GamepadAxis = (typeof GAMEPAD_AXES)[number];
export const GAMEPAD_BUTTONS = [
  "a", "b", "x", "y", "lb", "rb", "back", "start", "ls", "rs", "up", "down", "left", "right", "home",
] as const;
export type GamepadButton = (typeof GAMEPAD_BUTTONS)[number];
export const INPUT_AXES = [...AXIS_NAMES, "desk_x", "desk_z", "desk_yaw"] as const;
export type InputAxis = (typeof INPUT_AXES)[number];

export type MapInput =
  | { source: "object"; object: string; axis: InputAxis }
  | { source: "visible"; object: string }
  | { source: "pen"; object: string }
  | { source: "hand"; gesture: "pinch" | "pinch_middle" };

export type MapOutput =
  | { target: "gamepad_axis"; axis: GamepadAxis }
  | { target: "gamepad_button"; button: GamepadButton }
  | { target: "key"; key: string }
  | { target: "mouse"; action: "move_x" | "move_y" | "scroll" | "left" | "right" };

export interface Transform {
  mode: "absolute" | "velocity";
  range: [number, number];
  invert: boolean;
  deadzone: number;
  curve: "linear" | "expo";
  expo: number;
  on: number;
  off: number;
  smoothing_ms: number;
  on_lost: "hold" | "center" | "release";
  lost_ms: number;
}

export interface Mapping {
  id: string;
  label: string;
  enabled: boolean;
  input: MapInput;
  output: MapOutput;
  transform: Transform;
}

export interface Profile {
  version: 1;
  name: string;
  description: string;
  mappings: Mapping[];
}

export type OutputMode = "observe" | "send";

export interface MappingInfo {
  profile: Profile;
  mode: OutputMode;
  warnings: string[];
  hands_available: boolean;
}

export interface MappingLive {
  id: string;
  raw: number | null;
  value: number;
  active: boolean;
}

export interface ControllerComputed {
  axes: Record<GamepadAxis, number>;
  buttons: Record<GamepadButton, boolean>;
  keys: string[];
  mouse: { move: [number, number]; scroll: number; left: boolean; right: boolean };
}

/** 실제로 가상 싱크에 나간 값 (observe 모드면 중립) */
export interface ControllerOut {
  mode: OutputMode;
  axes: Record<GamepadAxis, number>;
  buttons: Record<GamepadButton, boolean>;
  keys: string[];
  key_events: { type: "down" | "up"; key: string }[];
}

export interface AxisSuggestion {
  axis: InputAxis;
  score: number;
  range: [number, number];
  range_positive: [number, number];
  invert_for_positive: boolean;
}

export interface ProfileSummary {
  name: string;
  description: string;
  mappings: number;
  modified: number;
}

export interface MouseSettings {
  mode: MouseMode;
  object_id: number | null;
  mirror: boolean;
  hand_region: [number, number, number, number];
  object_region: [number, number, number, number];
  hand_clicks: boolean;
  object_tap: boolean;
  object_tap_distance: number;
  smoothing: number;
  pinch_on: number;
  hand_control: "depth" | "touchpad" | "air";
  coordinate_mode: "depth" | "image";
  depth_sensitivity: number;
  depth_gain: number;
  depth_deadzone?: number;
  touch_sensitivity: number;
  touch_height: number;
  touch_margin: number;
  touch_depth_blend: number;
  touch_depth_gain?: number;
  touch_deadzone: number;
  scroll_gain: number;
  invert_y: boolean;
  /** 축별 감도 (0.2–5). 좌우 반전은 mirror, 상하 반전은 invert_y */
  sens_x: number;
  sens_y: number;
  /** 크기 기반 깊이 원근 보정: 가장자리에서 앞뒤로 움직일 때 사선으로 새는 좌우 이동을 뺀다 */
  depth_perspective: boolean;
  /** 종이(책상 4점) 보정이 있으면 깊이 커서를 책상 면 좌표로 계산 */
  desk_correct: boolean;
  invert_scroll: boolean;
  pen_relative: boolean;
  pen_sensitivity: number;
  pen_depth_blend: number;
  pen_depth_gain?: number;
  pen_deadzone?: number;
}

export type AutoCalibrationKind = 'hand' | 'object' | 'pen';
export interface AutoCalibrationState {
  id: string;
  kind: AutoCalibrationKind;
  object_id: number | null;
  phase: 'ready' | 'recording' | 'review' | 'complete' | 'cancelled';
  index: number;
  total: number;
  completed: number;
  skipped?: { key: string; title: string; reason: string }[];
  attempts_failed?: number;
  step: { key: string; title: string; instruction: string; duration: number };
  progress: number;
  samples: number;
  error: string | null;
  feedback?: { level: 'good' | 'warn' | 'waiting'; message: string; cycles: number | null } | null;
  result: { mouse: Partial<MouseSettings>; pen: Record<string, number>; notes: string[];
    summary: string[]; metrics: Record<string, number> } | null;
}

export interface MouseInfo {
  settings: MouseSettings;
  status: Partial<MouseState>;
  hands_available: boolean;
  hands_running: boolean;
  hands_error: string | null;
  /** 손 인식 엔진: vision(Apple Vision, 기본) | mediapipe */
  hand_backend?: HandBackend | null;
  hand_backends?: HandBackend[];
}
export type HandBackend = "vision" | "mediapipe";

export const HAND_CONNECTIONS: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [0, 17], [17, 18], [18, 19], [19, 20],
];
