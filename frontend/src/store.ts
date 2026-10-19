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
  FloorMapData, DepthMapData,
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

export type SelectMode = "object" | "pen";

const DEV_KEY = "anycontrol.devMode";
function readDevMode(): boolean {
  try { return localStorage.getItem(DEV_KEY) === "1"; } catch { return false; }
}

const IDLE_KEY = "anycontrol.idleShowcase";
const FLOAT_KEY = "anycontrol.floatingCamera";
function readFlag(key: string, fallback: boolean): boolean {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v === "1"; } catch { return fallback; }
}

/** 패치 케이블을 끄는 중: 어느 잭에서 시작했는지와 지금 포인터 위치 (화면 좌표) */
export interface PatchDrag {
  from: { kind: "obj"; name: string } | { kind: "fn"; id: string };
  x: number; y: number; startX: number; startY: number;
  /** 제자리에서 눌렀다 뗌 = 선을 집은 채로 다음 잭 클릭을 기다린다 */
  sticky: boolean;
}

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
  resetBusy: boolean;
  resetGeneration: number;
  handInputEnabled: boolean;
  touchOverlay: boolean;
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
  /** 다른 분할 후보로 교체 중인 물체 id (그동안 서버 상태가 먼저 와도 선택을 새 물체로 옮기기 위함) */
  replacingId: number | null;
  setReplacing: (id: number | null) => void;
  replaceObject: (oldId: number, info: ObjectInfo) => void;
  memoryOpen: boolean;
  setMemoryOpen: (open: boolean) => void;
  /** 고급 모드(내부 이름 devMode): 켜면 세부 설정·실험 기능·개발용 보기가 나타난다. 끄면 숨기고 열려 있던 개발용 보기도 닫는다. */
  devMode: boolean;
  setDevMode: (on: boolean) => void;
  /** 바닥 그라데이션 맵 보기(개발자). 열려 있는 동안 FloorMapView 가 받아 floorMap 에 넣고, 켜면 카메라 영상 위에도 겹친다. */
  floorMapOpen: boolean;
  setFloorMapOpen: (open: boolean) => void;
  floorOverlay: boolean;
  setFloorOverlay: (on: boolean) => void;
  floorMap: FloorMapData | null;
  /** Depth Anything 깊이 맵을 카메라 영상 위에 겹쳐 보기(개발자). 켜 있는 동안 CameraTools 의 DepthMapPoller 가 받아 depthMap 에 넣는다. */
  depthMapOverlay: boolean;
  setDepthMapOverlay: (on: boolean) => void;
  depthMap: DepthMapData | null;
  setDepthMap: (m: DepthMapData | null) => void;
  /** 겹쳐 볼 것: depth = Depth Anything 깊이, scene = 정지 배경 모델의 전경 판정(빨강 전경·파랑 배경) */
  depthMapKind: "depth" | "scene";
  setDepthMapKind: (k: "depth" | "scene") => void;
  /** 겹침 불투명도 0.2..1 */
  depthMapOpacity: number;
  setDepthMapOpacity: (v: number) => void;
  setFloorMap: (m: FloorMapData | null) => void;
  /** 영상 클릭이 무엇을 등록하나: 일반 물체(드래그·클릭) 또는 펜(두 점) */
  selectMode: SelectMode;
  setSelectMode: (m: SelectMode) => void;
  /** 다시 선택 중인 물체 id (영상에서 새로 드래그·클릭하면 같은 id 로 모양을 다시 기억). null = 아님 */
  reselectId: number | null;
  setReselect: (id: number | null) => void;
  /** 시작 튜토리얼 열림 (처음 여는 사람만 자동으로) */
  tourOpen: boolean;
  setTour: (open: boolean) => void;
  /** 패치 케이블: 끌고 있는 선 (물체 잭 ↔ 데모 기능 잭). null = 끌지 않음 */
  patchDrag: PatchDrag | null;
  setPatchDrag: (d: PatchDrag | null) => void;
  /** 매핑 패널이 열려 있는 동안 등록하는 연결 함수. null 이면 물체 카드의 잭을 숨긴다. */
  patchConnect: ((objectName: string, fnId: string) => void) | null;
  setPatchConnect: (f: ((objectName: string, fnId: string) => void) | null) => void;
  /** 120초 동안 입력이 없으면 시연 화면을 띄울지 (고급 모드에서 끌 수 있다) */
  /** 이 창이 연결을 놓았다: replaced = 다른 창이 열림, restarted = 서버를 다시 켜 새 창이 열림 */
  dormant: "replaced" | "restarted" | null;
  setDormant: (d: "replaced" | "restarted" | null) => void;
  idleShowcase: boolean;
  setIdleShowcase: (on: boolean) => void;
  /** 시연 화면까지 기다릴 무입력 시간 (초, 기본 120) */
  idleSeconds: number;
  setIdleSeconds: (s: number) => void;
  /** 카메라 미리보기가 스크롤로 가려지면 작은 실시간 카메라를 띄울지 (고급 모드에서 끌 수 있다) */
  floatingCamera: boolean;
  setFloatingCamera: (on: boolean) => void;
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
  resetBusy: false,
  resetGeneration: 0,
  handInputEnabled: true,
  touchOverlay: false,
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
  replacingId: null,
  setObjects: (objects) =>
    set((s) => {
      if (s.selectedId !== null && objects.some((o) => o.id === s.selectedId)) return { objects };
      // 선택한 물체가 사라졌다. 다른 분할 후보로 바꾸는 중이면 서버가 새 id 로 교체한 것이므로
      // 새로 생긴 물체(이전 목록에 없던 것)를 따라간다. 첫 번째 물체로 튀지 않게 한다.
      if (s.replacingId !== null && s.replacingId === s.selectedId) {
        const known = new Set(s.objects.map((o) => o.id));
        const fresh = objects.filter((o) => !known.has(o.id));
        if (fresh.length === 1) return { objects, selectedId: fresh[0]!.id, replacingId: null };
      }
      return { objects, selectedId: objects[0]?.id ?? null };
    }),
  select: (selectedId) => set({ selectedId }),
  setReplacing: (replacingId) => set({ replacingId }),
  /** 서버가 id 를 새로 발급해 물체를 교체했다 (다른 분할 후보). 선택 중이던 물체였으면 새 물체를 계속 선택한다. */
  replaceObject: (oldId, info) =>
    set((s) => {
      const has = s.objects.some((o) => o.id === oldId);
      const objects = has ? s.objects.map((o) => (o.id === oldId ? info : o)) : s.objects;
      const wasSelected = s.selectedId === oldId;
      const selectedId = wasSelected && objects.some((o) => o.id === info.id) ? info.id
        : s.selectedId !== null && objects.some((o) => o.id === s.selectedId) ? s.selectedId
          : (objects[0]?.id ?? null);
      return { objects, selectedId, replacingId: null };
    }),
  /** 물체 기억 보기가 켜져 있는지. 다른 물체를 선택하거나 후보를 바꿔도 유지된다. */
  memoryOpen: false,
  setMemoryOpen: (memoryOpen) => set({ memoryOpen }),
  devMode: readDevMode(),
  setDevMode: (devMode) => {
    try { localStorage.setItem(DEV_KEY, devMode ? "1" : "0"); } catch { /* 저장 불가 환경: 이번 세션만 */ }
    // 끄면 고급 전용 선택 모드(펜·종이·수평 보정)도 일반 물체 선택으로 되돌린다
    set(devMode ? { devMode } : { devMode, floorMapOpen: false, floorOverlay: false, floorMap: null, depthMapOverlay: false, depthMap: null });
  },
  depthMapOverlay: false,
  setDepthMapOverlay: (depthMapOverlay) => set(depthMapOverlay ? { depthMapOverlay } : { depthMapOverlay, depthMap: null }),
  depthMap: null,
  setDepthMap: (depthMap) => set({ depthMap }),
  depthMapKind: "depth",
  setDepthMapKind: (depthMapKind) => set({ depthMapKind, depthMap: null }),
  depthMapOpacity: 0.8,
  setDepthMapOpacity: (depthMapOpacity) => set({ depthMapOpacity }),
  floorMapOpen: false,
  setFloorMapOpen: (floorMapOpen) => set(floorMapOpen ? { floorMapOpen } : { floorMapOpen, floorOverlay: false, floorMap: null }),
  floorOverlay: false,
  setFloorOverlay: (floorOverlay) => set({ floorOverlay }),
  floorMap: null,
  setFloorMap: (floorMap) => set({ floorMap }),
  selectMode: "object",
  setSelectMode: (selectMode) => set({ selectMode, reselectId: null }),
  reselectId: null,
  setReselect: (reselectId) => set({ reselectId }),
  tourOpen: !tourSeen(),
  setTour: (tourOpen) => {
    if (!tourOpen) markTourSeen();
    set({ tourOpen });
  },
  patchDrag: null,
  setPatchDrag: (patchDrag) => set({ patchDrag }),
  patchConnect: null,
  setPatchConnect: (patchConnect) => set({ patchConnect }),
  dormant: null,
  setDormant: (dormant) => set({ dormant }),
  idleShowcase: readFlag(IDLE_KEY, true),
  setIdleShowcase: (idleShowcase) => {
    try { localStorage.setItem(IDLE_KEY, idleShowcase ? "1" : "0"); } catch { /* 이번 세션만 */ }
    set({ idleShowcase });
  },
  idleSeconds: (() => { try { const n = Number(localStorage.getItem("anycontrol.idleSeconds")); return n >= 5 && n <= 3600 ? n : 120; } catch { return 120; } })(),
  setIdleSeconds: (idleSeconds) => {
    try { localStorage.setItem("anycontrol.idleSeconds", String(idleSeconds)); } catch { /* 이번 세션만 */ }
    set({ idleSeconds });
  },
  floatingCamera: readFlag(FLOAT_KEY, true),
  setFloatingCamera: (floatingCamera) => {
    try { localStorage.setItem(FLOAT_KEY, floatingCamera ? "1" : "0"); } catch { /* 이번 세션만 */ }
    set({ floatingCamera });
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
