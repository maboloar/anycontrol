import { ActionIcon } from "./ActionIcon";
import { useEffect, useRef, useState } from "react";
import { getCameras, getSource, openDeskViewSetup, putCameraPower, putPlayback, putSource, restartSource, type SourceSpec } from "../api";
import type { CameraDevice } from "../protocol";
import { useApp } from "../store";
import { Panel } from "./Panel";

/** 카메라 선택. 연속성 카메라(iPhone)를 우선 추천한다. */
export function SourcePanel() {
  const [cams, setCams] = useState<CameraDevice[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [spec, setSpec] = useState<SourceSpec | null>(null);
  const src = useApp((s) => s.telemetry?.source);
  const conn = useApp((s) => s.conn);
  const normalCamera = useRef<Extract<SourceSpec, { kind: 'camera' }> | null>(null);

  useEffect(() => {
    if (conn !== "open") return;
    getCameras().then(setCams, (e: unknown) => setErr(String(e)));
    getSource().then((r) => setSpec(r.spec), (e: unknown) => setErr(String(e)));
  }, [conn]);

  const apply = async (spec: SourceSpec, reset = false) => {
    setBusy(true);
    setErr(null);
    try {
      if (reset) await putSource(spec, true); else await putSource(spec);
      setSpec(spec);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const currentIndex = src?.kind === "camera" ? src.index : undefined;
  const mirror = spec?.kind === "camera" ? Boolean(spec.mirror) : false;
  const deskOn = spec?.kind === 'camera' && Boolean(spec.desk_view);
  const deskAvailable = cams.some((c) => c.is_desk_view);
  const enabled = spec?.kind === "camera" ? (spec.enabled ?? src?.enabled ?? true) : true;
  const toggleDesk = async (enabled: boolean) => {
    if (spec?.kind !== 'camera') return;
    if (!enabled) {
      await apply(normalCamera.current ?? { ...spec, desk_view: false });
      return;
    }
    normalCamera.current = { ...spec, desk_view: false };
    const current = cams.find((c) => c.unique_id === spec.device_id) ?? cams.find((c) => c.index === currentIndex);
    const desk = cams.find((c) => c.unique_id === current?.companion_id) ?? cams.find((c) => c.is_desk_view);
    if (!desk) { setErr('Desk View 장치를 찾을 수 없습니다. iPhone을 연결하고 장치 새로고침을 누르세요.'); return; }
    const parent = cams.find((c) => c.unique_id === desk.parent_id);
    await apply({ ...spec, desk_view: true, device_id: parent?.unique_id ?? desk.unique_id,
      index: parent?.index ?? desk.index });
  };
  const refresh = async () => {
    setBusy(true);
    try { setCams(await getCameras()); setErr(null); }
    catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  };
  const setup = async () => {
    setBusy(true);
    try { await openDeskViewSetup(); setErr(null); }
    catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  };
  const playback = async () => {
    if (!spec) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await putPlayback(!(src?.paused ?? spec.paused));
      setSpec({ ...spec, paused: r.paused });
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const power = async () => {
    if (spec?.kind !== "camera") return;
    setBusy(true);
    try { const r = await putCameraPower(!enabled); setSpec({ ...spec, enabled: r.enabled }); setErr(null); }
    catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  };
  const restart = async () => {
    setBusy(true);
    try { const r = await restartSource(); setSpec(r.spec); setErr(null); }
    catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  };

  return (
    <Panel title="카메라" tour="source" info={<>입력 영상을 고릅니다. <b>iPhone 연속성 카메라</b>(USB 유선 권장)가 가장 정확합니다. 책상 옆에 수평으로 세우거나, Mac 위에 걸고 <b>Desk View</b>로 씁니다.</>}>
      <div className="row source-controls">
        {spec?.kind === "camera" && <button type="button" className={enabled ? "act-pause" : "act-go"} disabled={busy} aria-pressed={enabled}
          onClick={() => void power()}><ActionIcon name="power" />{enabled ? "카메라 끄기" : "카메라 켜기"}</button>}
        <button type="button" className={(src?.paused ?? spec?.paused) ? "act-go" : "act-pause"} disabled={busy || !spec || !enabled} onClick={() => void playback()}>
          <ActionIcon name={(src?.paused ?? spec?.paused) ? "play" : "pause"} />{(src?.paused ?? spec?.paused) ? "재생" : "일시정지"}</button>
        {spec && spec.kind !== "camera" && <button type="button" className="act-reset" disabled={busy} onClick={() => void restart()}><ActionIcon name="reset" />처음부터 선택</button>}
      </div>
      <label className="check"><input type="checkbox" checked={deskOn}
        disabled={busy || spec?.kind !== 'camera' || (!deskOn && !deskAvailable)}
        onChange={(e) => void toggleDesk(e.target.checked)} />Desk View · 책상 위에서 보기</label>
      <div className="row">
        <button type="button" disabled={busy} onClick={() => void refresh()}><ActionIcon name="reset" />장치 새로고침</button>
        {deskOn && <button type="button" disabled={busy} onClick={() => void setup()}>Desk View 설정 열기</button>}
        {deskOn && <button type="button" className="act-config" disabled={busy} onClick={() => { if (spec) void apply(spec, true); }}><ActionIcon name="check" />구도 적용 · 다시 선택</button>}
      </div>
      <p className="small muted">{deskOn
        ? 'Desk View 1920×1440 · 최대 30fps. 펜·손 이동에 책상 XY 좌표를 사용합니다. 설정 창에서 구도/줌을 바꾼 뒤 [구도 적용 · 다시 선택]을 누르고 물체를 다시 지정하세요. 종이 4점 보정으로 범위를 좁힐 수 있습니다.'
        : deskAvailable ? 'Desk View를 켜면 Apple의 책상 원근 보정 영상을 사용합니다. 끄면 기존 카메라 설정으로 돌아갑니다.'
          : '지원되는 iPhone을 연결하면 Desk View를 사용할 수 있습니다.'}</p>
      <label className="check"><input type="checkbox" checked={mirror}
        disabled={busy || spec?.kind !== "camera"}
        onChange={(e) => { if (spec?.kind === "camera") void apply({ ...spec, mirror: e.target.checked }); }} />
        카메라 영상 좌우 반전</label>
      <ul className="cam-list">
        <li><button type="button" disabled={busy} aria-pressed={spec?.kind === "camera" && spec.index === -1}
          className={spec?.kind === "camera" && spec.index === -1 ? "active" : ""}
          onClick={() => apply({ kind: "camera", index: -1, width: 1280, height: 720, fps: 30, mirror })}>
          <span>자동 선택</span><small>iPhone 연속성 카메라 우선</small></button></li>
        {cams.filter((c) => !c.is_desk_view).map((c) => {
          const best = c.formats.reduce((m, f) => Math.max(m, f.max_fps), 0);
          const active = src?.device_id === c.unique_id || src?.parent_id === c.unique_id || currentIndex === c.index;
          return (
            <li key={c.unique_id}>
              <button
                type="button"
                disabled={busy}
                aria-pressed={active}
                className={active ? "active" : ""}
                onClick={() => {
                  const camera = { kind: 'camera' as const, index: c.index, device_id: c.unique_id,
                    width: 1280, height: 720, fps: best >= 60 ? 60 : 30, mirror, desk_view: false };
                  normalCamera.current = camera;
                  void apply({ ...camera, desk_view: deskOn && Boolean(c.companion_id) });
                }}
              >
                <span>{c.name}</span>
                <small>
                  {c.is_continuity ? "iPhone · " : ""}최대 {best}fps
                </small>
              </button>
            </li>
          );
        })}
      </ul>
      {spec && spec.kind !== "camera" && <p className="small muted">일시정지는 등록·보정을 유지합니다. [처음부터 선택]은 장면과 등록을 초기화하고 첫 화면에서 멈춥니다.</p>}
      {err && <p className="error" role="alert">{err}</p>}
      {src?.status === 'error' && src.error && <p className="error" role="alert">{src.error}</p>}
    </Panel>
  );
}
