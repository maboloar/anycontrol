import { create } from "zustand";
import { markTourSeen, tourSeen } from "./tutorial";
import type {
  AutoCalibrationState,
  ControllerComputed,
  ControllerOut,
  FrameState,
  HandDrawingState,
  MappingInfo,
  MappingLive,
  MouseInfo,
  MouseState,
  ObjectInfo,
  PenState,
  Telemetry,
} from "./protocol";

export interface LiveState {
  real?: import("./protocol").RealInfo | null;
  mouse: MouseState | null;
  pens: Record<string, PenState>;
  handDrawing?: HandDrawingState | null;
  mapping: { live: MappingLive[]; computed: ControllerComputed } | null;
  controller: ControllerOut | null;
}

export type SelectMode = "object" | "pen" | "calib" | "calib-line";

export type ConnStatus = "connecting" | "open" | "closed";

export interface ClientStats {
  /** 캡처 → 브라우저 화면에 그려질 때까지 (ms) */
  glassP50: number | null;
  glassP95: number | null;
  renderFps: number | null;
  rttMs: number | null;
  decodeDropped: number;
}

interface AppState {
  inputMirror: boolean;
  setInputMirror: (value: boolean) => void;
  viewFlip: boolean;
  overlays: { objects: boolean; hands: boolean; pens: boolean };
  setView: (patch: { viewFlip?: boolean; overlays?: AppState['overlays'] }) => void;
  autoCalibration: AutoCalibrationState | null;
  setAutoCalibration: (c: AutoCalibrationState | null) => void;
  conn: ConnStatus;
  serverVersion: string | null;
  telemetry: Telemetry | null;
  client: ClientStats;
  frameSize: { width: number; height: number } | null;
  previewMirror: boolean;
  setPreviewMirror: (mirror: boolean) => void;
  calibration: FrameState["calibration"] | null;
  setCalibration: (c: FrameState["calibration"]) => void;
  /** 패널 표시용 (약 10Hz 로 갱신). 오버레이는 connection 에서 매 프레임 직접 받는다. */
  objects: ObjectInfo[];
  selectedId: number | null;
  setObjects: (o: ObjectInfo[]) => void;
  select: (id: number | null) => void;
  /** 영상 클릭이 무엇을 등록하나: 일반 물체(드래그·클릭) 또는 펜(두 점) */
  selectMode: SelectMode;
  setSelectMode: (m: SelectMode) => void;
  /** 다시 선택 중인 물체 id (영상에서 새로 드래그·클릭하면 같은 id 로 모양을 다시 기억). null = 아님 */
  reselectId: number | null;
  setReselect: (id: number | null) => void;
  /** 시작 튜토리얼 열림 (처음 여는 사람만 자동으로) */
  tourOpen: boolean;
  setTour: (open: boolean) => void;
  mouseInfo: MouseInfo | null;
  setMouseInfo: (m: MouseInfo | null) => void;
  /** 약 10Hz 로 갱신되는 마우스·펜·매핑 상태 (패널 표시용) */
  live: LiveState;
  setLive: (l: LiveState) => void;
  mappingInfo: MappingInfo | null;
  setMappingInfo: (m: MappingInfo | null) => void;
  setConn: (c: ConnStatus) => void;
  setHello: (v: string) => void;
  setTelemetry: (t: Telemetry) => void;
  setClient: (c: Partial<ClientStats>) => void;
  setFrameSize: (s: { width: number; height: number }) => void;
}

export const useApp = create<AppState>((set) => ({
  inputMirror: true,
  setInputMirror: (inputMirror) => set({ inputMirror }),
  viewFlip: true,
  overlays: { objects: true, hands: true, pens: true },
  setView: (patch) => set(patch),
  autoCalibration: null,
  setAutoCalibration: (autoCalibration) => set({ autoCalibration }),
  conn: "connecting",
  serverVersion: null,
  telemetry: null,
  client: { glassP50: null, glassP95: null, renderFps: null, rttMs: null, decodeDropped: 0 },
  frameSize: null,
  previewMirror: false,
  setPreviewMirror: (previewMirror) => set({ previewMirror }),
  calibration: null,
  setCalibration: (calibration) => set((s) => JSON.stringify(s.calibration) === JSON.stringify(calibration)
    ? s : { calibration }),
  objects: [],
  selectedId: null,
  setObjects: (objects) =>
    set((s) => ({
      objects,
      selectedId: s.selectedId !== null && objects.some((o) => o.id === s.selectedId) ? s.selectedId : (objects[0]?.id ?? null),
    })),
  select: (selectedId) => set({ selectedId }),
  selectMode: "object",
  setSelectMode: (selectMode) => set({ selectMode, reselectId: null }),
  reselectId: null,
  setReselect: (reselectId) => set({ reselectId }),
  tourOpen: !tourSeen(),
  setTour: (tourOpen) => {
    if (!tourOpen) markTourSeen();
    set({ tourOpen });
  },
  mouseInfo: null,
  setMouseInfo: (mouseInfo) => set({ mouseInfo }),
  live: { mouse: null, pens: {}, mapping: null, controller: null },
  setLive: (live) => set({ live }),
  mappingInfo: null,
  setMappingInfo: (mappingInfo) => set({ mappingInfo }),
  setConn: (conn) => set({ conn }),
  setHello: (serverVersion) => set({ serverVersion }),
  setTelemetry: (telemetry) => set({ telemetry }),
  setClient: (c) => set((s) => ({ client: { ...s.client, ...c } })),
  setFrameSize: (frameSize) =>
    set((s) =>
      s.frameSize && s.frameSize.width === frameSize.width && s.frameSize.height === frameSize.height
        ? s
        : { frameSize },
    ),
}));
