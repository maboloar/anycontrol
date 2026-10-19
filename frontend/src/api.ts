import { useApp } from "./store";
import { sv } from "./serverText";
import type {
  AutoCalibrationKind,
  AutoCalibrationState,
  AxisSuggestion,
  CameraDevice,
  MappingInfo,
  MouseInfo,
  MouseSettings,
  ObjectInfo,
  ObjectMemory,
  FloorMapData,
  OutputMode,
  PenState,
  Profile,
  ProfileSummary,
  RealInfo,
} from "./protocol";

export type SourceSpec =
  | { kind: "camera"; index: number; width: number; height: number; fps: number; mirror?: boolean;
      device_id?: string | null; desk_view?: boolean; paused?: boolean; enabled?: boolean }
  | { kind: "synthetic"; width: number; height: number; fps: number; paused?: boolean }
  | { kind: "file"; path: string; loop?: boolean; paused?: boolean };

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = (await res.json()) as { detail?: unknown };
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* 본문 없음 */
    }
    throw new Error(`${res.status} ${sv(detail)}`);
  }
  return (await res.json()) as T;
}

export const getCameras = () => request<CameraDevice[]>("GET", "/api/cameras");
export const putSource = (spec: SourceSpec, reset = false) => request<unknown>("PUT", `/api/source${reset ? "?reset=true" : ""}`, spec);
export const getSource = () => request<{ spec: SourceSpec }>("GET", "/api/source");
export const openDeskViewSetup = () => request<{ opened: boolean }>('POST', '/api/source/desk-view/setup');
export const putPlayback = (paused: boolean) => request<{ paused: boolean }>("PUT", "/api/source/playback", { paused });
export const putCameraPower = (enabled: boolean) => request<{ enabled: boolean }>("PUT", "/api/source/power", { enabled });
export const restartSource = () => request<{ spec: SourceSpec }>("POST", "/api/source/restart");

export type AddObjectReq =
  | { box: [number, number, number, number] }
  | { point: [number, number] }
  | { line: [number, number, number, number] }; // 펜: 펜촉 x,y, 반대쪽 끝 x,y

export const getMouse = () => request<MouseInfo>("GET", "/api/mouse");
export const getAutoCalibration = () => request<AutoCalibrationState | null>('GET', '/api/auto-calibration');
export const startAutoCalibration = (kind: AutoCalibrationKind, objectId: number | null, movementOnly = true) =>
  request<AutoCalibrationState>('POST', '/api/auto-calibration/start', { kind, object_id: objectId, movement_only: movementOnly });
export const autoCalibrationAction = (action: 'record' | 'back' | 'cancel' | 'skip', sessionId: string, stepKey?: string) =>
  request<AutoCalibrationState>('POST', `/api/auto-calibration/${action}`, { session_id: sessionId, step_key: stepKey });
export const applyAutoCalibration = (sessionId: string) =>
  request<{ calibration: AutoCalibrationState; mouse: MouseInfo; pen: PenState | null }>(
    'POST', '/api/auto-calibration/apply', { session_id: sessionId });
export const putMouse = (s: Partial<MouseSettings>) => request<MouseInfo>("PUT", "/api/mouse", s);
export const stopAll = () => {
  window.dispatchEvent(new Event("anycontrol-stop"));
  return request<MouseInfo>("POST", "/api/stop").then(info => {
    window.dispatchEvent(new CustomEvent("anycontrol.real-stopped", { detail: info }));
    return info;
  });
};
export const penAction = (id: number, action: "clear" | "touch" | "lift" | "down" | "up" | "auto" | "reset" | "config", body?: object) =>
  request<PenState>("POST", `/api/objects/${id}/pen/${action}`, body);
