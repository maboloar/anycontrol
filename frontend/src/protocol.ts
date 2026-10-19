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
  /** 커서를 움직이는 기준점: 물체 바닥 아래-가운데 (0..1). 보이지 않는 동안 null */
  anchor?: [number, number] | null;
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
  cursor_source?: "object" | "hand";
  hybrid?: boolean;
  hybrid_pending?: "object" | "hand" | null;
  hybrid_armed?: boolean;
  hybrid_gap?: number | null;
  touching?: boolean;
  surface_mode?: "quad" | "line" | "deskview" | null;
  /** 깊이 커서가 쓴 신호: desk = 종이(책상 면) 좌표, size = 크기 기반 */
  depth_source?: "desk" | "size" | "model";
  /** 이번 프레임에 크기 기반 원근 보정을 썼나 */
  perspective_active?: boolean;
  tip_mode?: boolean;
  tip_debug?: Record<string, { moved: number; gap: number; armed: boolean; rest: boolean }> | null;
  gesture?: "move" | "left" | "right" | "scroll" | "none" | "pen" | "object-tap" | "approach";
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

/** 물체 기억 (GET /api/objects/{id}/memory). 놓쳤을 때 복귀에 쓰는 기억을 그림으로 보여 준다. */
export interface MemorySnapshot {
  kind: 'registration' | 'anchor' | 'reacquired';
  t: number;
  age_s: number;
  image: string; // data URI (물체 바깥 어둡게 + 마스크 윤곽)
  info: Record<string, number | string | null>;
}
export interface ObjectMemory {
  id: number;
  name: string;
  color: string;
  state: string;
  lost_for_s: number | null;
  snapshots: MemorySnapshot[];
  shape: { template: string; elongation: number; area: number; hu: number[]; palette: { hex: string; weight: number }[] } | null;
  tier1: { anchors: number; recent: number; max_anchors: number | null } | null;
  still?: { locked: boolean; locks: number; committed: number; releases: Record<string, number>; rejected: Record<string, number> } | null;
  reacquire: { enabled: boolean; last: string | null; searches: number; recovered: number;
    thresholds: { iou: number; hu: number; color: number } };
}

/** 바닥 그라데이션 맵 (GET /api/objects/{id}/pen/floor-map, 개발자 보기). 가까움=밝음, 멈=어둠. */
/** 깊이 모델로 잰 카메라 롤을 바닥 평면 기울기로 쓰는 상태 (펜 기본 설정). */
export interface DepthRollInfo {
  enabled: boolean; available: boolean;
  deg: number | null;       // 깊이 모델이 잰 롤 (도). 아직 믿을 만하지 않으면 null
  n: number;                // 지금까지 잰 횟수 (최근 7개)
  applied: boolean;         // 평면 기울기를 이 값으로 고정했는가
  a: number | null;         // 평면의 좌우 기울기 (px)
  source: 'depth' | 'touch';
  error: string | null;
}
export interface FloorMapData {
  depth_roll?: DepthRollInfo | null;
  ready: boolean;
  reason?: 'contact_method' | 'learning' | 'no_table_color' | 'no_floor' | 'no_frame';
  size?: [number, number];
  k?: number | null; c?: number | null; a?: number; sigma?: number | null;
  samples?: number; anchors?: number; roll_deg?: number | null; valid_frac?: number; w_range?: [number, number];
  learning?: number;
  image?: string;     // 불투명 PNG (등고선 포함)
  overlay?: string;   // 알파가 있는 PNG (카메라 영상 위에 겹친다)
  tip?: [number, number] | null;  // 펜촉 위치 (프레임 대비 0..1, 처리 좌표)
  hover?: number | null;          // 펜 지름 단위 높이 (0 = 닿음)
  contact?: boolean;
}

/** 깊이 모델 비교 실험 (개발자 모드). 접촉 판정에는 쓰이지 않는다. */
export interface DepthModelStatus {
  available: boolean; downloading: boolean; error: string | null;
  downloaded_mb: number; size_mb: number; license: string; source: string; path: string;
}
export interface DepthCompareData {
  ready: boolean;
  reason?: 'model_missing' | 'no_frame' | 'contact_method' | 'learning' | 'no_floor';
  size?: [number, number]; ms?: number | null;
  depth_image?: string; fit_image?: string; touch_image?: string;
  plane_rms?: number; inlier_frac?: number;
  corr?: number | null; angle_deg?: number; roll_depth_deg?: number; roll_touch_deg?: number;
}