export interface HandDrawingInfo { enabled: boolean; hands_available: boolean; hands_error: string | null }
// 모드 전환·unmount 요청을 순서대로 보내 늦게 도착한 켜기 요청이 손 추적을 다시 켜지 않도록 한다.
let handDrawingQueue: Promise<unknown> = Promise.resolve();
export const putHandDrawing = (enabled: boolean): Promise<HandDrawingInfo> => {
  const next = handDrawingQueue.catch(() => undefined).then(() =>
    request<HandDrawingInfo>("PUT", "/api/drawing/hand", { enabled }));
  handDrawingQueue = next;
  return next;
};
export const clearHandDrawing = () => request<HandDrawingInfo>("POST", "/api/drawing/hand/clear");
export const addObject = (req: AddObjectReq) => request<ObjectInfo>("POST", "/api/objects", req);
/** 다시 선택: 같은 id 로 다시 분할해 모양을 새로 기억한다 (이름·색·매핑·마우스 연결 유지) */
export const reselectObject = (id: number, req: AddObjectReq) =>
  request<ObjectInfo>("POST", `/api/objects/${id}/reselect`, req);
export const deleteObject = async (id: number) => {
  const res = await fetch(`/api/objects/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 404) throw new Error(`${res.status}`);
  const app = useApp.getState();
  app.setObjects(app.objects.filter(o => o.id !== id));
};
export const setNeutral = (id: number) => request<ObjectInfo>("POST", `/api/objects/${id}/neutral`);
export const getFloorMap = (id: number) => request<FloorMapData>("GET", `/api/objects/${id}/pen/floor-map`);
export const resetDepthReference = () => request<import("./protocol").MouseInfo>("POST", "/api/mouse/depth-reference");
export const getDepthMap = () => request<import("./protocol").DepthMapData>("GET", "/api/dev/depth-map");
export interface AutoResegInfo { enabled: boolean; long_s: number }
export const getAutoReseg = () => request<AutoResegInfo>("GET", "/api/dev/auto-reseg");
export const putAutoReseg = (body: Partial<AutoResegInfo>) => request<AutoResegInfo>("PUT", "/api/dev/auto-reseg", body);
export const getSceneMap = () => request<import("./protocol").DepthMapData>("GET", "/api/dev/scene-map");
export const getDepthModel = () => request<import("./protocol").DepthModelStatus>("GET", "/api/dev/depth-model");
export const downloadDepthModel = () => request<import("./protocol").DepthModelStatus>("POST", "/api/dev/depth-model/download");
export const getDepthCompare = (id: number) => request<import("./protocol").DepthCompareData>("GET", `/api/dev/pen/${id}/depth-compare`);
export const getObjectMemory = (id: number) => request<ObjectMemory>("GET", `/api/objects/${id}/memory`);
/** 체크한 기억(AI 앵커·재획득)을 지운다. 등록 모습은 서버가 지우지 않는다. */
export const forgetObjectMemory = (id: number, items: { kind: string; t: number }[]) =>
  request<ObjectMemory & { removed: number }>("POST", `/api/objects/${id}/memory/forget`, { items });
/** 물체 패널 사진 카드 아이콘 (등록 모습). 없으면 image = null */
export const getObjectThumbnail = (id: number) => request<{ id: number; image: string | null }>("GET", `/api/objects/${id}/thumbnail`);
/** 시연 화면: 배경 깊이 대비 사람이 가까이 왔는지 (Depth Anything). reset = 지금 장면을 배경으로 */
export const getPresence = (reset = false) =>
  request<{ ready: boolean; present: boolean; near?: number; reason?: string }>("GET", `/api/idle/presence${reset ? "?reset=true" : ""}`);
export const pickCandidate = (id: number, index: number) =>
  request<ObjectInfo>("POST", `/api/objects/${id}/candidate`, { index });
export const renameObject = (id: number, name: string) => request<ObjectInfo>("PATCH", `/api/objects/${id}`, { name });

export const getReal = () => request<RealInfo>("GET", "/api/real");
export const putReal = (on: boolean) => request<RealInfo>("PUT", "/api/real", { on });
export const requestRealPermission = () => request<{ trusted: boolean }>("POST", "/api/real/permission");

export interface TrackingInfo { hand_input_enabled?: boolean; input_mirror?: boolean; ema?: boolean; hand_occlusion: boolean; hands_available: boolean;
  hand_backend?: import("./protocol").HandBackend | null; hand_backends?: import("./protocol").HandBackend[];
  tier1_mode?: string; tier1_stats?: { jobs?: number; applied?: number; resets?: number; errors?: number; reacq?: number; reacq_ok?: number };
  tier1_error?: string | null;
  segmentation_enabled?: boolean; segmentation_hz?: number; segmentation_effective_hz?: number;
  segmentation_ms?: number; segmentation_backend?: string | null;
  segmentation_stats?: { jobs: number; applied: number; rejected: number; errors: number }; segmentation_error?: string | null }
export const getTracking = () => request<TrackingInfo>("GET", "/api/tracking");
export const putTracking = (settings: boolean | Partial<TrackingInfo>) =>
  request<TrackingInfo>("PUT", "/api/tracking", typeof settings === "boolean" ? { hand_occlusion: settings } : settings);

// ---- 책상 보정 ----
export interface CalibrationInfo { calibrated: boolean; mode?: "quad" | "line" | "deskview" | null; quad?: [number, number][]; line?: [number, number][]; tilt?: number; yaw_ok?: boolean }
export const putCalibration = (points: [number, number][], width_m = 0.297, depth_m = 0.21) =>
  request<CalibrationInfo>("PUT", "/api/calibration", { points, width_m, depth_m });
export const putLineCalibration = (points: [number, number][]) =>
  request<CalibrationInfo>("PUT", "/api/calibration/line", { points });
export const getCalibration = () => request<CalibrationInfo>("GET", "/api/calibration");
export const deleteCalibration = async () => {
  const res = await fetch("/api/calibration", { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status}`);
};