/** Depth Anything 깊이 맵 (GET /api/dev/depth-map, 개발자 보기). 가까움=밝음. */
export interface DepthMapData {
  ready: boolean; reason?: 'model_missing' | 'no_frame' | 'computing' | 'disabled' | 'invalid';
  fg_frac?: number | null;   // 배경 모델 보기: 전경 비율 (무효면 null)
  grid?: { cols: number; rows: number; known: number; changed: number } | null;   // 무효 판정 격자
  info?: { valid: boolean; changed: number; shift: number[]; gain: number; depth: boolean; unstable_frac?: number; [k: string]: unknown };
  age?: number; ms?: number | null; size?: [number, number];
  image?: string;     // 불투명 PNG
  overlay?: string;   // 카메라 영상 위에 겹칠 반투명 PNG
  error?: string | null;
}

export interface PenFloorState {
  h_s?: number | null;      // 평활 hover (펜 지름 단위, 0 = 닿음)
  base?: number | null;     // 접촉 baseline
  lift_delta?: number;
  sigma?: number | null;    // 바닥 모델이 스스로 잰 접촉 잡음
  shadow?: 'gap' | 'attached' | null;
  shadow_light?: boolean;   // 직사광(그림자 단서 사용 가능)
  edge?: [number, number] | null; // 책상 먼 모서리 y = a·x + b (처리 해상도 px)
  holding?: boolean;        // 분할 탈락 중 접촉 유지
  samples?: number;
  reason?: string;
}

/** 펜 뼈대 (처리 해상도 px): 곧은 막대로 다시 맞춘 선. 손에 가려진 구간은 hidden. */
export interface PenSkeleton {
  tip: [number, number]; tail: [number, number];
  state: 'seen' | 'middle_hidden' | 'tip_hidden' | 'tail_hidden';
  evidence: '' | 'occluder' | 'skin';
  visible: [[number, number], [number, number]][];
  hidden: [[number, number], [number, number]][];
}
export interface PenState {
  skeleton?: PenSkeleton | null;
  contact_method?: 'legacy' | 'floor';
  pressed?: boolean;
  floor?: PenFloorState | null;
  depth_roll?: DepthRollInfo | null;
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
  tips?: Record<string, TipInfo>;
  pens?: Record<string, PenState>;
  hand_drawing?: HandDrawingState;
  controller?: ControllerOut;
  mapping?: { live: MappingLive[]; computed: ControllerComputed };
  /** 물체 터치 (매핑이 터치 입력을 쓸 때): 물체 id → 닿음·닿은 손끝 */
  touch?: Record<string, { on: boolean; point: [number, number] | null; occluded?: number; skin?: number; reason?: string;
    box?: [number, number, number, number] | null; min_change?: number }>;
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
  | { source: "hand"; gesture: "pinch" | "pinch_middle" | "x" | "y" }
  | { source: "touch"; object: string };

export type MapOutput =
  | { target: "gamepad_axis"; axis: GamepadAxis }
  | { target: "gamepad_button"; button: GamepadButton }
  | { target: "key"; key: string }
  | { target: "mouse"; action: "move_x" | "move_y" | "scroll" | "left" | "right" }
  | { target: "control"; name: string; kind: "bipolar" | "unipolar" | "digital" };

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
  /** 데모 조작 요소 (target: control): 이름 → 값 */
  controls?: Record<string, number>;
}

/** 실제로 가상 싱크에 나간 값 (observe 모드면 중립) */
export interface ControllerOut {
  mode: OutputMode;
  axes: Record<GamepadAxis, number>;
  buttons: Record<GamepadButton, boolean>;
  keys: string[];
  key_events: { type: "down" | "up"; key: string }[];
  controls?: Record<string, number>;
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

/** 검지·중지 끝점 추적 (정규화 좌표) */
export interface TipInfo { x: number; y: number; ok: boolean; conf: number; down: boolean; moved?: number; gap?: number; armed?: boolean; rest?: boolean }

export interface MouseSettings {
  mode: MouseMode;
  object_id: number | null;
  mirror: boolean;
  hand_region: [number, number, number, number];
  object_region: [number, number, number, number];
  hand_clicks: boolean;
  object_hybrid?: boolean;
  hybrid_detach?: number;
  /** Legacy saved setting; hybrid hand input is click-only. */
  hybrid_hand_control?: "air" | "depth";
  hand_click_style: "finger" | "pinch";
  finger_press: number;
  finger_track: boolean;
  tip_drop: number;
  tip_refine: boolean;
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
  /** 물체의 바닥 아래-가운데 기준점을 광학 흐름으로 따라가 커서를 움직인다 (기본 켬). 끄면 분할 중심 */
  anchor_cursor?: boolean;
  /** 물체 마우스의 앞뒤 신호: size = 물체 크기, model = 깊이 모델(실험) */
  depth_source?: 'size' | 'model';
  /** model 일 때 감도: 책상 맨 뒤→맨 앞 이동 시 커서가 움직이는 화면 높이 배수 */
  depth_model_range?: number;
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
  /** 깊이 모델(Depth Anything V2 Small) 가중치가 설치돼 있는가 (물체 마우스 깊이 옵션) */
  depth_model_available?: boolean;
  depth_reference?: { samples: number; resets: number; ready: boolean };
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