// ---- 매핑·프로필 ----
export const requestGameSetup = (object_id: number, position: boolean, profile: Profile) =>
  request<{ mouse: MouseInfo; mapping: MappingInfo }>('POST', '/api/game-setup', { object_id, position, profile });
export const getMapping = () => request<MappingInfo>("GET", "/api/mapping");
export const putMapping = (p: Profile) => request<MappingInfo>("PUT", "/api/mapping", p);
export const putOutputMode = (mode: OutputMode) => request<MappingInfo>("PUT", "/api/mapping/mode", { mode });
export const learnStart = async (objectId: number) => {
  const res = await fetch("/api/mapping/learn/start", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ object_id: objectId }),
  });
  if (!res.ok) throw new Error(`${res.status}`);
};
export const learnStop = () =>
  request<{ object_id: number; frames: number; suggestions: AxisSuggestion[] }>("POST", "/api/mapping/learn/stop");
export const listProfiles = () => request<ProfileSummary[]>("GET", "/api/profiles");
export const loadProfile = (name: string) => request<Profile>("GET", `/api/profiles/${encodeURIComponent(name)}`);
export const saveProfile = (p: Profile) => request<Profile>("PUT", `/api/profiles/${encodeURIComponent(p.name)}`, p);
export const deleteProfile = async (name: string) => {
  const res = await fetch(`/api/profiles/${encodeURIComponent(name)}`, { method: "DELETE" });
  if (!res.ok && res.status !== 404) throw new Error(`${res.status}`);
};
export interface TouchSettings { object_sensitivity: number }
export const getTouchSettings = () => request<TouchSettings>("GET", "/api/touch/settings");
export const putTouchSettings = (b: Partial<TouchSettings>) => request<TouchSettings>("PUT", "/api/touch/settings", b);

export const resetSettings = () => request<{ mouse: MouseInfo; mapping: MappingInfo }>("POST", "/api/settings/reset");
